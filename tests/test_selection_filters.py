"""Predicate-filter toggles for SelectionState (Phase 1, F6/F7/F8)."""
import curses
import unittest

from src.selection import Repo, SelectionState


def _repos() -> tuple[Repo, ...]:
    return (
        Repo("solo", "git@github.com:u/solo.git", "2026-01-01", False, 1,
             is_fork=False, contributors=("me",)),
        Repo("team", "git@github.com:u/team.git", "2026-01-01", False, 1,
             is_fork=False, contributors=("me", "you")),
        Repo("solo-fork", "git@github.com:u/solo-fork.git", "2026-01-01", False, 1,
             is_fork=True, contributors=("me",)),
        Repo("solo-readme", "git@github.com:u/solo-readme.git", "2026-01-01", True, 1,
             is_fork=False, contributors=("me",)),
    )


def _state() -> SelectionState:
    return SelectionState(
        repos=_repos(),
        cursor=0,
        selected=frozenset(),
        viewport_start=0,
        viewport_height=10,
    )


class TestPredicateFilterFields(unittest.TestCase):
    def test_default_flags_off(self) -> None:
        s = _state()
        self.assertFalse(s.solo_only)
        self.assertFalse(s.exclude_forks)
        self.assertFalse(s.exclude_existing_readme)

    def test_visible_indices_unfiltered(self) -> None:
        s = _state()
        self.assertEqual(len(s.visible_indices), 4)


class TestToggleSolo(unittest.TestCase):
    def test_solo_only_filters_to_solo(self) -> None:
        s = _state().toggle_solo_only()
        names = [s.repos[i].name for i in s.visible_indices]
        self.assertEqual(set(names), {"solo", "solo-fork", "solo-readme"})

    def test_toggle_twice_restores(self) -> None:
        s = _state().toggle_solo_only().toggle_solo_only()
        self.assertEqual(len(s.visible_indices), 4)
        self.assertFalse(s.solo_only)


class TestToggleForks(unittest.TestCase):
    def test_exclude_forks_drops_forks(self) -> None:
        s = _state().toggle_exclude_forks()
        names = [s.repos[i].name for i in s.visible_indices]
        self.assertNotIn("solo-fork", names)


class TestToggleReadme(unittest.TestCase):
    def test_exclude_existing_readme(self) -> None:
        s = _state().toggle_exclude_existing_readme()
        names = [s.repos[i].name for i in s.visible_indices]
        self.assertNotIn("solo-readme", names)


class TestKeyDispatch(unittest.TestCase):
    def test_s_toggles_solo(self) -> None:
        s = _state().handle_key(ord("s"))
        self.assertTrue(s.solo_only)

    def test_F_toggles_forks(self) -> None:
        s = _state().handle_key(ord("F"))
        self.assertTrue(s.exclude_forks)

    def test_r_toggles_readme(self) -> None:
        s = _state().handle_key(ord("r"))
        self.assertTrue(s.exclude_existing_readme)


class TestSelectionPreservedAcrossToggles(unittest.TestCase):
    """F8: selection state preserved across toggles."""

    def test_select_then_toggle_preserves_indices(self) -> None:
        s = _state()
        # Select "team" (idx 1).
        s = SelectionState(
            repos=s.repos,
            cursor=1,
            selected=frozenset({1}),
            viewport_start=0,
            viewport_height=10,
        )
        s2 = s.toggle_solo_only()  # team is filtered out of view
        self.assertIn(1, s2.selected)


class TestComposesWithTextFilter(unittest.TestCase):
    """F7: predicate filters AND with text search."""

    def test_text_and_solo(self) -> None:
        s = _state().toggle_solo_only().apply_filter("fork")
        names = [s.repos[i].name for i in s.visible_indices]
        self.assertEqual(names, ["solo-fork"])


if __name__ == "__main__":
    unittest.main()
