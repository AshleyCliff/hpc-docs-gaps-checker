#!/usr/bin/env python3
"""Render the charm-inventory check's findings into a committed run directory.

Reads the flat intermediates written by the `extract` workshop action:

    <findings-dir>/code-facts.json
    <findings-dir>/doc-claims.json
    <findings-dir>/deltas.json

and writes, creating the directory itself (per
specs/charm-inventory.md "Output paths"):

    <findings-dir>/run-<YYYY-MM-DD>-<docs-sha-first-8>/
    ├── report.md
    └── findings.json

`<docs-sha-first-8>` comes from the `docs` entry in `manifest.lock` -- the
docs pin identifies the run, since it is the side being audited.

If the run directory already exists, it is overwritten (re-running the same
pins is idempotent rather than accumulating near-duplicate directories).

The reproducibility header carries the resolved SHAs for all eight repos (from
manifest.lock), the extractor version, and the check ID -- per spec. Model
name and prompt hash are omitted, not faked: this check has no LLM layer.

Deterministic except for the run date, which is UTC "today" by construction --
re-running on the same day with the same pins overwrites in place; re-running
on a later day creates a new run directory even with unchanged pins, which is
intended (the directory name is "when, against what," not a content hash).

Usage:
    render.py <findings-dir>   # e.g. findings/
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CHECK = "charm-inventory"

# Bump this when code_facts.py, doc_claims.py, or diff.py's extraction logic
# changes in a way that could change output for the same inputs. Not tied to
# repo commit count or date -- a deliberate, hand-set version for this check's
# pipeline as a whole.
EXTRACTOR_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_LOCK = REPO_ROOT / "manifest.lock"

INTERMEDIATE_NAMES = {
    "code_facts": "code-facts.json",
    "doc_claims": "doc-claims.json",
    "deltas": "deltas.json",
}


def load_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.exit(f"error: could not read {label} ({path}): {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {label} ({path}) is not valid JSON: {exc}")


def load_manifest_lock() -> list[dict]:
    if not MANIFEST_LOCK.exists():
        sys.exit(f"error: {MANIFEST_LOCK} not found; run sync.py --freeze on the host first")
    data = load_json(MANIFEST_LOCK, "manifest.lock")
    repos = data.get("repos")
    if not isinstance(repos, list) or not repos:
        sys.exit(f"error: {MANIFEST_LOCK} has no 'repos' list")
    for r in repos:
        for field in ("name", "sha"):
            if field not in r:
                sys.exit(f"error: {MANIFEST_LOCK} entry missing '{field}': {r!r}")
    return repos


def docs_sha(repos: list[dict]) -> str:
    for r in repos:
        if r["name"] == "docs":
            return r["sha"]
    sys.exit("error: manifest.lock has no 'docs' entry")


def fmt_citation(c: dict | None) -> str:
    if c is None:
        return "—"
    file = c.get("file")
    line = c.get("line")
    if file is None:
        return "—"
    return f"`{file}:{line}`" if line is not None else f"`{file}`"


def render_header(repos: list[dict], run_date: str, sha8: str) -> str:
    lines = [
        f"# Charm inventory — run {run_date}-{sha8}",
        "",
        "## Reproducibility",
        "",
        f"- **Check ID:** `{CHECK}`",
        f"- **Extractor version:** `{EXTRACTOR_VERSION}`",
        f"- **Run date (UTC):** `{run_date}`",
        "",
        "| Repo | Resolved SHA |",
        "|---|---|",
    ]
    for r in sorted(repos, key=lambda r: r["name"]):
        lines.append(f"| `{r['name']}` | `{r['sha']}` |")
    lines.append("")
    lines.append(
        "No model name or prompt hash is recorded: this check is purely "
        "deterministic extraction and set operations, with no LLM layer."
    )
    lines.append("")
    return "\n".join(lines)


def render_findings_section(title: str, findings: list[dict]) -> str:
    lines = [f"## {title}", ""]
    if not findings:
        lines.append("None.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| ID | Name | Severity | Code | Docs |")
    lines.append("|---|---|---|---|---|")
    for f in findings:
        doc_cites = f.get("doc_citations") or []
        doc_str = "; ".join(fmt_citation(c) for c in doc_cites) if doc_cites else "—"
        lines.append(
            f"| `{f['id']}` | `{f['name']}` | {f['severity']} | "
            f"{fmt_citation(f.get('code_citation'))} | {doc_str} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_fixture_section(rows: list[dict]) -> str:
    lines = ["## Fixture-suspect charms", ""]
    lines.append(
        "Charms whose path contains a `test-` or `-test` segment. Reported "
        "separately per spec -- not mixed into undocumented-charm or "
        "phantom-charm findings above, because the fixture heuristic is a "
        "visibility measure, not a verdict."
    )
    lines.append("")
    if not rows:
        lines.append("None.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Name | Code | Documented? |")
    lines.append("|---|---|---|")
    for r in rows:
        lines.append(
            f"| `{r['name']}` | {fmt_citation(r.get('code_citation'))} | "
            f"{'yes' if r.get('documented') else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_skip_report(code_facts: dict, doc_claims: dict, deltas: dict) -> str:
    lines = ["## Skip report", ""]
    lines.append(
        "Per `AGENTS.md`'s \"report what you skipped\" convention: a zero "
        "count below is a meaningful result, not an omission."
    )
    lines.append("")

    cf_counts = code_facts.get("counts", {})
    cf_skipped = code_facts.get("skipped", {})
    lines.append("### Code side (`code_facts.py`)")
    lines.append("")
    lines.append(f"- `charmcraft.yaml` files found: **{cf_counts.get('charmcraft_files_found', '?')}**")
    lines.append(f"- Charms emitted: **{cf_counts.get('charms_emitted', '?')}**")
    lines.append(
        f"- Unparseable YAML: **{len(cf_skipped.get('unparseable_yaml', []))}**"
    )
    lines.append(
        f"- Missing `name:` key: **{len(cf_skipped.get('missing_name_key', []))}**"
    )
    lines.append(
        f"- Unreadable files: **{len(cf_skipped.get('unreadable_file', []))}**"
    )
    excl = cf_skipped.get("excluded_by_scope", {})
    lines.append(f"- Excluded by scope: **{excl.get('count', 0)}**")
    lines.append("")

    dc_counts = doc_claims.get("counts", {})
    dc_skipped = doc_claims.get("skipped", {})
    lines.append("### Docs side (`doc_claims.py`)")
    lines.append("")
    lines.append(f"- `.md` files scanned: **{dc_counts.get('md_files_scanned', '?')}**")
    lines.append(f"- Claims emitted: **{dc_counts.get('claims_emitted', '?')}**")
    lines.append(f"- Candidate names: **{dc_counts.get('candidate_names', '?')}**")
    lines.append(
        f"- Unreadable files: **{len(dc_skipped.get('unreadable_file', []))}**"
    )
    dc_excl = dc_skipped.get("excluded_by_scope", {})
    lines.append(f"- Excluded by scope: **{dc_excl.get('count', 0)}**")
    lines.append(
        f"- Unreliable fence classification: "
        f"**{len(dc_skipped.get('unreliable_fence_classification', []))}**"
    )
    lines.append("")

    diff_skipped = deltas.get("skipped", {})
    phantom_candidates = diff_skipped.get("phantom_charm_candidates", {})
    lines.append("### Diff (`diff.py`)")
    lines.append("")
    retired = phantom_candidates.get("retired_names_loaded", [])
    lines.append(f"- Known-retired charm names loaded: **{len(retired)}**")
    note = phantom_candidates.get("note")
    if note:
        lines.append(f"- Note: {note.get('reason')} (path: `{note.get('path')}`)")
    lines.append("")

    return "\n".join(lines)


def render_report(
    repos: list[dict],
    run_date: str,
    sha8: str,
    code_facts: dict,
    doc_claims: dict,
    deltas: dict,
) -> str:
    parts = [render_header(repos, run_date, sha8)]

    findings = deltas.get("findings", {})
    parts.append(
        render_findings_section(
            "Undocumented charms (in code, not mentioned in docs)",
            findings.get("undocumented-charm", []),
        )
    )
    parts.append(
        render_findings_section(
            "Phantom charms (named in docs, no matching charm in code)",
            findings.get("phantom-charm", []),
        )
    )
    parts.append(render_fixture_section(deltas.get("fixture_suspect", [])))
    parts.append(render_skip_report(code_facts, doc_claims, deltas))

    return "\n".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render.py <findings-dir>", file=sys.stderr)
        return 2

    findings_dir = Path(argv[1])
    if not findings_dir.is_dir():
        print(f"error: not a directory: {findings_dir}", file=sys.stderr)
        return 1

    code_facts_path = findings_dir / INTERMEDIATE_NAMES["code_facts"]
    doc_claims_path = findings_dir / INTERMEDIATE_NAMES["doc_claims"]
    deltas_path = findings_dir / INTERMEDIATE_NAMES["deltas"]

    for p, label in (
        (code_facts_path, "code-facts.json"),
        (doc_claims_path, "doc-claims.json"),
        (deltas_path, "deltas.json"),
    ):
        if not p.exists():
            print(
                f"error: {label} not found at {p}; run the `extract` action first",
                file=sys.stderr,
            )
            return 1

    code_facts = load_json(code_facts_path, "code-facts.json")
    doc_claims = load_json(doc_claims_path, "doc-claims.json")
    deltas = load_json(deltas_path, "deltas.json")

    repos = load_manifest_lock()
    sha8 = docs_sha(repos)[:8]
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    run_dir_name = f"run-{run_date}-{sha8}"
    run_dir = findings_dir / run_dir_name

    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    report_md = render_report(repos, run_date, sha8, code_facts, doc_claims, deltas)
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")

    findings_json = {
        "check": CHECK,
        "run": {
            "date": run_date,
            "extractor_version": EXTRACTOR_VERSION,
            "repos": sorted(repos, key=lambda r: r["name"]),
        },
        "findings": deltas.get("findings", {}),
        "fixture_suspect": deltas.get("fixture_suspect", []),
        "counts": deltas.get("counts", {}),
        "skipped": {
            "code_facts": code_facts.get("skipped", {}),
            "doc_claims": doc_claims.get("skipped", {}),
            "diff": deltas.get("skipped", {}),
        },
    }
    (run_dir / "findings.json").write_text(
        json.dumps(findings_json, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )

    print(f"wrote {run_dir}/report.md", file=sys.stderr)
    print(f"wrote {run_dir}/findings.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
