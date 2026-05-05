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

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src import safety, secrets
from src.ui import ReviewContext, UI

# Skill bundled in this repo at <program_root>/.claude/skills/create-readme/.
# Staged into each target repo before invoking claude, then removed so the
# blast-radius guard still sees only README.md as changed.
_PROGRAM_ROOT = Path(__file__).resolve().parent.parent
_SKILL_SRC = _PROGRAM_ROOT / ".claude" / "skills" / "create-readme" / "SKILL.md"

# RT-H2: only these keys (and CLAUDE_*, LC_*, XDG_* prefixes) are passed to claude.
_CLAUDE_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR",
})
_CLAUDE_ENV_PREFIXES = ("CLAUDE_", "LC_", "XDG_")


def _scrub_env_for_claude() -> dict[str, str]:
    """Return a minimal env dict for the claude subprocess.

    Drops credential-like vars (tokens, keys, secrets, passwords) by allowlist.
    """
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in _CLAUDE_ENV_ALLOWLIST or k.startswith(_CLAUDE_ENV_PREFIXES):
            out[k] = v
    return out


def _stage_skill(repo_dir: Path) -> None:
    dst = repo_dir / ".claude" / "skills" / "create-readme" / "SKILL.md"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SKILL_SRC, dst)
    except OSError as e:
        print(f"warning: could not stage create-readme skill: {e}", file=sys.stderr)


def _unstage_skill(repo_dir: Path) -> None:
    skill_dir = repo_dir / ".claude" / "skills" / "create-readme"
    shutil.rmtree(skill_dir, ignore_errors=True)
    for parent in (repo_dir / ".claude" / "skills", repo_dir / ".claude"):
        try:
            parent.rmdir()
        except OSError:
            break

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
        subprocess.run(["less"], input=text, text=True)
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


def _open_tty() -> int | None:
    """Return fd for /dev/tty if available, else None."""
    try:
        return os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None


def _save_tty_attrs(fd: int):
    """Return termios attrs for fd, or None if not a tty."""
    try:
        import termios
        return termios.tcgetattr(fd)
    except Exception:
        return None


def _restore_tty_attrs(fd: int, attrs) -> None:
    if attrs is None:
        return
    try:
        import termios
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except Exception:
        pass


def _invoke_claude(repo_dir: Path, timeout: int) -> subprocess.CompletedProcess | None:
    """Run claude and return its CompletedProcess.

    Returns None on TimeoutExpired (caller must handle).

    Stages the bundled /create-readme skill into repo_dir/.claude/ so the
    spawned claude session discovers it, then removes it after the run.
    """
    _stage_skill(repo_dir)
    tty_fd = _open_tty()
    saved = _save_tty_attrs(tty_fd) if tty_fd is not None else None
    try:
        return subprocess.run(
            ["claude", "-p", "/create-readme", "--permission-mode", "acceptEdits"],
            cwd=repo_dir,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            env=_scrub_env_for_claude(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        _unstage_skill(repo_dir)
        if tty_fd is not None:
            _restore_tty_attrs(tty_fd, saved)
            try:
                os.close(tty_fd)
            except OSError:
                pass


def _blast_radius_ok(repo_dir: Path) -> tuple[bool, str]:
    """Check that only README.md was modified.

    Uses NUL-delimited git queries to avoid quoted-path parsing pitfalls.
    Combines tracked changes (git diff --name-only -z) with untracked files
    (git ls-files -z --others --exclude-standard) and asserts the set is
    exactly {"README.md"}.
    """
    diff = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRT", "HEAD"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    paths = {p for p in (diff.stdout + untracked.stdout).split("\0") if p}
    if not paths:
        return False, "claude_touched_other_files"
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


def _tty_input(prompt: str) -> str:
    """Read a line from /dev/tty, falling back to builtin input()."""
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(prompt)
            tty.flush()
            line = tty.readline()
            if line == "":
                raise EOFError
            return line.rstrip("\r\n")
    except (OSError, EOFError):
        return input(prompt)


def _prompt_risky_files(risky: list[Path]) -> str:
    """Display risky-file warning and prompt [c]ontinue / [s]kip."""
    print(f"\nWARNING: found {len(risky)} risky file(s) in repo:")
    for p in risky[:10]:
        print(f"  {p}")
    if len(risky) > 10:
        print(f"  ... and {len(risky) - 10} more")
    while True:
        raw = _tty_input("[c]ontinue / [s]kip > ").strip().lower()
        if raw in ("c", "s"):
            return raw


def _prompt_timeout() -> str:
    """Prompt after claude timeout: [r]etry / [s]kip / [q]uit."""
    while True:
        raw = _tty_input("\nClaude timed out. [r]etry / [s]kip / [q]uit > ").strip().lower()
        if raw in ("r", "s", "q"):
            return raw


def _prompt_nonzero() -> str:
    """Prompt after claude non-zero exit: [r]edo / [d]iscard."""
    while True:
        raw = _tty_input("\nClaude exited with non-zero status. [r]edo / [d]iscard > ").strip().lower()
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
    raw = _tty_input("Override > ").strip()
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
        raw = _tty_input(prompt_str).strip()

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
    ui: UI | None = None,
    repo_index: int = 1,
    repo_total: int = 1,
    repo_name: str = "",
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
    prev_draft: str | None = None  # last Claude output before a redo iteration

    # Main FSM loop
    iteration = 0
    while True:
        iteration += 1
        # Step 2: Baseline restore invariant
        _restore_baseline(repo_dir)

        # Invoke Claude (with spinner if a UI was supplied)
        spinner_label = (
            f"{'Re-generating' if iteration > 1 else 'Generating'} README"
            f"{f' for {repo_name}' if repo_name else ''}…"
        )
        if ui is not None:
            with ui.spinner(spinner_label):
                proc = _invoke_claude(repo_dir, claude_timeout)
        else:
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
        if ui is not None:
            ctx = ReviewContext(
                repo_name=repo_name or repo_dir.name,
                index=repo_index,
                total=repo_total,
                head_readme=old_content or None,
                prev_draft=prev_draft,
                current_draft=new_content,
            )
            choice = ui.show_review(ctx)
            outcome = {
                "accept": "accepted",
                "redo": "redo",
                "discard": "skipped",
                "quit": "quit",
            }.get(choice, "skipped")
        else:
            outcome = _prompt_accept(repo_dir, had_readme_before, old_content, new_content)

        if outcome == "accepted":
            return ReviewResult(status="accepted", reason=None)

        if outcome == "skipped":
            safety.ensure_clean(repo_dir)
            return ReviewResult(status="skipped", reason="user_discarded")

        if outcome == "quit":
            safety.ensure_clean(repo_dir)
            return ReviewResult(status="quit", reason="user_quit")

        # "redo" → remember this draft as prev for next iteration
        prev_draft = new_content
        continue
