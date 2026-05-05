"""Commit and push module for gh-readme-pipeline.

Addresses: H4 (mode prompt), H7 (state persistence integration), M6 (verb + skip-ci), L2 (dry-run).

Public API
----------
    commit_and_push(repo_dir, mode, had_readme_before, dry_run, skip_ci, commit_message) -> CommitResult

    warn_gpg_signing()
        Read git config commit.gpgsign and user.signingkey.
        If signing is on but no key configured, print warning to stderr.

Modes
-----
    'pr'          — create feature branch, commit, push, open PR via gh cli
    'direct'      — commit + push to current branch (no branch creation)
    'commit-only' — commit only, no push
    'skip'        — no-op

All subprocess calls use list form, shell=False, check=False, capture_output=True, text=True.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CommitResult:
    status: Literal["pushed", "pr_opened", "commit_only", "skipped", "failed"]
    mode: str | None
    pr_url: str | None
    error: str | None


# ---------------------------------------------------------------------------
# GPG warn helper
# ---------------------------------------------------------------------------


def warn_gpg_signing() -> None:
    """Print a warning to stderr if GPG signing is on but no signing key is configured.

    Reads:
    - ``git config commit.gpgsign`` — True if signing is enabled.
    - ``git config user.signingkey`` — the signing key (empty / non-zero if absent).

    Only warns when both conditions hold: gpgsign is 'true' AND signingkey is absent/empty.
    """
    gpgsign_result = subprocess.run(
        ["git", "config", "commit.gpgsign"],
        check=False,
        capture_output=True,
        text=True,
    )
    if gpgsign_result.returncode != 0:
        return  # git config key not set at all → no signing
    gpgsign = gpgsign_result.stdout.strip().lower()
    if gpgsign != "true":
        return

    # Signing is on — check for key
    key_result = subprocess.run(
        ["git", "config", "user.signingkey"],
        check=False,
        capture_output=True,
        text=True,
    )
    has_key = key_result.returncode == 0 and key_result.stdout.strip()
    if not has_key:
        sys.stderr.write(
            "WARNING: GPG signing is enabled (commit.gpgsign=true) "
            "but no user.signingkey is configured. "
            "Commits may fail. Set user.signingkey or disable commit.gpgsign.\n"
        )


# ---------------------------------------------------------------------------
# Mode prompt
# ---------------------------------------------------------------------------

_MODE_CHARS = {
    "p": "pr",
    "m": "direct",
    "c": "commit-only",
    "n": "skip",
}


def _prompt_mode() -> str:
    """Interactively prompt the user to select a push mode.

    Returns one of: 'pr', 'direct', 'commit-only', 'skip'.
    """
    prompt = (
        "\nPush mode?\n"
        "  [p] PR (feature branch + gh pr create)\n"
        "  [m] direct to main/default branch\n"
        "  [c] commit only (no push)\n"
        "  [n] no commit (skip)\n"
        "> "
    )
    while True:
        raw = input(prompt).strip().lower()
        if raw in _MODE_CHARS:
            return _MODE_CHARS[raw]


# ---------------------------------------------------------------------------
# Commit message builder
# ---------------------------------------------------------------------------


def _build_commit_message(
    had_readme_before: bool,
    skip_ci: bool,
    commit_message: str | None,
) -> str:
    """Build the commit message string.

    Uses commit_message if provided, otherwise constructs default from verb.
    Appends ' [skip ci]' when skip_ci=True.
    """
    verb = "update" if had_readme_before else "add"
    msg = commit_message if commit_message is not None else f"docs: {verb} README"
    if skip_ci:
        msg += " [skip ci]"
    return msg


# ---------------------------------------------------------------------------
# Git operation helpers — all check=False, capture_output=True, text=True
# ---------------------------------------------------------------------------


def _git(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _check_git(
    result: subprocess.CompletedProcess,
    op: str,
    mode: str,
) -> CommitResult | None:
    """Return failed CommitResult if *result* is non-zero, else None.

    CR-HIGH-2: git operations were silently ignored before this helper.
    """
    if result.returncode == 0:
        return None
    err = result.stderr or f"git {op} failed (rc={result.returncode})"
    return CommitResult(status="failed", mode=mode, pr_url=None, error=err)


def _gh(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Per-mode implementations
# ---------------------------------------------------------------------------


def _run_pr_mode(
    repo_dir: Path,
    msg: str,
    dry_run: bool,
) -> CommitResult:
    """Execute PR mode: branch → add → commit → push → gh pr create."""
    branch = f"docs/readme-pipeline-{int(time.time())}"

    if (fail := _check_git(_git(["git", "checkout", "-b", branch], repo_dir), "checkout", "pr")):
        return fail
    if (fail := _check_git(_git(["git", "add", "README.md"], repo_dir), "add", "pr")):
        return fail
    if (fail := _check_git(_git(["git", "commit", "-m", msg], repo_dir), "commit", "pr")):
        return fail

    if dry_run:
        return CommitResult(status="pr_opened", mode="pr", pr_url=None, error=None)

    push_result = _git(["git", "push", "-u", "origin", branch], repo_dir)
    if push_result.returncode != 0:
        return CommitResult(
            status="failed",
            mode="pr",
            pr_url=None,
            error=push_result.stderr or f"git push failed (rc={push_result.returncode})",
        )

    gh_result = _gh(
        ["gh", "pr", "create", "--title", msg, "--body", "Generated by gh-readme-pipeline."],
        repo_dir,
    )
    pr_url = gh_result.stdout.strip() if gh_result.returncode == 0 else None
    return CommitResult(status="pr_opened", mode="pr", pr_url=pr_url, error=None)


def _run_direct_mode(
    repo_dir: Path,
    msg: str,
    dry_run: bool,
) -> CommitResult:
    """Execute direct mode: add → commit → push (no branch creation)."""
    if (fail := _check_git(_git(["git", "add", "README.md"], repo_dir), "add", "direct")):
        return fail
    if (fail := _check_git(_git(["git", "commit", "-m", msg], repo_dir), "commit", "direct")):
        return fail

    if dry_run:
        return CommitResult(status="pushed", mode="direct", pr_url=None, error=None)

    push_result = _git(["git", "push", "origin", "HEAD"], repo_dir)
    if push_result.returncode != 0:
        return CommitResult(
            status="failed",
            mode="direct",
            pr_url=None,
            error=push_result.stderr or f"git push failed (rc={push_result.returncode})",
        )

    return CommitResult(status="pushed", mode="direct", pr_url=None, error=None)


def _run_commit_only_mode(
    repo_dir: Path,
    msg: str,
) -> CommitResult:
    """Execute commit-only mode: add → commit, no push."""
    if (fail := _check_git(_git(["git", "add", "README.md"], repo_dir), "add", "commit-only")):
        return fail
    if (fail := _check_git(_git(["git", "commit", "-m", msg], repo_dir), "commit", "commit-only")):
        return fail
    return CommitResult(status="commit_only", mode="commit-only", pr_url=None, error=None)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def commit_and_push(
    repo_dir: Path,
    mode: str | None,
    had_readme_before: bool,
    dry_run: bool = False,
    skip_ci: bool = False,
    commit_message: str | None = None,
    ui=None,
) -> CommitResult:
    """Commit README.md and optionally push or open a PR.

    Args:
        repo_dir: Path to the cloned repository.
        mode: One of 'pr', 'direct', 'commit-only', 'skip', or None (prompt user).
        had_readme_before: Whether the repo had a README before this run.
        dry_run: When True, run commits but skip all network operations (push/PR).
        skip_ci: When True, append ' [skip ci]' to the commit message.
        commit_message: Override the default commit message template.

    Returns:
        CommitResult with status, mode, pr_url (if applicable), and error.
    """
    # CRIT-2: reject newline injection in commit_message before any git work.
    if commit_message is not None and ("\n" in commit_message or "\r" in commit_message):
        return CommitResult(
            status="failed",
            mode=mode,
            pr_url=None,
            error="commit_message must be single line",
        )

    # Resolve mode
    if mode is not None:
        resolved_mode = mode
    elif ui is not None:
        choice = ui.menu(
            "Push mode?",
            [
                ("p", "PR (feature branch + gh pr create)"),
                ("m", "direct to main/default branch"),
                ("c", "commit only (no push)"),
                ("n", "no commit (skip)"),
            ],
        )
        resolved_mode = _MODE_CHARS.get(choice, "skip")
    else:
        resolved_mode = _prompt_mode()

    if resolved_mode == "skip":
        return CommitResult(status="skipped", mode=None, pr_url=None, error=None)

    msg = _build_commit_message(had_readme_before, skip_ci, commit_message)

    if resolved_mode == "pr":
        return _run_pr_mode(repo_dir, msg, dry_run)

    if resolved_mode == "direct":
        return _run_direct_mode(repo_dir, msg, dry_run)

    if resolved_mode == "commit-only":
        return _run_commit_only_mode(repo_dir, msg)

    # Fallback (should not reach here with validated mode)
    return CommitResult(status="skipped", mode=None, pr_url=None, error=f"unknown mode: {resolved_mode!r}")
