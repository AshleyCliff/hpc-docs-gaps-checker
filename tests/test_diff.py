"""Tests for extractors/diff.py against tests/fixtures/diff/.

Fixtures:
    code-facts.json      3 charms: slurmctld (undocumented), slurmd
                         (documented), test-mount-client (fixture_suspect,
                         undocumented)
    doc-claims.json      mentions "slurmd" and "slurmrestd-legacy" (the
                         latter is not a real charm -- a phantom candidate)
    retired-charms.json  {"retired": ["slurmrestd-legacy"]}
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
DIFF_FIXTURES = FIXTURES_DIR / "diff"


def run_cli(code_facts: Path, doc_claims: Path, retired: Path | None = None) -> dict:
    cmd = [
        sys.executable,
        str(EXTRACTORS_DIR / "diff.py"),
        str(code_facts),
        str(doc_claims),
    ]
    if retired is not None:
        cmd += ["--retired-charms", str(retired)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_undocumented_charm_found_for_slurmctld():
    out = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    undoc = out["findings"]["undocumented-charm"]
    assert len(undoc) == 1
    assert undoc[0]["name"] == "slurmctld"
    assert undoc[0]["kind"] == "undocumented-charm"
    assert undoc[0]["severity"] == "missing-entry"
    assert undoc[0]["code_citation"] == {
        "file": "slurm-charms/charms/slurmctld/charmcraft.yaml",
        "line": 16,
    }


def test_slurmd_is_not_undocumented_because_it_is_mentioned():
    out = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    names = {f["name"] for f in out["findings"]["undocumented-charm"]}
    assert "slurmd" not in names


def test_fixture_suspect_charm_excluded_from_undocumented_findings():
    """test-mount-client is undocumented AND fixture_suspect -- it must
    appear in the fixture_suspect section, never in undocumented-charm."""
    out = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    names = {f["name"] for f in out["findings"]["undocumented-charm"]}
    assert "test-mount-client" not in names

    fixture_names = {r["name"] for r in out["fixture_suspect"]}
    assert "test-mount-client" in fixture_names
    row = next(r for r in out["fixture_suspect"] if r["name"] == "test-mount-client")
    assert row["documented"] is False


def test_no_phantom_findings_without_retired_list():
    """Per spec: if the committed known-retired list does not exist, emit
    zero phantom-charm findings and report it in skipped, rather than
    inventing candidates."""
    out = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    assert out["findings"]["phantom-charm"] == []
    note = out["skipped"]["phantom_charm_candidates"].get("note")
    assert note is not None
    assert "no --retired-charms list given" in note["reason"]


def test_phantom_finding_with_retired_list():
    out = run_cli(
        DIFF_FIXTURES / "code-facts.json",
        DIFF_FIXTURES / "doc-claims.json",
        DIFF_FIXTURES / "retired-charms.json",
    )
    phantom = out["findings"]["phantom-charm"]
    assert len(phantom) == 1
    assert phantom[0]["name"] == "slurmrestd-legacy"
    assert phantom[0]["kind"] == "phantom-charm"
    assert phantom[0]["severity"] == "wrong-value"
    assert phantom[0]["code_citation"] is None
    assert phantom[0]["doc_citations"] == [
        {"file": "docs/howto/deploy.md", "line": 20}
    ]


def test_missing_retired_list_file_is_reported_not_invented(tmp_path):
    """A --retired-charms path that does not exist on disk must behave like
    "no list given" -- zero phantom findings, reported in skipped -- not
    crash and not silently invent candidates."""
    missing = tmp_path / "does-not-exist.json"
    out = run_cli(
        DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json", missing
    )
    assert out["findings"]["phantom-charm"] == []
    assert "does not exist" in out["skipped"]["phantom_charm_candidates"]["note"]["reason"]


def test_malformed_retired_list_shape_is_reported(tmp_path):
    bad = tmp_path / "bad-retired.json"
    bad.write_text(json.dumps({"not_retired_key": ["x"]}))
    out = run_cli(
        DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json", bad
    )
    assert out["findings"]["phantom-charm"] == []
    assert "unrecognised shape" in out["skipped"]["phantom_charm_candidates"]["note"]["reason"]


# --- ID derivation, per specs/finding-ids.md -------------------------------


def test_finding_id_shape():
    fid = diff_mod.finding_id("charm-inventory", "undocumented-charm", "slurmctld")
    assert fid.startswith("charm-inventory:slurmctld:")
    check, subject, hash8 = fid.split(":")
    assert check == "charm-inventory"
    assert subject == "slurmctld"
    assert len(hash8) == 8
    assert all(c in "0123456789abcdef" for c in hash8)


def test_finding_id_is_deterministic():
    a = diff_mod.finding_id("charm-inventory", "undocumented-charm", "slurmctld")
    b = diff_mod.finding_id("charm-inventory", "undocumented-charm", "slurmctld")
    assert a == b


def test_finding_id_excludes_line_numbers_and_paths():
    """specs/finding-ids.md: line numbers and file paths must not affect the
    ID -- only check/kind/subject do. This is implicit in finding_id()'s
    signature (it never takes a line or path), but assert the behavioural
    consequence directly: two findings with the same check/kind/subject
    collide, regardless of what citation they carry."""
    out = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    undoc = out["findings"]["undocumented-charm"]
    assert len(undoc) == 1
    expected_id = diff_mod.finding_id("charm-inventory", "undocumented-charm", "slurmctld")
    assert undoc[0]["id"] == expected_id


def test_normalise_subject_strips_and_lowercases():
    assert diff_mod.normalise_subject("  Slurmctld  ") == "slurmctld"


def test_normalise_subject_replaces_invalid_chars_with_hyphen():
    # Per spec: replace any run of characters outside [a-z0-9.-] with a
    # single '-', then strip leading/trailing '-'. Underscore is NOT in the
    # allowed set, so "filesystem_client" normalises to "filesystem-client".
    assert diff_mod.normalise_subject("filesystem_client") == "filesystem-client"
    assert diff_mod.normalise_subject("Foo Bar") == "foo-bar"
    assert diff_mod.normalise_subject("--leading-and-trailing--") == "leading-and-trailing"


def test_normalise_subject_empty_raises():
    import pytest

    with pytest.raises(diff_mod.SubjectEmptyError):
        diff_mod.normalise_subject("___")


def test_severity_assigned_deterministically_from_kind():
    assert diff_mod.SEVERITY_BY_KIND["undocumented-charm"] == "missing-entry"
    assert diff_mod.SEVERITY_BY_KIND["phantom-charm"] == "wrong-value"


def test_output_is_deterministic():
    out1 = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    out2 = run_cli(DIFF_FIXTURES / "code-facts.json", DIFF_FIXTURES / "doc-claims.json")
    assert out1 == out2


def test_citations_present_on_every_finding():
    """Every finding must carry file:line citations wherever both sides
    apply -- undocumented-charm has a code citation (no doc side exists to
    cite, since it is undocumented); phantom-charm has doc citations (no
    code side exists, since it is phantom)."""
    out = run_cli(
        DIFF_FIXTURES / "code-facts.json",
        DIFF_FIXTURES / "doc-claims.json",
        DIFF_FIXTURES / "retired-charms.json",
    )
    for f in out["findings"]["undocumented-charm"]:
        assert f["code_citation"] is not None
        assert f["code_citation"]["file"]
        assert f["code_citation"]["line"] is not None

    for f in out["findings"]["phantom-charm"]:
        assert f["doc_citations"]
        for c in f["doc_citations"]:
            assert c["file"]
            assert c["line"] is not None
