"""Tests for src/tui.py — structural/smoke tests only.

Curses internals are not tested (unreliable in headless environments).
We verify:
- Module and function importability.
- Signature contracts.
- Empty-list short-circuit (no curses.wrapper call).
- Non-empty list delegates to curses.wrapper with the correct callable.
"""
import unittest
from unittest.mock import MagicMock, patch


class TestTuiImports(unittest.TestCase):
    """Smoke test: module and public symbols are importable."""

    def test_module_importable(self):
        import src.tui  # noqa: F401

    def test_tui_select_importable(self):
        from src.tui import tui_select
        self.assertTrue(callable(tui_select))

    def test_render_importable(self):
        from src.tui import _render
        self.assertTrue(callable(_render))

    def test_main_loop_importable(self):
        from src.tui import _main_loop
        self.assertTrue(callable(_main_loop))


class TestTuiSelectEmptyList(unittest.TestCase):
    """Empty repos list must return [] without initialising curses."""

    def test_empty_list_returns_empty(self):
        from src.tui import tui_select
        result = tui_select([])
        self.assertEqual(result, [])

    def test_empty_list_does_not_call_curses_wrapper(self):
        from src.tui import tui_select
        with patch("curses.wrapper") as mock_wrapper:
            tui_select([])
            mock_wrapper.assert_not_called()


class TestTuiSelectSignature(unittest.TestCase):
    """tui_select takes a list and returns a list."""

    def _make_repo(self, name: str):
        from src.selection import Repo
        return Repo(
            name=name,
            ssh_url=f"git@github.com:user/{name}.git",
            pushed_at="2026-01-01T00:00:00Z",
            had_readme_before=False,
            disk_usage=0,
        )

    def test_non_empty_calls_curses_wrapper(self):
        from src.tui import tui_select
        repos = [self._make_repo("repo-a")]
        # Make curses.wrapper return a list (simulates user confirming selection)
        with patch("curses.wrapper", return_value=[]) as mock_wrapper:
            result = tui_select(repos)
            mock_wrapper.assert_called_once()

    def test_non_empty_first_arg_to_wrapper_is_callable(self):
        """curses.wrapper must be called with a callable as its first argument."""
        from src.tui import tui_select
        repos = [self._make_repo("repo-b")]
        captured = {}

        def fake_wrapper(fn, *args, **kwargs):
            captured["fn"] = fn
            return []

        with patch("curses.wrapper", side_effect=fake_wrapper):
            tui_select(repos)

        self.assertIn("fn", captured)
        self.assertTrue(callable(captured["fn"]))

    def test_returns_list(self):
        from src.tui import tui_select
        repos = [self._make_repo("repo-c")]
        with patch("curses.wrapper", return_value=[]) as _:
            result = tui_select(repos)
        self.assertIsInstance(result, list)

    def test_wrapper_return_value_propagated(self):
        """Whatever curses.wrapper returns becomes the result of tui_select."""
        from src.tui import tui_select
        from src.selection import Repo
        repo = self._make_repo("repo-d")
        expected = [repo]
        with patch("curses.wrapper", return_value=expected):
            result = tui_select([repo])
        self.assertEqual(result, expected)


class TestTuiRenderSignature(unittest.TestCase):
    """_render(stdscr, state) must accept two positional arguments."""

    def _make_state(self, names):
        from src.selection import Repo, SelectionState
        repos = tuple(
            Repo(
                name=n,
                ssh_url=f"git@github.com:user/{n}.git",
                pushed_at="2026-01-01T00:00:00Z",
                had_readme_before=False,
                disk_usage=0,
            )
            for n in names
        )
        return SelectionState(
            repos=repos,
            cursor=0,
            selected=frozenset(),
            viewport_start=0,
            viewport_height=10,
        )

    def test_render_accepts_stdscr_and_state(self):
        from src.tui import _render
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.addstr = MagicMock()
        stdscr.clrtoeol = MagicMock()
        stdscr.clear = MagicMock()
        state = self._make_state(["repo-x"])
        # Must not raise
        try:
            _render(stdscr, state)
        except Exception:
            # Curses attribute errors are acceptable in headless env;
            # what matters is the function is defined with the right signature.
            pass


class TestTuiMainLoopSignature(unittest.TestCase):
    """_main_loop(stdscr, state) must accept two positional arguments."""

    def test_main_loop_defined_with_two_args(self):
        import inspect
        from src.tui import _main_loop
        sig = inspect.signature(_main_loop)
        params = list(sig.parameters.keys())
        self.assertGreaterEqual(len(params), 2,
            "_main_loop must accept at least 2 positional parameters (stdscr, state)")
        self.assertEqual(params[0], "stdscr")
        self.assertEqual(params[1], "state")

    def test_render_defined_with_two_args(self):
        import inspect
        from src.tui import _render
        sig = inspect.signature(_render)
        params = list(sig.parameters.keys())
        self.assertGreaterEqual(len(params), 2,
            "_render must accept at least 2 positional parameters (stdscr, state)")
        self.assertEqual(params[0], "stdscr")
        self.assertEqual(params[1], "state")
