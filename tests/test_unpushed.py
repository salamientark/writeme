"""Tests for src/unpushed.py — end-of-run dirty/unpushed scan."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.unpushed import UnpushedFinding, scan_repos


def _git(cwd, *args, env=None):
    e = os.environ.copy()
    e.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if env:
        e.update(env)
    subprocess.run(["git", *args], cwd=cwd, check=True, env=e,
                   capture_output=True, text=True)


def _make_remote(root: Path, name: str) -> Path:
    """Create a bare 'remote' repo + a working clone with one commit pushed."""
    bare = root / f"{name}.git"
    _git(root, "init", "--bare", str(bare))
    work = root / name
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "x.txt").write_text("hello\n")
    _git(work, "add", "x.txt")
    _git(work, "commit", "-m", "init")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-u", "origin", "main")
    return work


class TestScanRepos(unittest.TestCase):
    def test_missing_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(scan_repos(Path(td) / "nope"), [])

    def test_empty_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(scan_repos(Path(td)), [])

    def test_clean_repo_with_upstream_yields_no_finding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            _make_remote(repos, "a")
            self.assertEqual(scan_repos(repos), [])

    def test_dirty_tree_yields_finding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            work = _make_remote(repos, "a")
            (work / "x.txt").write_text("dirty\n")
            findings = scan_repos(repos)
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0].dirty)
            self.assertEqual(findings[0].path, work)

    def test_unpushed_commit_yields_finding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            work = _make_remote(repos, "a")
            (work / "y.txt").write_text("y\n")
            _git(work, "add", "y.txt")
            _git(work, "commit", "-m", "more")
            findings = scan_repos(repos)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].unpushed_commits, 1)
            self.assertFalse(findings[0].dirty)

    def test_no_upstream_clean_yields_no_finding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            work = repos / "solo"
            work.mkdir()
            _git(work, "init", "-b", "main")
            (work / "f").write_text("x")
            _git(work, "add", "f")
            _git(work, "commit", "-m", "init")
            self.assertEqual(scan_repos(repos), [])

    def test_no_upstream_dirty_yields_finding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            work = repos / "solo"
            work.mkdir()
            _git(work, "init", "-b", "main")
            (work / "f").write_text("x")
            _git(work, "add", "f")
            _git(work, "commit", "-m", "init")
            (work / "f").write_text("dirty")
            findings = scan_repos(repos)
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0].dirty)
            self.assertEqual(findings[0].unpushed_commits, 0)

    def test_skips_non_git_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repos = root / "repo"
            repos.mkdir()
            (repos / "not_a_repo").mkdir()
            (repos / "stray.txt").write_text("hi")
            self.assertEqual(scan_repos(repos), [])


if __name__ == "__main__":
    unittest.main()
