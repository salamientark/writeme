"""Tests for src/sandbox.py — per-job XDG sandbox dirs (Phase 2 P7)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestSandboxFor(unittest.TestCase):
    def test_creates_four_subdirs(self):
        from src.sandbox import sandbox_for
        with tempfile.TemporaryDirectory() as tmp:
            paths = sandbox_for(Path(tmp), "myrepo")
            self.assertEqual(set(paths), {"config", "data", "cache", "state"})
            for p in paths.values():
                self.assertTrue(p.is_dir(), f"missing {p}")

    def test_path_layout(self):
        from src.sandbox import sandbox_for
        with tempfile.TemporaryDirectory() as tmp:
            paths = sandbox_for(Path(tmp), "myrepo")
            root = Path(tmp) / "claude-jobs" / "myrepo"
            self.assertEqual(paths["config"], root / "config")
            self.assertEqual(paths["state"], root / "state")

    def test_rejects_unsafe_repo_name(self):
        from src.sandbox import sandbox_for
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sandbox_for(Path(tmp), "../escape")

    def test_idempotent(self):
        from src.sandbox import sandbox_for
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_for(Path(tmp), "myrepo")
            paths = sandbox_for(Path(tmp), "myrepo")
            self.assertTrue(paths["data"].is_dir())


class TestSandboxEnv(unittest.TestCase):
    def test_maps_xdg_keys(self):
        from src.sandbox import sandbox_env
        paths = {
            "config": Path("/sb/c"),
            "data": Path("/sb/d"),
            "cache": Path("/sb/ca"),
            "state": Path("/sb/s"),
        }
        env = sandbox_env(paths)
        self.assertEqual(env["XDG_CONFIG_HOME"], "/sb/c")
        self.assertEqual(env["XDG_DATA_HOME"], "/sb/d")
        self.assertEqual(env["XDG_CACHE_HOME"], "/sb/ca")
        self.assertEqual(env["XDG_STATE_HOME"], "/sb/s")


if __name__ == "__main__":
    unittest.main()
