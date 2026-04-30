"""Tests for src/fetch.py — fetch_repos() function.

Tests use unittest.mock to avoid real network calls. All subprocess.run
calls are intercepted via patch('src.fetch.subprocess.run').

Phase 3: L1 (multi-expr readme detection), M3 (rate-limit / cap),
         L5 (user mismatch), L6 (disk pre-flight).
"""
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Helpers to build GraphQL response fixtures
# ---------------------------------------------------------------------------

def _make_node(
    name: str = "my-repo",
    ssh_url: str = "git@github.com:user/my-repo.git",
    pushed_at: str = "2024-01-01T00:00:00Z",
    disk_usage: int = 100,
    readme_md: object = None,
    readme_lc: object = None,
    readme_cap: object = None,
    readme_rst: object = None,
    readme_docs: object = None,
) -> dict:
    """Return a single node dict as returned by the GraphQL repository edge."""
    return {
        "name": name,
        "sshUrl": ssh_url,
        "pushedAt": pushed_at,
        "diskUsage": disk_usage,
        "readmeMd": readme_md,
        "readmeLc": readme_lc,
        "readmeCap": readme_cap,
        "readmeRst": readme_rst,
        "readmeDocs": readme_docs,
    }


def _make_response(
    nodes: list,
    has_next_page: bool = False,
    end_cursor: str | None = None,
    rate_remaining: int = 100,
    rate_reset_at: str = "2024-01-01T00:05:00Z",
) -> bytes:
    """Return JSON bytes matching the shape fetch_repos expects."""
    payload = {
        "data": {
            "user": {
                "repositories": {
                    "nodes": nodes,
                    "pageInfo": {
                        "hasNextPage": has_next_page,
                        "endCursor": end_cursor,
                    },
                }
            },
            "rateLimit": {
                "remaining": rate_remaining,
                "resetAt": rate_reset_at,
            },
        }
    }
    return json.dumps(payload).encode()


def _subprocess_result(stdout: bytes) -> MagicMock:
    """Return a mock CompletedProcess with the given stdout."""
    result = MagicMock()
    result.stdout = stdout
    result.returncode = 0
    return result


# ---------------------------------------------------------------------------
# Single-page tests
# ---------------------------------------------------------------------------

class TestFetchSinglePage(unittest.TestCase):
    """fetch_repos returns correct Repo objects for a one-page response."""

    def _run_fetch(self, nodes: list, **response_kwargs):
        """Patch subprocess.run and gh-user call, return fetch_repos result."""
        import src.fetch as fetch_mod
        stdout = _make_response(nodes, **response_kwargs)
        run_mock = MagicMock(return_value=_subprocess_result(stdout))

        def side_effect(cmd, **kwargs):
            # gh api user --jq .login
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            return fetch_mod.fetch_repos("testuser", limit=10)

    def test_single_node_returns_one_repo(self):
        from src.selection import Repo
        node = _make_node(
            name="alpha",
            ssh_url="git@github.com:user/alpha.git",
            pushed_at="2024-03-01T00:00:00Z",
            disk_usage=512,
        )
        repos = self._run_fetch([node])
        self.assertEqual(len(repos), 1)
        self.assertIsInstance(repos[0], Repo)

    def test_repo_fields_mapped_correctly(self):
        node = _make_node(
            name="alpha",
            ssh_url="git@github.com:user/alpha.git",
            pushed_at="2024-03-01T00:00:00Z",
            disk_usage=512,
        )
        repos = self._run_fetch([node])
        r = repos[0]
        self.assertEqual(r.name, "alpha")
        self.assertEqual(r.ssh_url, "git@github.com:user/alpha.git")
        self.assertEqual(r.pushed_at, "2024-03-01T00:00:00Z")
        self.assertEqual(r.disk_usage, 512)

    def test_multiple_nodes_returned(self):
        nodes = [
            _make_node(name="a", pushed_at="2024-03-02T00:00:00Z"),
            _make_node(name="b", pushed_at="2024-03-01T00:00:00Z"),
        ]
        repos = self._run_fetch(nodes)
        self.assertEqual(len(repos), 2)

    def test_result_sorted_by_pushed_at_desc(self):
        nodes = [
            _make_node(name="old", pushed_at="2023-01-01T00:00:00Z"),
            _make_node(name="new", pushed_at="2024-06-01T00:00:00Z"),
            _make_node(name="mid", pushed_at="2024-01-01T00:00:00Z"),
        ]
        repos = self._run_fetch(nodes)
        self.assertEqual([r.name for r in repos], ["new", "mid", "old"])

    def test_subprocess_called_with_list_form(self):
        """Ensures list-form subprocess, not shell=True."""
        import src.fetch as fetch_mod
        stdout = _make_response([_make_node()])

        captured_calls = []

        def side_effect(cmd, **kwargs):
            captured_calls.append(cmd)
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            fetch_mod.fetch_repos("testuser", limit=5)

        # Every call must be a list, not a string
        for cmd in captured_calls:
            self.assertIsInstance(cmd, list, f"subprocess.run called with non-list: {cmd!r}")

    def test_empty_response_returns_empty_list(self):
        repos = self._run_fetch([])
        self.assertEqual(repos, [])


# ---------------------------------------------------------------------------
# Pagination tests
# ---------------------------------------------------------------------------

class TestFetchPagination(unittest.TestCase):
    """fetch_repos follows pageInfo.hasNextPage and merges pages."""

    def test_two_pages_merged_and_sorted(self):
        import src.fetch as fetch_mod

        page1_nodes = [_make_node(name="repo-a", pushed_at="2024-06-01T00:00:00Z")]
        page2_nodes = [_make_node(name="repo-b", pushed_at="2024-01-01T00:00:00Z")]

        page1_bytes = _make_response(page1_nodes, has_next_page=True, end_cursor="cursor123")
        page2_bytes = _make_response(page2_nodes, has_next_page=False)

        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            call_count += 1
            if call_count == 1:
                return _subprocess_result(page1_bytes)
            return _subprocess_result(page2_bytes)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            repos = fetch_mod.fetch_repos("testuser", limit=100)

        self.assertEqual(len(repos), 2)
        # sorted DESC: repo-a (2024-06) first
        self.assertEqual(repos[0].name, "repo-a")
        self.assertEqual(repos[1].name, "repo-b")
        # Exactly two graphql calls were made
        self.assertEqual(call_count, 2)

    def test_cursor_passed_to_second_page_call(self):
        """The endCursor from page 1 must appear in the page 2 subprocess call."""
        import src.fetch as fetch_mod

        page1_bytes = _make_response(
            [_make_node(name="r1")], has_next_page=True, end_cursor="MY_CURSOR"
        )
        page2_bytes = _make_response([_make_node(name="r2")], has_next_page=False)

        call_count = 0
        page2_cmd = None

        def side_effect(cmd, **kwargs):
            nonlocal call_count, page2_cmd
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            call_count += 1
            if call_count == 1:
                return _subprocess_result(page1_bytes)
            page2_cmd = cmd
            return _subprocess_result(page2_bytes)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            fetch_mod.fetch_repos("testuser", limit=100)

        # The cursor value must appear somewhere in the second page arguments
        self.assertIsNotNone(page2_cmd)
        cmd_str = " ".join(str(a) for a in page2_cmd)
        self.assertIn("MY_CURSOR", cmd_str)


# ---------------------------------------------------------------------------
# README detection tests
# ---------------------------------------------------------------------------

class TestReadmeDetection(unittest.TestCase):
    """had_readme_before is True iff any of the 5 readme expression fields is non-null."""

    def _fetch_one(self, node: dict) -> object:
        import src.fetch as fetch_mod
        stdout = _make_response([node])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            repos = fetch_mod.fetch_repos("testuser", limit=5)
        return repos[0]

    def test_all_null_means_no_readme(self):
        node = _make_node(
            readme_md=None, readme_lc=None, readme_cap=None,
            readme_rst=None, readme_docs=None,
        )
        repo = self._fetch_one(node)
        self.assertFalse(repo.had_readme_before)

    def test_readme_md_non_null_sets_true(self):
        node = _make_node(readme_md={"text": "# Hello"})
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)

    def test_readme_lc_non_null_sets_true(self):
        node = _make_node(readme_lc={"text": "# hello"})
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)

    def test_readme_cap_non_null_sets_true(self):
        node = _make_node(readme_cap={"text": "# Readme"})
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)

    def test_readme_rst_non_null_sets_true(self):
        node = _make_node(readme_rst={"text": "Title\n====="})
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)

    def test_readme_docs_non_null_sets_true(self):
        node = _make_node(readme_docs={"text": "docs readme"})
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)

    def test_only_one_field_non_null_still_true(self):
        node = _make_node(
            readme_md=None, readme_lc=None, readme_cap=None,
            readme_rst=None, readme_docs={"text": "x"},
        )
        repo = self._fetch_one(node)
        self.assertTrue(repo.had_readme_before)


# ---------------------------------------------------------------------------
# Limit cap tests
# ---------------------------------------------------------------------------

class TestLimitCap(unittest.TestCase):
    """LIMIT > 1000 is silently capped at 1000 with a warning on stderr."""

    def test_limit_above_1000_capped_to_1000(self):
        import src.fetch as fetch_mod
        stdout = _make_response([])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            # capture stderr to verify warning
            import io
            from contextlib import redirect_stderr
            buf = io.StringIO()
            with redirect_stderr(buf):
                fetch_mod.fetch_repos("testuser", limit=2000)

        warning_output = buf.getvalue()
        self.assertIn("1000", warning_output)

    def test_limit_at_1000_no_warning(self):
        import src.fetch as fetch_mod
        stdout = _make_response([])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            import io
            from contextlib import redirect_stderr
            buf = io.StringIO()
            with redirect_stderr(buf):
                fetch_mod.fetch_repos("testuser", limit=1000)

        # No cap warning for exactly 1000
        self.assertNotIn("capped", buf.getvalue().lower())

    def test_limit_below_1000_unchanged(self):
        """Limits below 1000 must not be modified (verified via page-size in cmd)."""
        import src.fetch as fetch_mod
        stdout = _make_response([])
        captured = []

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            captured.append(cmd)
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            fetch_mod.fetch_repos("testuser", limit=50)

        # 50 should appear somewhere in the args (as page size or variable)
        cmd_str = " ".join(str(a) for a in captured[0])
        self.assertIn("50", cmd_str)


# ---------------------------------------------------------------------------
# Rate-limit tests
# ---------------------------------------------------------------------------

class TestRateLimit(unittest.TestCase):
    """remaining < 10 triggers sleep until resetAt; remaining >= 10 skips sleep."""

    def _fetch_with_rate(self, remaining: int, reset_at: str = "2024-01-01T01:00:00Z"):
        import src.fetch as fetch_mod
        stdout = _make_response(
            [_make_node()], rate_remaining=remaining, rate_reset_at=reset_at
        )

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        sleep_mock = MagicMock()
        # Freeze time so sleep duration is deterministic
        # reset_at is in the future relative to our fake "now"
        fake_now = 1_704_067_200.0  # 2024-01-01T00:00:00Z

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False), \
             patch("src.fetch.time.sleep", sleep_mock), \
             patch("src.fetch.time.time", return_value=fake_now):
            fetch_mod.fetch_repos("testuser", limit=5)

        return sleep_mock

    def test_remaining_below_10_triggers_sleep(self):
        sleep_mock = self._fetch_with_rate(remaining=5)
        sleep_mock.assert_called_once()

    def test_remaining_at_9_triggers_sleep(self):
        sleep_mock = self._fetch_with_rate(remaining=9)
        sleep_mock.assert_called_once()

    def test_remaining_at_10_no_sleep(self):
        sleep_mock = self._fetch_with_rate(remaining=10)
        sleep_mock.assert_not_called()

    def test_remaining_above_10_no_sleep(self):
        sleep_mock = self._fetch_with_rate(remaining=100)
        sleep_mock.assert_not_called()

    def test_sleep_duration_based_on_reset_at(self):
        """Sleep duration should be (resetAt_epoch - now), clamped to >= 0."""
        import src.fetch as fetch_mod
        reset_at = "2024-01-01T00:01:00Z"  # 60 seconds after fake_now
        stdout = _make_response([_make_node()], rate_remaining=5, rate_reset_at=reset_at)

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        sleep_mock = MagicMock()
        fake_now = 1_704_067_200.0  # 2024-01-01T00:00:00Z

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False), \
             patch("src.fetch.time.sleep", sleep_mock), \
             patch("src.fetch.time.time", return_value=fake_now):
            fetch_mod.fetch_repos("testuser", limit=5)

        args, _ = sleep_mock.call_args
        sleep_secs = args[0]
        # Should sleep approximately 60 seconds (resetAt - now)
        self.assertGreater(sleep_secs, 0)
        self.assertLessEqual(sleep_secs, 65)  # small tolerance


# ---------------------------------------------------------------------------
# User mismatch tests
# ---------------------------------------------------------------------------

class TestUserMismatch(unittest.TestCase):
    """CR-HIGH-1: fetch_repos must NOT call input() for user-mismatch.

    The pipeline _resolve_user() is the single source of truth.
    """

    def test_fetch_repos_never_prompts_on_mismatch(self):
        import src.fetch as fetch_mod
        stdout = _make_response([])

        def subprocess_side_effect(cmd, **kwargs):
            return _subprocess_result(stdout)

        input_mock = MagicMock()
        with patch.object(fetch_mod.subprocess, "run", side_effect=subprocess_side_effect), \
             patch.dict(os.environ, {"GH_USER": "my_user"}, clear=False), \
             patch("builtins.input", input_mock):
            fetch_mod.fetch_repos("my_user", limit=5)

        input_mock.assert_not_called()

    def test_check_user_mismatch_function_removed(self):
        import src.fetch as fetch_mod
        self.assertFalse(
            hasattr(fetch_mod, "_check_user_mismatch"),
            "CR-HIGH-1: _check_user_mismatch must be deleted",
        )


# ---------------------------------------------------------------------------
# Disk pre-flight tests
# ---------------------------------------------------------------------------

class TestDiskPreflight(unittest.TestCase):
    """Warn on stderr when sum(diskUsage)*2 > available*0.8."""

    def _fetch_with_disk(self, disk_usage_kb: int, free_kb: int):
        import src.fetch as fetch_mod
        node = _make_node(disk_usage=disk_usage_kb)
        stdout = _make_response([node])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        # shutil.disk_usage returns namedtuple with .free in bytes
        disk_mock = MagicMock()
        disk_mock.free = free_kb * 1024  # convert to bytes

        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False), \
             patch("src.fetch.shutil.disk_usage", return_value=disk_mock):
            with redirect_stderr(buf):
                fetch_mod.fetch_repos("testuser", limit=5)

        return buf.getvalue()

    def test_warns_when_disk_usage_exceeds_80_percent(self):
        # disk_usage = 1000 KB, free = 100 KB
        # required = 1000 * 2 = 2000 KB = 2_048_000 bytes
        # free = 100 KB = 102_400 bytes
        # 2_048_000 > 102_400 * 0.8? No. We need required > free * 0.8
        # i.e. sum_kb * 2 * 1024 > free_bytes * 0.8
        # Let free_kb=100, sum_kb * 2 * 1024 > 100 * 1024 * 0.8
        # sum_kb > 40 → use 1000
        output = self._fetch_with_disk(disk_usage_kb=1000, free_kb=100)
        self.assertTrue(len(output) > 0, "Expected a disk warning on stderr")
        self.assertIn("disk", output.lower())

    def test_no_warning_when_plenty_of_disk(self):
        # disk_usage = 10 KB, free = 1_000_000 KB — no warning expected
        output = self._fetch_with_disk(disk_usage_kb=10, free_kb=1_000_000)
        self.assertNotIn("disk", output.lower())


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestRepoValidation(unittest.TestCase):
    """Malicious repo names in GraphQL responses raise ValueError."""

    def _fetch_malicious(self, malicious_name: str):
        import src.fetch as fetch_mod
        node = _make_node(name=malicious_name)
        stdout = _make_response([node])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            fetch_mod.fetch_repos("testuser", limit=5)

    def test_path_traversal_raises(self):
        with self.assertRaises(ValueError):
            self._fetch_malicious("..")

    def test_slash_in_name_raises(self):
        with self.assertRaises(ValueError):
            self._fetch_malicious("foo/bar")

    def test_semicolon_in_name_raises(self):
        with self.assertRaises(ValueError):
            self._fetch_malicious("foo;rm")

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            self._fetch_malicious("")

    def test_valid_name_accepted(self):
        """Standard names with hyphens, underscores, dots must be accepted."""
        import src.fetch as fetch_mod
        node = _make_node(name="valid-repo_name.v2")
        stdout = _make_response([node])

        def side_effect(cmd, **kwargs):
            if "--jq" in cmd:
                res = MagicMock()
                res.stdout = b"testuser\n"
                res.returncode = 0
                return res
            return _subprocess_result(stdout)

        with patch.object(fetch_mod.subprocess, "run", side_effect=side_effect), \
             patch.dict(os.environ, {"GH_USER": "testuser"}, clear=False):
            repos = fetch_mod.fetch_repos("testuser", limit=5)

        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].name, "valid-repo_name.v2")


if __name__ == "__main__":
    unittest.main()
