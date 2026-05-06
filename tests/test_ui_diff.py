"""Tests for src/ui/diff.py — pure diff computation for review screen.

TDD RED phase: written before implementation per docs/UI-REDESIGN.md.

Covers:
- Unified diff between two non-empty texts
- diff_vs_head: returns fallback string when HEAD has no README
- diff_vs_prev: returns fallback string on first draft
- Identical inputs → "(no changes)" sentinel
- Trailing-newline robustness (difflib quirk)
- Header labels ("README.md (HEAD)" vs "README.md (prev draft)")
"""
from __future__ import annotations

import unittest

from src.ui import diff as ui_diff


class TestUnifiedDiff(unittest.TestCase):
    def test_changes_produce_unified_diff(self) -> None:
        out = ui_diff.unified("a\nb\nc\n", "a\nB\nc\n", fromfile="x", tofile="y")
        self.assertIn("--- x", out)
        self.assertIn("+++ y", out)
        self.assertIn("-b", out)
        self.assertIn("+B", out)

    def test_identical_inputs_returns_no_changes_sentinel(self) -> None:
        self.assertEqual(
            ui_diff.unified("same\n", "same\n", fromfile="a", tofile="b"),
            "(no changes)",
        )

    def test_missing_trailing_newline_does_not_crash(self) -> None:
        out = ui_diff.unified("a\nb", "a\nc", fromfile="x", tofile="y")
        self.assertIn("-b", out)
        self.assertIn("+c", out)


class TestDiffVsHead(unittest.TestCase):
    def test_no_head_readme_returns_fallback(self) -> None:
        self.assertEqual(
            ui_diff.diff_vs_head(None, "new draft\n"),
            ui_diff.NO_HEAD_DIFF,
        )

    def test_empty_head_produces_real_diff(self) -> None:
        # Empty-but-tracked baseline is a valid state; only None means "no prior".
        out = ui_diff.diff_vs_head("", "new draft\n")
        self.assertNotEqual(out, ui_diff.NO_HEAD_DIFF)
        self.assertIn("+new draft", out)

    def test_real_diff_uses_head_label(self) -> None:
        out = ui_diff.diff_vs_head("old\n", "new\n")
        self.assertIn("README.md (HEAD)", out)
        self.assertIn("README.md (draft)", out)
        self.assertIn("-old", out)
        self.assertIn("+new", out)


class TestDiffVsPrev(unittest.TestCase):
    def test_no_prev_draft_returns_fallback(self) -> None:
        self.assertEqual(
            ui_diff.diff_vs_prev(None, "new\n"),
            ui_diff.NO_PREV_DIFF,
        )

    def test_empty_prev_produces_real_diff(self) -> None:
        # Empty-but-present prev draft is valid; only None means "first iteration".
        out = ui_diff.diff_vs_prev("", "new\n")
        self.assertNotEqual(out, ui_diff.NO_PREV_DIFF)
        self.assertIn("+new", out)

    def test_real_diff_uses_prev_label(self) -> None:
        out = ui_diff.diff_vs_prev("draft1\n", "draft2\n")
        self.assertIn("README.md (prev draft)", out)
        self.assertIn("README.md (draft)", out)


if __name__ == "__main__":
    unittest.main()
