"""Tests for PlainUI.select_repos non-TTY selection flow."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from src.selection import Repo
from src.ui.plain_ui import PlainUI


def _repo(name: str, has: bool = False) -> Repo:
    return Repo(
        name=name,
        ssh_url=f"git@github.com:test/{name}.git",
        pushed_at="2026-04-30",
        had_readme_before=has,
        disk_usage=100,
    )


REPOS = [_repo("repo-a", True), _repo("repo-b"), _repo("repo-c", True)]


def _run(repos: list[Repo], input_text: str) -> tuple[list[Repo], str]:
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        result = PlainUI().select_repos(repos)
    return result, stdout.getvalue()


class TestPlainUISelect(unittest.TestCase):
    def test_select_all(self) -> None:
        out, _ = _run(REPOS, "a\n")
        self.assertEqual(out, REPOS)

    def test_select_quit_returns_empty(self) -> None:
        out, _ = _run(REPOS, "q\n")
        self.assertEqual(out, [])

    def test_select_eof_returns_empty(self) -> None:
        out, _ = _run(REPOS, "")
        self.assertEqual(out, [])

    def test_select_range(self) -> None:
        out, _ = _run(REPOS, "1,3\n")
        self.assertEqual(out, [REPOS[0], REPOS[2]])

    def test_select_range_dash(self) -> None:
        out, _ = _run(REPOS, "1-2\n")
        self.assertEqual(out, [REPOS[0], REPOS[1]])

    def test_invalid_then_valid_reprompts(self) -> None:
        out, stdout = _run(REPOS, "foo\n2\n")
        self.assertEqual(out, [REPOS[1]])
        self.assertTrue("error" in stdout.lower() or "invalid" in stdout.lower())

    def test_empty_repo_list_returns_empty(self) -> None:
        out, _ = _run([], "")
        self.assertEqual(out, [])

    def test_listing_includes_repo_names(self) -> None:
        _, stdout = _run(REPOS, "q\n")
        for n in ("repo-a", "repo-b", "repo-c"):
            self.assertIn(n, stdout)

    def test_listing_shows_has_readme_badge(self) -> None:
        _, stdout = _run(REPOS, "q\n")
        self.assertIn("HAS README", stdout)


class TestPlainUIStatusLine(unittest.TestCase):
    def test_status_line_prints(self):
        from src.ui.plain_ui import PlainUI
        from io import StringIO
        import sys
        ui = PlainUI()
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            ui.status_line(2, 5, 1, 2)
        finally:
            sys.stdout = old
        self.assertIn("[2/5]", buf.getvalue())
        self.assertIn("running=1", buf.getvalue())
        self.assertIn("queued=2", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
