"""Review loop FSM for gh-readme-pipeline.

Addresses: C1 (clean baseline), C4 (blast-radius guard), H2, H3, H6, M5.

Public API
----------
    review_loop(repo_dir, had_readme_before, claude_timeout) -> ReviewResult

    _show_pager(text)
        Display text using 'less -R' if stdout is a tty and less is available,
        otherwise fall back to print().

FSM Steps
---------
1. Pre-Claude risky-file scan. If found → prompt [c]ontinue / [s]kip.
2. Baseline restore (git checkout -- README.md; git clean -f README.md).
   Invoke claude.
   - TimeoutExpired → [r]etry / [s]kip / [q]uit
   - Non-zero exit → [r]edo / [d]iscard
3. Blast-radius guard: only README.md may be changed.
4. Secret scan on new README content.
5. Accept prompt: [a]ccept / [r]edo / [d]iscard / [v]iew diff / [V]full / [o]ld.
   had_readme_before=True → accept requires typed 'yes'.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src import safety, secrets

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ReviewResult:
    status: Literal["accepted", "skipped", "failed", "quit"]
    reason: str | None


# ---------------------------------------------------------------------------
# Pager helper
# ---------------------------------------------------------------------------


def _show_pager(text: str) -> None:
    """Display *text* in a pager if possible, else print directly.

    Uses ``less -R`` when both conditions hold:
    - ``sys.stdout.isatty()`` is True
    - ``shutil.which('less')`` returns a path (less is installed)

    Falls back to ``print(text)`` otherwise.
    """
    if sys.stdout.isatty() and shutil.which("less"):
        subprocess.run(["less", "-R"], input=text, text=True)
    else:
        print(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    """Read file contents, returning empty string if the file does not exist."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _restore_baseline(repo_dir: Path) -> None:
    """Restore README.md to its HEAD state (or remove it if untracked).

    Both commands are run with check=False because README.md may not exist in
    the repository yet (new repo, first run).
    """
    subprocess.run(
        ["git", "checkout", "--", "README.md"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "clean", "-f", "README.md"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )


def _invoke_claude(repo_dir: Path, timeout: int) -> subprocess.CompletedProcess | None:
    """Run claude and return its CompletedProcess.

    Returns None on TimeoutExpired (caller must handle).
    """
    try:
        return subprocess.run(
            ["claude", "-p", "/create-readme", "--permission-mode", "acceptEdits"],
            cwd=repo_dir,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None


def _blast_radius_ok(repo_dir: Path) -> tuple[bool, str]:
    """Check that only README.md was modified.

    Returns (True, '') if only README.md changed (including newly created).
    Returns (False, reason) otherwise.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return False, "claude_touched_other_files"  # nothing changed at all
    # Each porcelain line is like " M README.md" or "?? README.md"
    paths = set()
    for line in lines:
        # Porcelain v1: 2-char status + space + path (possibly with rename arrow)
        parts = line.split()
        if len(parts) >= 2:
            # Handle rename "old -> new" format
            path_part = parts[-1]
            paths.add(path_part)
    if paths == {"README.md"}:
        return True, ""
    return False, "claude_touched_other_files"


def _build_diff(old_content: str, new_content: str) -> str:
    """Build a simple unified-style diff string from old and new content."""
    import difflib
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="README.md (old)",
        tofile="README.md (new)",
    )
    return "".join(diff) or "(no changes)"


# ---------------------------------------------------------------------------
# Prompt helpers (pure logic — separated for testability)
# ---------------------------------------------------------------------------


def _prompt_risky_files(risky: list[Path]) -> str:
    """Display risky-file warning and prompt [c]ontinue / [s]kip."""
    print(f"\nWARNING: found {len(risky)} risky file(s) in repo:")
    for p in risky[:10]:
        print(f"  {p}")
    if len(risky) > 10:
        print(f"  ... and {len(risky) - 10} more")
    while True:
        raw = input("[c]ontinue / [s]kip > ").strip().lower()
        if raw in ("c", "s"):
            return raw


def _prompt_timeout() -> str:
    """Prompt after claude timeout: [r]etry / [s]kip / [q]uit."""
    while True:
        raw = input("\nClaude timed out. [r]etry / [s]kip / [q]uit > ").strip().lower()
        if raw in ("r", "s", "q"):
            return raw


def _prompt_nonzero() -> str:
    """Prompt after claude non-zero exit: [r]edo / [d]iscard."""
    while True:
        raw = input("\nClaude exited with non-zero status. [r]edo / [d]iscard > ").strip().lower()
        if raw in ("r", "d"):
            return raw


def _prompt_secret_override(matches: list[str]) -> str:
    """Loud warning about secrets; require 'yes-i-checked' to override."""
    print("\n" + "=" * 60)
    print("WARNING: POSSIBLE SECRETS DETECTED IN GENERATED README:")
    for m in matches:
        print(f"  {m!r}")
    print("=" * 60)
    print("Type 'yes-i-checked' to accept anyway, or anything else to discard.")
    raw = input("Override > ").strip()
    return raw


def _prompt_accept(
    repo_dir: Path,
    had_readme_before: bool,
    old_content: str,
    new_content: str,
) -> str:
    """Accept prompt loop with view toggles.

    Returns: 'accepted', 'redo', 'skipped'.
    """
    # Default first view
    if had_readme_before:
        diff_text = _build_diff(old_content, new_content)
        _show_pager(diff_text)
    else:
        _show_pager(new_content)

    accept_hint = "type 'yes'" if had_readme_before else "[a]ccept"
    prompt_str = (
        f"\n[{accept_hint}] / [r]edo / [d]iscard / "
        "[v]iew diff / [V]iew full new / [o]ld README > "
    )

    while True:
        raw = input(prompt_str).strip()

        if raw == "v":
            diff_text = _build_diff(old_content, new_content)
            _show_pager(diff_text)
            continue

        if raw == "V":
            _show_pager(new_content)
            continue

        if raw == "o":
            _show_pager(old_content if old_content else "(no previous README)")
            continue

        if raw == "r":
            return "redo"

        if raw == "d":
            return "skipped"

        if had_readme_before:
            if raw == "yes":
                return "accepted"
            # anything else (including 'a', 'y') re-prompts
            print("  (type 'yes' to confirm accept, or choose another option)")
            continue
        else:
            if raw == "a":
                return "accepted"
            # Unrecognised input: re-prompt
            print("  (press 'a' to accept, 'r' redo, 'd' discard, 'v'/'V'/'o' to view)")
            continue


# ---------------------------------------------------------------------------
# Main FSM
# ---------------------------------------------------------------------------


def review_loop(
    repo_dir: Path,
    had_readme_before: bool,
    claude_timeout: int = 300,
) -> ReviewResult:
    """Run the full review FSM for one repository.

    Args:
        repo_dir: Path to the cloned repository directory.
        had_readme_before: Whether a README existed before this pipeline run.
        claude_timeout: Seconds to allow Claude before triggering timeout prompt.

    Returns:
        ReviewResult with status in {"accepted", "skipped", "failed", "quit"}.
    """
    # Step 1: Pre-Claude risky-file scan
    risky = secrets.scan_repo_for_risky_files(repo_dir)
    if risky:
        choice = _prompt_risky_files(risky)
        if choice == "s":
            return ReviewResult(status="skipped", reason="risky_files_found")

    # Capture old README content once (before any modifications)
    old_content = _read_file(repo_dir / "README.md")

    # Main FSM loop
    while True:
        # Step 2: Baseline restore invariant
        _restore_baseline(repo_dir)

        # Invoke Claude
        proc = _invoke_claude(repo_dir, claude_timeout)

        # Handle timeout
        if proc is None:
            choice = _prompt_timeout()
            if choice == "r":
                continue  # retry → back to step 2
            if choice == "s":
                safety.ensure_clean(repo_dir)
                return ReviewResult(status="skipped", reason="claude_timeout")
            # "q"
            return ReviewResult(status="quit", reason="claude_timeout")

        # Handle non-zero exit
        if proc.returncode != 0:
            choice = _prompt_nonzero()
            if choice == "r":
                continue  # redo → back to step 2
            # "d" discard
            safety.ensure_clean(repo_dir)
            return ReviewResult(status="skipped", reason="claude_nonzero_exit")

        # Step 3: Blast-radius guard
        ok, reason = _blast_radius_ok(repo_dir)
        if not ok:
            safety.ensure_clean(repo_dir)
            return ReviewResult(status="failed", reason=reason)

        # Step 4: Secret scan on new README content
        new_content = _read_file(repo_dir / "README.md")
        secret_matches = secrets.scan_text_for_secrets(new_content)
        if secret_matches:
            override = _prompt_secret_override(secret_matches)
            if override != "yes-i-checked":
                safety.ensure_clean(repo_dir)
                return ReviewResult(status="skipped", reason="secrets_detected")
            # Proceed to accept prompt with override

        # Step 5: Accept prompt with view toggles
        outcome = _prompt_accept(repo_dir, had_readme_before, old_content, new_content)

        if outcome == "accepted":
            return ReviewResult(status="accepted", reason=None)

        if outcome == "skipped":
            safety.ensure_clean(repo_dir)
            return ReviewResult(status="skipped", reason="user_discarded")

        # "redo" → loop back to step 2
        # old_content stays the same (captured once at step 1)
        continue
