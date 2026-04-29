"""Tests for src/commit.py — commit_and_push FSM.

TDD Phase 7: tests written BEFORE implementation (RED phase).

Covers:
- Mode prompt: each input char maps to correct mode; --mode bypasses
- Verb selection: had_readme_before=True → 'update', False → 'add'
- skip_ci=True appends '[skip ci]' to commit message
- PR mode: branch checkout, git add, commit, push, gh pr create
- Direct mode: no branch, git add, commit, push (current branch)
- Commit-only: git add, commit, no push/PR
- Dry-run: commits but skips git push and gh pr create
- Push rejection: stderr captured, status='failed'
- GPG warn: commit.gpgsign=true + no signingkey → prints warning to stderr
- commit_message override
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from src.commit import CommitResult, commit_and_push, warn_gpg_signing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# Section 1: CommitResult dataclass
# ---------------------------------------------------------------------------

class TestCommitResult(unittest.TestCase):

    def test_pushed_result(self):
        r = CommitResult(status="pushed", mode="direct", pr_url=None, error=None)
        self.assertEqual(r.status, "pushed")
        self.assertEqual(r.mode, "direct")

    def test_pr_opened_result(self):
        r = CommitResult(status="pr_opened", mode="pr", pr_url="https://github.com/x/y/pull/1", error=None)
        self.assertEqual(r.status, "pr_opened")
        self.assertEqual(r.pr_url, "https://github.com/x/y/pull/1")

    def test_commit_only_result(self):
        r = CommitResult(status="commit_only", mode="commit-only", pr_url=None, error=None)
        self.assertEqual(r.status, "commit_only")

    def test_skipped_result(self):
        r = CommitResult(status="skipped", mode=None, pr_url=None, error=None)
        self.assertEqual(r.status, "skipped")

    def test_failed_result(self):
        r = CommitResult(status="failed", mode="direct", pr_url=None, error="push rejected")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error, "push rejected")


# ---------------------------------------------------------------------------
# Section 2: Mode prompt
# ---------------------------------------------------------------------------

class TestModePrompt(unittest.TestCase):

    def _run_with_mode_input(self, char: str, had_readme_before: bool = False) -> CommitResult:
        """Run commit_and_push with no --mode flag, providing char as input."""
        # We need enough subprocess side effects for whatever mode the user picks
        side_effects = [
            # git add README.md
            _make_completed(0),
            # git commit
            _make_completed(0),
            # git push (for direct/pr modes) — only used if not skipped
            _make_completed(0),
            # gh pr create — only used in pr mode
            _make_completed(0, stdout="https://github.com/x/y/pull/1"),
            # branch checkout — only in pr mode
            _make_completed(0),
        ]

        def smart_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if not cmd:
                return _make_completed(0)
            if cmd[0] == "git" and cmd[1] == "checkout" and cmd[2] == "-b":
                return _make_completed(0)
            if cmd[0] == "git" and cmd[1] == "add":
                return _make_completed(0)
            if cmd[0] == "git" and cmd[1] == "commit":
                return _make_completed(0)
            if cmd[0] == "git" and cmd[1] == "push":
                return _make_completed(0)
            if cmd[0] == "gh" and cmd[1] == "pr":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=smart_run), \
             patch("builtins.input", return_value=char):
            return commit_and_push(
                Path("/repo"),
                mode=None,
                had_readme_before=had_readme_before,
            )

    def test_p_selects_pr_mode(self):
        result = self._run_with_mode_input("p")
        self.assertEqual(result.status, "pr_opened")

    def test_m_selects_direct_mode(self):
        result = self._run_with_mode_input("m")
        self.assertEqual(result.status, "pushed")

    def test_c_selects_commit_only_mode(self):
        result = self._run_with_mode_input("c")
        self.assertEqual(result.status, "commit_only")

    def test_n_selects_skip(self):
        result = self._run_with_mode_input("n")
        self.assertEqual(result.status, "skipped")

    def test_invalid_input_re_prompts(self):
        """Invalid chars should re-prompt until valid input."""
        def smart_run(*args, **kwargs):
            return _make_completed(0)

        with patch("subprocess.run", side_effect=smart_run), \
             patch("builtins.input", side_effect=["x", "z", "n"]):
            result = commit_and_push(Path("/repo"), mode=None, had_readme_before=False)

        self.assertEqual(result.status, "skipped")

    def test_mode_flag_bypasses_prompt(self):
        """When mode='skip', input() is never called."""
        with patch("builtins.input") as mock_input:
            result = commit_and_push(Path("/repo"), mode="skip", had_readme_before=False)

        mock_input.assert_not_called()
        self.assertEqual(result.status, "skipped")

    def test_mode_pr_flag_bypasses_prompt(self):
        """mode='pr' bypasses prompt and enters PR flow."""
        def smart_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=smart_run), \
             patch("builtins.input") as mock_input:
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        mock_input.assert_not_called()
        self.assertEqual(result.status, "pr_opened")

    def test_mode_direct_flag_bypasses_prompt(self):
        """mode='direct' bypasses prompt."""
        with patch("subprocess.run", return_value=_make_completed(0)), \
             patch("builtins.input") as mock_input:
            result = commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        mock_input.assert_not_called()
        self.assertEqual(result.status, "pushed")

    def test_mode_commit_only_flag_bypasses_prompt(self):
        """mode='commit-only' bypasses prompt."""
        with patch("subprocess.run", return_value=_make_completed(0)), \
             patch("builtins.input") as mock_input:
            result = commit_and_push(Path("/repo"), mode="commit-only", had_readme_before=False)

        mock_input.assert_not_called()
        self.assertEqual(result.status, "commit_only")


# ---------------------------------------------------------------------------
# Section 3: Verb selection
# ---------------------------------------------------------------------------

class TestVerbSelection(unittest.TestCase):

    def _capture_commit_message(self, had_readme_before: bool) -> str:
        """Run commit-only mode and capture the commit message used."""
        captured = {}

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "commit":
                # Find -m argument
                try:
                    idx = cmd.index("-m")
                    captured["msg"] = cmd[idx + 1]
                except (ValueError, IndexError):
                    pass
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(
                Path("/repo"),
                mode="commit-only",
                had_readme_before=had_readme_before,
            )
        return captured.get("msg", "")

    def test_add_verb_when_no_prior_readme(self):
        msg = self._capture_commit_message(had_readme_before=False)
        self.assertIn("add", msg)
        self.assertNotIn("update", msg)

    def test_update_verb_when_had_readme_before(self):
        msg = self._capture_commit_message(had_readme_before=True)
        self.assertIn("update", msg)
        self.assertNotIn("add", msg)

    def test_default_message_format(self):
        msg = self._capture_commit_message(had_readme_before=False)
        self.assertEqual(msg, "docs: add README")

    def test_default_message_update_format(self):
        msg = self._capture_commit_message(had_readme_before=True)
        self.assertEqual(msg, "docs: update README")


# ---------------------------------------------------------------------------
# Section 4: skip_ci flag
# ---------------------------------------------------------------------------

class TestSkipCiFlag(unittest.TestCase):

    def _capture_commit_message(self, skip_ci: bool, had_readme_before: bool = False) -> str:
        captured = {}

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "commit":
                try:
                    idx = cmd.index("-m")
                    captured["msg"] = cmd[idx + 1]
                except (ValueError, IndexError):
                    pass
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(
                Path("/repo"),
                mode="commit-only",
                had_readme_before=had_readme_before,
                skip_ci=skip_ci,
            )
        return captured.get("msg", "")

    def test_skip_ci_appends_marker(self):
        msg = self._capture_commit_message(skip_ci=True)
        self.assertIn("[skip ci]", msg)

    def test_no_skip_ci_no_marker(self):
        msg = self._capture_commit_message(skip_ci=False)
        self.assertNotIn("[skip ci]", msg)

    def test_skip_ci_message_format(self):
        msg = self._capture_commit_message(skip_ci=True, had_readme_before=False)
        self.assertEqual(msg, "docs: add README [skip ci]")


# ---------------------------------------------------------------------------
# Section 5: commit_message override
# ---------------------------------------------------------------------------

class TestCommitMessageOverride(unittest.TestCase):

    def test_custom_message_used(self):
        captured = {}

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "commit":
                try:
                    idx = cmd.index("-m")
                    captured["msg"] = cmd[idx + 1]
                except (ValueError, IndexError):
                    pass
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(
                Path("/repo"),
                mode="commit-only",
                had_readme_before=False,
                commit_message="custom: my message",
            )

        self.assertEqual(captured.get("msg"), "custom: my message")

    def test_custom_message_with_skip_ci(self):
        captured = {}

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "commit":
                try:
                    idx = cmd.index("-m")
                    captured["msg"] = cmd[idx + 1]
                except (ValueError, IndexError):
                    pass
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(
                Path("/repo"),
                mode="commit-only",
                had_readme_before=False,
                commit_message="custom: my message",
                skip_ci=True,
            )

        self.assertEqual(captured.get("msg"), "custom: my message [skip ci]")


# ---------------------------------------------------------------------------
# Section 6: PR mode
# ---------------------------------------------------------------------------

class TestPRMode(unittest.TestCase):

    def test_pr_mode_creates_branch(self):
        """PR mode runs git checkout -b docs/readme-pipeline-<ts>."""
        branch_name_used = {}
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
                if cmd[:2] == ["git", "checkout"] and len(cmd) > 2 and cmd[2] == "-b":
                    branch_name_used["branch"] = cmd[3]
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertEqual(result.status, "pr_opened")
        self.assertIn("branch", branch_name_used)
        self.assertTrue(branch_name_used["branch"].startswith("docs/readme-pipeline-"))

    def test_pr_mode_git_add_readme(self):
        """PR mode stages only README.md."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        add_calls = [c for c in commands_run if c[:2] == ["git", "add"]]
        self.assertTrue(any("README.md" in c for c in add_calls))

    def test_pr_mode_calls_gh_pr_create(self):
        """PR mode calls gh pr create with title and body."""
        gh_calls = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "gh":
                gh_calls.append(list(cmd))
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertEqual(result.status, "pr_opened")
        self.assertTrue(any(
            c[:3] == ["gh", "pr", "create"] for c in gh_calls
        ))

    def test_pr_mode_captures_pr_url(self):
        """PR mode captures pr_url from gh pr create stdout."""
        expected_url = "https://github.com/owner/repo/pull/42"

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout=expected_url + "\n")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertEqual(result.pr_url, expected_url.strip())

    def test_pr_mode_push_uses_u_flag(self):
        """PR mode git push uses -u origin <branch>."""
        push_calls = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:2] == ["git", "push"]:
                push_calls.append(list(cmd))
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertTrue(len(push_calls) > 0)
        push_cmd = push_calls[0]
        self.assertIn("-u", push_cmd)
        self.assertIn("origin", push_cmd)


# ---------------------------------------------------------------------------
# Section 7: Direct mode
# ---------------------------------------------------------------------------

class TestDirectMode(unittest.TestCase):

    def test_direct_mode_no_branch_checkout(self):
        """Direct mode never runs git checkout -b."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        branch_checkouts = [c for c in commands_run if c[:3] == ["git", "checkout", "-b"]]
        self.assertEqual(branch_checkouts, [])
        self.assertEqual(result.status, "pushed")

    def test_direct_mode_pushes(self):
        """Direct mode calls git push."""
        push_calls = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:2] == ["git", "push"]:
                push_calls.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        self.assertTrue(len(push_calls) > 0)

    def test_direct_mode_no_gh_pr(self):
        """Direct mode never calls gh pr create."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        gh_calls = [c for c in commands_run if c and c[0] == "gh"]
        self.assertEqual(gh_calls, [])


# ---------------------------------------------------------------------------
# Section 8: Commit-only mode
# ---------------------------------------------------------------------------

class TestCommitOnlyMode(unittest.TestCase):

    def test_commit_only_no_push(self):
        """Commit-only mode never calls git push."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="commit-only", had_readme_before=False)

        push_calls = [c for c in commands_run if c[:2] == ["git", "push"]]
        self.assertEqual(push_calls, [])
        self.assertEqual(result.status, "commit_only")

    def test_commit_only_no_gh_pr(self):
        """Commit-only mode never calls gh pr create."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="commit-only", had_readme_before=False)

        gh_calls = [c for c in commands_run if c and c[0] == "gh"]
        self.assertEqual(gh_calls, [])

    def test_commit_only_commits(self):
        """Commit-only mode does run git add and git commit."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(Path("/repo"), mode="commit-only", had_readme_before=False)

        add_calls = [c for c in commands_run if c[:2] == ["git", "add"]]
        commit_calls = [c for c in commands_run if c[:2] == ["git", "commit"]]
        self.assertTrue(len(add_calls) > 0)
        self.assertTrue(len(commit_calls) > 0)


# ---------------------------------------------------------------------------
# Section 9: Skip mode
# ---------------------------------------------------------------------------

class TestSkipMode(unittest.TestCase):

    def test_skip_does_nothing(self):
        """Skip mode runs no subprocess calls."""
        with patch("subprocess.run") as mock_run:
            result = commit_and_push(Path("/repo"), mode="skip", had_readme_before=False)

        mock_run.assert_not_called()
        self.assertEqual(result.status, "skipped")
        self.assertIsNone(result.pr_url)
        self.assertIsNone(result.error)


# ---------------------------------------------------------------------------
# Section 10: Dry-run
# ---------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):

    def test_dry_run_direct_skips_push(self):
        """Dry-run direct mode commits but does not push."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(
                Path("/repo"), mode="direct", had_readme_before=False, dry_run=True
            )

        push_calls = [c for c in commands_run if c[:2] == ["git", "push"]]
        commit_calls = [c for c in commands_run if c[:2] == ["git", "commit"]]
        self.assertEqual(push_calls, [])  # no push
        self.assertTrue(len(commit_calls) > 0)  # still commits
        self.assertEqual(result.status, "pushed")

    def test_dry_run_pr_skips_push_and_gh(self):
        """Dry-run PR mode commits but does not push or call gh pr create."""
        commands_run = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd:
                commands_run.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(
                Path("/repo"), mode="pr", had_readme_before=False, dry_run=True
            )

        push_calls = [c for c in commands_run if c[:2] == ["git", "push"]]
        gh_calls = [c for c in commands_run if c and c[0] == "gh"]
        commit_calls = [c for c in commands_run if c[:2] == ["git", "commit"]]
        self.assertEqual(push_calls, [])
        self.assertEqual(gh_calls, [])
        self.assertTrue(len(commit_calls) > 0)
        self.assertEqual(result.status, "pr_opened")
        self.assertIsNone(result.pr_url)  # no actual PR URL since skipped

    def test_dry_run_pr_still_creates_branch(self):
        """Dry-run PR mode still creates the branch (just doesn't push)."""
        branch_checkouts = []

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:3] == ["git", "checkout", "-b"]:
                branch_checkouts.append(list(cmd))
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            commit_and_push(
                Path("/repo"), mode="pr", had_readme_before=False, dry_run=True
            )

        self.assertTrue(len(branch_checkouts) > 0)


# ---------------------------------------------------------------------------
# Section 11: Push rejection
# ---------------------------------------------------------------------------

class TestPushRejection(unittest.TestCase):

    def test_direct_push_failure_returns_failed(self):
        """git push non-zero → status='failed', error captures stderr."""
        push_stderr = "error: failed to push some refs"

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:2] == ["git", "push"]:
                return _make_completed(1, stderr=push_stderr)
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        self.assertEqual(result.status, "failed")
        self.assertIn("push", result.error.lower())

    def test_pr_push_failure_returns_failed(self):
        """PR mode git push non-zero → failed."""
        push_stderr = "remote: Repository not found"

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:2] == ["git", "push"]:
                return _make_completed(1, stderr=push_stderr)
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)

    def test_failed_result_has_stderr(self):
        """Push failure result.error contains the stderr text."""
        push_stderr = "remote: Permission denied (publickey)"

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[:2] == ["git", "push"]:
                return _make_completed(128, stderr=push_stderr)
            return _make_completed(0)

        with patch("subprocess.run", side_effect=capturing_run):
            result = commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        self.assertEqual(result.status, "failed")
        self.assertIn("Permission denied", result.error)


# ---------------------------------------------------------------------------
# Section 12: GPG warn helper
# ---------------------------------------------------------------------------

class TestWarnGpgSigning(unittest.TestCase):

    def test_warns_when_gpgsign_true_no_signingkey(self):
        """gpgsign=true + no signingkey → prints warning to stderr."""
        def gpg_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if "commit.gpgsign" in cmd:
                return _make_completed(0, stdout="true\n")
            if "user.signingkey" in cmd:
                return _make_completed(1, stdout="\n")  # key not set
            return _make_completed(0)

        with patch("subprocess.run", side_effect=gpg_run), \
             patch("sys.stderr") as mock_stderr:
            warn_gpg_signing()

        mock_stderr.write.assert_called()
        # Grab all writes and check warning text
        written = "".join(call_args[0][0] for call_args in mock_stderr.write.call_args_list)
        self.assertIn("GPG", written.upper())

    def test_no_warn_when_gpgsign_false(self):
        """gpgsign=false → no warning."""
        def gpg_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if "commit.gpgsign" in cmd:
                return _make_completed(0, stdout="false\n")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=gpg_run), \
             patch("sys.stderr") as mock_stderr:
            warn_gpg_signing()

        mock_stderr.write.assert_not_called()

    def test_no_warn_when_gpgsign_not_set(self):
        """git config exits non-zero (key not set) → no warning."""
        def gpg_run(*args, **kwargs):
            return _make_completed(1, stdout="\n")

        with patch("subprocess.run", side_effect=gpg_run), \
             patch("sys.stderr") as mock_stderr:
            warn_gpg_signing()

        mock_stderr.write.assert_not_called()

    def test_no_warn_when_gpgsign_true_but_has_key(self):
        """gpgsign=true + signingkey present → no warning."""
        def gpg_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if "commit.gpgsign" in cmd:
                return _make_completed(0, stdout="true\n")
            if "user.signingkey" in cmd:
                return _make_completed(0, stdout="ABC123\n")  # key is set
            return _make_completed(0)

        with patch("subprocess.run", side_effect=gpg_run), \
             patch("sys.stderr") as mock_stderr:
            warn_gpg_signing()

        mock_stderr.write.assert_not_called()


# ---------------------------------------------------------------------------
# Section 13: Mode stored in result
# ---------------------------------------------------------------------------

class TestModeInResult(unittest.TestCase):

    def test_pr_mode_result_has_mode(self):
        def smart_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and cmd[0] == "gh":
                return _make_completed(0, stdout="https://github.com/x/y/pull/1")
            return _make_completed(0)

        with patch("subprocess.run", side_effect=smart_run):
            result = commit_and_push(Path("/repo"), mode="pr", had_readme_before=False)

        self.assertEqual(result.mode, "pr")

    def test_direct_mode_result_has_mode(self):
        with patch("subprocess.run", return_value=_make_completed(0)):
            result = commit_and_push(Path("/repo"), mode="direct", had_readme_before=False)

        self.assertEqual(result.mode, "direct")

    def test_commit_only_mode_result_has_mode(self):
        with patch("subprocess.run", return_value=_make_completed(0)):
            result = commit_and_push(Path("/repo"), mode="commit-only", had_readme_before=False)

        self.assertEqual(result.mode, "commit-only")

    def test_skip_mode_result_has_none_mode(self):
        result = commit_and_push(Path("/repo"), mode="skip", had_readme_before=False)
        self.assertIsNone(result.mode)


if __name__ == "__main__":
    unittest.main()
