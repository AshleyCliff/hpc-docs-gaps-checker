#!/usr/bin/env python3
"""Emit charm facts for the `charm-inventory` check.

Scope (per specs/charm-inventory.md): every `charmcraft.yaml` under the given
root, excluding anything under a `.git/` directory. One fact is emitted per
`charmcraft.yaml` that has a readable `name:` key.

Deterministic: no network, no clock, no model. Output is sorted so two runs
against the same tree diff cleanly.

Usage:
    code_facts.py <repos-root>   # e.g. /inputs/repos

Prints a single JSON object to stdout:
    {
      "check": "charm-inventory",
      "facts": [ {...one per charm...} ],
      "skipped": { ... },
      "counts": { ... }
    }

Paths in output are relative to <repos-root>, never absolute -- an absolute
path would embed the mount point (e.g. /inputs/repos) into committed output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("error: PyYAML is required (see workshop.yaml's install-deps action)")

CHECK = "charm-inventory"
FILENAME = "charmcraft.yaml"


def find_charmcraft_files(root: Path) -> list[Path]:
    """Every charmcraft.yaml under root, excluding .git/, sorted for determinism."""
    found: list[Path] = []
    for path in root.rglob(FILENAME):
        if ".git" in path.parts:
            continue
        found.append(path)
    return sorted(found)


def line_of_name_key(text: str) -> int | None:
    """1-based line number of the top-level `name:` key, or None if absent.

    We need the *line the name key itself appears on*, which a YAML round-trip
    through PyYAML does not preserve by default. Scan raw lines for a
    top-level (column 0) `name:` key -- charmcraft.yaml's schema requires
    `name` to be a top-level key, never nested, so this is unambiguous for
    well-formed input.
    """
    for i, line in enumerate(text.splitlines(), start=1):
        if line.startswith("name:"):
            return i
    return None


def fixture_suspect(rel_path: str) -> bool:
    """True if any path segment contains a `test-` or `-test` substring.

    Per spec: "Set fixture_suspect: true on any charm whose path contains a
    test- or -test path segment." Deliberately narrow -- do not widen this
    heuristic. See specs/charm-inventory.md "Fixture charms".
    """
    for segment in Path(rel_path).parts:
        if "test-" in segment or "-test" in segment:
            return True
    return False


def repo_of(rel_path: str) -> str:
    """First path segment is the repo name, by construction of inputs/repos/<repo>/..."""
    return Path(rel_path).parts[0]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: code_facts.py <repos-root>", file=sys.stderr)
        return 2

    root = Path(argv[1])
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    charmcraft_files = find_charmcraft_files(root)

    facts: list[dict] = []
    skipped_unparseable: list[dict] = []
    skipped_missing_name: list[dict] = []
    skipped_unreadable: list[dict] = []

    extra_test_segments: list[str] = []

    for abs_path in charmcraft_files:
        rel_path = str(abs_path.relative_to(root))

        try:
            text = abs_path.read_text(encoding="utf-8")
        except OSError as exc:
            skipped_unreadable.append({"file": rel_path, "reason": str(exc)})
            continue
        except UnicodeDecodeError as exc:
            skipped_unreadable.append({"file": rel_path, "reason": f"not valid UTF-8: {exc}"})
            continue

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            skipped_unparseable.append({"file": rel_path, "reason": str(exc)})
            continue

        if not isinstance(data, dict):
            skipped_unparseable.append(
                {"file": rel_path, "reason": f"top level is not a mapping (got {type(data).__name__})"}
            )
            continue

        if "name" not in data:
            skipped_missing_name.append({"file": rel_path})
            continue

        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            skipped_missing_name.append(
                {"file": rel_path, "reason": f"'name' is not a non-empty string (got {name!r})"}
            )
            continue

        line = line_of_name_key(text)
        if line is None:
            # The key parsed via YAML but our raw-line scan did not find it at
            # column 0. This can legitimately happen if `name:` is indented
            # (e.g. nested under something unexpected) -- which would be an
            # unusual charmcraft.yaml shape worth surfacing rather than
            # silently guessing a line number.
            skipped_unparseable.append(
                {
                    "file": rel_path,
                    "reason": "parsed 'name' key via YAML but could not locate its line "
                    "via raw-text scan (not at column 0); charmcraft.yaml shape may be unusual",
                }
            )
            continue

        is_fixture = fixture_suspect(rel_path)
        if is_fixture and Path(rel_path).name != FILENAME:
            pass  # unreachable; defensive only

        facts.append(
            {
                "check": CHECK,
                "kind": "charm",
                "name": name,
                "repo": repo_of(rel_path),
                "file": rel_path,
                "line": line,
                "fixture_suspect": is_fixture,
            }
        )

    # Report test-/-test path segments regardless of whether the charm parsed,
    # per Step 0's "raw observation" requirement -- this is informational, not
    # a skip category.
    for abs_path in charmcraft_files:
        rel_path = str(abs_path.relative_to(root))
        if fixture_suspect(rel_path):
            extra_test_segments.append(rel_path)

    facts.sort(key=lambda f: (f["file"],))

    output = {
        "check": CHECK,
        "facts": facts,
        "skipped": {
            "unparseable_yaml": sorted(skipped_unparseable, key=lambda x: x["file"]),
            "missing_name_key": sorted(skipped_missing_name, key=lambda x: x["file"]),
            "unreadable_file": sorted(skipped_unreadable, key=lambda x: x["file"]),
            "excluded_by_scope": {"count": 0, "paths": []},
        },
        "counts": {
            "charmcraft_files_found": len(charmcraft_files),
            "charms_emitted": len(facts),
        },
        "fixture_suspect_paths": sorted(extra_test_segments),
    }

    print(json.dumps(output, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
