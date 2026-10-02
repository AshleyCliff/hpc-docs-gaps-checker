"""Tests for extractors/code_facts.py against tests/fixtures/code/.

Fixture tree (see tests/fixtures/code/):

    apptainer-operator/charmcraft.yaml                           name: apptainer   (dir != name)
    sssd-operator/charmcraft.yaml                                name: sssd        (dir != name)
    slurm-charms/charms/slurmctld/charmcraft.yaml                name: slurmctld
    slurm-charms/charms/slurmd/charmcraft.yaml                   name: slurmd
    slurm-charms/charms/slurmdbd/charmcraft.yaml                 name: slurmdbd
    filesystem-charms/charms/test-mount-client/charmcraft.yaml   name: test-mount-client, fixture_suspect
    broken-charms/no-name/charmcraft.yaml                        no `name:` key
    broken-charms/malformed-yaml/charmcraft.yaml                 invalid YAML

8 files total; 6 emit a fact; 2 are skipped (1 unparseable, 1 missing-name).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import code_facts

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CODE_FIXTURES = FIXTURES_DIR / "code"


def run_cli(root: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(EXTRACTORS_DIR / "code_facts.py"), str(root)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_finds_all_charmcraft_files_excluding_git():
    files = code_facts.find_charmcraft_files(CODE_FIXTURES)
    rels = sorted(str(p.relative_to(CODE_FIXTURES)) for p in files)
    assert rels == [
        "apptainer-operator/charmcraft.yaml",
        "broken-charms/malformed-yaml/charmcraft.yaml",
        "broken-charms/no-name/charmcraft.yaml",
        "filesystem-charms/charms/test-mount-client/charmcraft.yaml",
        "slurm-charms/charms/slurmctld/charmcraft.yaml",
        "slurm-charms/charms/slurmd/charmcraft.yaml",
        "slurm-charms/charms/slurmdbd/charmcraft.yaml",
        "sssd-operator/charmcraft.yaml",
    ]


def test_counts():
    out = run_cli(CODE_FIXTURES)
    assert out["counts"]["charmcraft_files_found"] == 8
    assert out["counts"]["charms_emitted"] == 6


def test_name_is_read_from_name_key_not_directory():
    """The live trap from the spec: directory != declared name."""
    out = run_cli(CODE_FIXTURES)
    by_file = {f["file"]: f for f in out["facts"]}

    apptainer = by_file["apptainer-operator/charmcraft.yaml"]
    assert apptainer["name"] == "apptainer"
    assert apptainer["repo"] == "apptainer-operator"

    sssd = by_file["sssd-operator/charmcraft.yaml"]
    assert sssd["name"] == "sssd"
    assert sssd["repo"] == "sssd-operator"


def test_fixture_suspect_flagged_for_test_dash_segment():
    out = run_cli(CODE_FIXTURES)
    by_name = {f["name"]: f for f in out["facts"]}
    assert by_name["test-mount-client"]["fixture_suspect"] is True
    # Everything else must be False -- the heuristic must not over-fire.
    for name, fact in by_name.items():
        if name != "test-mount-client":
            assert fact["fixture_suspect"] is False, name


def test_missing_name_key_is_skipped_and_reported():
    out = run_cli(CODE_FIXTURES)
    skipped = out["skipped"]["missing_name_key"]
    assert len(skipped) == 1
    assert skipped[0]["file"] == "broken-charms/no-name/charmcraft.yaml"
    # And it must not appear in facts.
    assert all(f["file"] != "broken-charms/no-name/charmcraft.yaml" for f in out["facts"])


def test_malformed_yaml_is_skipped_and_reported():
    out = run_cli(CODE_FIXTURES)
    skipped = out["skipped"]["unparseable_yaml"]
    assert len(skipped) == 1
    assert skipped[0]["file"] == "broken-charms/malformed-yaml/charmcraft.yaml"
    assert all(f["file"] != "broken-charms/malformed-yaml/charmcraft.yaml" for f in out["facts"])


def test_line_is_the_name_key_line_not_file_start():
    out = run_cli(CODE_FIXTURES)
    by_name = {f["name"]: f for f in out["facts"]}
    # Every fixture file in tests/fixtures/code/ has `name:` on line 2.
    assert by_name["slurmctld"]["line"] == 2
    assert by_name["apptainer"]["line"] == 2


def test_file_paths_are_relative_never_absolute():
    out = run_cli(CODE_FIXTURES)
    for f in out["facts"]:
        assert not f["file"].startswith("/")
        assert str(CODE_FIXTURES) not in f["file"]


def test_output_is_deterministic_across_runs():
    out1 = run_cli(CODE_FIXTURES)
    out2 = run_cli(CODE_FIXTURES)
    assert out1 == out2


def test_excluded_by_scope_is_zero_for_code_side():
    """code_facts.py has no scope exclusions (unlike doc_claims.py) -- the
    key must still be present and zero, per the "report what you skipped"
    convention: a zero count is a result, not an omission."""
    out = run_cli(CODE_FIXTURES)
    assert out["skipped"]["excluded_by_scope"] == {"count": 0, "paths": []}


def test_unreadable_file_handling(tmp_path):
    """A charmcraft.yaml that cannot be read (permission denied) is reported
    under skipped.unreadable_file, not silently dropped or crashed on."""
    bad_dir = tmp_path / "unreadable-charm"
    bad_dir.mkdir()
    bad_file = bad_dir / "charmcraft.yaml"
    bad_file.write_text("name: unreadable\n")
    bad_file.chmod(0o000)
    try:
        out = run_cli(tmp_path)
    finally:
        bad_file.chmod(0o644)  # restore so tmp_path cleanup can remove it

    assert out["counts"]["charmcraft_files_found"] == 1
    assert out["counts"]["charms_emitted"] == 0
    assert len(out["skipped"]["unreadable_file"]) == 1
    assert out["skipped"]["unreadable_file"][0]["file"] == "unreadable-charm/charmcraft.yaml"
