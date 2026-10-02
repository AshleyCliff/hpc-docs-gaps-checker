#!/usr/bin/env python3
"""Emit charm-mention claims for the `charm-inventory` check.

Scope (per specs/charm-inventory.md), docs side: every `.md` under
<docs-root>, excluding:

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

Usage:
    doc_claims.py <docs-root> --names-from <code-facts.json>

<code-facts.json> is the output of code_facts.py; its `facts[*].name` values
are the only candidate names this extractor looks for. This keeps doc_claims
deterministic and scoped: it never invents a list of charm-shaped substrings
from docs prose.

Prints a single JSON object to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CHECK = "charm-inventory"

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


def discover_md_files(root: Path) -> tuple[list[Path], dict]:
    """Every .md under root, minus exclusions. Returns (kept, exclusion report)."""
    all_md = sorted(p for p in root.rglob("*.md"))

    kept: list[Path] = []
    excluded: list[str] = []

    for p in all_md:
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

    return kept, {"count": len(excluded), "paths": sorted(excluded)}


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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docs_root", type=Path, help="e.g. /inputs/repos/docs")
    ap.add_argument(
        "--names-from",
        type=Path,
        required=True,
        help="code-facts.json; candidate names come from facts[*].name",
    )
    args = ap.parse_args(argv)

    if not args.docs_root.is_dir():
        print(f"error: not a directory: {args.docs_root}", file=sys.stderr)
        return 1

    try:
        code_facts = json.loads(args.names_from.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read --names-from {args.names_from}: {exc}", file=sys.stderr)
        return 1

    names = sorted({f["name"] for f in code_facts.get("facts", [])})
    pattern = build_name_pattern(names)

    md_files, excluded_report = discover_md_files(args.docs_root)

    all_claims: list[dict] = []
    unreadable: list[dict] = []
    fence_notes: list[dict] = []

    if pattern is not None:
        for path in md_files:
            claims, notes = scan_file(path, args.docs_root, pattern)
            all_claims.extend(claims)
            for n in notes:
                if n.get("line") is None and "unreadable" in n.get("reason", ""):
                    unreadable.append(n)
                else:
                    fence_notes.append(n)

    all_claims.sort(key=lambda c: (c["file"], c["line"], c["name"]))

    output = {
        "check": CHECK,
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

    print(json.dumps(output, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
