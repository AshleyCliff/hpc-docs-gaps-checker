"""Shared `csv-table` body parser, for any check that needs to read a MyST
`:::{csv-table}` directive out of raw Markdown text.

Built for `deploy-register` (specs/deploy-register-consistency.md), but
written to be reused by later checks that read the same register page for
config options and actions -- see AGENTS.md's survey note on
`reference/underlying-projects-and-dependencies.md`'s `charm, configuration
options, actions` table.

No Sphinx build is available (AGENTS.md "Working without a Sphinx build"), so
this reads the fence and its rows as plain text, using the same colon-run
fence-nesting approach `doc_claims.py` uses for charm-mention context
classification.

Two things this module deliberately does NOT do:

- It does not resolve which semantic table (Core, Machine charms, ...) a
  block belongs to -- it only records the nearest preceding Markdown heading
  text, verbatim. Mapping that heading to a known table identity is the
  caller's job, because the mapping is check-specific.
- It does not decide whether a cell is a link or a bare name -- `link_text()`
  is offered as a separate helper so callers can apply the right rule per
  table (see "Two namespaces" in specs/deploy-register-consistency.md: some
  tables hold bare names, others hold `[name](url)` links).
"""

from __future__ import annotations

import csv
import io
import re

FENCE_OPEN_RE = re.compile(r"^(:{3,})\{([A-Za-z0-9_-]+)\}")
FENCE_CLOSE_RE = re.compile(r"^(:{3,})\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]*)\)$")

TABLE_DIRECTIVE = "csv-table"


def link_text(cell: str) -> str | None:
    """`[name](url)` -> `name`; `None` if `cell` is not a single Markdown link.

    Per specs/deploy-register-consistency.md: charm names in the Machine and
    Kubernetes tables must be read from link *text*, never from the raw
    cell -- this is the only extraction route for that shape.
    """
    m = LINK_RE.match(cell.strip())
    if m is None:
        return None
    return m.group(1)


def parse_csv_tables(text: str) -> tuple[list[dict], list[dict]]:
    """Every `:::{csv-table}` block in `text`.

    Returns `(blocks, skip_notes)`.

    Each block:
        {
            "heading": str | None,       # nearest preceding heading text
            "heading_line": int | None,  # 1-based line of that heading
            "fence_line": int,           # 1-based line of the opening fence
            "rows": [
                {"cells": [str, ...], "line": int},   # 1-based source line
                ...
            ],
        }

    `skip_notes` record shapes this parser could not interpret -- a
    mismatched fence-close length, an unclosed fence at EOF, or a data line
    that did not parse as CSV. This module never raises on them; it is the
    caller's job to decide how loud to be (see `doc_claims.py`'s
    `unrecognised_register_table`, which must be loud per
    specs/deploy-register-consistency.md).

    Lines inside a csv-table fence that start with `:` are MyST field
    directives (`:header:`, `:widths:`, and the continuation line for a
    multi-line `:header:` value) and are skipped as non-data, not treated as
    rows -- confirmed against the real pinned docs tree (Step 0, fact 1).
    """
    blocks: list[dict] = []
    notes: list[dict] = []

    fence_stack: list[tuple[int, str]] = []  # (colon-run-length, directive-name)
    current_heading: str | None = None
    current_heading_line: int | None = None

    active_block: dict | None = None
    active_fence_depth: int | None = None

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not fence_stack:
            hm = HEADING_RE.match(line)
            if hm:
                current_heading = hm.group(2)
                current_heading_line = lineno
                continue

        open_m = FENCE_OPEN_RE.match(line)
        close_m = FENCE_CLOSE_RE.match(line) if not open_m else None

        if open_m:
            depth, name = len(open_m.group(1)), open_m.group(2)
            fence_stack.append((depth, name))
            if name == TABLE_DIRECTIVE and active_block is None:
                active_block = {
                    "heading": current_heading,
                    "heading_line": current_heading_line,
                    "fence_line": lineno,
                    "rows": [],
                }
                active_fence_depth = len(fence_stack)
            continue

        if close_m:
            n = len(close_m.group(1))
            if fence_stack and fence_stack[-1][0] == n:
                fence_stack.pop()
                if active_block is not None and len(fence_stack) < active_fence_depth:
                    blocks.append(active_block)
                    active_block = None
                    active_fence_depth = None
            else:
                notes.append(
                    {
                        "line": lineno,
                        "reason": f"fence close ':'x{n} did not match open stack "
                        f"{fence_stack!r}",
                    }
                )
            continue

        if active_block is not None:
            stripped = line.strip()
            if stripped == "" or stripped.startswith(":"):
                continue  # blank line, or a MyST field directive (:header:, :widths:, ...)
            try:
                row = next(csv.reader(io.StringIO(line)))
            except csv.Error as exc:
                notes.append({"line": lineno, "reason": f"unparseable csv-table row: {exc}"})
                continue
            cells = [c.strip() for c in row]
            active_block["rows"].append({"cells": cells, "line": lineno})

    if fence_stack:
        notes.append(
            {
                "line": None,
                "reason": f"unclosed fence(s) at EOF: {fence_stack!r}",
            }
        )
    if active_block is not None:
        # The csv-table fence itself never closed. Still surface what rows
        # were captured up to EOF -- discarding them would be a second,
        # silent failure on top of the first -- but flag it loudly via notes.
        blocks.append(active_block)
        notes.append(
            {
                "line": active_block["fence_line"],
                "reason": "csv-table fence never closed before EOF; "
                "rows captured up to EOF may be incomplete",
            }
        )

    return blocks, notes
