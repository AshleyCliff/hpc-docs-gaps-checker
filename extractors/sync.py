#!/usr/bin/env python3
"""Clone the pinned input repos and freeze them read-only.

This script owns the inputs tree. Nothing else creates, updates, or unfreezes
it. See "Read-only enforcement" in AGENTS.md.

Modes:
  --freeze              clone/checkout every pin, then chmod -R a-w  (default)
  --resolve             print current head SHA per repo; write nothing
  --report-staleness    report how far each pin is behind its branch
  --unfreeze            chmod -R u+w and stop (for a manual refresh)

Staleness is advisory. This script never edits manifest.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("error: PyYAML is required (uv pip install pyyaml)")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO_ROOT.parent / "hpc-docs-gaps-checker-inputs"
LOCK_NAME = "manifest.lock"


class SyncError(RuntimeError):
    pass


@dataclass
class Pin:
    name: str
    repo: str
    kind: str
    ref: str | None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}.git"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def run(
    cmd: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise SyncError(
            f"command failed: {' '.join(cmd)}\n"
            f"  cwd: {cwd or Path.cwd()}\n"
            f"  stderr: {proc.stderr.strip()}"
        )
    return proc


def load_manifest(path: Path) -> tuple[list[Pin], str]:
    if not path.exists():
        raise SyncError(f"manifest not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "repos" not in data:
        raise SyncError(f"malformed manifest (no 'repos' key): {path}")

    branch = (data.get("defaults") or {}).get("branch", "main")
    pins: list[Pin] = []
    seen: set[str] = set()
    for i, entry in enumerate(data["repos"]):
        for field in ("name", "repo", "kind"):
            if not entry.get(field):
                raise SyncError(f"repos[{i}] missing required field '{field}'")
        name = entry["name"]
        if name in seen:
            raise SyncError(f"duplicate repo name: {name}")
        seen.add(name)
        pins.append(
            Pin(
                name=name,
                repo=entry["repo"],
                kind=entry["kind"],
                ref=entry.get("ref"),
            )
        )
    if not pins:
        raise SyncError("manifest lists no repos")
    return pins, branch


# --- freeze / unfreeze -------------------------------------------------------
#
# chmod -R a-w strips write for everyone including the owner. Removing `w` from
# a directory blocks creating, deleting, and renaming entries in it, which is
# what stops a stray write landing in the tree. Read and traverse are untouched.
#
# A frozen tree cannot be fetched into, so a refresh must unfreeze first.


def _walk_paths(root: Path):
    yield root
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for n in dirnames + filenames:
            yield d / n


def set_writable(root: Path, writable: bool) -> int:
    """Add or remove the write bit for all users, recursively."""
    count = 0
    # Deepest-first when freezing, so we do not lose write access to a parent
    # before finishing its children.
    paths = sorted(_walk_paths(root), key=lambda p: len(p.parts), reverse=not writable)
    for path in paths:
        try:
            mode = path.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISLNK(mode):
            continue  # symlink perms are not meaningful; the target is covered
        write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        new_mode = (mode | stat.S_IWUSR) if writable else (mode & ~write_bits)
        if stat.S_IMODE(new_mode) != stat.S_IMODE(mode):
            try:
                os.chmod(path, stat.S_IMODE(new_mode))
                count += 1
            except OSError as exc:
                log(f"  warn: chmod failed on {path}: {exc}")
    return count


def freeze(dest: Path) -> None:
    n = set_writable(dest, writable=False)
    log(f"froze {dest} ({n} paths changed)")


def unfreeze(dest: Path) -> None:
    n = set_writable(dest, writable=True)
    log(f"unfroze {dest} ({n} paths changed)")


# --- git ---------------------------------------------------------------------


def remote_head(pin: Pin, branch: str) -> str | None:
    proc = run(["git", "ls-remote", pin.url, f"refs/heads/{branch}"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.split()[0]


def ensure_clone(pin: Pin, repos_dir: Path) -> Path:
    path = repos_dir / pin.name
    if (path / ".git").is_dir():
        run(["git", "fetch", "--tags", "--force", "origin"], cwd=path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        log(f"  cloning {pin.repo}")
        run(["git", "clone", "--no-checkout", pin.url, str(path)])
    return path


def checkout(path: Path, ref: str) -> str:
    proc = run(["git", "cat-file", "-t", ref], cwd=path, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "commit":
        raise SyncError(f"ref not found in {path.name}: {ref}")
    run(["git", "-c", "advice.detachedHead=false", "checkout", "--force", ref], cwd=path)
    return run(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()


def commits_between(path: Path, ref: str, head: str) -> int | None:
    proc = run(["git", "rev-list", "--count", f"{ref}..{head}"], cwd=path, check=False)
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


# --- staleness ---------------------------------------------------------------


def report_staleness(pins: list[Pin], branch: str, repos_dir: Path) -> list[dict]:
    """Compare each pin against the current branch head. Advisory only."""
    rows: list[dict] = []
    for pin in pins:
        head = remote_head(pin, branch)
        behind: int | None = None
        if head and pin.ref and head != pin.ref:
            local = repos_dir / pin.name
            if (local / ".git").is_dir():
                behind = commits_between(local, pin.ref, head)
        rows.append(
            {
                "name": pin.name,
                "repo": pin.repo,
                "pinned": pin.ref,
                "branch": branch,
                "head": head,
                "current": bool(head and pin.ref and head == pin.ref),
                "behind": behind,
            }
        )
    return rows


def print_staleness(rows: list[dict]) -> None:
    stale = [r for r in rows if r["pinned"] and not r["current"] and r["head"]]
    unknown = [r for r in rows if r["head"] is None]
    unpinned = [r for r in rows if not r["pinned"]]

    log("")
    log("=" * 72)
    if stale:
        log(f"REMINDER: {len(stale)} of {len(rows)} pins are behind "
            f"'{rows[0]['branch']}'.")
        log("The audit reflects the pinned SHAs, not current upstream code.")
        log("")
        for r in stale:
            n = f"{r['behind']} commits" if r["behind"] is not None else "? commits"
            log(f"  {r['name']:<24} behind by {n}")
            log(f"  {'':<24} pinned {r['pinned'][:12]} -> head {r['head'][:12]}")
        log("")
        log("To bump: edit `ref` in manifest.yaml deliberately, then re-run.")
        log("Nothing has been changed automatically.")
    else:
        pinned_ok = [r for r in rows if r["current"]]
        log(f"All {len(pinned_ok)} pinned repo(s) match '{rows[0]['branch']}' head.")

    if unpinned:
        log("")
        log(f"UNPINNED: {len(unpinned)} repo(s) have no `ref` in manifest.yaml:")
        for r in unpinned:
            head = r["head"][:12] if r["head"] else "unavailable"
            log(f"  {r['name']:<24} current head: {head}")
        log("Pin these before relying on a run being reproducible.")

    if unknown:
        log("")
        log(f"note: could not reach {len(unknown)} remote(s); staleness unknown")
    log("=" * 72)


# --- main --------------------------------------------------------------------


def do_freeze(pins: list[Pin], branch: str, dest: Path, check_staleness: bool) -> int:
    repos_dir = dest / "repos"
    unpinned = [p.name for p in pins if not p.ref]
    if unpinned:
        raise SyncError(
            "cannot freeze: unpinned repos in manifest.yaml: "
            + ", ".join(unpinned)
            + "\n  run `sync.py --resolve` to get current SHAs, then pin them."
        )

    if dest.exists():
        unfreeze(dest)
    repos_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[dict] = []
    for pin in pins:
        log(f"{pin.name}:")
        path = ensure_clone(pin, repos_dir)
        sha = checkout(path, pin.ref)
        resolved.append(
            {"name": pin.name, "repo": pin.repo, "kind": pin.kind, "sha": sha}
        )
        log(f"  at {sha}")

    lock = {
        "version": 1,
        "note": "Resolved SHAs for the last --freeze. Commit this.",
        "repos": resolved,
    }
    (REPO_ROOT / LOCK_NAME).write_text(json.dumps(lock, indent=2) + "\n")
    log(f"wrote {LOCK_NAME}")

    freeze(dest)

    if check_staleness:
        try:
            print_staleness(report_staleness(pins, branch, repos_dir))
        except SyncError as exc:
            log(f"note: staleness check skipped: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", type=Path, default=REPO_ROOT / "manifest.yaml")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--freeze", action="store_true", help="clone, checkout, freeze")
    mode.add_argument("--resolve", action="store_true", help="print head SHAs")
    mode.add_argument("--report-staleness", action="store_true")
    mode.add_argument("--unfreeze", action="store_true")
    ap.add_argument(
        "--no-staleness-check",
        action="store_true",
        help="skip the network call after --freeze (offline runs)",
    )
    args = ap.parse_args(argv)

    try:
        pins, branch = load_manifest(args.manifest)

        if args.resolve:
            for pin in pins:
                head = remote_head(pin, branch)
                print(f"{pin.name:<24} {head or 'unavailable'}")
            return 0

        if args.unfreeze:
            if not args.dest.exists():
                raise SyncError(f"nothing to unfreeze: {args.dest} does not exist")
            unfreeze(args.dest)
            log("tree is writable; re-freeze with --freeze when done")
            return 0

        if args.report_staleness:
            print_staleness(report_staleness(pins, branch, args.dest / "repos"))
            return 0

        return do_freeze(pins, branch, args.dest, not args.no_staleness_check)

    except SyncError as exc:
        log(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
