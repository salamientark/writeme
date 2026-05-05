#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7.0"]
# ///
"""gh-readme-pipeline — interactive CLI to generate README files via Claude.

Usage
-----
    uv run gh_readme_pipeline.py [FLAGS]

Flags
-----
    --mode {pr,direct,commit-only}   Skip per-repo mode prompt.
    --dry-run                        Full loop but never push.
    --repos-dir PATH                 Override cache clone dir.
    --claude-timeout INT             Claude subprocess timeout (default 300).
    --resume                         Skip already-processed repos.
    --clean                          Remove cache dir, exit 0.
    --skip-ci                        Append [skip ci] to commit message.

Env-only
--------
    LIMIT              Repo cap (hard-capped at 1000).
    GH_USER            Override authed user.
    COMMIT_MESSAGE     Override commit message template.
    GH_README_REPOS_DIR  Override repos-dir.
    CLAUDE_TIMEOUT     Default claude timeout.
    SKIP_CI            Set skip-ci flag.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARD_LIMIT = 1000
DEFAULT_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments and apply environment variable fallbacks.

    Returns an argparse.Namespace with attributes:
        mode, dry_run, repos_dir, claude_timeout, resume, clean, skip_ci
    """
    parser = argparse.ArgumentParser(
        prog="gh-readme-pipeline",
        description="Generate README files for GitHub repositories using Claude.",
    )

    parser.add_argument(
        "--mode",
        choices=["pr", "direct", "commit-only"],
        default=None,
        help="Push mode (default: ask per repo)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run full loop but never push.",
    )
    parser.add_argument(
        "--repos-dir",
        type=Path,
        default=None,
        help="Override clone cache directory.",
    )
    parser.add_argument(
        "--claude-timeout",
        type=int,
        default=None,
        help="Claude subprocess timeout in seconds (default 300).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Skip already-processed repos from state file.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Remove cache dir and exit 0.",
    )
    parser.add_argument(
        "--skip-ci",
        action="store_true",
        default=False,
        help="Append [skip ci] to commit message.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        default=False,
        help="Disable Rich UI (force plain prints — useful for non-TTY/CI).",
    )

    ns = parser.parse_args(argv)

    # Apply env-var fallbacks
    if ns.repos_dir is None:
        env_repos_dir = os.environ.get("GH_README_REPOS_DIR")
        if env_repos_dir:
            ns.repos_dir = Path(env_repos_dir)
        else:
            from src.state import xdg_cache_dir
            ns.repos_dir = xdg_cache_dir() / "repos"

    if ns.claude_timeout is None:
        env_timeout = os.environ.get("CLAUDE_TIMEOUT")
        if env_timeout:
            try:
                ns.claude_timeout = int(env_timeout)
            except ValueError:
                ns.claude_timeout = DEFAULT_TIMEOUT
        else:
            ns.claude_timeout = DEFAULT_TIMEOUT

    if not ns.skip_ci:
        ns.skip_ci = bool(os.environ.get("SKIP_CI", ""))

    return ns


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------


def _resolve_user() -> str:
    """Return the GitHub username to operate on.

    If GH_USER env is set, return it.  Otherwise query 'gh api user'.
    If both are available and different, prompt the user to confirm.
    """
    env_user = os.environ.get("GH_USER", "").strip()

    # Query authenticated user from gh CLI
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            check=False,
            capture_output=True,
            text=True,
        )
        api_user = result.stdout.strip() if result.returncode == 0 else ""
    except FileNotFoundError:
        api_user = ""

    if env_user and api_user and env_user != api_user:
        # Mismatch: prompt for confirmation
        print(
            f"WARNING: GH_USER={env_user!r} but authenticated as {api_user!r}.",
            file=sys.stderr,
        )
        confirm = input(
            f"Operating on {env_user}'s repos as {api_user}. Continue? [y/N] "
        ).strip().lower()
        if confirm != "y":
            sys.exit(1)

    return env_user or api_user or ""


# ---------------------------------------------------------------------------
# Clone-or-fetch helper
# ---------------------------------------------------------------------------


def _clone_or_fetch(repo, repos_dir: Path) -> Path:
    """Ensure a shallow clone exists at repos_dir/<name>, return its path.

    If the directory already contains a .git folder, fetch instead of clone.
    Uses depth=1 and filter=blob:none to minimise disk usage.
    """
    from src import safety

    safety.validate_repo_name(repo.name)
    safety.validate_ssh_url(repo.ssh_url)

    repo_dir = repos_dir / repo.name
    repos_dir.mkdir(parents=True, exist_ok=True)

    if (repo_dir / ".git").exists():
        # Already cloned — just fetch to get latest
        subprocess.run(
            ["git", "fetch", "--depth=1"],
            cwd=repo_dir,
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        subprocess.run(
            [
                "git", "clone",
                "--depth=1",
                "--filter=blob:none",
                repo.ssh_url,
                str(repo_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    return repo_dir


# ---------------------------------------------------------------------------
# Per-repo processing
# ---------------------------------------------------------------------------


def process_repo(
    repo,
    repos_dir: Path,
    mode: str | None,
    dry_run: bool,
    skip_ci: bool,
    commit_message: str | None,
    claude_timeout: int,
    state_store,
    ui=None,
    repo_index: int = 1,
    repo_total: int = 1,
) -> str | None:
    """Run the full pipeline for one repository.

    Steps:
    1. Clone or fetch the repo into repos_dir/<name>.
    2. Run review_loop → ReviewResult.
    3. If accepted, commit_and_push.
    4. On KeyboardInterrupt in review: ensure_clean then re-raise.
    5. Finally: ensure_clean + record state.

    Returns:
        None on normal completion (accepted, skipped, failed).
        'quit' sentinel when review_loop returns status='quit' (signals outer loop to stop).

    Raises:
        KeyboardInterrupt — propagated after cleanup.
    """
    from src import safety, review, commit

    repo_dir = _clone_or_fetch(repo, repos_dir)

    result_status = "failed"
    result_mode: str | None = None
    result_pr_url: str | None = None
    result_error: str | None = None
    _state_recorded = False

    def _record(status, mode=None, error=None, pr_url=None):
        nonlocal _state_recorded
        try:
            state_store.record(repo.name, status, mode=mode, error=error, pr_url=pr_url)
        except Exception:
            pass
        _state_recorded = True

    try:
        review_result = review.review_loop(
            repo_dir=repo_dir,
            had_readme_before=repo.had_readme_before,
            claude_timeout=claude_timeout,
            ui=ui,
            repo_index=repo_index,
            repo_total=repo_total,
            repo_name=repo.name,
        )

        if review_result.status == "accepted":
            commit_result = commit.commit_and_push(
                repo_dir=repo_dir,
                mode=mode,
                had_readme_before=repo.had_readme_before,
                dry_run=dry_run,
                skip_ci=skip_ci,
                commit_message=commit_message,
            )
            result_status = commit_result.status
            result_mode = commit_result.mode
            result_pr_url = commit_result.pr_url
            result_error = commit_result.error

        elif review_result.status == "quit":
            # Record state then return sentinel to stop outer loop.
            # The finally block will still call ensure_clean.
            result_status = "skipped"
            result_error = "user_quit"
            _record(result_status, mode=result_mode, error=result_error, pr_url=result_pr_url)
            return "quit"

        else:
            result_status = review_result.status
            result_error = review_result.reason

    except KeyboardInterrupt:
        # CR-MED-1: finally block handles ensure_clean; record then re-raise.
        _record("failed", error="KeyboardInterrupt")
        raise

    finally:
        safety.ensure_clean(repo_dir)
        # Record state if not already recorded (quit and KeyboardInterrupt paths record early)
        if not _state_recorded:
            _record(
                result_status,
                mode=result_mode,
                error=result_error,
                pr_url=result_pr_url,
            )

    return None


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _summary_rows(state_store) -> list:
    """Build a list of SummaryRow from the state store (last record per repo wins)."""
    from src.ui import SummaryRow
    records = state_store._read_all()
    last: dict[str, dict] = {}
    for rec in records:
        name = rec.get("repo")
        if name:
            last[name] = rec
    status_map = {
        "pushed": "accepted",
        "pr_opened": "accepted",
        "commit_only": "accepted",
        "skipped": "skipped",
        "failed": "failed",
    }
    rows = []
    for name, rec in last.items():
        outcome = status_map.get(rec.get("status", ""), "skipped")
        rows.append(SummaryRow(repo=name, outcome=outcome, pr_url=rec.get("pr_url")))
    return rows


def _print_summary(state_store) -> None:
    """Print end-of-run summary table to stdout."""
    summary = state_store.summary()

    print("\n--- Summary ---")
    label_map = {
        "pr_opened": "Pushed (PR)",
        "pushed": "Pushed (direct)",
        "commit_only": "Commit only",
        "skipped": "Skipped",
        "failed": "Failed",
    }
    for key, label in label_map.items():
        count = summary.get(key, 0)
        print(f"  {label:<20} {count}")

    pr_urls = summary.get("pr_urls", [])
    if pr_urls:
        print("\nPR URLs:")
        for url in pr_urls:
            print(f"  {url}")

    failed_repos = summary.get("failed_repos", [])
    if failed_repos:
        print("\nFailed repos:")
        for name in failed_repos:
            print(f"  {name}")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the gh-readme-pipeline tool.

    Returns:
        0 on success, 1 on fatal error.
    """
    from src import safety, commit as commit_mod
    from src.fetch import fetch_repos
    from src.state import StateStore, xdg_state_dir, prompt_resume
    from src.unpushed import scan_repos as scan_unpushed
    from src.ui import make_ui, SummaryRow
    import src.tui as tui_mod

    ns = parse_args(argv)
    ui = make_ui(plain=ns.plain)

    # --clean: remove repos dir and exit
    if ns.clean:
        shutil.rmtree(ns.repos_dir, ignore_errors=True)
        sys.exit(0)

    # Resolve state dir and store
    state_dir = xdg_state_dir()

    # Resolve user
    user = _resolve_user()
    if not user:
        print("ERROR: could not determine GitHub user. Set GH_USER or run 'gh auth login'.",
              file=sys.stderr)
        return 1

    # Resolve limit from env (hard cap 1000)
    raw_limit = os.environ.get("LIMIT", "500")
    try:
        limit = min(int(raw_limit), HARD_LIMIT)
    except ValueError:
        limit = 500

    # Commit message from env
    commit_message = os.environ.get("COMMIT_MESSAGE") or None

    # Initialise state store
    state_store = StateStore(user, state_dir)

    # SIGINT handler — flush state + print summary + exit 130
    _sigint_fired = [False]

    def _sigint_handler(signum, frame):
        if not _sigint_fired[0]:
            _sigint_fired[0] = True
            print("\nInterrupted. Flushing state...", file=sys.stderr)
            _print_summary(state_store)
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint_handler)

    # Acquire advisory lock
    lock_path = state_dir / "lock"

    with safety.acquire_lock(lock_path):
        # GPG signing warning
        commit_mod.warn_gpg_signing()

        # Intro banner + fetch spinner
        ui.show_intro()
        try:
            with ui.spinner("Fetching your repos from GitHub…"):
                repos = fetch_repos(user, limit)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            ui.error(f"failed to fetch repositories: {e}")
            return 1

        # Resume handling
        selected_repos = list(repos)
        if ns.resume and state_store.has_prior_state():
            processed = state_store.load_processed()
            if processed:
                choice = prompt_resume(len(processed))
                if choice == "quit":
                    return 0
                if choice == "resume":
                    selected_repos = [r for r in repos if r.name not in processed]
                elif choice == "fresh":
                    selected_repos = list(repos)
                # "all" → keep all repos including already-processed

        # TUI selection
        selected = tui_mod.tui_select(selected_repos)
        if not selected:
            print("Nothing selected.")
            return 0

        # Process each selected repo
        total = len(selected)
        for idx, repo in enumerate(selected, start=1):
            sentinel = process_repo(
                repo=repo,
                repos_dir=ns.repos_dir,
                mode=ns.mode,
                dry_run=ns.dry_run,
                skip_ci=ns.skip_ci,
                commit_message=commit_message,
                claude_timeout=ns.claude_timeout,
                state_store=state_store,
                ui=ui,
                repo_index=idx,
                repo_total=total,
            )
            if sentinel == "quit":
                ui.warn("User quit. Stopping.")
                break

        # End-of-run summary (Rich table when UI present, plain otherwise)
        ui.show_summary(_summary_rows(state_store))

        # Unpushed-work scan: exit 2 if any clone is dirty or has unpushed commits
        findings = scan_unpushed(ns.repos_dir)
        if findings:
            print("\nUnpushed/dirty work detected:", file=sys.stderr)
            for f in findings:
                bits = []
                if f.dirty:
                    bits.append("dirty")
                if f.unpushed_commits:
                    bits.append(f"{f.unpushed_commits} unpushed commit(s)")
                print(f"  {f.path}: {', '.join(bits)}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
