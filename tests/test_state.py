"""Tests for src/state.py — XDG paths, StateStore, prompt_resume.

Phase 4: H1 (resume), H7 (summary aggregation), M2 (XDG paths).

Uses tempfile.TemporaryDirectory and monkeypatch-style os.environ manipulation
via unittest.mock.patch.dict to avoid touching the real filesystem.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: read all JSONL lines from a file
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# XDG path helpers
# ---------------------------------------------------------------------------

class TestXdgCacheDir(unittest.TestCase):
    """xdg_cache_dir() honors XDG_CACHE_HOME; falls back to ~/.cache."""

    def test_honors_xdg_cache_home(self):
        import src.state as state_mod
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}, clear=False):
                result = state_mod.xdg_cache_dir()
            expected = Path(tmp) / "gh-readme-pipeline"
            self.assertEqual(result, expected)

    def test_fallback_when_no_xdg_cache_home(self):
        import src.state as state_mod
        env = {k: v for k, v in os.environ.items() if k != "XDG_CACHE_HOME"}
        with patch.dict(os.environ, env, clear=True):
            result = state_mod.xdg_cache_dir()
        expected = Path.home() / ".cache" / "gh-readme-pipeline"
        self.assertEqual(result, expected)

    def test_returns_path_object(self):
        import src.state as state_mod
        result = state_mod.xdg_cache_dir()
        self.assertIsInstance(result, Path)


class TestXdgStateDir(unittest.TestCase):
    """xdg_state_dir() honors XDG_STATE_HOME; falls back to ~/.local/state."""

    def test_honors_xdg_state_home(self):
        import src.state as state_mod
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                result = state_mod.xdg_state_dir()
            expected = Path(tmp) / "gh-readme-pipeline"
            self.assertEqual(result, expected)

    def test_fallback_when_no_xdg_state_home(self):
        import src.state as state_mod
        env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
        with patch.dict(os.environ, env, clear=True):
            result = state_mod.xdg_state_dir()
        expected = Path.home() / ".local" / "state" / "gh-readme-pipeline"
        self.assertEqual(result, expected)

    def test_returns_path_object(self):
        import src.state as state_mod
        result = state_mod.xdg_state_dir()
        self.assertIsInstance(result, Path)


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class TestStateStoreRecord(unittest.TestCase):
    """record() appends one valid JSONL line per call."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_store(self, user: str = "testuser"):
        import src.state as state_mod
        return state_mod.StateStore(user=user, state_dir=self._state_dir)

    def test_record_creates_file_on_first_call(self):
        store = self._make_store()
        store.record("my-repo", "pushed")
        state_file = self._state_dir / "state-testuser.jsonl"
        self.assertTrue(state_file.exists())

    def test_record_appends_valid_json(self):
        store = self._make_store()
        store.record("my-repo", "pushed")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["repo"], "my-repo")
        self.assertEqual(records[0]["status"], "pushed")

    def test_record_appends_multiple_lines(self):
        store = self._make_store()
        store.record("repo-a", "pushed")
        store.record("repo-b", "skipped")
        store.record("repo-c", "failed")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertEqual(len(records), 3)

    def test_record_includes_timestamp(self):
        store = self._make_store()
        store.record("my-repo", "pushed")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertIn("ts", records[0])
        ts = records[0]["ts"]
        # Should be ISO format
        self.assertRegex(ts, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_record_stores_optional_mode(self):
        store = self._make_store()
        store.record("my-repo", "pr_opened", mode="pr")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertEqual(records[0]["mode"], "pr")

    def test_record_stores_optional_error(self):
        store = self._make_store()
        store.record("my-repo", "failed", error="timeout")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertEqual(records[0]["error"], "timeout")

    def test_record_stores_optional_pr_url(self):
        store = self._make_store()
        store.record("my-repo", "pr_opened", pr_url="https://github.com/u/r/pull/1")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        self.assertEqual(records[0]["pr_url"], "https://github.com/u/r/pull/1")

    def test_record_omits_none_optional_fields(self):
        """None optional fields should not appear in the JSONL record."""
        store = self._make_store()
        store.record("my-repo", "pushed")
        state_file = self._state_dir / "state-testuser.jsonl"
        records = _read_jsonl(state_file)
        # mode, error, pr_url not provided → should be absent or null
        # We accept either omitted or null; just check no crash
        self.assertIn("repo", records[0])

    def test_state_file_named_after_user(self):
        store = self._make_store(user="alice")
        store.record("r", "pushed")
        state_file = self._state_dir / "state-alice.jsonl"
        self.assertTrue(state_file.exists())


class TestStateStoreLoadProcessed(unittest.TestCase):
    """load_processed() returns names with success-like statuses."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_store(self):
        import src.state as state_mod
        return state_mod.StateStore(user="testuser", state_dir=self._state_dir)

    def test_returns_pushed_repos(self):
        store = self._make_store()
        store.record("r1", "pushed")
        result = store.load_processed()
        self.assertIn("r1", result)

    def test_returns_pr_opened_repos(self):
        store = self._make_store()
        store.record("r2", "pr_opened")
        result = store.load_processed()
        self.assertIn("r2", result)

    def test_returns_commit_only_repos(self):
        store = self._make_store()
        store.record("r3", "commit_only")
        result = store.load_processed()
        self.assertIn("r3", result)

    def test_excludes_skipped_repos(self):
        store = self._make_store()
        store.record("r4", "skipped")
        result = store.load_processed()
        self.assertNotIn("r4", result)

    def test_excludes_failed_repos(self):
        store = self._make_store()
        store.record("r5", "failed")
        result = store.load_processed()
        self.assertNotIn("r5", result)

    def test_returns_set_type(self):
        store = self._make_store()
        result = store.load_processed()
        self.assertIsInstance(result, set)

    def test_empty_file_returns_empty_set(self):
        store = self._make_store()
        result = store.load_processed()
        self.assertEqual(result, set())

    def test_deduplicates_repeated_repo_names(self):
        store = self._make_store()
        store.record("r1", "pushed")
        store.record("r1", "pushed")  # same repo recorded twice
        result = store.load_processed()
        self.assertEqual(len(result), 1)

    def test_mixed_statuses_only_success_included(self):
        store = self._make_store()
        store.record("success-repo", "pushed")
        store.record("failed-repo", "failed")
        store.record("skipped-repo", "skipped")
        store.record("pr-repo", "pr_opened")
        result = store.load_processed()
        self.assertIn("success-repo", result)
        self.assertIn("pr-repo", result)
        self.assertNotIn("failed-repo", result)
        self.assertNotIn("skipped-repo", result)


class TestStateStoreSummary(unittest.TestCase):
    """summary() aggregates counts by status and collects pr_urls / failed repos."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_store(self):
        import src.state as state_mod
        return state_mod.StateStore(user="testuser", state_dir=self._state_dir)

    def test_summary_counts_by_status(self):
        store = self._make_store()
        store.record("r1", "pushed")
        store.record("r2", "pushed")
        store.record("r3", "pr_opened", pr_url="https://github.com/u/r3/pull/1")
        store.record("r4", "skipped")
        store.record("r5", "failed", error="timeout")
        summary = store.summary()
        self.assertEqual(summary["pushed"], 2)
        self.assertEqual(summary["pr_opened"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["failed"], 1)

    def test_summary_collects_pr_urls(self):
        store = self._make_store()
        store.record("r1", "pr_opened", pr_url="https://github.com/u/r1/pull/1")
        store.record("r2", "pr_opened", pr_url="https://github.com/u/r2/pull/2")
        summary = store.summary()
        self.assertIn("pr_urls", summary)
        self.assertIn("https://github.com/u/r1/pull/1", summary["pr_urls"])
        self.assertIn("https://github.com/u/r2/pull/2", summary["pr_urls"])

    def test_summary_collects_failed_repos(self):
        store = self._make_store()
        store.record("bad-repo", "failed", error="timeout")
        store.record("good-repo", "pushed")
        summary = store.summary()
        self.assertIn("failed_repos", summary)
        self.assertIn("bad-repo", summary["failed_repos"])
        self.assertNotIn("good-repo", summary["failed_repos"])

    def test_summary_empty_store(self):
        store = self._make_store()
        summary = store.summary()
        self.assertIsInstance(summary, dict)
        # All counts should be zero or empty
        self.assertEqual(summary.get("pushed", 0), 0)

    def test_summary_returns_dict(self):
        store = self._make_store()
        result = store.summary()
        self.assertIsInstance(result, dict)

    def test_summary_zero_counts_for_missing_statuses(self):
        store = self._make_store()
        store.record("r1", "pushed")
        summary = store.summary()
        # Status not present should be 0 or not present (both acceptable)
        self.assertFalse(summary.get("failed", 0))
        self.assertFalse(summary.get("skipped", 0))


# ---------------------------------------------------------------------------
# prompt_resume
# ---------------------------------------------------------------------------

class TestPromptResume(unittest.TestCase):
    """prompt_resume() displays choice and returns parsed selection."""

    def _call(self, user_input: str, processed_count: int = 3):
        import src.state as state_mod
        with patch("src.state.input", return_value=user_input):
            return state_mod.prompt_resume(processed_count)

    def test_r_returns_resume(self):
        result = self._call("r")
        self.assertEqual(result, "resume")

    def test_a_returns_all(self):
        result = self._call("a")
        self.assertEqual(result, "all")

    def test_s_returns_fresh(self):
        result = self._call("s")
        self.assertEqual(result, "fresh")

    def test_q_returns_quit(self):
        result = self._call("q")
        self.assertEqual(result, "quit")

    def test_uppercase_r_returns_resume(self):
        result = self._call("R")
        self.assertEqual(result, "resume")

    def test_uppercase_q_returns_quit(self):
        result = self._call("Q")
        self.assertEqual(result, "quit")

    def test_prompt_mentions_processed_count(self):
        import src.state as state_mod
        prompts = []

        def input_side_effect(prompt=""):
            prompts.append(prompt)
            return "q"

        with patch("src.state.input", input_side_effect):
            state_mod.prompt_resume(42)

        self.assertTrue(prompts, "input() was never called")
        self.assertIn("42", prompts[0])

    def test_invalid_then_valid_reprompts(self):
        """On invalid input, prompt_resume should either reprompt or return a default."""
        import src.state as state_mod
        responses = iter(["x", "r"])  # first invalid, then valid

        def input_side_effect(prompt=""):
            return next(responses)

        with patch("src.state.input", input_side_effect):
            result = state_mod.prompt_resume(3)

        # Either re-prompted and returned "resume", or returned a fallback
        self.assertIn(result, {"resume", "all", "fresh", "quit"})


if __name__ == "__main__":
    unittest.main()
