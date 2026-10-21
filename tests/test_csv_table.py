"""Unit tests for the shared extractors/csv_table.py module.

Exercises the parser directly (not via subprocess), since it has no CLI of
its own -- it is a library used by doc_claims.py's deploy-register path.
"""

from __future__ import annotations

import csv_table


def test_link_text_extracts_name_from_markdown_link():
    assert csv_table.link_text("[sssd](https://charmhub.io/sssd)") == "sssd"


def test_link_text_returns_none_for_non_link_cell():
    assert csv_table.link_text("sssd-operator") is None
    assert csv_table.link_text("") is None


def test_link_text_strips_surrounding_whitespace_before_matching():
    assert csv_table.link_text("  [apptainer](https://charmhub.io/apptainer)  ") == "apptainer"


def test_parses_single_csv_table_block():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        ":header: >\n"
        ": project, source code\n"
        "\n"
        "widget-charms, [Source](https://example.com)\n"
        ":::\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert notes == []
    assert len(blocks) == 1
    assert blocks[0]["heading"] == "Core"
    assert len(blocks[0]["rows"]) == 1
    assert blocks[0]["rows"][0]["cells"][0] == "widget-charms"


def test_parses_multiple_blocks_with_distinct_headings():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        "widget-a\n"
        ":::\n"
        "\n"
        "### Dependencies\n"
        "\n"
        ":::{csv-table}\n"
        "widget-b\n"
        ":::\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert notes == []
    assert len(blocks) == 2
    assert [b["heading"] for b in blocks] == ["Core", "Dependencies"]


def test_blank_lines_and_myst_field_lines_inside_fence_are_not_rows():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        ":header: >\n"
        ": project, source code\n"
        ":widths: 15, 10\n"
        "\n"
        "widget-a, [Source](https://example.com)\n"
        ":::\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert notes == []
    assert len(blocks[0]["rows"]) == 1


def test_non_csv_table_directives_are_ignored():
    """A fence around an unrelated directive (e.g. admonition) must not be
    mistaken for a csv-table block."""
    text = (
        ":::{admonition} Blank cells\n"
        ":class: note\n"
        "\n"
        "Some text that could look like a row, but is not inside a csv-table.\n"
        ":::\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert blocks == []
    assert notes == []


def test_unclosed_fence_at_eof_is_reported_but_rows_still_captured():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        "widget-a\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert len(blocks) == 1
    assert len(blocks[0]["rows"]) == 1
    assert any("never closed" in n["reason"] for n in notes)


def test_mismatched_fence_close_length_is_reported():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        "widget-a\n"
        "::::\n"  # four colons closing a three-colon open -- mismatch
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert any("did not match open stack" in n["reason"] for n in notes)


def test_line_numbers_are_one_based_and_correct():
    text = (
        "### Core\n"
        "\n"
        ":::{csv-table}\n"
        "widget-a\n"
        ":::\n"
    )
    blocks, _ = csv_table.parse_csv_tables(text)
    assert blocks[0]["fence_line"] == 3
    assert blocks[0]["rows"][0]["line"] == 4
    assert blocks[0]["heading_line"] == 1


def test_row_with_blank_second_cell_parses_without_error():
    """Real-world shape from the Machine charms table: `[apptainer](url), ,
    [Actions](url)` -- a blank middle cell, which csv.reader must parse as
    an empty string, not raise on."""
    text = (
        "### Machine charms\n"
        "\n"
        ":::{csv-table}\n"
        "[apptainer](https://charmhub.io/apptainer), , [Actions](https://charmhub.io/apptainer/actions)\n"
        ":::\n"
    )
    blocks, notes = csv_table.parse_csv_tables(text)
    assert notes == []
    cells = blocks[0]["rows"][0]["cells"]
    assert cells[0] == "[apptainer](https://charmhub.io/apptainer)"
    assert cells[1] == ""
