"""Tests for extractors/render.py.

render.py reads flat intermediates (code-facts.json, doc-claims.json,
deltas.json) from a findings directory and writes
run-<date>-<sha8>/{report.md,findings.json} into it, creating the run
directory itself and overwriting it if it already exists.

These tests build a self-contained findings directory per test (via
tmp_path) using the diff-fixtures from tests/fixtures/diff/, run the full
code_facts -> doc_claims is not needed here since we feed deltas.json
directly -- and exercise render.py in isolation.

manifest.lock is read from the real repo root (not faked), since it is a
committed, versioned file that render.py is specified to read from exactly
that location.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DIFF_FIXTURES = FIXTURES_DIR / "diff"
MANIFEST_LOCK = REPO_ROOT / "manifest.lock"


def make_findings_dir(tmp_path: Path) -> Path:
    """A findings/ dir with code-facts.json, doc-claims.json, deltas.json."""
    d = tmp_path / "findings"
    d.mkdir()
    shutil.copy(DIFF_FIXTURES / "code-facts.json", d / "code-facts.json")
    shutil.copy(DIFF_FIXTURES / "doc-claims.json", d / "doc-claims.json")

    diff_proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "diff.py"),
            str(DIFF_FIXTURES / "code-facts.json"),
            str(DIFF_FIXTURES / "doc-claims.json"),
            "--retired-charms",
            str(DIFF_FIXTURES / "retired-charms.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert diff_proc.returncode == 0, diff_proc.stderr
    (d / "deltas.json").write_text(diff_proc.stdout)
    return d


def run_render(findings_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXTRACTORS_DIR / "render.py"), str(findings_dir)],
        capture_output=True,
        text=True,
    )


def expected_docs_sha8() -> str:
    lock = json.loads(MANIFEST_LOCK.read_text())
    docs = next(r for r in lock["repos"] if r["name"] == "docs")
    return docs["sha"][:8]


def test_creates_run_directory_with_expected_name(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dirs = list(findings_dir.glob(f"run-*-{sha8}"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "report.md").exists()
    assert (run_dir / "findings.json").exists()


def test_report_contains_reproducibility_header(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dir = next(findings_dir.glob(f"run-*-{sha8}"))
    report = (run_dir / "report.md").read_text()

    assert "charm-inventory" in report
    assert sha8 in report or expected_docs_sha8() in report
    lock = json.loads(MANIFEST_LOCK.read_text())
    for repo in lock["repos"]:
        assert repo["sha"] in report
    # No model/prompt-hash claims, since this check has no LLM layer.
    assert "model" not in report.lower() or "no model name" in report.lower()


def test_findings_json_contains_findings_and_counts(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dir = next(findings_dir.glob(f"run-*-{sha8}"))
    data = json.loads((run_dir / "findings.json").read_text())

    assert data["check"] == "charm-inventory"
    assert "undocumented-charm" in data["findings"]
    assert "phantom-charm" in data["findings"]
    assert len(data["findings"]["undocumented-charm"]) == 1
    assert len(data["findings"]["phantom-charm"]) == 1
    assert data["run"]["extractor_version"]
    assert len(data["run"]["repos"]) == 8


def test_rerun_overwrites_run_directory_idempotently(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc1 = run_render(findings_dir)
    assert proc1.returncode == 0, proc1.stderr

    sha8 = expected_docs_sha8()
    run_dirs_before = list(findings_dir.glob(f"run-*-{sha8}"))
    assert len(run_dirs_before) == 1

    proc2 = run_render(findings_dir)
    assert proc2.returncode == 0, proc2.stderr

    run_dirs_after = list(findings_dir.glob(f"run-*-{sha8}"))
    assert len(run_dirs_after) == 1  # not duplicated
    assert run_dirs_after[0] == run_dirs_before[0]


def test_missing_intermediate_fails_loudly(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    (findings_dir / "deltas.json").unlink()

    proc = run_render(findings_dir)
    assert proc.returncode != 0
    assert "deltas.json" in proc.stderr


def test_fixture_suspect_rendered_in_own_section(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dir = next(findings_dir.glob(f"run-*-{sha8}"))
    report = (run_dir / "report.md").read_text()

    assert "Fixture-suspect" in report
    assert "test-mount-client" in report
