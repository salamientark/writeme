"""Tests for src/review.py — review_loop FSM.

TDD Phase 6: tests written BEFORE implementation (RED phase).

Covers:
- Baseline restore invariant
- Happy path (accept with typed 'yes' when had_readme_before=True)
- Claude non-zero exit → redo/discard prompt only
- Claude timeout → retry/skip/quit
- Blast guard: 2 changed files → failed + ensure_clean
- Secret detected → force typed 'yes-i-checked'
- Accept with had_readme_before=True requires typed 'yes'
- View toggle: v/V/o re-display then re-prompt
- Redo loop N times then accept
- Discard restores baseline
- _show_pager fallback logic
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Module under test (not yet written — tests will FAIL until implementation done)
from src.review import ReviewResult, _show_pager, review_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# Porcelain output for a single README change
_PORCELAIN_README_ONLY = " M README.md\n"
# Porcelain output touching README + another file (blast guard trip)
_PORCELAIN_TWO_FILES = " M README.md\n M src/main.py\n"
# Empty porcelain (no changes)
_PORCELAIN_EMPTY = ""


# ---------------------------------------------------------------------------
# Helper: build a subprocess.run side_effect list
# ---------------------------------------------------------------------------

def _make_subprocess_side_effects(
    *,
    extra_before_claude=None,   # list of CompletedProcess inserted before claude call
    claude_result=None,          # what claude returns (default: returncode=0)
    porcelain_output=_PORCELAIN_README_ONLY,
    readme_content="# Generated README\n",
    git_checkout_result=None,    # what git checkout returns (default: returncode=0)
):
    """Build a deterministic side_effect list for subprocess.run calls.

    Call order for a single iteration (step 2 → step 4):
      0: git checkout -- README.md   (baseline restore)
      1: git clean -f README.md      (baseline restore)
      2: claude -p /create-readme …  (invoke claude)
      3: git status --porcelain      (blast guard)
    """
    results = []
    if extra_before_claude:
        results.extend(extra_before_claude)

    # git checkout -- README.md
    co = git_checkout_result if git_checkout_result is not None else _make_completed(0)
    results.append(co)
    # git clean -f README.md
    results.append(_make_completed(0))

    # claude
    if claude_result is None:
        claude_result = _make_completed(0)
    results.append(claude_result)

    # git status --porcelain
    results.append(_make_completed(0, stdout=porcelain_output))

    return results


# ---------------------------------------------------------------------------
# Section 1: _show_pager
# ---------------------------------------------------------------------------

class TestShowPager(unittest.TestCase):

    def test_uses_less_when_tty_and_less_available(self):
        with patch("shutil.which", return_value="/usr/bin/less"), \
             patch("sys.stdout") as mock_stdout, \
             patch("subprocess.run") as mock_run:
            mock_stdout.isatty.return_value = True
            _show_pager("hello")
        mock_run.assert_called_once_with(
            ["less", "-R"], input="hello", text=True
        )

    def test_falls_back_to_print_when_not_tty(self):
        with patch("shutil.which", return_value="/usr/bin/less"), \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.print") as mock_print, \
             patch("subprocess.run") as mock_run:
            mock_stdout.isatty.return_value = False
            _show_pager("some text")
        mock_print.assert_called_once_with("some text")
        mock_run.assert_not_called()

    def test_falls_back_to_print_when_less_not_found(self):
        with patch("shutil.which", return_value=None), \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.print") as mock_print, \
             patch("subprocess.run") as mock_run:
            mock_stdout.isatty.return_value = True
            _show_pager("some text")
        mock_print.assert_called_once_with("some text")
        mock_run.assert_not_called()

    def test_falls_back_to_print_when_not_tty_and_no_less(self):
        with patch("shutil.which", return_value=None), \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.print") as mock_print, \
             patch("subprocess.run") as mock_run:
            mock_stdout.isatty.return_value = False
            _show_pager("some text")
        mock_print.assert_called_once_with("some text")
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Section 2: Baseline restore invariant
# ---------------------------------------------------------------------------

class TestBaselineRestoreInvariant(unittest.TestCase):

    def test_baseline_restore_called_on_first_entry(self):
        """Step 2 always calls git checkout -- README.md and git clean -f README.md."""
        readme_content = "# My README\n"
        subprocess_effects = _make_subprocess_side_effects(
            readme_content=readme_content,
        )

        with patch("subprocess.run", side_effect=subprocess_effects) as mock_run, \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["yes"]):  # accept with typed yes
            result = review_loop(Path("/repo"), had_readme_before=True)

        # The first two subprocess calls must be baseline restore
        calls = mock_run.call_args_list
        self.assertEqual(calls[0], call(
            ["git", "checkout", "--", "README.md"],
            cwd=Path("/repo"),
            check=False,
            capture_output=True,
            text=True,
        ))
        self.assertEqual(calls[1], call(
            ["git", "clean", "-f", "README.md"],
            cwd=Path("/repo"),
            check=False,
            capture_output=True,
            text=True,
        ))
        self.assertEqual(result.status, "accepted")

    def test_baseline_restore_called_on_redo(self):
        """When user chooses redo, step-2 baseline restore runs again."""
        readme_content = "# My README\n"
        # First iteration: claude succeeds, blast guard passes, user says redo
        # Second iteration: claude succeeds, blast guard passes, user says accept
        iter1_checkout = _make_completed(0)
        iter1_clean = _make_completed(0)
        iter1_claude = _make_completed(0)
        iter1_porcelain = _make_completed(0, stdout=_PORCELAIN_README_ONLY)

        iter2_checkout = _make_completed(0)
        iter2_clean = _make_completed(0)
        iter2_claude = _make_completed(0)
        iter2_porcelain = _make_completed(0, stdout=_PORCELAIN_README_ONLY)

        subprocess_effects = [
            iter1_checkout, iter1_clean, iter1_claude, iter1_porcelain,
            iter2_checkout, iter2_clean, iter2_claude, iter2_porcelain,
        ]

        with patch("subprocess.run", side_effect=subprocess_effects) as mock_run, \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["r", "yes"]):  # redo, then accept
            result = review_loop(Path("/repo"), had_readme_before=True)

        calls = mock_run.call_args_list
        # calls[0..1] = first baseline restore
        # calls[2] = first claude
        # calls[3] = first porcelain
        # calls[4..5] = second baseline restore (redo entry)
        # calls[6] = second claude
        # calls[7] = second porcelain
        self.assertEqual(len(calls), 8)

        # Verify second baseline restore
        self.assertEqual(calls[4], call(
            ["git", "checkout", "--", "README.md"],
            cwd=Path("/repo"),
            check=False,
            capture_output=True,
            text=True,
        ))
        self.assertEqual(calls[5], call(
            ["git", "clean", "-f", "README.md"],
            cwd=Path("/repo"),
            check=False,
            capture_output=True,
            text=True,
        ))
        self.assertEqual(result.status, "accepted")

    def test_baseline_restore_ok_when_readme_not_exist(self):
        """git checkout returns non-zero (README.md not tracked) — that is OK."""
        readme_content = "# Brand new\n"
        subprocess_effects = _make_subprocess_side_effects(
            git_checkout_result=_make_completed(1, stderr="error: pathspec 'README.md' did not match any file"),
            readme_content=readme_content,
        )
        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", return_value="a"):  # accept (no had_readme_before)
            result = review_loop(Path("/repo"), had_readme_before=False)
        self.assertEqual(result.status, "accepted")


# ---------------------------------------------------------------------------
# Section 3: Happy path
# ---------------------------------------------------------------------------

class TestHappyPath(unittest.TestCase):

    def test_accept_without_had_readme_before(self):
        """New repo: accept with single 'a' key, no typed 'yes' required."""
        readme_content = "# New README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", return_value="a"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")
        self.assertIsNone(result.reason)

    def test_accept_with_had_readme_before_requires_typed_yes(self):
        """Existing repo: accept requires explicit typed 'yes'."""
        readme_content = "# Updated README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", return_value="yes"):
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "accepted")

    def test_risky_files_found_then_skip(self):
        """Pre-Claude risky scan finds files → user chooses skip → skipped."""
        with patch("subprocess.run"), \
             patch("src.review.secrets.scan_repo_for_risky_files",
                   return_value=[Path("/repo/.env")]), \
             patch("builtins.input", return_value="s"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")

    def test_risky_files_found_then_continue(self):
        """Pre-Claude risky scan finds files → user continues → proceeds."""
        readme_content = "# README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files",
                   return_value=[Path("/repo/.env")]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["c", "a"]):  # continue, then accept
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")


# ---------------------------------------------------------------------------
# Section 4: Claude non-zero exit
# ---------------------------------------------------------------------------

class TestClaudeNonZeroExit(unittest.TestCase):

    def test_nonzero_exit_shows_redo_discard_prompt(self):
        """Claude non-zero → redo/discard only, no accept prompt shown."""
        subprocess_effects = [
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(1),   # claude non-zero
        ]

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.safety.ensure_clean"), \
             patch("builtins.input", return_value="d") as mock_input:
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")

    def test_nonzero_exit_redo_then_success(self):
        """Claude non-zero → redo → claude success → accept."""
        readme_content = "# README\n"
        subprocess_effects = [
            # First iteration: claude fails
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(1),   # claude non-zero
            # Second iteration (redo): success
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(0),   # claude success
            _make_completed(0, stdout=_PORCELAIN_README_ONLY),  # porcelain
        ]

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["r", "a"]):  # redo, accept
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")


# ---------------------------------------------------------------------------
# Section 5: Claude timeout
# ---------------------------------------------------------------------------

class TestClaudeTimeout(unittest.TestCase):

    def _timeout_side_effect(self, *args, **kwargs):
        """Raise TimeoutExpired for claude invocation, succeed for git ops."""
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "claude":
            raise subprocess.TimeoutExpired(cmd, timeout=300)
        return _make_completed(0)

    def test_timeout_skip(self):
        """Claude timeout → user chooses skip → skipped."""
        with patch("subprocess.run", side_effect=self._timeout_side_effect), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("builtins.input", return_value="s"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")

    def test_timeout_quit(self):
        """Claude timeout → user chooses quit → quit."""
        with patch("subprocess.run", side_effect=self._timeout_side_effect), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("builtins.input", return_value="q"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "quit")

    def test_timeout_retry_triggers_baseline_restore_and_reinvoke(self):
        """Claude timeout → retry → baseline restore runs + claude invoked again."""
        readme_content = "# README after retry\n"
        call_count = {"n": 0}

        def smart_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if not cmd:
                return _make_completed(0)
            if cmd[0] == "claude":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise subprocess.TimeoutExpired(cmd, timeout=300)
                # Second call succeeds
                return _make_completed(0)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _make_completed(0, stdout=_PORCELAIN_README_ONLY)
            return _make_completed(0)

        with patch("subprocess.run", side_effect=smart_side_effect) as mock_run, \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["r", "a"]):  # retry, then accept
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")
        self.assertEqual(call_count["n"], 2)

        # After retry, baseline restore must appear in call_args_list
        git_checkout_calls = [
            c for c in mock_run.call_args_list
            if c.args and c.args[0][:3] == ["git", "checkout", "--"]
        ]
        # Should have been called at least twice: initial entry + retry entry
        self.assertGreaterEqual(len(git_checkout_calls), 2)


# ---------------------------------------------------------------------------
# Section 6: Blast-radius guard
# ---------------------------------------------------------------------------

class TestBlastRadiusGuard(unittest.TestCase):

    def test_two_changed_files_returns_failed(self):
        """git status --porcelain shows 2 files → failed with ensure_clean called."""
        subprocess_effects = [
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(0),   # claude
            _make_completed(0, stdout=_PORCELAIN_TWO_FILES),  # porcelain: 2 files
        ]

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.safety.ensure_clean") as mock_ensure_clean:
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "failed")
        self.assertIn("claude_touched_other_files", result.reason)
        mock_ensure_clean.assert_called_once_with(Path("/repo"))

    def test_empty_porcelain_returns_failed(self):
        """git status --porcelain shows no changes → claude did nothing → failed."""
        subprocess_effects = [
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(0),   # claude
            _make_completed(0, stdout=_PORCELAIN_EMPTY),  # no changes
        ]

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.safety.ensure_clean") as mock_ensure_clean:
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "failed")
        mock_ensure_clean.assert_called_once()

    def test_readme_only_passes_blast_guard(self):
        """Only README.md changed → blast guard passes, proceeds to accept."""
        readme_content = "# README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", return_value="a"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")


# ---------------------------------------------------------------------------
# Section 7: Secret scan in README content
# ---------------------------------------------------------------------------

class TestSecretScanInReadme(unittest.TestCase):

    def test_secret_detected_typed_yes_i_checked_accepts(self):
        """Secret found → user types 'yes-i-checked' → accepted."""
        readme_content = "AKIAIOSFODNN7EXAMPLE\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets",
                   return_value=["AKIAIOSFODNN7EXAMPLE"]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["yes-i-checked", "a"]):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")

    def test_secret_detected_wrong_input_discards(self):
        """Secret found → user does NOT type 'yes-i-checked' → skipped."""
        readme_content = "AKIAIOSFODNN7EXAMPLE\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets",
                   return_value=["AKIAIOSFODNN7EXAMPLE"]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("src.review.safety.ensure_clean"), \
             patch("builtins.input", return_value="yes"):  # close but not exact
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")

    def test_no_secret_proceeds_normally(self):
        """No secrets → accept prompt shown normally."""
        readme_content = "# Clean README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", return_value="a"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")


# ---------------------------------------------------------------------------
# Section 8: Accept prompt — had_readme_before=True requires typed 'yes'
# ---------------------------------------------------------------------------

class TestAcceptPromptTypedYes(unittest.TestCase):

    def test_typing_y_alone_re_prompts(self):
        """Typing 'y' (not 'yes') when had_readme_before=True should re-prompt."""
        readme_content = "# Updated\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["y", "yes"]):  # y ignored, then yes
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "accepted")

    def test_typing_a_when_had_readme_before_re_prompts(self):
        """Typing 'a' when had_readme_before=True must not accept — requires 'yes'."""
        readme_content = "# Updated\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["a", "yes"]):  # 'a' ignored, then yes
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "accepted")

    def test_discard_works_for_had_readme_before(self):
        """Typing 'd' discards even when had_readme_before=True."""
        readme_content = "# Updated\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("src.review.safety.ensure_clean"), \
             patch("builtins.input", return_value="d"):
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "skipped")


# ---------------------------------------------------------------------------
# Section 9: View toggle
# ---------------------------------------------------------------------------

class TestViewToggle(unittest.TestCase):

    def test_view_diff_re_displays_then_re_prompts(self):
        """Typing 'v' shows diff via _show_pager then re-prompts (same step)."""
        readme_content = "# README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager") as mock_pager, \
             patch("builtins.input", side_effect=["v", "a"]):  # view diff, then accept
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")
        # _show_pager should have been called at least for the initial display + view
        self.assertGreaterEqual(mock_pager.call_count, 1)

    def test_view_full_new_re_displays_then_re_prompts(self):
        """Typing 'V' shows full new README via _show_pager then re-prompts."""
        readme_content = "# README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager") as mock_pager, \
             patch("builtins.input", side_effect=["V", "a"]):  # view full, then accept
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")
        self.assertGreaterEqual(mock_pager.call_count, 1)

    def test_view_old_readme_re_displays_then_re_prompts(self):
        """Typing 'o' shows old README then re-prompts."""
        readme_content = "# README\n"
        old_content = "# Old README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file",
                   side_effect=[old_content, readme_content]), \
             patch("src.review._show_pager") as mock_pager, \
             patch("builtins.input", side_effect=["o", "yes"]):  # view old, then accept
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "accepted")

    def test_multiple_view_toggles_before_accept(self):
        """Multiple view toggles (v, V, o) all work and loop stays at step 6."""
        readme_content = "# README\n"
        old_content = "# Old README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file",
                   side_effect=[old_content, readme_content, old_content]), \
             patch("src.review._show_pager") as mock_pager, \
             patch("builtins.input", side_effect=["v", "V", "o", "yes"]):
            result = review_loop(Path("/repo"), had_readme_before=True)

        self.assertEqual(result.status, "accepted")
        self.assertGreaterEqual(mock_pager.call_count, 3)


# ---------------------------------------------------------------------------
# Section 10: Redo loop
# ---------------------------------------------------------------------------

class TestRedoLoop(unittest.TestCase):

    def test_redo_three_times_then_accept(self):
        """User redoes 3 times, then accepts — all baseline restores accounted for."""
        readme_content = "# Final README\n"
        # Build 4 iterations (3 redo + 1 accept)
        subprocess_effects = []
        for _ in range(4):
            subprocess_effects.extend([
                _make_completed(0),  # git checkout
                _make_completed(0),  # git clean
                _make_completed(0),  # claude
                _make_completed(0, stdout=_PORCELAIN_README_ONLY),  # porcelain
            ])

        with patch("subprocess.run", side_effect=subprocess_effects) as mock_run, \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["r", "r", "r", "a"]):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "accepted")

        # Count git checkout -- README.md calls = 4 (once per iteration)
        checkout_calls = [
            c for c in mock_run.call_args_list
            if c.args and c.args[0][:3] == ["git", "checkout", "--"]
        ]
        self.assertEqual(len(checkout_calls), 4)


# ---------------------------------------------------------------------------
# Section 11: Discard restores baseline
# ---------------------------------------------------------------------------

class TestDiscardRestoresBaseline(unittest.TestCase):

    def test_discard_calls_ensure_clean(self):
        """Discarding calls safety.ensure_clean to restore baseline state."""
        readme_content = "# README\n"
        subprocess_effects = _make_subprocess_side_effects(readme_content=readme_content)

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._read_file", return_value=readme_content), \
             patch("src.review._show_pager"), \
             patch("src.review.safety.ensure_clean") as mock_ensure_clean, \
             patch("builtins.input", return_value="d"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")
        mock_ensure_clean.assert_called_once_with(Path("/repo"))

    def test_nonzero_discard_calls_ensure_clean(self):
        """Non-zero exit then discard also calls ensure_clean."""
        subprocess_effects = [
            _make_completed(0),   # git checkout
            _make_completed(0),   # git clean
            _make_completed(1),   # claude non-zero
        ]

        with patch("subprocess.run", side_effect=subprocess_effects), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.safety.ensure_clean") as mock_ensure_clean, \
             patch("builtins.input", return_value="d"):
            result = review_loop(Path("/repo"), had_readme_before=False)

        self.assertEqual(result.status, "skipped")
        mock_ensure_clean.assert_called_once_with(Path("/repo"))


# ---------------------------------------------------------------------------
# Section 12: ReviewResult dataclass
# ---------------------------------------------------------------------------

class TestReviewResult(unittest.TestCase):

    def test_accepted_result(self):
        r = ReviewResult(status="accepted", reason=None)
        self.assertEqual(r.status, "accepted")
        self.assertIsNone(r.reason)

    def test_failed_result_has_reason(self):
        r = ReviewResult(status="failed", reason="claude_touched_other_files")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.reason, "claude_touched_other_files")

    def test_skipped_result(self):
        r = ReviewResult(status="skipped", reason=None)
        self.assertEqual(r.status, "skipped")

    def test_quit_result(self):
        r = ReviewResult(status="quit", reason=None)
        self.assertEqual(r.status, "quit")


if __name__ == "__main__":
    unittest.main()
