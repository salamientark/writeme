"""Tests for src/filters.py — pure predicates.

Phase 1 (parallel-readme-and-solo-filter plan): pure predicates
``is_solo``, ``is_fork``, ``has_readme`` plus ``apply_filters`` composer.
"""
import unittest

from src.filters import apply_filters, has_readme, is_fork, is_solo
from src.selection import Repo


def _make_repo(
    name: str = "r",
    is_fork_: bool = False,
    had_readme_before: bool = False,
    contributors: tuple[str, ...] | None = None,
) -> Repo:
    return Repo(
        name=name,
        ssh_url=f"git@github.com:u/{name}.git",
        pushed_at="2026-05-06T00:00:00Z",
        had_readme_before=had_readme_before,
        disk_usage=10,
        is_fork=is_fork_,
        contributors=contributors,
    )


class TestIsSolo(unittest.TestCase):
    def test_unknown_contributors_returns_false(self) -> None:
        # F2: cannot confirm solo without REST data.
        self.assertFalse(is_solo(_make_repo(contributors=None)))

    def test_empty_repo_counts_as_solo(self) -> None:
        # F3: 0 contributors (empty repo) counts as solo.
        self.assertTrue(is_solo(_make_repo(contributors=())))

    def test_single_contributor_is_solo(self) -> None:
        self.assertTrue(is_solo(_make_repo(contributors=("alice",))))

    def test_multiple_contributors_not_solo(self) -> None:
        self.assertFalse(is_solo(_make_repo(contributors=("alice", "bob"))))


class TestIsFork(unittest.TestCase):
    def test_fork_true(self) -> None:
        self.assertTrue(is_fork(_make_repo(is_fork_=True)))

    def test_fork_false(self) -> None:
        self.assertFalse(is_fork(_make_repo(is_fork_=False)))


class TestHasReadme(unittest.TestCase):
    def test_with_readme(self) -> None:
        self.assertTrue(has_readme(_make_repo(had_readme_before=True)))

    def test_without_readme(self) -> None:
        self.assertFalse(has_readme(_make_repo(had_readme_before=False)))


class TestApplyFilters(unittest.TestCase):
    """Compose toggle flags onto a list of repos (F6/F7 AND-composition)."""

    def setUp(self) -> None:
        self.solo_no_fork_no_readme = _make_repo(
            "solo", contributors=("me",), is_fork_=False, had_readme_before=False
        )
        self.team_no_fork_no_readme = _make_repo(
            "team", contributors=("a", "b"), is_fork_=False, had_readme_before=False
        )
        self.solo_fork = _make_repo(
            "solofork", contributors=("me",), is_fork_=True, had_readme_before=False
        )
        self.solo_with_readme = _make_repo(
            "solored", contributors=("me",), is_fork_=False, had_readme_before=True
        )
        self.unknown = _make_repo("unknown", contributors=None)
        self.all_ = [
            self.solo_no_fork_no_readme,
            self.team_no_fork_no_readme,
            self.solo_fork,
            self.solo_with_readme,
            self.unknown,
        ]

    def test_no_flags_returns_all(self) -> None:
        out = apply_filters(self.all_)
        self.assertEqual(out, self.all_)

    def test_solo_only_filters_to_solo(self) -> None:
        out = apply_filters(self.all_, solo_only=True)
        self.assertIn(self.solo_no_fork_no_readme, out)
        self.assertIn(self.solo_fork, out)
        self.assertIn(self.solo_with_readme, out)
        self.assertNotIn(self.team_no_fork_no_readme, out)
        self.assertNotIn(self.unknown, out)

    def test_exclude_forks(self) -> None:
        out = apply_filters(self.all_, exclude_forks=True)
        self.assertNotIn(self.solo_fork, out)
        self.assertIn(self.solo_no_fork_no_readme, out)

    def test_exclude_existing_readme(self) -> None:
        out = apply_filters(self.all_, exclude_existing_readme=True)
        self.assertNotIn(self.solo_with_readme, out)
        self.assertIn(self.solo_no_fork_no_readme, out)

    def test_combined_and_semantics(self) -> None:
        out = apply_filters(
            self.all_,
            solo_only=True,
            exclude_forks=True,
            exclude_existing_readme=True,
        )
        self.assertEqual(out, [self.solo_no_fork_no_readme])


if __name__ == "__main__":
    unittest.main()
