"""Tests for src/contributors.py — REST contributor fetch + bot strip + cache."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.contributors import (
    cache_key,
    enrich_repos,
    fetch_contributors,
    is_bot,
    load_cache,
    save_cache,
    strip_bots,
)
from src.selection import Repo


def _repo(name: str = "r", pushed_at: str = "2026-05-06T00:00:00Z") -> Repo:
    return Repo(
        name=name,
        ssh_url=f"git@github.com:owner/{name}.git",
        pushed_at=pushed_at,
        had_readme_before=False,
        disk_usage=10,
    )


class TestIsBot(unittest.TestCase):
    def test_bracket_bot(self) -> None:
        self.assertTrue(is_bot("renovate[bot]"))
        self.assertTrue(is_bot("anything[bot]"))

    def test_dependabot(self) -> None:
        self.assertTrue(is_bot("dependabot"))
        self.assertTrue(is_bot("dependabot-preview"))

    def test_github_actions(self) -> None:
        self.assertTrue(is_bot("github-actions"))
        self.assertTrue(is_bot("github-actions[bot]"))

    def test_human(self) -> None:
        self.assertFalse(is_bot("alice"))
        self.assertFalse(is_bot("bob123"))
        self.assertFalse(is_bot("a-developer"))


class TestStripBots(unittest.TestCase):
    def test_keeps_humans_drops_bots(self) -> None:
        out = strip_bots(["alice", "dependabot", "bob", "renovate[bot]"])
        self.assertEqual(out, ("alice", "bob"))


class TestCacheRoundtrip(unittest.TestCase):
    def test_save_then_load(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".contributors.json"
            save_cache(p, {"r@t": ["alice"]})
            loaded = load_cache(p)
            self.assertEqual(loaded, {"r@t": ["alice"]})

    def test_load_missing_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            self.assertEqual(load_cache(p), {})

    def test_load_corrupt_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("not json")
            self.assertEqual(load_cache(p), {})


class TestCacheKey(unittest.TestCase):
    def test_includes_pushed_at(self) -> None:
        self.assertNotEqual(
            cache_key("r", "2026-05-06T00:00:00Z"),
            cache_key("r", "2026-05-07T00:00:00Z"),
        )


def _fake_run(stdout: bytes, returncode: int = 0) -> MagicMock:
    res = MagicMock()
    res.stdout = stdout
    res.returncode = returncode
    return res


class TestFetchContributors(unittest.TestCase):
    def test_strips_bots(self) -> None:
        body = json.dumps([
            {"login": "alice", "type": "User"},
            {"login": "dependabot", "type": "User"},
        ]).encode()
        with patch("src.contributors.subprocess.run",
                   return_value=_fake_run(body)):
            out = fetch_contributors("owner", "repo")
        self.assertEqual(out, ("alice",))

    def test_empty_repo_returns_empty_tuple(self) -> None:
        # GitHub returns 404 for repos with no commits.
        err = subprocess.CalledProcessError(1, "gh", b"", b"404")
        with patch("src.contributors.subprocess.run", side_effect=err):
            self.assertEqual(fetch_contributors("o", "r"), ())

    def test_per_page_2_passed(self) -> None:
        body = b"[]"
        with patch("src.contributors.subprocess.run",
                   return_value=_fake_run(body)) as m:
            fetch_contributors("owner", "repo")
        cmd = m.call_args.args[0]
        joined = " ".join(cmd)
        self.assertIn("per_page=2", joined)
        self.assertIn("/repos/owner/repo/contributors", joined)


class TestEnrichRepos(unittest.TestCase):
    def test_uses_cache_when_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / ".contributors.json"
            r = _repo("alpha", "2026-01-01T00:00:00Z")
            save_cache(cache_path, {cache_key("alpha", "2026-01-01T00:00:00Z"): ["alice"]})
            with patch("src.contributors.fetch_contributors") as m:
                out = enrich_repos([r], owner="owner", cache_path=cache_path, max_workers=1)
            m.assert_not_called()
            self.assertEqual(out[0].contributors, ("alice",))

    def test_fetches_when_stale(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / ".contributors.json"
            r = _repo("alpha", "2026-05-06T00:00:00Z")
            save_cache(cache_path, {cache_key("alpha", "2026-01-01T00:00:00Z"): ["old"]})
            with patch("src.contributors.fetch_contributors",
                       return_value=("alice",)) as m:
                out = enrich_repos([r], owner="owner", cache_path=cache_path, max_workers=1)
            m.assert_called_once_with("owner", "alpha")
            self.assertEqual(out[0].contributors, ("alice",))

    def test_writes_back_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / ".contributors.json"
            r = _repo("alpha", "2026-05-06T00:00:00Z")
            with patch("src.contributors.fetch_contributors",
                       return_value=("alice",)):
                enrich_repos([r], owner="owner", cache_path=cache_path, max_workers=1)
            self.assertEqual(
                load_cache(cache_path),
                {cache_key("alpha", "2026-05-06T00:00:00Z"): ["alice"]},
            )


if __name__ == "__main__":
    unittest.main()
