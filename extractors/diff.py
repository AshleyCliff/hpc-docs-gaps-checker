#!/usr/bin/env python3
"""Diff code facts against doc claims for the `charm-inventory` check.

Two set operations, per specs/charm-inventory.md "diff.py -- two set
differences":

    undocumented-charm   in code, zero mentions in docs      severity: missing-entry
    phantom-charm        named in docs, no matching charm    severity: wrong-value

`phantom-charm`'s candidate set is deliberately narrow: it is the charm names
already known from the code side, plus a *committed* list of known-retired
names. This check does not scan docs prose for arbitrary charm-shaped
strings -- that would be a different, noisier check. If the committed list
does not exist, this extractor emits zero phantom-charm findings and reports
that in the skip block, per spec, rather than inventing candidates.

Fixture-suspect charms (fixture_suspect: true in code-facts.json) are
reported separately under their own section -- never mixed into
undocumented-charm findings. See "Fixture charms" in the spec.

ID derivation follows specs/finding-ids.md exactly:

    id = <check>:<subject>:<hash8>
    hash8 = sha256("<check>\\x1f<kind>\\x1f<subject>")[:8] (hex)

Deterministic: no network, no clock, no model.

Usage:
    diff.py <code-facts.json> <doc-claims.json> [--retired-charms <file>]

Prints a single JSON object to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

CHECK = "charm-inventory"

# specs/finding-ids.md "The rule" / "Normalising <subject>".
_SUBJECT_INVALID_RUN_RE = re.compile(r"[^a-z0-9.-]+")

KIND_UNDOCUMENTED = "undocumented-charm"
KIND_PHANTOM = "phantom-charm"

# specs/charm-inventory.md "diff.py -- two set differences".
SEVERITY_BY_KIND = {
    KIND_UNDOCUMENTED: "missing-entry",
    KIND_PHANTOM: "wrong-value",
}


class SubjectEmptyError(RuntimeError):
    """Raised when subject normalisation yields an empty string.

    specs/finding-ids.md step 5: "If empty after this, the check must fail
    loudly rather than emit an ID." This is deliberately not caught anywhere
    that would let a run continue past it.
    """


def normalise_subject(raw: str) -> str:
    """specs/finding-ids.md 'Normalising <subject>', steps 1-5."""
    s = raw.strip()
    s = s.lower()
    s = _SUBJECT_INVALID_RUN_RE.sub("-", s)
    s = s.strip("-")
    if not s:
        raise SubjectEmptyError(f"subject normalises to empty string: {raw!r}")
    return s


def finding_id(check: str, kind: str, subject: str) -> str:
    """specs/finding-ids.md 'The rule' and 'The canonical key'."""
    key = f"{check}\x1f{kind}\x1f{subject}".encode("utf-8")
    hash8 = hashlib.sha256(key).hexdigest()[:8]
    return f"{check}:{subject}:{hash8}"


def load_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.exit(f"error: could not read {label} ({path}): {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {label} ({path}) is not valid JSON: {exc}")


def load_retired_charms(path: Path | None) -> tuple[list[str], dict]:
    """A committed list of known-retired charm names, or ([], skip-note).

    Per spec: "If the committed list does not exist yet, emit zero
    phantom-charm findings and say so in the skip report rather than
    inventing candidates." Expected shape, if present: a JSON array of
    strings, or a JSON object with a top-level "retired" array of strings.
    Any other shape is reported as unparseable, not guessed at.
    """
    if path is None:
        return [], {
            "reason": "no --retired-charms list given; phantom-charm "
            "candidate set is empty by design (see spec)",
            "path": None,
        }
    if not path.exists():
        return [], {
            "reason": "committed known-retired-charms list does not exist; "
            "emitting zero phantom-charm findings per spec",
            "path": str(path),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], {
            "reason": f"could not read/parse retired-charms list: {exc}",
            "path": str(path),
        }

    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return data, {}
    if (
        isinstance(data, dict)
        and isinstance(data.get("retired"), list)
        and all(isinstance(x, str) for x in data["retired"])
    ):
        return data["retired"], {}

    return [], {
        "reason": "retired-charms list has an unrecognised shape "
        "(expected a JSON array of strings, or {\"retired\": [...]})",
        "path": str(path),
    }


def citation(file: str, line: int | None) -> dict:
    return {"file": file, "line": line}


def build_undocumented_findings(
    code_facts: list[dict], mentioned_names: set[str]
) -> list[dict]:
    """Charms in code with zero docs mentions, excluding fixture_suspect ones.

    Fixture-suspect charms get their own section (build_fixture_section) --
    never mixed into undocumented-charm findings, per spec.
    """
    findings: list[dict] = []
    for fact in code_facts:
        if fact.get("fixture_suspect"):
            continue
        name = fact["name"]
        if name in mentioned_names:
            continue
        subject = normalise_subject(name)
        findings.append(
            {
                "id": finding_id(CHECK, KIND_UNDOCUMENTED, subject),
                "check": CHECK,
                "kind": KIND_UNDOCUMENTED,
                "subject": subject,
                "severity": SEVERITY_BY_KIND[KIND_UNDOCUMENTED],
                "name": name,
                "code_citation": citation(fact["file"], fact["line"]),
                "doc_citations": [],
            }
        )
    findings.sort(key=lambda f: f["id"])
    return findings


def build_phantom_findings(
    doc_claims: list[dict],
    code_names: set[str],
    retired_names: set[str],
) -> list[dict]:
    """Names mentioned in docs that match neither a real nor a retired charm.

    Candidate set is deliberately narrow (code names + retired names) -- see
    module docstring. A doc_claim's `name` is always drawn from code_facts by
    construction of doc_claims.py (it only searches for known code names), so
    with an empty retired list this will always be empty; it exists so a
    future retired-charms list can produce real findings without changing
    this function.
    """
    candidate_names = code_names | retired_names
    findings: list[dict] = []
    by_name: dict[str, list[dict]] = {}
    for claim in doc_claims:
        name = claim["name"]
        if name in code_names:
            continue  # matches a real charm; not phantom
        if name not in candidate_names:
            continue  # not in the allowed candidate set at all; cannot occur
            # given doc_claims.py's construction, but guarded defensively.
        by_name.setdefault(name, []).append(claim)

    for name, claims in by_name.items():
        subject = normalise_subject(name)
        doc_citations = sorted(
            (citation(c["file"], c["line"]) for c in claims),
            key=lambda c: (c["file"], c["line"]),
        )
        findings.append(
            {
                "id": finding_id(CHECK, KIND_PHANTOM, subject),
                "check": CHECK,
                "kind": KIND_PHANTOM,
                "subject": subject,
                "severity": SEVERITY_BY_KIND[KIND_PHANTOM],
                "name": name,
                "code_citation": None,
                "doc_citations": doc_citations,
            }
        )
    findings.sort(key=lambda f: f["id"])
    return findings


def build_fixture_section(code_facts: list[dict], mentioned_names: set[str]) -> list[dict]:
    """fixture_suspect charms, reported separately -- never mixed into findings.

    Per spec: "have diff.py report its finding separately, under a
    fixture-suspect heading in the report rather than mixed into real
    findings." These are not assigned an id/kind/severity because they are
    explicitly not findings in the undocumented-charm/phantom-charm sense --
    they are a visibility measure over a heuristic, not a verdict.
    """
    rows: list[dict] = []
    for fact in code_facts:
        if not fact.get("fixture_suspect"):
            continue
        name = fact["name"]
        rows.append(
            {
                "name": name,
                "code_citation": citation(fact["file"], fact["line"]),
                "documented": name in mentioned_names,
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("code_facts", type=Path, help="code-facts.json")
    ap.add_argument("doc_claims", type=Path, help="doc-claims.json")
    ap.add_argument(
        "--retired-charms",
        type=Path,
        default=None,
        help="committed JSON list of known-retired charm names "
        "(array of strings, or {\"retired\": [...]})); omit if none exists",
    )
    args = ap.parse_args(argv)

    code_data = load_json(args.code_facts, "code-facts.json")
    doc_data = load_json(args.doc_claims, "doc-claims.json")

    code_facts = code_data.get("facts", [])
    doc_claims = doc_data.get("claims", [])

    code_names = {f["name"] for f in code_facts}
    mentioned_names = {c["name"] for c in doc_claims}

    retired_names_list, retired_skip_note = load_retired_charms(args.retired_charms)
    retired_names = set(retired_names_list)

    try:
        undocumented = build_undocumented_findings(code_facts, mentioned_names)
        phantom = build_phantom_findings(doc_claims, code_names, retired_names)
    except SubjectEmptyError as exc:
        sys.exit(f"error: {exc}")

    fixture_section = build_fixture_section(code_facts, mentioned_names)

    skipped: dict = {
        "phantom_charm_candidates": {
            "retired_names_loaded": sorted(retired_names),
        },
    }
    if retired_skip_note:
        skipped["phantom_charm_candidates"]["note"] = retired_skip_note

    output = {
        "check": CHECK,
        "findings": {
            KIND_UNDOCUMENTED: undocumented,
            KIND_PHANTOM: phantom,
        },
        "fixture_suspect": fixture_section,
        "skipped": skipped,
        "counts": {
            "code_charms": len(code_facts),
            "doc_claims": len(doc_claims),
            "undocumented_charm_findings": len(undocumented),
            "phantom_charm_findings": len(phantom),
            "fixture_suspect_charms": len(fixture_section),
        },
    }

    print(json.dumps(output, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
