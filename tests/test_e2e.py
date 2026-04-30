"""End-to-end tests using real git, real filesystem, and PATH shims for gh/claude.

Scope: validate the security fixes behave correctly when wired together.
- review_loop: real git repo + shim claude writing README → accepted path.
- review_loop: shim claude touching extra files → blast guard trips (RT-H3).
- commit_and_push: real bare+working repo, direct mode pushes via origin HEAD (CR-MED-3).
- commit_and_push: failing real git commit (no staged change) surfaces as failed (CR-HIGH-2).
- env scrub: real claude shim sees only allowlisted vars (RT-H2).
- StateStore: invalid GH_USER refuses StateStore creation (RT-L1) — already unit-tested,
  covered here through a real on-disk state record.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from src import commit, review, state


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=check,
                          capture_output=True, text=True)


def _make_repo_with_remote(tmp: Path) -> tuple[Path, Path]:
    """Create a bare 'remote' and a working clone with one initial commit."""
    bare = tmp / "remote.git"
    work = tmp / "work"
    _git(tmp, "init", "-q", "--bare", str(bare))
    _git(tmp, "clone", "-q", str(bare), str(work))
    (work / "code.py").write_text("print('hi')\n")
    _git(work, "add", "code.py")
    _git(work, "commit", "-q", "-m", "initial")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-q", "-u", "origin", "main")
    return bare, work


def _make_shim_dir(tmp: Path, scripts: dict[str, str]) -> Path:
    d = tmp / "shims"
    d.mkdir(exist_ok=True)
    for name, body in scripts.items():
        p = d / name
        p.write_text(body)
        p.chmod(0o755)
    return d


class TestReviewLoopRealGit(unittest.TestCase):
    """Drive review.review_loop against a real git repo and shimmed claude."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="e2e."))
        self.bare, self.work = _make_repo_with_remote(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_claude_shim(self, claude_body: str, inputs: list[str]):
        shim_dir = _make_shim_dir(self.tmp, {"claude": claude_body})
        env = os.environ.copy()
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
        with patch.dict(os.environ, env, clear=True), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=inputs):
            return review.review_loop(
                repo_dir=self.work,
                had_readme_before=False,
                claude_timeout=30,
            )

    def test_accepts_when_claude_creates_readme_only(self):
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            cat > README.md <<'README'
            # Generated
            content
            README
            exit 0
        """)
        result = self._run_with_claude_shim(body, inputs=["a"])
        self.assertEqual(result.status, "accepted")
        self.assertTrue((self.work / "README.md").exists())
        self.assertIn("Generated", (self.work / "README.md").read_text())

    def test_blast_guard_trips_when_claude_touches_other_files(self):
        # RT-H3: NUL-delimited blast guard with real git diff + ls-files.
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            echo '# README' > README.md
            echo 'malicious' > code.py
            exit 0
        """)
        result = self._run_with_claude_shim(body, inputs=[])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "claude_touched_other_files")
        # ensure_clean ran → tracked file restored, untracked removed
        self.assertEqual((self.work / "code.py").read_text(), "print('hi')\n")
        self.assertFalse((self.work / "README.md").exists())

    def test_blast_guard_trips_on_untracked_extra_file(self):
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            echo '# README' > README.md
            echo 'sneak' > new_file.txt
            exit 0
        """)
        result = self._run_with_claude_shim(body, inputs=[])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "claude_touched_other_files")
        self.assertFalse((self.work / "new_file.txt").exists())

    def test_env_scrub_drops_secrets_for_claude(self):
        # RT-H2: claude must not see GH_TOKEN, ANTHROPIC_API_KEY, etc.
        env_dump = self.tmp / "env_dump.txt"
        body = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            env > "{env_dump}"
            echo '# README' > README.md
            exit 0
        """)
        shim_dir = _make_shim_dir(self.tmp, {"claude": body})
        dirty = {
            "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": os.environ.get("HOME", "/root"),
            "GH_TOKEN": "ghp_secret_should_be_scrubbed",
            "ANTHROPIC_API_KEY": "sk-secret-should-be-scrubbed",
            "AWS_SECRET_ACCESS_KEY": "aws-secret-should-be-scrubbed",
            "MY_API_TOKEN": "tok-should-be-scrubbed",
        }
        with patch.dict(os.environ, dirty, clear=True), \
             patch("src.review.secrets.scan_repo_for_risky_files", return_value=[]), \
             patch("src.review.secrets.scan_text_for_secrets", return_value=[]), \
             patch("src.review._show_pager"), \
             patch("builtins.input", side_effect=["a"]):
            review.review_loop(
                repo_dir=self.work,
                had_readme_before=False,
                claude_timeout=30,
            )

        dump = env_dump.read_text()
        for secret in ("ghp_secret_should_be_scrubbed",
                       "sk-secret-should-be-scrubbed",
                       "aws-secret-should-be-scrubbed",
                       "tok-should-be-scrubbed"):
            self.assertNotIn(secret, dump, f"secret leaked to claude env: {secret}")
        # PATH/HOME must survive the scrub
        self.assertIn("PATH=", dump)
        self.assertIn("HOME=", dump)


class TestCommitAndPushRealGit(unittest.TestCase):
    """commit_and_push against real bare+working repo."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="e2e."))
        self.bare, self.work = _make_repo_with_remote(self.tmp)
        # Stage a README in working tree so add+commit have content.
        (self.work / "README.md").write_text("# from claude\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direct_mode_pushes_to_origin_head(self):
        # CR-MED-3: direct mode pushes via 'git push origin HEAD'.
        result = commit.commit_and_push(
            repo_dir=self.work,
            mode="direct",
            had_readme_before=False,
        )
        self.assertEqual(result.status, "pushed")
        # Confirm bare remote received the commit on main.
        log = _git(self.bare, "log", "--oneline", "main").stdout
        self.assertIn("docs: add README", log)

    def test_commit_only_does_not_push(self):
        result = commit.commit_and_push(
            repo_dir=self.work,
            mode="commit-only",
            had_readme_before=False,
        )
        self.assertEqual(result.status, "commit_only")
        # bare remote still has only the initial commit (no docs commit).
        log = _git(self.bare, "log", "--oneline", "main").stdout
        self.assertNotIn("docs", log)

    def test_failing_commit_propagates_as_failed(self):
        # CR-HIGH-2: empty staging → real `git commit` fails → CommitResult.failed.
        # Reset the README so there is nothing to add/commit.
        (self.work / "README.md").unlink()
        # Stage nothing; git add of missing file fails (rc!=0 on add of missing file).
        result = commit.commit_and_push(
            repo_dir=self.work,
            mode="commit-only",
            had_readme_before=False,
        )
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.error)

    def test_commit_message_newline_rejected_before_any_git_call(self):
        # CRIT-2: no git work happens when commit_message is multi-line.
        head_before = _git(self.work, "rev-parse", "HEAD").stdout.strip()
        result = commit.commit_and_push(
            repo_dir=self.work,
            mode="direct",
            had_readme_before=False,
            commit_message="title\ninjected",
        )
        self.assertEqual(result.status, "failed")
        head_after = _git(self.work, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head_before, head_after, "git HEAD must not advance on rejected message")


class TestStateStorePersistedRecord(unittest.TestCase):
    """RT-L1 + CR-LOW-1: real on-disk state file lifecycle."""

    def test_record_then_resume_via_has_prior_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = state.StateStore("octocat", state_dir=Path(td))
            self.assertFalse(store.has_prior_state())
            store.record("repo-1", "pushed", mode="direct")
            self.assertTrue(store.has_prior_state())
            self.assertEqual(store.load_processed(), {"repo-1"})
            # State file lives at predictable path under state_dir.
            self.assertTrue((Path(td) / "state-octocat.jsonl").exists())

    def test_invalid_user_blocks_state_creation_on_disk(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                state.StateStore("../../etc/passwd", state_dir=Path(td))
            # No file leaked into the directory.
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
