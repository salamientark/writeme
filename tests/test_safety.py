"""Tests for src/safety.py — TDD RED phase."""
import fcntl
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.safety import (
    acquire_lock,
    ensure_clean,
    validate_repo_name,
    validate_ssh_url,
)


class TestValidateRepoName(unittest.TestCase):
    """Unit tests for validate_repo_name."""

    def test_accepts_simple_name(self) -> None:
        validate_repo_name("foo")  # must not raise

    def test_accepts_name_with_hyphen_dot_underscore_digit(self) -> None:
        validate_repo_name("foo-bar.baz_1")  # must not raise

    def test_rejects_double_dot(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("..")

    def test_rejects_single_dot(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name(".")

    def test_rejects_path_traversal_with_slash(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo/bar")

    def test_rejects_shell_injection(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo;rm")

    def test_rejects_empty_string(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("")

    def test_rejects_space(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo bar")

    def test_rejects_at_sign(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo@bar")

    def test_rejects_backtick(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo`bar`")

    def test_rejects_dollar_sign(self) -> None:
        with self.assertRaises(ValueError):
            validate_repo_name("foo$bar")

    def test_accepts_all_allowed_chars(self) -> None:
        validate_repo_name("ABCXYZ-abcxyz.0123_456")  # must not raise


class TestValidateSshUrl(unittest.TestCase):
    """Unit tests for validate_ssh_url."""

    def test_accepts_git_at_github(self) -> None:
        validate_ssh_url("git@github.com:x/y.git")  # must not raise

    def test_accepts_https_github(self) -> None:
        validate_ssh_url("https://github.com/x/y")  # must not raise

    def test_rejects_ssh_scheme(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("ssh://evil.com/repo.git")

    def test_rejects_upload_pack_injection(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("--upload-pack=evil")

    def test_rejects_arbitrary_string(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("file:///etc/passwd")

    def test_rejects_empty_string(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("")

    def test_rejects_http_non_github(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("https://evil.com/repo.git")

    def test_rejects_git_at_non_github(self) -> None:
        with self.assertRaises(ValueError):
            validate_ssh_url("git@evil.com:x/y.git")


class TestEnsureClean(unittest.TestCase):
    """Integration tests for ensure_clean using a real temp git repo."""

    def _make_git_repo(self, tmp: Path) -> Path:
        """Create a minimal git repo and return its path."""
        subprocess.run(["git", "init", str(tmp)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp, check=True, capture_output=True,
        )
        # Initial commit so HEAD exists
        readme = tmp / "README.md"
        readme.write_text("# Hello\n")
        subprocess.run(["git", "add", "README.md"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp, check=True, capture_output=True,
        )
        return tmp

    def test_removes_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            # Dirty: add an untracked file
            (repo / "dirty.txt").write_text("oops\n")
            self.assertTrue((repo / "dirty.txt").exists())
            ensure_clean(repo)
            self.assertFalse((repo / "dirty.txt").exists())

    def test_resets_modified_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            # Dirty: modify tracked file
            (repo / "README.md").write_text("# Modified\n")
            ensure_clean(repo)
            content = (repo / "README.md").read_text()
            self.assertEqual(content, "# Hello\n")

    def test_removes_merge_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            merge_head = repo / ".git" / "MERGE_HEAD"
            merge_head.write_text("abc123\n")
            ensure_clean(repo)
            self.assertFalse(merge_head.exists())

    def test_removes_cherry_pick_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            cp_head = repo / ".git" / "CHERRY_PICK_HEAD"
            cp_head.write_text("abc123\n")
            ensure_clean(repo)
            self.assertFalse(cp_head.exists())

    def test_removes_rebase_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            rb_head = repo / ".git" / "REBASE_HEAD"
            rb_head.write_text("abc123\n")
            ensure_clean(repo)
            self.assertFalse(rb_head.exists())

    def test_tolerates_already_clean_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_git_repo(Path(td))
            ensure_clean(repo)  # must not raise


class TestAcquireLock(unittest.TestCase):
    """Tests for acquire_lock context manager."""

    def test_lock_acquired_and_released(self) -> None:
        with tempfile.NamedTemporaryFile() as tf:
            lock_path = Path(tf.name)
            with acquire_lock(lock_path):
                pass  # must not raise

    def test_lock_file_created_if_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "new_lock"
            self.assertFalse(lock_path.exists())
            with acquire_lock(lock_path):
                self.assertTrue(lock_path.exists())

    def test_second_process_cannot_acquire_same_lock(self) -> None:
        """A second concurrent process must fail to acquire the lock."""
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            lock_path = Path(tf.name)

        script = textwrap.dedent(f"""\
            import fcntl, sys
            from pathlib import Path
            lock_path = Path({str(lock_path)!r})
            try:
                fd = open(lock_path, 'w')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                print("ACQUIRED")
                sys.exit(0)
            except (BlockingIOError, OSError):
                print("BLOCKED")
                sys.exit(1)
        """)

        with acquire_lock(lock_path):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
            )
            self.assertIn("BLOCKED", result.stdout)
            self.assertNotEqual(result.returncode, 0)

        # After context exit, lock is released — second process can now acquire
        result2 = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertIn("ACQUIRED", result2.stdout)
        self.assertEqual(result2.returncode, 0)

        lock_path.unlink(missing_ok=True)

    def test_lock_released_on_exception(self) -> None:
        """Lock must be released even when body raises."""
        with tempfile.NamedTemporaryFile() as tf:
            lock_path = Path(tf.name)
            with self.assertRaises(RuntimeError):
                with acquire_lock(lock_path):
                    raise RuntimeError("boom")
            # Verify lock is released by acquiring again
            with acquire_lock(lock_path):
                pass  # must not raise


if __name__ == "__main__":
    unittest.main()
