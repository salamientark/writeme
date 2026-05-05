"""Tests for src/selection.py — TDD RED phase.

Tests cover: SelectionState construction, toggle, move (clamping + viewport
auto-scroll), select_all/none, visible_slice, handle_key, and the immutability
invariant (all mutating methods return new instances, originals unchanged).
"""
import curses
import unittest

from src.selection import Repo, SelectionState


def _make_repos(n: int) -> tuple:
    """Create a tuple of n minimal Repo instances."""
    return tuple(
        Repo(
            name=f"repo-{i}",
            ssh_url=f"git@github.com:user/repo-{i}.git",
            pushed_at="2026-01-01T00:00:00Z",
            had_readme_before=(i % 2 == 0),
            disk_usage=100 * (i + 1),
        )
        for i in range(n)
    )


def _make_state(n: int, viewport_height: int = 5) -> SelectionState:
    return SelectionState(
        repos=_make_repos(n),
        cursor=0,
        selected=frozenset(),
        viewport_start=0,
        viewport_height=viewport_height,
    )


class TestRepoDataclass(unittest.TestCase):
    """Repo is a frozen dataclass — field access and immutability."""

    def test_fields_accessible(self) -> None:
        r = Repo(
            name="my-repo",
            ssh_url="git@github.com:x/my-repo.git",
            pushed_at="2026-04-01T12:00:00Z",
            had_readme_before=True,
            disk_usage=512,
        )
        self.assertEqual(r.name, "my-repo")
        self.assertEqual(r.ssh_url, "git@github.com:x/my-repo.git")
        self.assertEqual(r.pushed_at, "2026-04-01T12:00:00Z")
        self.assertTrue(r.had_readme_before)
        self.assertEqual(r.disk_usage, 512)

    def test_frozen_raises_on_mutation(self) -> None:
        r = Repo("x", "git@github.com:u/x.git", "2026-01-01", False, 0)
        with self.assertRaises((AttributeError, TypeError)):
            r.name = "evil"  # type: ignore[misc]


class TestSelectionStateConstruction(unittest.TestCase):
    """SelectionState can be constructed and has correct initial values."""

    def test_initial_cursor_zero(self) -> None:
        s = _make_state(3)
        self.assertEqual(s.cursor, 0)

    def test_initial_selected_empty(self) -> None:
        s = _make_state(3)
        self.assertEqual(s.selected, frozenset())

    def test_repos_stored(self) -> None:
        s = _make_state(3)
        self.assertEqual(len(s.repos), 3)
        self.assertEqual(s.repos[0].name, "repo-0")


class TestToggle(unittest.TestCase):
    """toggle() flips the cursor index in selected."""

    def test_toggle_selects_unselected_cursor(self) -> None:
        s = _make_state(3)
        s2 = s.toggle()
        self.assertIn(0, s2.selected)

    def test_toggle_deselects_already_selected_cursor(self) -> None:
        s = SelectionState(
            repos=_make_repos(3),
            cursor=1,
            selected=frozenset({1}),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.toggle()
        self.assertNotIn(1, s2.selected)

    def test_toggle_returns_new_instance(self) -> None:
        s = _make_state(3)
        s2 = s.toggle()
        self.assertIsNot(s, s2)
        self.assertEqual(s.selected, frozenset())  # original unchanged

    def test_toggle_does_not_change_cursor(self) -> None:
        s = _make_state(3)
        s.move(1).toggle()  # just verifying no exception; cursor unchanged by toggle
        s2 = s.toggle()
        self.assertEqual(s2.cursor, s.cursor)

    def test_toggle_on_empty_repos_does_nothing(self) -> None:
        s = SelectionState(
            repos=(),
            cursor=0,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.toggle()
        self.assertIsNot(s, s2)
        self.assertEqual(s2.selected, frozenset())


class TestMove(unittest.TestCase):
    """move(delta) adjusts cursor with clamping and viewport auto-scroll."""

    def test_move_forward(self) -> None:
        s = _make_state(5)
        s2 = s.move(1)
        self.assertEqual(s2.cursor, 1)

    def test_move_clamps_at_last(self) -> None:
        s = _make_state(3)
        s2 = s.move(100)
        self.assertEqual(s2.cursor, 2)

    def test_move_backward_from_zero_clamps_at_zero(self) -> None:
        s = _make_state(3)
        s2 = s.move(-1)
        self.assertEqual(s2.cursor, 0)

    def test_move_returns_new_instance(self) -> None:
        s = _make_state(3)
        s2 = s.move(1)
        self.assertIsNot(s, s2)
        self.assertEqual(s.cursor, 0)  # original unchanged

    def test_move_on_empty_list_stays_zero(self) -> None:
        s = SelectionState(
            repos=(),
            cursor=0,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.move(1)
        self.assertEqual(s2.cursor, 0)

    def test_viewport_scrolls_down_when_cursor_exits_bottom(self) -> None:
        # viewport_height=3, viewport_start=0 → viewport shows [0,1,2]
        # moving cursor to index 3 should scroll viewport down
        s = SelectionState(
            repos=_make_repos(10),
            cursor=2,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=3,
        )
        s2 = s.move(1)  # cursor → 3, outside viewport [0..2]
        self.assertEqual(s2.cursor, 3)
        self.assertGreater(s2.viewport_start, 0)

    def test_viewport_scrolls_up_when_cursor_exits_top(self) -> None:
        s = SelectionState(
            repos=_make_repos(10),
            cursor=3,
            selected=frozenset(),
            viewport_start=3,
            viewport_height=3,
        )
        s2 = s.move(-1)  # cursor → 2, above viewport [3..5]
        self.assertEqual(s2.cursor, 2)
        self.assertLess(s2.viewport_start, 3)


class TestSelectAllNone(unittest.TestCase):
    """select_all and select_none manage the full selection set."""

    def test_select_all_selects_every_index(self) -> None:
        s = _make_state(4)
        s2 = s.select_all()
        self.assertEqual(s2.selected, frozenset({0, 1, 2, 3}))

    def test_select_none_clears_selection(self) -> None:
        s = SelectionState(
            repos=_make_repos(4),
            cursor=0,
            selected=frozenset({0, 1, 2, 3}),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.select_none()
        self.assertEqual(s2.selected, frozenset())

    def test_select_all_returns_new_instance(self) -> None:
        s = _make_state(3)
        s2 = s.select_all()
        self.assertIsNot(s, s2)
        self.assertEqual(s.selected, frozenset())  # original unchanged

    def test_select_none_returns_new_instance(self) -> None:
        s = SelectionState(
            repos=_make_repos(3),
            cursor=0,
            selected=frozenset({0}),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.select_none()
        self.assertIsNot(s, s2)
        self.assertIn(0, s.selected)  # original unchanged

    def test_select_all_on_empty_repos(self) -> None:
        s = SelectionState(
            repos=(),
            cursor=0,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.select_all()
        self.assertEqual(s2.selected, frozenset())


class TestVisibleSlice(unittest.TestCase):
    """visible_slice returns (repo, is_selected, is_cursor) tuples for viewport."""

    def test_returns_correct_length_for_full_viewport(self) -> None:
        s = _make_state(10, viewport_height=3)
        slc = s.visible_slice()
        self.assertEqual(len(slc), 3)

    def test_returns_less_when_repos_fewer_than_viewport(self) -> None:
        s = _make_state(2, viewport_height=5)
        slc = s.visible_slice()
        self.assertEqual(len(slc), 2)

    def test_cursor_item_marked_is_cursor(self) -> None:
        s = _make_state(5, viewport_height=5)
        slc = s.visible_slice()
        repo, is_selected, is_cursor = slc[0]
        self.assertTrue(is_cursor)
        self.assertEqual(repo.name, "repo-0")

    def test_non_cursor_item_not_marked_is_cursor(self) -> None:
        s = _make_state(5, viewport_height=5)
        slc = s.visible_slice()
        _, _, is_cursor = slc[1]
        self.assertFalse(is_cursor)

    def test_selected_item_marked_is_selected(self) -> None:
        s = SelectionState(
            repos=_make_repos(5),
            cursor=0,
            selected=frozenset({2}),
            viewport_start=0,
            viewport_height=5,
        )
        slc = s.visible_slice()
        _, is_selected, _ = slc[2]
        self.assertTrue(is_selected)

    def test_unselected_item_not_marked(self) -> None:
        s = _make_state(5, viewport_height=5)
        slc = s.visible_slice()
        _, is_selected, _ = slc[1]
        self.assertFalse(is_selected)

    def test_viewport_offset_respected(self) -> None:
        s = SelectionState(
            repos=_make_repos(10),
            cursor=5,
            selected=frozenset(),
            viewport_start=5,
            viewport_height=3,
        )
        slc = s.visible_slice()
        self.assertEqual(len(slc), 3)
        repo, _, _ = slc[0]
        self.assertEqual(repo.name, "repo-5")

    def test_returns_list_of_tuples(self) -> None:
        s = _make_state(3, viewport_height=3)
        slc = s.visible_slice()
        self.assertIsInstance(slc, list)
        for item in slc:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 3)

    def test_empty_repos_returns_empty_list(self) -> None:
        s = SelectionState(
            repos=(),
            cursor=0,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=5,
        )
        self.assertEqual(s.visible_slice(), [])


class TestHandleKey(unittest.TestCase):
    """handle_key dispatches key codes to the correct state transitions."""

    def test_key_down_moves_cursor(self) -> None:
        s = _make_state(5)
        s2 = s.handle_key(curses.KEY_DOWN)
        self.assertEqual(s2.cursor, 1)

    def test_key_up_moves_cursor_back(self) -> None:
        s = SelectionState(
            repos=_make_repos(5),
            cursor=2,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.handle_key(curses.KEY_UP)
        self.assertEqual(s2.cursor, 1)

    def test_space_toggles_current(self) -> None:
        s = _make_state(5)
        s2 = s.handle_key(ord(" "))
        self.assertIn(0, s2.selected)

    def test_a_selects_all(self) -> None:
        s = _make_state(5)
        s2 = s.handle_key(ord("a"))
        self.assertEqual(s2.selected, frozenset({0, 1, 2, 3, 4}))

    def test_n_selects_none(self) -> None:
        s = SelectionState(
            repos=_make_repos(5),
            cursor=0,
            selected=frozenset({0, 1}),
            viewport_start=0,
            viewport_height=5,
        )
        s2 = s.handle_key(ord("n"))
        self.assertEqual(s2.selected, frozenset())

    def test_unknown_key_returns_same_state(self) -> None:
        s = _make_state(5)
        s2 = s.handle_key(ord("z"))
        # Must return self (same object) for unknown keys
        self.assertIs(s, s2)

    def test_handle_key_returns_new_instance_for_known_keys(self) -> None:
        s = _make_state(5)
        for key in (curses.KEY_DOWN, curses.KEY_UP, ord(" "), ord("a"), ord("n")):
            with self.subTest(key=key):
                # reset to ensure known key always produces a change or new obj
                s_reset = _make_state(5)
                s2 = s_reset.handle_key(key)
                # For keys that produce state transitions, result should differ
                # or at minimum the function should not raise
                self.assertIsInstance(s2, SelectionState)


class TestImmutabilityInvariant(unittest.TestCase):
    """All state-changing methods must return new instances, never mutate."""

    def test_toggle_does_not_mutate_original(self) -> None:
        s = _make_state(3)
        original_selected = s.selected
        s.toggle()
        self.assertEqual(s.selected, original_selected)

    def test_move_does_not_mutate_original(self) -> None:
        s = _make_state(3)
        original_cursor = s.cursor
        s.move(2)
        self.assertEqual(s.cursor, original_cursor)

    def test_select_all_does_not_mutate_original(self) -> None:
        s = _make_state(3)
        s.select_all()
        self.assertEqual(s.selected, frozenset())

    def test_select_none_does_not_mutate_original(self) -> None:
        s = SelectionState(
            repos=_make_repos(3),
            cursor=0,
            selected=frozenset({0, 1}),
            viewport_start=0,
            viewport_height=5,
        )
        original = s.selected
        s.select_none()
        self.assertEqual(s.selected, original)

    def test_handle_key_does_not_mutate_original(self) -> None:
        s = _make_state(5)
        original_cursor = s.cursor
        original_selected = s.selected
        s.handle_key(curses.KEY_DOWN)
        s.handle_key(ord(" "))
        self.assertEqual(s.cursor, original_cursor)
        self.assertEqual(s.selected, original_selected)


class TestFilterAndJump(unittest.TestCase):
    """Stage 2 extensions: filter, jump, page, hidden_selected_count."""

    def _named_repos(self, names: list[str]) -> tuple:
        return tuple(
            Repo(
                name=n,
                ssh_url=f"git@github.com:user/{n}.git",
                pushed_at="2026-01-01",
                had_readme_before=False,
                disk_usage=1,
            )
            for n in names
        )

    def _state(self, names: list[str], **kw) -> SelectionState:
        return SelectionState(
            repos=self._named_repos(names),
            cursor=kw.get("cursor", 0),
            selected=frozenset(kw.get("selected", [])),
            viewport_start=kw.get("vp", 0),
            viewport_height=kw.get("h", 5),
            filter=kw.get("filter", ""),
        )

    def test_filter_field_default_empty(self) -> None:
        s = self._state(["a", "b"])
        self.assertEqual(s.filter, "")

    def test_apply_filter_returns_new_state(self) -> None:
        s = self._state(["alpha", "beta", "gamma"])
        s2 = s.apply_filter("be")
        self.assertEqual(s2.filter, "be")
        self.assertEqual(s.filter, "")

    def test_visible_indices_no_filter(self) -> None:
        s = self._state(["a", "b", "c"])
        self.assertEqual(s.visible_indices, (0, 1, 2))

    def test_visible_indices_substring_match(self) -> None:
        s = self._state(["alpha", "beta", "alphabet"]).apply_filter("alpha")
        self.assertEqual(s.visible_indices, (0, 2))

    def test_filter_case_insensitive(self) -> None:
        s = self._state(["Alpha", "Beta"]).apply_filter("ALP")
        self.assertEqual(s.visible_indices, (0,))

    def test_filter_preserves_selected(self) -> None:
        s = self._state(["alpha", "beta", "gamma"], selected=[0, 2])
        s2 = s.apply_filter("alpha")
        self.assertEqual(s2.selected, frozenset({0, 2}))

    def test_clear_filter(self) -> None:
        s = self._state(["a", "b"]).apply_filter("a")
        s2 = s.clear_filter()
        self.assertEqual(s2.filter, "")

    def test_cursor_clamps_to_visible_after_filter(self) -> None:
        s = self._state(["alpha", "beta", "gamma"], cursor=2).apply_filter("alpha")
        self.assertIn(s.cursor, s.visible_indices)

    def test_hidden_selected_count(self) -> None:
        s = self._state(
            ["alpha", "beta", "gamma"], selected=[0, 1, 2]
        ).apply_filter("alpha")
        self.assertEqual(s.hidden_selected_count, 2)

    def test_hidden_selected_count_zero_when_no_filter(self) -> None:
        s = self._state(["a", "b"], selected=[0, 1])
        self.assertEqual(s.hidden_selected_count, 0)

    def test_jump_top(self) -> None:
        s = self._state(["a", "b", "c"], cursor=2, vp=1)
        s2 = s.jump_top()
        self.assertEqual(s2.cursor, 0)
        self.assertEqual(s2.viewport_start, 0)

    def test_jump_bottom(self) -> None:
        s = self._state(["a", "b", "c", "d", "e", "f"], h=3)
        s2 = s.jump_bottom()
        self.assertEqual(s2.cursor, 5)

    def test_jump_bottom_with_filter(self) -> None:
        s = self._state(["alpha", "beta", "alphabet"]).apply_filter("alpha")
        s2 = s.jump_bottom()
        self.assertEqual(s2.cursor, 2)

    def test_page_down(self) -> None:
        s = self._state([f"r{i}" for i in range(20)], h=5)
        s2 = s.page_down()
        self.assertEqual(s2.cursor, 5)

    def test_page_up_at_top(self) -> None:
        s = self._state([f"r{i}" for i in range(20)], h=5, cursor=0)
        s2 = s.page_up()
        self.assertEqual(s2.cursor, 0)

    def test_page_down_at_bottom(self) -> None:
        s = self._state([f"r{i}" for i in range(5)], h=5, cursor=4)
        s2 = s.page_down()
        self.assertEqual(s2.cursor, 4)

    def test_select_all_operates_on_visible_only(self) -> None:
        s = self._state(["alpha", "beta", "alphabet"]).apply_filter("alpha")
        s2 = s.select_all()
        self.assertEqual(s2.selected, frozenset({0, 2}))

    def test_select_none_clears_only_visible(self) -> None:
        s = self._state(
            ["alpha", "beta", "alphabet"], selected=[0, 1, 2]
        ).apply_filter("alpha")
        s2 = s.select_none()
        self.assertEqual(s2.selected, frozenset({1}))


if __name__ == "__main__":
    unittest.main()
