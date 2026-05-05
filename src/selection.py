"""Pure immutable selection state for the repository TUI.

Addresses: M1 — pure, unit-tested SelectionState backed by frozen dataclasses.

All state-changing methods return a NEW SelectionState; no mutation ever occurs.
This makes the selection logic trivially testable and safe to use in curses event
loops where unexpected mutation could corrupt the display.
"""
import curses
from dataclasses import dataclass, replace
from typing import NamedTuple


@dataclass(frozen=True)
class Repo:
    """Immutable representation of a GitHub repository as returned by fetch_repos.

    Fields mirror the GraphQL response fields we care about:
    - name:              repository name (validated by safety.validate_repo_name)
    - ssh_url:           clone URL (validated by safety.validate_ssh_url)
    - pushed_at:         ISO-8601 timestamp of last push
    - had_readme_before: True if any README variant was detected pre-pipeline
    - disk_usage:        repository disk usage in kilobytes (from GraphQL)
    """
    name: str
    ssh_url: str
    pushed_at: str
    had_readme_before: bool
    disk_usage: int


class VisibleRow(NamedTuple):
    """A single row of the visible slice: (repo, is_selected, is_cursor)."""
    repo: Repo
    is_selected: bool
    is_cursor: bool


@dataclass(frozen=True)
class SelectionState:
    """Immutable TUI selection state: cursor position, selected set, viewport.

    All methods that logically 'change' state return a NEW SelectionState
    instance; the original is never modified (frozen dataclass + immutable
    field types enforce this at the interpreter level).

    Fields:
    - repos:           ordered tuple of all available Repo objects
    - cursor:          index of the currently highlighted row (0-based)
    - selected:        frozenset of repo indices that are checked
    - viewport_start:  index of the first repo shown in the visible window
    - viewport_height: number of rows the terminal window can display
    """
    repos: tuple
    cursor: int
    selected: frozenset
    viewport_start: int
    viewport_height: int
    filter: str = ""

    # ------------------------------------------------------------------
    # Core mutation helpers (return new instances)
    # ------------------------------------------------------------------

    def toggle(self) -> "SelectionState":
        """Flip the selection state of the repo at the current cursor position.

        Returns a new SelectionState with the cursor index added to or removed
        from ``selected``.  Calling on an empty repo list is a no-op.
        """
        if not self.repos:
            return replace(self)
        if self.cursor in self.selected:
            new_selected = self.selected - {self.cursor}
        else:
            new_selected = self.selected | {self.cursor}
        return replace(self, selected=frozenset(new_selected))

    def move(self, delta: int) -> "SelectionState":
        """Move the cursor by *delta* rows, clamping to valid range.

        Also auto-scrolls the viewport to keep the cursor visible:
        - If cursor moves below the bottom of the viewport, shift viewport down.
        - If cursor moves above the top of the viewport, shift viewport up.

        Returns a new SelectionState; original is unchanged.
        """
        if not self.repos:
            return replace(self)

        n = len(self.repos)
        new_cursor = max(0, min(n - 1, self.cursor + delta))

        # Compute new viewport_start to keep cursor in view
        new_vp_start = self.viewport_start

        # Cursor scrolled below visible window
        if new_cursor >= new_vp_start + self.viewport_height:
            new_vp_start = new_cursor - self.viewport_height + 1

        # Cursor scrolled above visible window
        if new_cursor < new_vp_start:
            new_vp_start = new_cursor

        # Clamp viewport_start to valid range
        new_vp_start = max(0, min(n - 1, new_vp_start))

        return replace(self, cursor=new_cursor, viewport_start=new_vp_start)

    def select_all(self) -> "SelectionState":
        """Mark every visible repo as selected (preserves out-of-filter selections)."""
        visible = set(self.visible_indices)
        return replace(self, selected=frozenset(self.selected | visible))

    def select_none(self) -> "SelectionState":
        """Clear selections of visible repos (preserves out-of-filter selections)."""
        visible = set(self.visible_indices)
        return replace(self, selected=frozenset(self.selected - visible))

    # ------------------------------------------------------------------
    # Filter / jump / page (Stage 2)
    # ------------------------------------------------------------------

    def apply_filter(self, q: str) -> "SelectionState":
        """Set filter substring; clamp cursor to visible range; reset viewport."""
        new = replace(self, filter=q, viewport_start=0)
        if not new.repos:
            return new
        visible = new.visible_indices
        if not visible:
            return new
        cursor = self.cursor if self.cursor in visible else visible[0]
        return replace(new, cursor=cursor)

    def clear_filter(self) -> "SelectionState":
        return replace(self, filter="")

    def jump_top(self) -> "SelectionState":
        visible = self.visible_indices
        if not visible:
            return self
        return replace(self, cursor=visible[0], viewport_start=0)

    def jump_bottom(self) -> "SelectionState":
        visible = self.visible_indices
        if not visible:
            return self
        new_cursor = visible[-1]
        new_vp = max(0, len(visible) - self.viewport_height)
        return replace(self, cursor=new_cursor, viewport_start=new_vp)

    def page_down(self) -> "SelectionState":
        return self.move(self.viewport_height)

    def page_up(self) -> "SelectionState":
        return self.move(-self.viewport_height)

    @property
    def visible_indices(self) -> tuple[int, ...]:
        """Indices into self.repos matching current filter (case-insensitive)."""
        if not self.filter:
            return tuple(range(len(self.repos)))
        q = self.filter.lower()
        return tuple(i for i, r in enumerate(self.repos) if q in r.name.lower())

    @property
    def hidden_selected_count(self) -> int:
        """Count of selected repos not in current visible_indices."""
        if not self.filter:
            return 0
        visible = set(self.visible_indices)
        return sum(1 for i in self.selected if i not in visible)

    # ------------------------------------------------------------------
    # Read-only query
    # ------------------------------------------------------------------

    def visible_slice(self) -> list:
        """Return the rows that should be rendered in the current viewport.

        Returns a list of ``VisibleRow`` named tuples:
        ``(repo: Repo, is_selected: bool, is_cursor: bool)``

        The slice starts at ``viewport_start`` and includes at most
        ``viewport_height`` items (or fewer if fewer repos remain).
        """
        start = self.viewport_start
        end = start + self.viewport_height
        result: list[VisibleRow] = []
        for idx, repo in enumerate(self.repos[start:end], start=start):
            result.append(VisibleRow(
                repo=repo,
                is_selected=(idx in self.selected),
                is_cursor=(idx == self.cursor),
            ))
        return result

    # ------------------------------------------------------------------
    # Key dispatcher
    # ------------------------------------------------------------------

    def handle_key(self, c: int) -> "SelectionState":
        """Dispatch a key code *c* to the appropriate state transition.

        Recognized keys:
        - ``curses.KEY_DOWN``: move cursor down 1
        - ``curses.KEY_UP``:   move cursor up 1
        - ``ord(' ')``:        toggle selection at cursor
        - ``ord('a')``:        select all
        - ``ord('n')``:        select none

        Unknown keys: return ``self`` unchanged (identity, not a copy).
        """
        if c == curses.KEY_DOWN:
            return self.move(1)
        if c == curses.KEY_UP:
            return self.move(-1)
        if c == ord(" "):
            return self.toggle()
        if c == ord("a"):
            return self.select_all()
        if c == ord("n"):
            return self.select_none()
        return self
