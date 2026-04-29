"""Thin curses shim around SelectionState for repository selection TUI.

Public API
----------
    tui_select(repos: list[Repo]) -> list[Repo]
        Display the interactive TUI and return the user's selected repos.
        Returns [] immediately if repos is empty (no curses init).

    _main_loop(stdscr, state: SelectionState) -> list[Repo]
        Curses event loop; called via curses.wrapper.

    _render(stdscr, state: SelectionState) -> None
        Draw the current state to stdscr.

Key bindings
------------
    KEY_UP / KEY_DOWN  move cursor
    SPACE              toggle selection
    a                  select all
    n                  select none
    ENTER              confirm and return selected repos
    q                  abort, return empty list
    KEY_RESIZE         recompute viewport height
"""
from __future__ import annotations

import curses

from src.selection import Repo, SelectionState


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def tui_select(repos: list[Repo]) -> list[Repo]:
    """Display the interactive selection TUI and return selected repos.

    If *repos* is empty, return [] immediately without initialising curses.

    Args:
        repos: All candidate repositories to show in the TUI.

    Returns:
        The subset of *repos* that the user confirmed (in ascending index order).
        Empty list if the user quit with 'q' or confirmed with nothing selected.
    """
    if not repos:
        return []

    initial_state = SelectionState(
        repos=tuple(repos),
        cursor=0,
        selected=frozenset(),
        viewport_start=0,
        viewport_height=20,  # overridden by _main_loop on first render
    )
    return curses.wrapper(_main_loop, initial_state)


# ---------------------------------------------------------------------------
# Curses event loop
# ---------------------------------------------------------------------------


def _main_loop(stdscr, state: SelectionState) -> list[Repo]:
    """Curses event loop; called via curses.wrapper.

    Args:
        stdscr: The curses window supplied by curses.wrapper.
        state:  Initial SelectionState.

    Returns:
        List of selected Repo objects in ascending index order (may be empty).
    """
    curses.curs_set(0)
    stdscr.keypad(True)

    # Initialise viewport height from actual terminal size
    rows, _cols = stdscr.getmaxyx()
    # Reserve 3 rows: header, help line, and one spare
    vp_height = max(1, rows - 3)
    from dataclasses import replace
    state = replace(state, viewport_height=vp_height)

    while True:
        _render(stdscr, state)
        c = stdscr.getch()

        if c in (ord("\n"), curses.KEY_ENTER, 10, 13):
            # Confirm: return selected repos in sorted index order
            return [state.repos[i] for i in sorted(state.selected)]

        if c == ord("q"):
            return []

        if c == curses.KEY_RESIZE:
            rows, _cols = stdscr.getmaxyx()
            vp_height = max(1, rows - 3)
            state = replace(state, viewport_height=vp_height)
        else:
            state = state.handle_key(c)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _render(stdscr, state: SelectionState) -> None:
    """Draw the current TUI state to *stdscr*.

    Layout:
        Row 0: header  "Select repos for /create-readme  (N selected of M)"
        Row 1: help    "↑/↓ move  space toggle  a all  n none  enter confirm  q quit"
        Row 2+: one repo row per visible entry

    Each repo row:
        "[x] [HAS README   ] <name>  <pushed_at>"
    Cursor row rendered with A_REVERSE (reverse video).

    Args:
        stdscr: The curses window.
        state:  Current SelectionState to render.
    """
    stdscr.clear()
    rows, cols = stdscr.getmaxyx()

    n_selected = len(state.selected)
    n_total = len(state.repos)

    # Row 0: header
    header = f"Select repos for /create-readme  ({n_selected} selected of {n_total})"
    _safe_addstr(stdscr, 0, 0, header[:cols - 1])

    # Row 1: help
    help_line = "↑/↓ move  space toggle  a all  n none  enter confirm  q quit"
    _safe_addstr(stdscr, 1, 0, help_line[:cols - 1])

    # Rows 2+: repo list
    for display_row, visible_row in enumerate(state.visible_slice()):
        screen_row = display_row + 2
        if screen_row >= rows - 1:
            break

        check = "x" if visible_row.is_selected else " "
        readme_badge = "HAS README" if visible_row.repo.had_readme_before else " " * 10
        line = f"[{check}] [{readme_badge}] {visible_row.repo.name}  {visible_row.repo.pushed_at}"
        line = line[:cols - 1]

        attr = curses.A_REVERSE if visible_row.is_cursor else curses.A_NORMAL
        _safe_addstr(stdscr, screen_row, 0, line, attr)

    stdscr.refresh()


def _safe_addstr(stdscr, row: int, col: int, text: str, attr: int = curses.A_NORMAL) -> None:
    """Call stdscr.addstr, suppressing the error raised at the last cell."""
    try:
        stdscr.addstr(row, col, text, attr)
    except curses.error:
        pass
