"""End-of-run unpushed/dirty work scanner.

Per design v2: just before normal termination, scan ``$GH_README_REPOS_DIR/*/``.
For each clone, run ``git status --porcelain`` and ``git rev-list @{u}..HEAD``
(skip clones with no upstream). If any clone has a dirty working tree OR
unpushed commits, return the list of offending paths. ``main()`` uses this to
decide between exit 0 and exit 2.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UnpushedFinding:
    """One repo with unpushed work."""

    path: Path
    dirty: bool
    unpushed_commits: int  # 0 if upstream missing or all pushed


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _has_upstream(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _is_dirty(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _unpushed_count(repo_dir: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "@{u}..HEAD"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def scan_repos(repos_dir: Path) -> list[UnpushedFinding]:
    """Return per-repo findings of dirty trees or unpushed commits.

    Clones without an upstream are checked only for dirtiness; their
    unpushed_commits is 0. Non-git directories are silently skipped.
    """
    if not repos_dir.exists():
        return []

    findings: list[UnpushedFinding] = []
    for child in sorted(repos_dir.iterdir()):
        if not child.is_dir() or not _is_git_repo(child):
            continue

        dirty = _is_dirty(child)
        unpushed = 0
        if _has_upstream(child):
            unpushed = _unpushed_count(child)

        if dirty or unpushed > 0:
            findings.append(
                UnpushedFinding(path=child, dirty=dirty, unpushed_commits=unpushed)
            )
    return findings
