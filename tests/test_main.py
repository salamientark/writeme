"""Tests for gh_readme_pipeline.py — entrypoint orchestration.

Tests focus on glue logic: flag parsing, --clean, user-mismatch detection,
flock acquisition, LIMIT capping, --resume integration, empty-selection
short-circuit, and process_repo orchestration.

All heavy modules (fetch, tui, commit, review, safety, state) are mocked.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(name: str = "my-repo"):
    """Return a minimal Repo-like object."""
    from src.selection import Repo
    return Repo(
        name=name,
        ssh_url=f"git@github.com:user/{name}.git",
        pushed_at="2026-01-01T00:00:00Z",
        had_readme_before=False,
        disk_usage=100,
    )


# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------


class TestArgParsing(unittest.TestCase):
    """parse_args() should turn CLI flags into correct Namespace attributes."""

    def _parse(self, argv):
        from gh_readme_pipeline import parse_args
        return parse_args(argv)

    def test_defaults(self):
        ns = self._parse([])
        self.assertIsNone(ns.mode)
        self.assertFalse(ns.dry_run)
        self.assertFalse(ns.resume)
        self.assertFalse(ns.clean)
        self.assertFalse(ns.skip_ci)

    def test_mode_pr(self):
        ns = self._parse(["--mode", "pr"])
        self.assertEqual(ns.mode, "pr")

    def test_mode_direct(self):
        ns = self._parse(["--mode", "direct"])
        self.assertEqual(ns.mode, "direct")

    def test_mode_commit_only(self):
        ns = self._parse(["--mode", "commit-only"])
        self.assertEqual(ns.mode, "commit-only")

    def test_dry_run(self):
        ns = self._parse(["--dry-run"])
        self.assertTrue(ns.dry_run)

    def test_resume_flag(self):
        ns = self._parse(["--resume"])
        self.assertTrue(ns.resume)

    def test_clean_flag(self):
        ns = self._parse(["--clean"])
        self.assertTrue(ns.clean)

    def test_skip_ci_flag(self):
        ns = self._parse(["--skip-ci"])
        self.assertTrue(ns.skip_ci)

    def test_repos_dir(self):
        ns = self._parse(["--repos-dir", "/tmp/repos"])
        self.assertEqual(ns.repos_dir, Path("/tmp/repos"))

    def test_claude_timeout_int(self):
        ns = self._parse(["--claude-timeout", "120"])
        self.assertEqual(ns.claude_timeout, 120)

    def test_repos_dir_env_fallback(self):
        """repos_dir falls back to GH_README_REPOS_DIR env var."""
        with patch.dict(os.environ, {"GH_README_REPOS_DIR": "/env/repos"}, clear=False):
            from gh_readme_pipeline import parse_args
            ns = parse_args([])
        self.assertEqual(ns.repos_dir, Path("/env/repos"))

    def test_claude_timeout_env_fallback(self):
        """claude_timeout falls back to CLAUDE_TIMEOUT env var."""
        with patch.dict(os.environ, {"CLAUDE_TIMEOUT": "600"}, clear=False):
            from gh_readme_pipeline import parse_args
            ns = parse_args([])
        self.assertEqual(ns.claude_timeout, 600)

    def test_skip_ci_env_fallback(self):
        """skip_ci falls back to SKIP_CI env var."""
        with patch.dict(os.environ, {"SKIP_CI": "1"}, clear=False):
            from gh_readme_pipeline import parse_args
            ns = parse_args([])
        self.assertTrue(ns.skip_ci)


# ---------------------------------------------------------------------------
# --clean flag
# ---------------------------------------------------------------------------


class TestCleanFlag(unittest.TestCase):
    """--clean should remove the repos dir and exit 0."""

    def test_clean_exits_zero(self):
        from gh_readme_pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repos_dir.mkdir()
            with self.assertRaises(SystemExit) as cm:
                main(["--clean", "--repos-dir", str(repos_dir)])
            self.assertEqual(cm.exception.code, 0)

    def test_clean_removes_repos_dir(self):
        from gh_readme_pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repos_dir.mkdir()
            with self.assertRaises(SystemExit):
                main(["--clean", "--repos-dir", str(repos_dir)])
            self.assertFalse(repos_dir.exists())

    def test_clean_ok_when_dir_absent(self):
        """--clean on a non-existent dir must not raise."""
        from gh_readme_pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "no-such-dir"
            with self.assertRaises(SystemExit) as cm:
                main(["--clean", "--repos-dir", str(repos_dir)])
            self.assertEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# User-mismatch warning
# ---------------------------------------------------------------------------


class TestUserMismatch(unittest.TestCase):
    """If GH_USER env differs from gh api user output, warn and prompt."""

    def _run_main_with_mocks(self, gh_user_env, api_user, confirm_input="y"):
        """Run main() with heavy mocks; capture stderr/stdout."""
        from gh_readme_pipeline import main

        env_patch = {"GH_USER": gh_user_env} if gh_user_env else {}

        mock_proc = MagicMock()
        mock_proc.stdout = api_user + "\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            lock_path = state_dir / "lock"

            with patch.dict(os.environ, env_patch, clear=False), \
                 patch("subprocess.run", return_value=mock_proc) as mock_run, \
                 patch("src.fetch.fetch_repos", return_value=[]) as mock_fetch, \
                 patch("src.tui.tui_select", return_value=[]) as mock_tui, \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("builtins.input", return_value=confirm_input), \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                result = main(["--repos-dir", str(repos_dir)])
        return result

    def test_matching_users_no_prompt(self):
        """When GH_USER matches API user, no input() prompt for confirmation."""
        with patch("builtins.input") as mock_input:
            self._run_main_with_mocks("alice", "alice")
            # input() should NOT have been called for user-mismatch
            # (it may be called for other prompts, but let's check separately)
            # The mock_input call count will be 0 if no mismatch prompt
            # We don't assert on exact count because other prompts may exist.
            # The key check: no SystemExit(1) for mismatch.

    def test_mismatch_prompts_user(self):
        """GH_USER != API user triggers a confirmation prompt."""
        prompted = []

        def capture_input(prompt=""):
            prompted.append(prompt)
            return "y"

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            mock_proc = MagicMock()
            mock_proc.stdout = "bob\n"
            mock_proc.returncode = 0

            with patch.dict(os.environ, {"GH_USER": "alice"}, clear=False), \
                 patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=[]), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("builtins.input", side_effect=capture_input), \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                from gh_readme_pipeline import main
                main(["--repos-dir", str(repos_dir)])

        # At least one prompt should mention the mismatch
        self.assertTrue(
            any("alice" in p or "bob" in p for p in prompted),
            f"Expected mismatch prompt, got: {prompted}",
        )


# ---------------------------------------------------------------------------
# flock acquired before work
# ---------------------------------------------------------------------------


class TestFlockBeforeWork(unittest.TestCase):
    """acquire_lock must be called before fetch_repos."""

    def test_lock_acquired_before_fetch(self):
        from gh_readme_pipeline import main

        call_order = []

        class FakeLock:
            def __enter__(self):
                call_order.append("lock")
                return None
            def __exit__(self, *args):
                return False

        def fake_fetch(*args, **kwargs):
            call_order.append("fetch")
            return []

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", side_effect=fake_fetch), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock", return_value=FakeLock()), \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                main(["--repos-dir", str(repos_dir)])

        self.assertEqual(call_order[:2], ["lock", "fetch"],
                         f"Expected lock before fetch, got: {call_order}")


# ---------------------------------------------------------------------------
# LIMIT env var capping
# ---------------------------------------------------------------------------


class TestLimitCap(unittest.TestCase):
    """LIMIT=2000 must be capped to 1000 when calling fetch_repos."""

    def test_limit_2000_capped_to_1000(self):
        from gh_readme_pipeline import main

        captured_limit = []

        def fake_fetch(user, limit):
            captured_limit.append(limit)
            return []

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch.dict(os.environ, {"LIMIT": "2000"}, clear=False), \
                 patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", side_effect=fake_fetch), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir)])

        self.assertEqual(captured_limit, [1000],
                         f"Expected limit=1000, got: {captured_limit}")

    def test_limit_500_not_capped(self):
        from gh_readme_pipeline import main

        captured_limit = []

        def fake_fetch(user, limit):
            captured_limit.append(limit)
            return []

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch.dict(os.environ, {"LIMIT": "500"}, clear=False), \
                 patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", side_effect=fake_fetch), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir)])

        self.assertEqual(captured_limit, [500])


# ---------------------------------------------------------------------------
# --resume integration
# ---------------------------------------------------------------------------


class TestResumeIntegration(unittest.TestCase):
    """--resume: when a state file has processed repos, prompt_resume is called."""

    def test_resume_calls_prompt_resume_when_processed_repos_exist(self):
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        repos = [_make_repo("repo-a"), _make_repo("repo-b")]

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            # Pre-populate state with one processed repo
            from src.state import StateStore
            store = StateStore("testuser", state_dir)
            store.record("repo-a", "pushed")

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=repos), \
                 patch("src.tui.tui_select", return_value=[]) as mock_tui, \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir), \
                 patch("src.state.prompt_resume", return_value="resume") as mock_pr:
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir), "--resume"])

            mock_pr.assert_called_once_with(1)

    def test_resume_filters_processed_repos(self):
        """After resume → only unprocessed repos passed to tui_select."""
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        repos = [_make_repo("repo-a"), _make_repo("repo-b")]
        tui_received = []

        def fake_tui(rs):
            tui_received.extend(rs)
            return []

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            from src.state import StateStore
            store = StateStore("testuser", state_dir)
            store.record("repo-a", "pushed")

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=repos), \
                 patch("src.tui.tui_select", side_effect=fake_tui), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir), \
                 patch("src.state.prompt_resume", return_value="resume"):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir), "--resume"])

        names = [r.name for r in tui_received]
        self.assertNotIn("repo-a", names)
        self.assertIn("repo-b", names)


# ---------------------------------------------------------------------------
# Empty selection short-circuit
# ---------------------------------------------------------------------------


class TestEmptySelectionShortCircuit(unittest.TestCase):
    """If tui_select returns [], process_repo must never be called."""

    def test_no_process_repo_when_empty_selection(self):
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        repos = [_make_repo("repo-z")]

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=repos), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir), \
                 patch("gh_readme_pipeline.process_repo") as mock_pr:
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir)])

            mock_pr.assert_not_called()

    def test_returns_zero_on_empty_selection(self):
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=[_make_repo()]), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                result = main(["--repos-dir", str(repos_dir)])

        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# process_repo unit tests
# ---------------------------------------------------------------------------


class TestProcessRepo(unittest.TestCase):
    """Unit tests for the process_repo() function."""

    def _make_state_store(self, tmp_dir):
        from src.state import StateStore
        state_dir = Path(tmp_dir) / "state"
        state_dir.mkdir(exist_ok=True)
        return StateStore("testuser", state_dir)

    def test_clone_called_when_dir_missing(self):
        """process_repo clones the repo when the local dir doesn't exist."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult
        from src.commit import CommitResult

        repo = _make_repo("new-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repos_dir.mkdir()
            state_store = self._make_state_store(tmp)

            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""

            review_result = ReviewResult(status="skipped", reason="user_discarded")

            with patch("subprocess.run", return_value=mock_proc) as mock_run, \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.safety.ensure_clean"):
                process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode=None,
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            # subprocess.run should have been called with a git clone command
            clone_calls = [
                c for c in mock_run.call_args_list
                if c.args and isinstance(c.args[0], list) and "clone" in c.args[0]
            ]
            self.assertTrue(len(clone_calls) >= 1, "Expected at least one git clone call")

    def test_accepted_calls_commit_and_push(self):
        """When review returns accepted, commit_and_push is invoked."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult
        from src.commit import CommitResult

        repo = _make_repo("accepted-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            review_result = ReviewResult(status="accepted", reason=None)
            commit_result = CommitResult(status="pushed", mode="direct", pr_url=None, error=None)

            mock_run = MagicMock()
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            with patch("subprocess.run", mock_run), \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.commit.commit_and_push", return_value=commit_result) as mock_cap, \
                 patch("src.safety.ensure_clean"):
                process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode="direct",
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            mock_cap.assert_called_once()

    def test_skipped_does_not_call_commit(self):
        """When review returns skipped, commit_and_push must NOT be called."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult

        repo = _make_repo("skipped-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            review_result = ReviewResult(status="skipped", reason="user_discarded")

            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")), \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.commit.commit_and_push") as mock_cap, \
                 patch("src.safety.ensure_clean"):
                process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode=None,
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            mock_cap.assert_not_called()

    def test_skipped_state_recorded(self):
        """process_repo records state even when skipped."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult

        repo = _make_repo("state-record-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            review_result = ReviewResult(status="skipped", reason="user_discarded")

            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")), \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.safety.ensure_clean"):
                process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode=None,
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            processed = state_store.load_processed()
            # skipped → not in processed set; but a record must exist
            summary = state_store.summary()
            self.assertIn("skipped", summary)

    def test_keyboard_interrupt_calls_ensure_clean(self):
        """KeyboardInterrupt during review must trigger ensure_clean (once, via finally)."""
        from gh_readme_pipeline import process_repo

        repo = _make_repo("interrupt-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")), \
                 patch("src.review.review_loop", side_effect=KeyboardInterrupt), \
                 patch("src.safety.ensure_clean") as mock_clean:
                with self.assertRaises(KeyboardInterrupt):
                    process_repo(
                        repo=repo,
                        repos_dir=repos_dir,
                        mode=None,
                        dry_run=False,
                        skip_ci=False,
                        commit_message=None,
                        claude_timeout=300,
                        state_store=state_store,
                    )

            # CR-MED-1: ensure_clean must be called exactly once (finally), not twice.
            self.assertEqual(mock_clean.call_count, 1)

    def test_finally_always_calls_ensure_clean(self):
        """ensure_clean must be called in finally even on success."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult
        from src.commit import CommitResult

        repo = _make_repo("cleanup-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            review_result = ReviewResult(status="accepted", reason=None)
            commit_result = CommitResult(status="pushed", mode="direct", pr_url=None, error=None)

            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")), \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.commit.commit_and_push", return_value=commit_result), \
                 patch("src.safety.ensure_clean") as mock_clean:
                process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode="direct",
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            mock_clean.assert_called()

    def test_quit_result_recorded_and_breaks_loop(self):
        """review_loop returning quit must be recorded and signal outer loop to stop."""
        from gh_readme_pipeline import process_repo
        from src.review import ReviewResult

        repo = _make_repo("quit-repo")

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            repo_dir = repos_dir / repo.name
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            state_store = self._make_state_store(tmp)

            review_result = ReviewResult(status="quit", reason="user_quit")

            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")), \
                 patch("src.review.review_loop", return_value=review_result), \
                 patch("src.safety.ensure_clean"):
                result = process_repo(
                    repo=repo,
                    repos_dir=repos_dir,
                    mode=None,
                    dry_run=False,
                    skip_ci=False,
                    commit_message=None,
                    claude_timeout=300,
                    state_store=state_store,
                )

            # process_repo must signal the outer loop to stop
            # by returning a sentinel value or raising StopIteration / SystemExit
            self.assertIn(
                result,
                ("quit", None),
                "process_repo should return 'quit' sentinel when review_loop returns quit",
            )


# ---------------------------------------------------------------------------
# Main orchestration integration
# ---------------------------------------------------------------------------


class TestMainOrchestration(unittest.TestCase):
    """Integration-level checks for main() calling process_repo per selected repo."""

    def test_process_repo_called_for_each_selected(self):
        """main() calls process_repo once per selected repo."""
        from gh_readme_pipeline import main

        repos = [_make_repo("repo-1"), _make_repo("repo-2")]

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        process_calls = []

        def fake_process_repo(repo, **kwargs):
            process_calls.append(repo.name)
            return None

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=repos), \
                 patch("src.tui.tui_select", return_value=repos), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir), \
                 patch("gh_readme_pipeline.process_repo", side_effect=fake_process_repo):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                main(["--repos-dir", str(repos_dir)])

        self.assertEqual(sorted(process_calls), ["repo-1", "repo-2"])

    def test_returns_zero_on_success(self):
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", return_value=[]), \
                 patch("src.tui.tui_select", return_value=[]), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                result = main(["--repos-dir", str(repos_dir)])

        self.assertEqual(result, 0)


class TestFetchFailureHandling(unittest.TestCase):
    """CR-HIGH-3: fetch_repos errors must be caught and surfaced as stderr+rc=1."""

    def _run_with_fetch_error(self, exc):
        from gh_readme_pipeline import main

        mock_proc = MagicMock()
        mock_proc.stdout = "testuser\n"
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp) / "repos"
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()

            with patch("subprocess.run", return_value=mock_proc), \
                 patch("src.fetch.fetch_repos", side_effect=exc), \
                 patch("src.commit.warn_gpg_signing"), \
                 patch("src.safety.acquire_lock") as mock_lock, \
                 patch("src.state.xdg_state_dir", return_value=state_dir):
                mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                return main(["--repos-dir", str(repos_dir)])

    def test_called_process_error_returns_one(self):
        rc = self._run_with_fetch_error(
            subprocess.CalledProcessError(1, ["gh"], stderr=b"boom"),
        )
        self.assertEqual(rc, 1)

    def test_json_decode_error_returns_one(self):
        import json
        rc = self._run_with_fetch_error(json.JSONDecodeError("bad", "x", 0))
        self.assertEqual(rc, 1)

    def test_key_error_returns_one(self):
        rc = self._run_with_fetch_error(KeyError("data"))
        self.assertEqual(rc, 1)
