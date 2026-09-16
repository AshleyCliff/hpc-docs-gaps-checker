#!/usr/bin/env python3
"""Assert the inputs tree was not modified. Layer 3 of read-only enforcement.

Every git repo under <inputs>/repos/ must be clean, and the tree must still be
unwritable. Exits non-zero and loudly on any violation: a dirty inputs tree
invalidates the run, because findings can no longer be attributed to the
pinned SHAs.

Also cross-checks HEAD against manifest.lock, if present, so a silent checkout
of a different ref is caught too.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO_ROOT.parent / "hpc-docs-gaps-checker-inputs"
LOCK_NAME = "manifest.lock"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def load_lock() -> dict[str, str]:
    path = REPO_ROOT / LOCK_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        log(f"warn: {LOCK_NAME} is not valid JSON; skipping SHA cross-check")
        return {}
    return {r["name"]: r["sha"] for r in data.get("repos", []) if "sha" in r}


def find_repos(repos_dir: Path) -> list[Path]:
    if not repos_dir.is_dir():
        return []
    return sorted(p for p in repos_dir.iterdir() if (p / ".git").is_dir())


def writable_paths(root: Path, limit: int = 10) -> list[Path]:
    """Paths that still carry a write bit. Should be empty after --freeze."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in [*dirnames, *filenames]:
            p = d / name
            try:
                if p.is_symlink():
                    continue
                if p.lstat().st_mode & 0o222:
                    found.append(p)
                    if len(found) >= limit:
                        return found
            except OSError:
                continue
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "dest",
        nargs="?",
        type=Path,
        default=DEFAULT_DEST,
        help="the inputs tree (default: ../hpc-docs-gaps-checker-inputs)",
    )
    ap.add_argument(
        "--skip-perm-check",
        action="store_true",
        help="skip the write-bit scan (it is slow on large trees)",
    )
    args = ap.parse_args(argv)

    dest: Path = args.dest
    repos_dir = dest / "repos"
    failures: list[str] = []

    if not dest.exists():
        log(f"error: inputs tree not found: {dest}")
        return 1

    repos = find_repos(repos_dir)
    if not repos:
        log(f"error: no git repos under {repos_dir}")
        log("  a run against an empty inputs tree finds nothing and proves nothing")
        return 1

    locked = load_lock()

    for path in repos:
        name = path.name

        rc, porcelain = git(["status", "--porcelain"], path)
        if rc != 0:
            failures.append(f"{name}: git status failed")
            continue
        if porcelain:
            n = len(porcelain.splitlines())
            failures.append(f"{name}: WORKING TREE DIRTY ({n} change(s))")
            for line in porcelain.splitlines()[:5]:
                log(f"    {line}")

        rc, head = git(["rev-parse", "HEAD"], path)
        if rc != 0:
            failures.append(f"{name}: cannot resolve HEAD")
            continue

        expected = locked.get(name)
        if expected and head != expected:
            failures.append(
                f"{name}: HEAD {head[:12]} != locked {expected[:12]}"
            )

        rc, stash = git(["stash", "list"], path)
        if rc == 0 and stash:
            failures.append(f"{name}: stash is non-empty")

    if not args.skip_perm_check:
        writable = writable_paths(dest)
        if writable:
            failures.append(
                f"inputs tree is writable ({len(writable)}+ paths); "
                "was it unfrozen?"
            )
            for p in writable[:5]:
                log(f"    {p}")

    if failures:
        log("")
        log("=" * 72)
        log("READ-ONLY ASSERTION FAILED")
        log("")
        for f in failures:
            log(f"  {f}")
        log("")
        log("The inputs tree must be pristine. Findings from this run cannot be")
        log("attributed to the pinned SHAs. Investigate before trusting output;")
        log("re-freeze with `sync.py --freeze`.")
        log("=" * 72)
        return 1

    checked = f"{len(repos)} repo(s)"
    extra = "" if args.skip_perm_check else ", permissions verified"
    log(f"OK: {checked} clean{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
