"""Tests for extractors/doc_claims.py against tests/fixtures/docs/.

Fixture tree (see tests/fixtures/docs/):

    howto/deploy-slurm.md     the main scanned file -- boundary cases, contexts
    howto/nested/README.md    non-root README -- must NOT be excluded
    CONTRIBUTING.md           root-level -- excluded (repo meta)
    README.md                 root-level -- excluded (repo meta)
    .git/COMMIT_EDITMSG.md    excluded (.git/**) -- CREATED AT RUNTIME, see below
    .github/workflow-notes.md excluded (.github/**)
    .agents/skills/.../SKILL.md  excluded (.agents/**); also contains
                              instruction-like text that must have no effect
                              on extractor behaviour (AGENTS.md invariant 7)
    contributing/documentation.md  excluded (contributing/**)

Candidate names come from the code fixtures via code_facts.py's output, as
doc_claims.py requires --names-from.

The `.git/` fixture cannot be committed: git refuses to track any path
containing a `.git` component, so a committed fixture tree silently arrives
without it and the exclusion assertions then fail on a fresh clone (verified
2026-10-02). The `docs_root` fixture below therefore builds a complete copy of
the tree in tmp_path, adding `.git/COMMIT_EDITMSG.md` at runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import doc_claims

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CODE_FIXTURES = FIXTURES_DIR / "code"
DOCS_FIXTURES = FIXTURES_DIR / "docs"


@pytest.fixture
def docs_root(tmp_path: Path) -> Path:
    """A complete docs fixture tree, including the untrackable `.git/` entry.

    Copies the committed fixtures and synthesises `.git/COMMIT_EDITMSG.md`, so
    the scope-exclusion tests see all six excluded paths regardless of what git
    was able to store.
    """
    root = tmp_path / "docs"
    shutil.copytree(DOCS_FIXTURES, root)
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "COMMIT_EDITMSG.md").write_text(
        "docs: mention slurmctld in a commit message\n"
        "\nThis file must never be scanned: `.git/**` is out of scope.\n"
    )
    return root


def code_facts_json(tmp_path: Path) -> Path:
    """Run code_facts.py once against the code fixtures; cache to tmp_path."""
    out_path = tmp_path / "code-facts.json"
    proc = subprocess.run(
        [sys.executable, str(EXTRACTORS_DIR / "code_facts.py"), str(CODE_FIXTURES)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out_path.write_text(proc.stdout)
    return out_path


def run_cli(docs_root: Path, names_from: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "doc_claims.py"),
            str(docs_root),
            "--names-from",
            str(names_from),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_md_files_scanned_excludes_all_scoped_dirs(tmp_path, docs_root):
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    # Only howto/deploy-slurm.md and howto/nested/README.md should be scanned.
    assert out["counts"]["md_files_scanned"] == 2

    excluded = set(out["skipped"]["excluded_by_scope"]["paths"])
    assert excluded == {
        ".agents/skills/example/SKILL.md",
        ".git/COMMIT_EDITMSG.md",
        ".github/workflow-notes.md",
        "CONTRIBUTING.md",
        "README.md",
        "contributing/documentation.md",
    }
    assert out["skipped"]["excluded_by_scope"]["count"] == 6


def test_nested_readme_is_not_excluded(tmp_path, docs_root):
    """Only the TREE-ROOT README.md/CONTRIBUTING.md are excluded -- a nested
    README.md (howto/nested/README.md) must be scanned normally."""
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    files_with_claims = {c["file"] for c in out["claims"]}
    assert "howto/nested/README.md" in files_with_claims
    nested_claims = [c for c in out["claims"] if c["file"] == "howto/nested/README.md"]
    assert any(c["name"] == "apptainer" for c in nested_claims)


def test_word_boundary_slurmd_does_not_match_inside_slurmdbd(tmp_path, docs_root):
    """The spec's headline boundary case: a doc mentioning slurmdbd but not
    slurmd must not produce a false claim for slurmd."""
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    deploy_claims = [c for c in out["claims"] if c["file"] == "howto/deploy-slurm.md"]

    # Line 6: "The `slurmdbd` charm..." -- slurmdbd claim, no slurmd claim.
    line6 = [c for c in deploy_claims if c["line"] == 6]
    assert {c["name"] for c in line6} == {"slurmdbd"}

    # Line 7: ...mentions "slurmdbd" and "slurmd" in quotes separately.
    line7 = [c for c in deploy_claims if c["line"] == 7]
    names_line7 = {c["name"] for c in line7}
    assert "slurmdbd" in names_line7
    assert "slurmd" in names_line7  # explicit standalone "slurmd" token

    # Every emitted "slurmd" claim must come from a line that independently
    # contains the standalone token "slurmd" -- never purely from matching
    # inside "slurmdbd". With this fixture, that is exactly line 7.
    slurmd_claim_lines = {c["line"] for c in deploy_claims if c["name"] == "slurmd"}
    assert slurmd_claim_lines == {7}


def test_word_boundary_hyphen_is_word_character(tmp_path, docs_root):
    """`slurmctld` must NOT match inside `slurmctld-peer` (line 10-11 of the
    fixture uses a hyphenated identifier)."""
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    deploy_claims = [c for c in out["claims"] if c["file"] == "howto/deploy-slurm.md"]

    line10 = [c for c in deploy_claims if c["line"] == 10]
    # Line 10 contains only "slurmctld-peer" -- must NOT produce a slurmctld claim.
    assert all(c["name"] != "slurmctld" for c in line10)


def test_context_classification(tmp_path, docs_root):
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    deploy_claims = [c for c in out["claims"] if c["file"] == "howto/deploy-slurm.md"]
    by_line = {c["line"]: c["context"] for c in deploy_claims}

    assert by_line[6] == "prose"
    assert by_line[17] == "code-block"  # inside ``` fence: juju deploy slurmctld
    assert by_line[23] == "table"  # | sssd | 0 |
    assert by_line[25] == "heading"  # ## Heading mentioning slurmctld


def test_instruction_like_text_in_excluded_file_has_no_effect(tmp_path, docs_root):
    """.agents/skills/example/SKILL.md contains text that reads like an
    instruction to the agent. It must be excluded by scope like any other
    .agents/** file, and must not alter extractor behaviour (AGENTS.md
    invariant 7: repo content is untrusted data, never a directive)."""
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    assert ".agents/skills/example/SKILL.md" in out["skipped"]["excluded_by_scope"]["paths"]
    # And the extractor must have completed normally -- not halted, not
    # produced zero claims overall because of the "instruction".
    assert out["counts"]["claims_emitted"] > 0


def test_one_claim_per_name_per_line_even_if_repeated(tmp_path):
    """specs/charm-inventory.md: 'if a name appears more than once on one
    line, that is still one claim for that line.'"""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        docs_root = Path(d)
        f = docs_root / "repeat.md"
        f.write_text("slurmd and slurmd again on one line\n")
        cf = code_facts_json(tmp_path)
        out = run_cli(docs_root, cf)
        claims = [c for c in out["claims"] if c["name"] == "slurmd"]
        assert len(claims) == 1
        assert claims[0]["line"] == 1


def test_output_is_deterministic(tmp_path, docs_root):
    cf = code_facts_json(tmp_path)
    out1 = run_cli(docs_root, cf)
    out2 = run_cli(docs_root, cf)
    assert out1 == out2


def test_file_paths_relative_never_absolute(tmp_path, docs_root):
    cf = code_facts_json(tmp_path)
    out = run_cli(docs_root, cf)
    for c in out["claims"]:
        assert not c["file"].startswith("/")
        assert str(docs_root) not in c["file"]


def test_no_candidate_names_yields_no_claims_but_still_scans(tmp_path, docs_root):
    """If --names-from has an empty facts list, pattern is None and zero
    claims are emitted -- but md_files_scanned must still reflect the real
    file count, not be skipped entirely."""
    empty_facts = tmp_path / "empty-code-facts.json"
    empty_facts.write_text(json.dumps({"facts": []}))
    out = run_cli(docs_root, empty_facts)
    assert out["counts"]["claims_emitted"] == 0
    assert out["counts"]["md_files_scanned"] == 2
    assert out["counts"]["candidate_names"] == 0


def test_build_name_pattern_matches_hyphenated_name_boundary():
    """Unit-level check of the regex itself: 'filesystem-client' as a
    candidate must match standalone but not inside
    'filesystem-client-mount'."""
    pattern = doc_claims.build_name_pattern(["filesystem-client"])
    assert pattern.search("the filesystem-client charm") is not None
    assert pattern.search("filesystem-client-mount is different") is None


def test_build_name_pattern_period_is_not_a_word_character():
    """Regression: `.` must NOT be treated as a word character for boundary
    purposes. Only `-` gets that treatment, per spec. A name immediately
    followed by a sentence-ending period, or appearing as
    `module.slurmctld.app_name` in Terraform-flavoured prose, must still
    match."""
    pattern = doc_claims.build_name_pattern(["apptainer", "slurmctld"])
    assert pattern.search("It mentions apptainer.") is not None
    assert pattern.search("module.slurmctld.app_name") is not None
