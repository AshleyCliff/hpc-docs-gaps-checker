"""Tests for diff.py's `deploy-register` check, against
tests/fixtures/diff_deploy_register/doc-claims.json.

Fixture claims (see the committed file for the full list):

    sssd            deployed once, registered in machine-charms -> no finding
    orphan-charm    deployed TWICE (two files), registered nowhere ->
                    ONE finding, two deploy_citations
    widget-project  deployed once, registered only in the "dependencies"
                    project table (never a charm table) -> still a finding,
                    with register_citations showing the project-table entry
                    as triage context (does not satisfy the instruction)
    widget-k8s      registered in kubernetes-charms, never deployed ->
                    NOT a finding; reported under
                    skipped.registered_but_never_deployed
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import diff as diff_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DIFF_FIXTURES = FIXTURES_DIR / "diff_deploy_register"


def run_cli(doc_claims: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "diff.py"),
            str(doc_claims),
            "--check",
            "deploy-register",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_check_field_is_deploy_register():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    assert out["check"] == "deploy-register"


def test_registered_and_deployed_charm_is_not_a_finding():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    names = {f["name"] for f in out["findings"]["unregistered-deployed-charm"]}
    assert "sssd" not in names


def test_charm_deployed_twice_in_different_files_yields_one_finding_two_citations():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    findings = out["findings"]["unregistered-deployed-charm"]
    orphan = [f for f in findings if f["name"] == "orphan-charm"]
    assert len(orphan) == 1
    assert len(orphan[0]["deploy_citations"]) == 2
    files = {c["file"] for c in orphan[0]["deploy_citations"]}
    assert files == {"docs/getting-started.md", "docs/howto/deploy-echo-again.md"}


def test_two_namespaces_project_table_entry_does_not_satisfy_deploy_instruction():
    """widget-project is deployed, and is registered -- but ONLY in the
    "dependencies" project table, never in a charm table. Per "Two
    namespaces" in the spec, this must still produce a finding: a project
    table entry does not satisfy a deploy instruction."""
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    findings = out["findings"]["unregistered-deployed-charm"]
    widget = [f for f in findings if f["name"] == "widget-project"]
    assert len(widget) == 1
    # Nearest register context is still cited, for triage, even though it
    # does not satisfy the instruction.
    assert widget[0]["register_citations"] == [
        {"file": "docs/reference/underlying-projects-and-dependencies.md", "line": 24}
    ]


def test_registered_but_never_deployed_is_not_a_finding():
    """The reverse direction is deliberately not a finding -- widget-k8s is
    registered in kubernetes-charms but has no juju-deploy instruction
    anywhere in the fixture claims."""
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    names = {f["name"] for f in out["findings"]["unregistered-deployed-charm"]}
    assert "widget-k8s" not in names

    skip = out["skipped"]["registered_but_never_deployed"]
    assert skip["count"] == 1
    assert skip["names"] == ["widget-k8s"]


def test_finding_count_matches_fixture_expectation():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    findings = out["findings"]["unregistered-deployed-charm"]
    assert len(findings) == 2
    assert {f["name"] for f in findings} == {"orphan-charm", "widget-project"}


def test_severity_is_missing_entry_deterministically():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    for f in out["findings"]["unregistered-deployed-charm"]:
        assert f["severity"] == "missing-entry"
    assert diff_mod.SEVERITY_BY_KIND["unregistered-deployed-charm"] == "missing-entry"


def test_finding_id_shape_and_check_prefix():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    for f in out["findings"]["unregistered-deployed-charm"]:
        assert f["id"].startswith("deploy-register:")
        check, subject, hash8 = f["id"].split(":")
        assert check == "deploy-register"
        assert subject == f["subject"]
        assert len(hash8) == 8


def test_finding_id_matches_deterministic_derivation():
    expected = diff_mod.finding_id(
        "deploy-register", "unregistered-deployed-charm", "orphan-charm"
    )
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    orphan = next(
        f for f in out["findings"]["unregistered-deployed-charm"] if f["name"] == "orphan-charm"
    )
    assert orphan["id"] == expected


def test_output_is_deterministic():
    out1 = run_cli(DIFF_FIXTURES / "doc-claims.json")
    out2 = run_cli(DIFF_FIXTURES / "doc-claims.json")
    assert out1 == out2


def test_citations_present_on_every_finding():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    for f in out["findings"]["unregistered-deployed-charm"]:
        assert f["deploy_citations"]
        for c in f["deploy_citations"]:
            assert c["file"]
            assert c["line"] is not None


def test_counts_reflect_claims_and_findings():
    out = run_cli(DIFF_FIXTURES / "doc-claims.json")
    assert out["counts"]["deploy_instructions"] == 4
    assert out["counts"]["register_entries"] == 3
    assert out["counts"]["unregistered_deployed_charm_findings"] == 2
