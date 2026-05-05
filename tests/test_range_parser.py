"""Tests for src/ui/range_parser.py."""
from __future__ import annotations

import unittest

from src.ui.range_parser import parse_selection


N = 10


class TestRangeParser(unittest.TestCase):
    def test_single_index(self) -> None:
        r = parse_selection("1", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({0}))

    def test_multiple_singletons(self) -> None:
        r = parse_selection("1,3,5", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({0, 2, 4}))

    def test_simple_range(self) -> None:
        r = parse_selection("5-7", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({4, 5, 6}))

    def test_mixed_range_and_singletons(self) -> None:
        r = parse_selection("1,3,5-7", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({0, 2, 4, 5, 6}))

    def test_whitespace_tolerant(self) -> None:
        r = parse_selection("  1 , 3 ,  5-7 ", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({0, 2, 4, 5, 6}))

    def test_all_keyword_lower(self) -> None:
        self.assertEqual(parse_selection("a", N).kind, "all")

    def test_all_keyword_upper(self) -> None:
        self.assertEqual(parse_selection("A", N).kind, "all")

    def test_quit_keyword_lower(self) -> None:
        self.assertEqual(parse_selection("q", N).kind, "quit")

    def test_quit_keyword_upper(self) -> None:
        self.assertEqual(parse_selection("Q", N).kind, "quit")

    def test_empty_string_is_quit(self) -> None:
        self.assertEqual(parse_selection("", N).kind, "quit")

    def test_whitespace_only_is_quit(self) -> None:
        self.assertEqual(parse_selection("   ", N).kind, "quit")

    def test_invalid_token_is_error(self) -> None:
        r = parse_selection("foo", N)
        self.assertEqual(r.kind, "error")
        self.assertTrue(r.message)

    def test_out_of_range_high(self) -> None:
        self.assertEqual(parse_selection("99", N).kind, "error")

    def test_out_of_range_zero(self) -> None:
        self.assertEqual(parse_selection("0", N).kind, "error")

    def test_negative(self) -> None:
        self.assertEqual(parse_selection("-1", N).kind, "error")

    def test_inverted_range(self) -> None:
        self.assertEqual(parse_selection("7-5", N).kind, "error")

    def test_partial_invalid_in_list(self) -> None:
        self.assertEqual(parse_selection("1,foo,3", N).kind, "error")

    def test_range_at_boundary(self) -> None:
        r = parse_selection("1-10", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset(range(N)))

    def test_duplicates_collapse(self) -> None:
        r = parse_selection("1,1,2-3,3", N)
        self.assertEqual(r.kind, "ok")
        self.assertEqual(r.indices, frozenset({0, 1, 2}))


if __name__ == "__main__":
    unittest.main()
