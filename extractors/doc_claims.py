#!/usr/bin/env python3
"""Emit docs-side claims for the `charm-inventory` and `deploy-register` checks.

Dispatched by `--check`, default `charm-inventory` so existing callers and
`workshop.yaml`'s `extract` action are unaffected:

    doc_claims.py <docs-root> --names-from <code-facts.json>
    doc_claims.py <docs-root> --check deploy-register

Both checks share this module rather than forking into parallel copies,
because they scan overlapping territory (the same docs tree, the same
fence-aware line classification) and diverging them would mean fixing the
same parsing bug twice. See the module's `main()` for the dispatch point.

---

## `charm-inventory` (default)

Scope, docs side: every `.md` under <docs-root>, excluding:

    .git/**
    .github/**
    .agents/**
    CONTRIBUTING.md, README.md   (tree root only)
    contributing/**

Every exclusion is counted and reported, never silently applied.

For each file, scan every line for occurrences of a *candidate charm name*
(from code_facts.py's output) using a word-boundary match where `-` counts as
a word character -- see "Matching rule" in specs/charm-inventory.md. One claim
is emitted per (name, file, line): if a name appears more than once on one
line, that is still one claim for that line, since the claim's unit is "this
name appeared at this site," not "this many times."

`context` is one of `prose`, `code-block`, `table`, `heading` -- descriptive
only. It does NOT judge adequacy of documentation.

<code-facts.json> is the output of code_facts.py; its `facts[*].name` values
are the only candidate names this extractor looks for. This keeps doc_claims
deterministic and scoped: it never invents a list of charm-shaped substrings
from docs prose.

## `deploy-register`

Scope, docs side, per specs/deploy-register-consistency.md: every `.md` AND
`.txt` under <docs-root>, same directory exclusions as above (`.txt` is
included here but not for `charm-inventory`, because `reuse/**` holds
`{include}`-d command transcripts with real `juju deploy` lines reachable no
other way).

Emits two claim kinds:
  - `deploy-instruction` -- a `juju deploy <name>` occurrence.
  - `register-entry` -- a row from one of the six `csv-table` blocks in
    `reference/underlying-projects-and-dependencies.md`, via `csv_table.py`.

Prints a single JSON object to stdout.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

import csv_table

CHECK_CHARM_INVENTORY = "charm-inventory"
CHECK_DEPLOY_REGISTER = "deploy-register"

CHECK = CHECK_CHARM_INVENTORY  # retained for backward compatibility; charm-inventory's own CHECK

EXCLUDED_DIRS = {".git", ".github", ".agents", "contributing"}
EXCLUDED_ROOT_FILES = {"CONTRIBUTING.md", "README.md"}

# MyST/reStructuredText fenced-directive markers: ":::" or more, optionally
# followed by "{name}". A fence's run length (3, 4, 5, ... colons) must match
# its opener to close it -- MyST nests fences by using a longer run on the
# outer fence. See the "Fenced regions" note below for why we track this.
FENCE_OPEN_RE = re.compile(r"^(:{3,})\{([A-Za-z0-9_-]+)\}")
FENCE_CLOSE_RE = re.compile(r"^(:{3,})\s*$")

# Markdown triple-backtick fences (used in a handful of files, e.g.
# CONTRIBUTING.md, alongside the MyST ::: fences used elsewhere).
BACKTICK_FENCE_RE = re.compile(r"^(`{3,})")

HEADING_RE = re.compile(r"^#{1,6}\s")

# Directive names whose body is a table, for `context: table`.
TABLE_DIRECTIVES = {"csv-table", "list-table"}

# Directive names whose body is code, for `context: code-block`.
CODE_DIRECTIVES = {"code-block", "code", "literalinclude", "terminal"}


def discover_files(root: Path, suffixes: tuple[str, ...]) -> tuple[list[Path], dict]:
    """Every file under root matching one of `suffixes`, minus exclusions.

    Shared by both checks: `charm-inventory` calls this with `(".md",)`;
    `deploy-register` calls it with `(".md", ".txt")` per
    specs/deploy-register-consistency.md's wider scope. The exclusion rules
    (EXCLUDED_DIRS, EXCLUDED_ROOT_FILES) are identical for both -- only the
    extension set differs.

    Returns (kept, exclusion report).
    """
    all_files = sorted(
        p for suffix in suffixes for p in root.rglob(f"*{suffix}")
    )

    kept: list[Path] = []
    excluded: list[str] = []

    for p in all_files:
        rel = p.relative_to(root)
        parts = rel.parts

        if any(seg in EXCLUDED_DIRS for seg in parts[:-1]):
            excluded.append(str(rel))
            continue

        # Root-level CONTRIBUTING.md / README.md only (len(parts) == 1).
        if len(parts) == 1 and parts[0] in EXCLUDED_ROOT_FILES:
            excluded.append(str(rel))
            continue

        kept.append(p)

    return sorted(set(kept)), {"count": len(excluded), "paths": sorted(set(excluded))}


def discover_md_files(root: Path) -> tuple[list[Path], dict]:
    """Every .md under root, minus exclusions. Returns (kept, exclusion report).

    Thin wrapper kept for charm-inventory's existing call sites and tests.
    """
    return discover_files(root, (".md",))


def build_name_pattern(names: list[str]) -> re.Pattern | None:
    """Word-boundary pattern over all candidate names, `-` as a word char.

    `(?<![A-Za-z0-9_-])NAME(?![A-Za-z0-9_-])` ensures:
      - `slurmd` does not match inside `slurmdbd` (trailing boundary fails).
      - `slurmctld` does not match inside `slurmctld-peer` (trailing `-`
        is treated as a word character, so the boundary fails).

    Deliberately NOT including `.` in the boundary class, even though an
    earlier version of this pattern did. Per spec, the only addition to the
    normal `\\w` boundary is `-`; `.` is ordinary punctuation and must not
    suppress a match. A charm name immediately followed by a sentence-ending
    period (e.g. "...mentions apptainer.") or appearing as
    `module.slurmctld.app_name` in Terraform must still register as a
    mention. See tests/test_doc_claims.py for the regression fixture.

    Longer names are tried first so overlapping candidates (there are none in
    this corpus, but this is defensive) do not shadow each other oddly.
    """
    if not names:
        return None
    ordered = sorted(set(names), key=len, reverse=True)
    alts = "|".join(re.escape(n) for n in ordered)
    return re.compile(r"(?<![A-Za-z0-9_-])(" + alts + r")(?![A-Za-z0-9_-])")


def classify_line(
    line: str,
    fence_stack: list[tuple[int, str]],
    backtick_fence_open: bool,
) -> str:
    """context for a mention on this line, given current fence state.

    Order of precedence: heading > code-block (open fence of a code-like
    directive, or inside a backtick fence) > table (open csv-table/list-table
    directive) > prose.
    """
    if HEADING_RE.match(line):
        return "heading"
    if backtick_fence_open:
        return "code-block"
    if fence_stack:
        _, name = fence_stack[-1]
        if name in CODE_DIRECTIVES:
            return "code-block"
        if name in TABLE_DIRECTIVES:
            return "table"
    # Plain pipe-table row: starts with '|' and contains another '|'.
    stripped = line.strip()
    if stripped.startswith("|") and stripped.count("|") >= 2:
        return "table"
    return "prose"


def scan_file(path: Path, root: Path, pattern: re.Pattern) -> tuple[list[dict], list[dict]]:
    """Return (claims, skip-notes) for one file.

    skip-notes record fence-nesting shapes we could not interpret (unequal
    close length, unclosed fence at EOF) -- see "Report what you skipped" in
    AGENTS.md. These do not drop any claims; they only affect `context`
    classification confidence, so we report rather than silently guess.
    """
    rel = str(path.relative_to(root))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [{"file": rel, "reason": f"unreadable: {exc}"}]

    claims: list[dict] = []
    notes: list[dict] = []

    fence_stack: list[tuple[int, str]] = []  # (colon-run-length, directive-name)
    backtick_fence_open = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        bt_m = BACKTICK_FENCE_RE.match(line)
        if bt_m:
            backtick_fence_open = not backtick_fence_open
            continue  # the fence marker line itself is not scanned for mentions

        if not backtick_fence_open:
            open_m = FENCE_OPEN_RE.match(line)
            close_m = FENCE_CLOSE_RE.match(line) if not open_m else None

            if open_m:
                fence_stack.append((len(open_m.group(1)), open_m.group(2)))
                continue  # directive marker line, not scanned
            if close_m:
                n = len(close_m.group(1))
                if fence_stack and fence_stack[-1][0] == n:
                    fence_stack.pop()
                else:
                    notes.append(
                        {
                            "file": rel,
                            "line": lineno,
                            "reason": f"fence close ':'x{n} did not match open stack "
                            f"{fence_stack!r}; context classification for subsequent "
                            "lines in this file may be unreliable",
                        }
                    )
                continue  # closing marker line, not scanned

        context = classify_line(line, fence_stack, backtick_fence_open)

        for m in pattern.finditer(line):
            claims.append(
                {
                    "check": CHECK,
                    "kind": "charm-mention",
                    "name": m.group(1),
                    "file": rel,
                    "line": lineno,
                    "context": context,
                }
            )

    if fence_stack:
        notes.append(
            {
                "file": rel,
                "line": None,
                "reason": f"unclosed fence(s) at EOF: {fence_stack!r}; "
                "context classification near EOF may be unreliable",
            }
        )

    # One claim per (name, line) -- collapse duplicate names on one line.
    seen: set[tuple[str, int]] = set()
    deduped: list[dict] = []
    for c in claims:
        key = (c["name"], c["line"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    return deduped, notes


# --- deploy-register ---------------------------------------------------- #
#
# specs/deploy-register-consistency.md "Recognising a deploy instruction" /
# "doc_claims.py -- two new claim kinds".

# `juju deploy` followed by whitespace and a capturing group for whatever
# token (if any) comes next. The group is deliberately permissive -- it
# captures any non-whitespace run, including one that is not a valid name
# (e.g. `./local.charm`, `{{ sub }}`) or empty (nothing follows the command on
# this line, the inline-code prose case). Validity is judged afterwards
# against NAME_RE, so every case the spec distinguishes is visible to the
# caller rather than silently merged by the regex itself.
JUJU_DEPLOY_RE = re.compile(r"\bjuju deploy\b(?:[ \t]+(\S+))?")

# specs/deploy-register-consistency.md "Recognising a deploy instruction":
# "Match juju deploy followed by a single charm name, where the name matches
# [a-z0-9][a-z0-9-]*."
DEPLOY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# specs/deploy-register-consistency.md "doc_claims.py -- two new claim
# kinds": the six recognised table identities, keyed by the heading text
# that precedes each csv-table block in the committed register page.
REGISTER_TABLE_HEADINGS = {
    "Core": "core",
    "Dependencies": "dependencies",
    "Optional dependencies": "optional-dependencies",
    "Machine charms": "machine-charms",
    "Kubernetes charms": "kubernetes-charms",
    "Integrations": "integrations",
}

# Per "Two namespaces" in the spec: only these two tables hold *charm* names
# (read from link text); the rest hold *project/repo* names (read from the
# bare first cell).
REGISTER_LINK_TABLES = {"machine-charms", "kubernetes-charms"}


def scan_file_for_deploy_instructions(
    path: Path, root: Path
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (claims, unparseable-target notes, context-classification notes)
    for one file's `juju deploy` occurrences.

    A line matches `JUJU_DEPLOY_RE` in exactly one of three ways, per the
    spec's table under "Recognising a deploy instruction":

      - a name token follows, matching DEPLOY_NAME_RE -> emit a
        `deploy-instruction` claim.
      - a token follows, but it does not match DEPLOY_NAME_RE (a local path,
        a substitution, ...) -> no claim; recorded as an unparseable-target
        note.
      - no token follows at all (the inline-code prose case, `` `juju
        deploy`{l=shell} to deploy SSSD`` with nothing after the command on
        that line) -> no claim, and NOT recorded as an unparseable target --
        this is prose, not a malformed instruction. It is still visible via
        `claims_emitted` being lower than raw `juju deploy` occurrences, but
        the spec does not ask for a separate prose-mention count, so none is
        emitted here; see doc_claims.py tests for the regression fixture.

    A line continuation (`juju deploy microceph \\`) is handled by
    construction: the regex only ever looks at the first line, and the name
    token it captures is whatever immediately follows on THAT line --
    `microceph`, in that example -- never the continuation line, which this
    function never inspects as a second `juju deploy` site.

    Reuses the same fence-tracking as `classify_line` for `context`, since a
    deploy instruction's citation is as useful with a context tag as a
    charm-mention's.
    """
    rel = str(path.relative_to(root))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [], [{"file": rel, "reason": f"unreadable: {exc}"}]

    claims: list[dict] = []
    unparseable: list[dict] = []
    fence_notes: list[dict] = []

    fence_stack: list[tuple[int, str]] = []
    backtick_fence_open = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        bt_m = BACKTICK_FENCE_RE.match(line)
        if bt_m:
            backtick_fence_open = not backtick_fence_open
            continue

        if not backtick_fence_open:
            open_m = FENCE_OPEN_RE.match(line)
            close_m = FENCE_CLOSE_RE.match(line) if not open_m else None

            if open_m:
                fence_stack.append((len(open_m.group(1)), open_m.group(2)))
                continue
            if close_m:
                n = len(close_m.group(1))
                if fence_stack and fence_stack[-1][0] == n:
                    fence_stack.pop()
                else:
                    fence_notes.append(
                        {
                            "file": rel,
                            "line": lineno,
                            "reason": f"fence close ':'x{n} did not match open stack "
                            f"{fence_stack!r}",
                        }
                    )
                continue

        context = classify_line(line, fence_stack, backtick_fence_open)

        for m in JUJU_DEPLOY_RE.finditer(line):
            token = m.group(1)
            if token is None:
                continue  # prose: no token at all on this line -- not a skip
            if DEPLOY_NAME_RE.match(token):
                claims.append(
                    {
                        "check": CHECK_DEPLOY_REGISTER,
                        "kind": "deploy-instruction",
                        "name": token,
                        "file": rel,
                        "line": lineno,
                        "context": context,
                    }
                )
            else:
                unparseable.append({"file": rel, "line": lineno, "raw": line.strip()})

    if fence_stack:
        fence_notes.append(
            {
                "file": rel,
                "line": None,
                "reason": f"unclosed fence(s) at EOF: {fence_stack!r}",
            }
        )

    return claims, unparseable, fence_notes


def parse_register_entries(
    path: Path, root: Path
) -> tuple[list[dict], list[dict]]:
    """Return (register-entry claims, unrecognised-table notes) for the
    register page at `path`.

    Uses csv_table.parse_csv_tables() for the fence/row mechanics, then maps
    each block's heading to a `table` identity via REGISTER_TABLE_HEADINGS.
    A block whose heading does not match any of the six known identities is
    NOT silently dropped -- it is recorded as `unrecognised_register_table`,
    which specs/deploy-register-consistency.md requires be loud: "If the
    register's markup changes upstream and a table stops parsing, every
    charm in it silently becomes 'unregistered'."

    For the two charm tables (machine-charms, kubernetes-charms), the name is
    read from the first cell's Markdown link *text* (`csv_table.link_text`),
    per "Two namespaces" in the spec -- never from the raw cell. A row whose
    first cell is not a parseable link in one of those two tables is also
    reported under unrecognised_register_table, since the spec's Step-0 fact
    2 established that shape as universal in the pinned tree; a cell
    violating it is itself a sign the markup has drifted.

    For the other four tables (core, dependencies, optional-dependencies,
    integrations), the name is the bare first cell, per Step-0 fact 3.
    """
    rel = str(path.relative_to(root))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [{"file": rel, "line": None, "reason": f"unreadable: {exc}"}]

    blocks, parse_notes = csv_table.parse_csv_tables(text)

    claims: list[dict] = []
    unrecognised: list[dict] = []

    for note in parse_notes:
        unrecognised.append(
            {
                "file": rel,
                "line": note.get("line"),
                "reason": f"csv-table parse issue: {note['reason']}",
            }
        )

    for block in blocks:
        heading = block["heading"]
        table = REGISTER_TABLE_HEADINGS.get(heading or "")
        if table is None:
            unrecognised.append(
                {
                    "file": rel,
                    "line": block["fence_line"],
                    "reason": f"csv-table block's nearest heading {heading!r} does not "
                    "match any of the six known table identities",
                }
            )
            continue

        for row in block["rows"]:
            if not row["cells"] or not row["cells"][0]:
                unrecognised.append(
                    {
                        "file": rel,
                        "line": row["line"],
                        "reason": f"row in {table!r} table has an empty first cell",
                    }
                )
                continue

            cell0 = row["cells"][0]
            if table in REGISTER_LINK_TABLES:
                name = csv_table.link_text(cell0)
                if name is None:
                    unrecognised.append(
                        {
                            "file": rel,
                            "line": row["line"],
                            "reason": f"row in {table!r} table's first cell is not a "
                            f"Markdown link, expected [name](url): {cell0!r}",
                        }
                    )
                    continue
            else:
                name = cell0

            claims.append(
                {
                    "check": CHECK_DEPLOY_REGISTER,
                    "kind": "register-entry",
                    "name": name,
                    "table": table,
                    "file": rel,
                    "line": row["line"],
                }
            )

    return claims, unrecognised


REGISTER_PAGE_RELATIVE_PATH = "reference/underlying-projects-and-dependencies.md"


def run_deploy_register(docs_root: Path) -> dict:
    """Full doc-claims.py pipeline for the `deploy-register` check."""
    files, excluded_report = discover_files(docs_root, (".md", ".txt"))
    md_count = sum(1 for f in files if f.suffix == ".md")
    txt_count = sum(1 for f in files if f.suffix == ".txt")

    all_claims: list[dict] = []
    unreadable: list[dict] = []
    unparseable_targets: list[dict] = []
    fence_notes: list[dict] = []
    unrecognised_register_table: list[dict] = []

    register_path = docs_root / REGISTER_PAGE_RELATIVE_PATH
    register_scanned = False

    for path in files:
        rel = str(path.relative_to(docs_root))
        if rel == REGISTER_PAGE_RELATIVE_PATH:
            register_scanned = True
            reg_claims, reg_notes = parse_register_entries(path, docs_root)
            all_claims.extend(reg_claims)
            unrecognised_register_table.extend(reg_notes)
            # The register page can ALSO contain `juju deploy` text in
            # principle (it currently does not -- verified empty on the
            # pinned tree) -- scan it for deploy instructions too, so a
            # future edit adding one is not silently missed.
            d_claims, d_unparseable, d_fence_notes = scan_file_for_deploy_instructions(
                path, docs_root
            )
            all_claims.extend(d_claims)
            unparseable_targets.extend(d_unparseable)
            fence_notes.extend(d_fence_notes)
            continue

        d_claims, d_unparseable, d_fence_notes = scan_file_for_deploy_instructions(
            path, docs_root
        )
        all_claims.extend(d_claims)
        unparseable_targets.extend(d_unparseable)
        for n in d_fence_notes:
            if n.get("line") is None and "unreadable" in n.get("reason", ""):
                unreadable.append(n)
            else:
                fence_notes.append(n)

    if not register_scanned and register_path.exists():
        # Only reachable if the register page exists but was excluded by
        # scope or missed by discovery -- surface it loudly rather than
        # silently emitting zero register-entry claims.
        unrecognised_register_table.append(
            {
                "file": REGISTER_PAGE_RELATIVE_PATH,
                "line": None,
                "reason": "register page exists on disk but was not in the scanned "
                "file set (excluded by scope, or missing .md discovery)",
            }
        )
    elif not register_path.exists():
        unrecognised_register_table.append(
            {
                "file": REGISTER_PAGE_RELATIVE_PATH,
                "line": None,
                "reason": "register page does not exist at the expected path",
            }
        )

    all_claims.sort(
        key=lambda c: (c["file"], c["line"], c["kind"], c["name"])
    )

    return {
        "check": CHECK_DEPLOY_REGISTER,
        "claims": all_claims,
        "skipped": {
            "unparseable_deploy_target": sorted(
                unparseable_targets, key=lambda x: (x["file"], x["line"])
            ),
            "unrecognised_register_table": sorted(
                unrecognised_register_table,
                key=lambda x: (x["file"], x["line"] if x["line"] is not None else -1),
            ),
            "unreadable_file": sorted(unreadable, key=lambda x: x["file"]),
            "excluded_by_scope": excluded_report,
            "unreliable_fence_classification": fence_notes,
        },
        "counts": {
            "md_files_scanned": md_count,
            "txt_files_scanned": txt_count,
            "deploy_instructions_found": sum(
                1 for c in all_claims if c["kind"] == "deploy-instruction"
            ),
            "register_entries_found": sum(
                1 for c in all_claims if c["kind"] == "register-entry"
            ),
            "claims_emitted": len(all_claims),
        },
    }


def run_charm_inventory(docs_root: Path, names_from: Path) -> dict | int:
    """Full doc-claims.py pipeline for the `charm-inventory` check.

    Returns the output dict, or an int exit code on error (so `main()` can
    propagate a non-zero return the same way the original single-check
    version did).
    """
    try:
        code_facts = json.loads(names_from.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read --names-from {names_from}: {exc}", file=sys.stderr)
        return 1

    names = sorted({f["name"] for f in code_facts.get("facts", [])})
    pattern = build_name_pattern(names)

    md_files, excluded_report = discover_md_files(docs_root)

    all_claims: list[dict] = []
    unreadable: list[dict] = []
    fence_notes: list[dict] = []

    if pattern is not None:
        for path in md_files:
            claims, notes = scan_file(path, docs_root, pattern)
            all_claims.extend(claims)
            for n in notes:
                if n.get("line") is None and "unreadable" in n.get("reason", ""):
                    unreadable.append(n)
                else:
                    fence_notes.append(n)

    all_claims.sort(key=lambda c: (c["file"], c["line"], c["name"]))

    return {
        "check": CHECK_CHARM_INVENTORY,
        "claims": all_claims,
        "skipped": {
            "unreadable_file": sorted(unreadable, key=lambda x: x["file"]),
            "excluded_by_scope": excluded_report,
            "unreliable_fence_classification": fence_notes,
        },
        "counts": {
            "md_files_scanned": len(md_files),
            "claims_emitted": len(all_claims),
            "candidate_names": len(names),
        },
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docs_root", type=Path, help="e.g. /inputs/repos/docs")
    ap.add_argument(
        "--check",
        choices=[CHECK_CHARM_INVENTORY, CHECK_DEPLOY_REGISTER],
        default=CHECK_CHARM_INVENTORY,
        help="which check to run (default: charm-inventory, for backward "
        "compatibility with existing callers)",
    )
    ap.add_argument(
        "--names-from",
        type=Path,
        default=None,
        help="code-facts.json; candidate names come from facts[*].name. "
        "Required for --check charm-inventory; unused by deploy-register.",
    )
    args = ap.parse_args(argv)

    if not args.docs_root.is_dir():
        print(f"error: not a directory: {args.docs_root}", file=sys.stderr)
        return 1

    if args.check == CHECK_CHARM_INVENTORY:
        if args.names_from is None:
            print(
                "error: --names-from is required for --check charm-inventory",
                file=sys.stderr,
            )
            return 2
        result = run_charm_inventory(args.docs_root, args.names_from)
        if isinstance(result, int):
            return result
        output = result
    else:
        output = run_deploy_register(args.docs_root)

    print(json.dumps(output, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
