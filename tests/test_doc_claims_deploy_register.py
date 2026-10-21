"""Tests for doc_claims.py's `deploy-register` check, against
tests/fixtures/docs_deploy_register/ and
tests/fixtures/docs_deploy_register_bad_table/.

Fixture tree (see tests/fixtures/docs_deploy_register/):

    getting-started.md                     exercises every case under
                                            "Recognising a deploy
                                            instruction": a plain deploy, a
                                            line-continuation deploy, a
                                            non-name target (local path), a
                                            substitution target, a charm
                                            correctly registered+deployed,
                                            and a charm deployed twice
                                            (second site in a different
                                            file).
    howto/deploy-echo-again.md             second deploy site for
                                            orphan-charm.
    reference/underlying-projects-and-dependencies.md
                                            all six csv-table blocks, in
                                            miniature: bare-name+Source cells
                                            for the four project tables,
                                            [name](url) link cells for the
                                            two charm tables.
    reuse/deploy-sssd.txt                  the real-world prose-then-command
                                            shape from
                                            reuse/howto/setup/.../deploy-sssd.txt
                                            -- an inline-code prose mention
                                            with no name token, followed by
                                            the real instruction in a fenced
                                            block.

tests/fixtures/docs_deploy_register_bad_table/ is a separate, minimal fixture
tree holding one register page whose sole csv-table block's nearest heading
("Mystery charms") does not match any of the six known table identities --
the `unrecognised_register_table` loud-failure case.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DOCS_FIXTURES = FIXTURES_DIR / "docs_deploy_register"
BAD_TABLE_FIXTURES = FIXTURES_DIR / "docs_deploy_register_bad_table"


def run_cli(docs_root: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(EXTRACTORS_DIR / "doc_claims.py"),
            str(docs_root),
            "--check",
            "deploy-register",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- scope: .md AND .txt, with the same directory exclusions ------------- #


def test_scans_both_md_and_txt_files():
    out = run_cli(DOCS_FIXTURES)
    assert out["counts"]["md_files_scanned"] == 3  # getting-started, echo-again, register page
    assert out["counts"]["txt_files_scanned"] == 1  # reuse/deploy-sssd.txt


def test_check_field_is_deploy_register():
    out = run_cli(DOCS_FIXTURES)
    assert out["check"] == "deploy-register"
    for c in out["claims"]:
        assert c["check"] == "deploy-register"


# --- "Recognising a deploy instruction": the four explicit cases --------- #


def test_trailing_flags_take_first_token_only():
    """`juju deploy sssd --base ... --channel ...` -> name is "sssd" only."""
    out = run_cli(DOCS_FIXTURES)
    sssd_claims = [
        c
        for c in out["claims"]
        if c["kind"] == "deploy-instruction" and c["name"] == "sssd"
    ]
    assert len(sssd_claims) == 2  # getting-started.md AND reuse/deploy-sssd.txt
    files = {c["file"] for c in sssd_claims}
    assert files == {"getting-started.md", "reuse/deploy-sssd.txt"}


def test_line_continuation_is_one_deploy_not_two():
    """`juju deploy microceph \\` followed by continuation lines must yield
    exactly one `microceph` claim, from the first line only."""
    out = run_cli(DOCS_FIXTURES)
    microceph_claims = [
        c
        for c in out["claims"]
        if c["kind"] == "deploy-instruction" and c["name"] == "microceph"
    ]
    assert len(microceph_claims) == 1
    assert microceph_claims[0]["file"] == "getting-started.md"


def test_non_name_target_local_path_is_skipped_not_emitted():
    """`juju deploy ./local.charm` must not emit a claim -- it is reported
    under skipped.unparseable_deploy_target instead."""
    out = run_cli(DOCS_FIXTURES)
    assert all(
        c["kind"] != "deploy-instruction" or "local.charm" not in c["name"]
        for c in out["claims"]
    )
    unparseable = out["skipped"]["unparseable_deploy_target"]
    assert any("./local.charm" in u["raw"] for u in unparseable)


def test_substitution_target_is_skipped_not_emitted():
    """`juju deploy {{ widget_channel }}` is a hard stop for that line, not
    a guess -- must not be emitted, must be counted under
    unparseable_deploy_target."""
    out = run_cli(DOCS_FIXTURES)
    assert all(
        c["kind"] != "deploy-instruction" or "{{" not in c["name"]
        for c in out["claims"]
    )
    unparseable = out["skipped"]["unparseable_deploy_target"]
    assert any("{{ widget_channel }}" in u["raw"] for u in unparseable)


def test_unparseable_deploy_target_count_is_exactly_two():
    out = run_cli(DOCS_FIXTURES)
    assert len(out["skipped"]["unparseable_deploy_target"]) == 2


def test_inline_code_prose_mention_with_no_name_token_is_not_a_skip():
    """`` `juju deploy`{l=shell} to deploy SSSD `` has no name token on that
    line -- it must emit no claim, and (per spec) must NOT be counted as an
    unparseable target either; it is prose, not a malformed instruction."""
    out = run_cli(DOCS_FIXTURES)
    # The only unparseable targets are the local-path and substitution
    # cases, both in getting-started.md -- the prose line in
    # reuse/deploy-sssd.txt contributes neither a claim nor a skip entry.
    files_in_unparseable = {u["file"] for u in out["skipped"]["unparseable_deploy_target"]}
    assert "reuse/deploy-sssd.txt" not in files_in_unparseable


def test_charm_deployed_twice_yields_two_distinct_claims_not_deduped():
    """Unlike charm-inventory's one-claim-per-line dedup, deploy-register
    claims are per occurrence -- two deploy sites for orphan-charm must
    appear as two separate deploy-instruction claims (diff.py is what
    collapses them into one finding, not doc_claims.py)."""
    out = run_cli(DOCS_FIXTURES)
    orphan_claims = [
        c
        for c in out["claims"]
        if c["kind"] == "deploy-instruction" and c["name"] == "orphan-charm"
    ]
    assert len(orphan_claims) == 2
    files = {c["file"] for c in orphan_claims}
    assert files == {"getting-started.md", "howto/deploy-echo-again.md"}


# --- register-entry extraction: csv-table parsing, two namespaces -------- #


def test_six_register_tables_all_recognised():
    out = run_cli(DOCS_FIXTURES)
    tables = {c["table"] for c in out["claims"] if c["kind"] == "register-entry"}
    assert tables == {
        "core",
        "dependencies",
        "optional-dependencies",
        "machine-charms",
        "kubernetes-charms",
        "integrations",
    }
    assert out["skipped"]["unrecognised_register_table"] == []


def test_charm_table_names_read_from_link_text_not_raw_cell():
    """Per Step 0 fact 2: Machine/Kubernetes charm cells are
    [name](https://charmhub.io/name) links -- the register entry's name must
    be the link TEXT, never the raw cell (which would include the brackets
    and URL)."""
    out = run_cli(DOCS_FIXTURES)
    machine_entries = [
        c
        for c in out["claims"]
        if c["kind"] == "register-entry" and c["table"] == "machine-charms"
    ]
    names = {c["name"] for c in machine_entries}
    assert names == {"sssd", "echo-server"}
    for c in machine_entries:
        assert "[" not in c["name"]
        assert "charmhub.io" not in c["name"]


def test_project_table_names_read_from_bare_cell():
    """Per Step 0 fact 3: Core/Dependencies/Optional-dependencies cells are
    bare names followed by a [Source](...) link -- the name is the bare
    first cell, not a link text extraction."""
    out = run_cli(DOCS_FIXTURES)
    dependencies_entries = [
        c
        for c in out["claims"]
        if c["kind"] == "register-entry" and c["table"] == "dependencies"
    ]
    assert {c["name"] for c in dependencies_entries} == {"widget-project"}


def test_register_entries_carry_table_field_on_every_entry():
    out = run_cli(DOCS_FIXTURES)
    register_entries = [c for c in out["claims"] if c["kind"] == "register-entry"]
    assert register_entries  # non-empty, so this test is meaningful
    for c in register_entries:
        assert c["table"] in {
            "core",
            "dependencies",
            "optional-dependencies",
            "machine-charms",
            "kubernetes-charms",
            "integrations",
        }


def test_unrecognised_register_table_is_loud_when_heading_does_not_match():
    """A csv-table block whose nearest heading does not match any of the six
    known table identities must be reported under
    skipped.unrecognised_register_table -- never silently dropped."""
    out = run_cli(BAD_TABLE_FIXTURES)
    unrecognised = out["skipped"]["unrecognised_register_table"]
    assert len(unrecognised) == 1
    assert unrecognised[0]["file"] == "reference/underlying-projects-and-dependencies.md"
    assert "Mystery charms" in unrecognised[0]["reason"]
    # And the row inside that block must NOT silently become a register
    # entry under some default/guessed table.
    assert not any(c["kind"] == "register-entry" for c in out["claims"])


# --- citations, determinism, relative paths ------------------------------ #


def test_every_claim_has_file_and_line():
    out = run_cli(DOCS_FIXTURES)
    for c in out["claims"]:
        assert c["file"]
        assert c["line"] is not None


def test_file_paths_relative_never_absolute():
    out = run_cli(DOCS_FIXTURES)
    for c in out["claims"]:
        assert not c["file"].startswith("/")
        assert str(DOCS_FIXTURES) not in c["file"]


def test_output_is_deterministic():
    out1 = run_cli(DOCS_FIXTURES)
    out2 = run_cli(DOCS_FIXTURES)
    assert out1 == out2


def test_excluded_by_scope_reported():
    """Same directory exclusions as charm-inventory -- zero in this fixture
    tree (no .git/.github/.agents/contributing content), but the key must
    still be present per the "report what you skipped" convention."""
    out = run_cli(DOCS_FIXTURES)
    assert "excluded_by_scope" in out["skipped"]
    assert out["skipped"]["excluded_by_scope"]["count"] == 0
