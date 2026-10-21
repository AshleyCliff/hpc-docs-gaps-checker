"""Tests for render.py's `deploy-register` support.

Builds a self-contained findings directory per test from
tests/fixtures/diff_deploy_register/doc-claims.json, running diff.py to
produce deltas-deploy-register.json, then exercises render.py --check
deploy-register in isolation -- mirroring test_render.py's approach for
charm-inventory.

manifest.lock is read from the real repo root (not faked), per the same
reasoning as test_render.py.
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
DIFF_FIXTURES = FIXTURES_DIR / "diff_deploy_register"
MANIFEST_LOCK = REPO_ROOT / "manifest.lock"


def make_findings_dir(tmp_path: Path) -> Path:
    d = tmp_path / "findings"
    d.mkdir()
    shutil.copy(
        DIFF_FIXTURES / "doc-claims.json", d / "doc-claims-deploy-register.json"
    )

    diff_proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "diff.py"),
            str(DIFF_FIXTURES / "doc-claims.json"),
            "--check",
            "deploy-register",
        ],
        capture_output=True,
        text=True,
    )
    assert diff_proc.returncode == 0, diff_proc.stderr
    (d / "deltas-deploy-register.json").write_text(diff_proc.stdout)
    return d


def run_render(findings_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "render.py"),
            str(findings_dir),
            "--check",
            "deploy-register",
        ],
        capture_output=True,
        text=True,
    )


def expected_docs_sha8() -> str:
    lock = json.loads(MANIFEST_LOCK.read_text())
    docs = next(r for r in lock["repos"] if r["name"] == "docs")
    return docs["sha"][:8]


def test_creates_run_directory_with_check_suffix(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dirs = list(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "report.md").exists()
    assert (run_dir / "findings.json").exists()


def test_run_directory_name_never_collides_with_charm_inventory(tmp_path):
    """Both checks key off the same docs SHA -- the deploy-register run dir
    must carry a distinguishing suffix so a same-day run of both checks
    does not overwrite one with the other."""
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    charm_inventory_style = list(findings_dir.glob(f"run-*-{sha8}"))
    deploy_register_style = list(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    assert len(deploy_register_style) == 1
    # The charm-inventory-shaped glob must not also match the
    # deploy-register directory (it would, without the suffix).
    assert deploy_register_style[0] not in charm_inventory_style


def test_report_contains_reproducibility_header(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dir = next(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    report = (run_dir / "report.md").read_text()

    assert "deploy-register" in report
    lock = json.loads(MANIFEST_LOCK.read_text())
    for repo in lock["repos"]:
        assert repo["sha"] in report
    assert "no model name" in report.lower() or "no llm" in report.lower()


def test_findings_json_contains_findings_and_counts(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc = run_render(findings_dir)
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dir = next(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    data = json.loads((run_dir / "findings.json").read_text())

    assert data["check"] == "deploy-register"
    assert "unregistered-deployed-charm" in data["findings"]
    assert len(data["findings"]["unregistered-deployed-charm"]) == 2
    assert len(data["run"]["repos"]) == 8


def test_rerun_overwrites_run_directory_idempotently(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    proc1 = run_render(findings_dir)
    assert proc1.returncode == 0, proc1.stderr

    sha8 = expected_docs_sha8()
    run_dirs_before = list(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    assert len(run_dirs_before) == 1

    proc2 = run_render(findings_dir)
    assert proc2.returncode == 0, proc2.stderr

    run_dirs_after = list(findings_dir.glob(f"run-*-{sha8}-deploy-register"))
    assert len(run_dirs_after) == 1
    assert run_dirs_after[0] == run_dirs_before[0]


def test_missing_intermediate_fails_loudly(tmp_path):
    findings_dir = make_findings_dir(tmp_path)
    (findings_dir / "deltas-deploy-register.json").unlink()

    proc = run_render(findings_dir)
    assert proc.returncode != 0
    assert "deltas-deploy-register.json" in proc.stderr


def test_charm_inventory_default_still_works_unaffected(tmp_path):
    """render.py with no --check flag must still behave exactly as before
    -- the deploy-register support must be strictly additive."""
    d = tmp_path / "ci-findings"
    d.mkdir()
    ci_fixtures = FIXTURES_DIR / "diff"
    shutil.copy(ci_fixtures / "code-facts.json", d / "code-facts.json")
    shutil.copy(ci_fixtures / "doc-claims.json", d / "doc-claims.json")
    diff_proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "diff.py"),
            str(ci_fixtures / "code-facts.json"),
            str(ci_fixtures / "doc-claims.json"),
            "--retired-charms",
            str(ci_fixtures / "retired-charms.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert diff_proc.returncode == 0, diff_proc.stderr
    (d / "deltas.json").write_text(diff_proc.stdout)

    proc = subprocess.run(
        [sys.executable, str(EXTRACTORS_DIR / "render.py"), str(d)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    sha8 = expected_docs_sha8()
    run_dirs = list(d.glob(f"run-*-{sha8}"))
    assert len(run_dirs) == 1
    assert "charm-inventory" in (run_dirs[0] / "report.md").read_text()
