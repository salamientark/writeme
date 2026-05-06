"""UI protocol for writeme pipeline.

Pipeline code (gh_readme_pipeline.py, src/review.py) imports only this module.
Concrete renderers (RichUI, PlainUI) implement the Protocol so the renderer is
swappable. See docs/UI-REDESIGN.md.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Literal, Protocol

if TYPE_CHECKING:
    from src.selection import Repo


@dataclass(frozen=True)
class ReviewContext:
    """Inputs for the review screen."""
    repo_name: str
    index: int
    total: int
    head_readme: str | None
    prev_draft: str | None
    current_draft: str


@dataclass(frozen=True)
class SummaryRow:
    repo: str
    outcome: Literal["accepted", "redone", "skipped", "failed"]
    pr_url: str | None


class UI(Protocol):
    def clear(self) -> None:
        """Clear the terminal screen (no-op when not a TTY)."""
        ...

    def show_intro(self) -> None: ...

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]: ...

    def select_repos(self, repos: list["Repo"]) -> list["Repo"]:
        """Display the repo selection screen. Returns chosen subset (ascending).

        Empty list means user quit / nothing selected.
        """
        ...

    def show_review(self, ctx: ReviewContext) -> str:
        """Display review screen. Returns user choice: 'accept'|'redo'|'discard'|'quit'."""
        ...

    def show_summary(self, rows: list[SummaryRow]) -> None: ...

    def menu(self, title: str, options: list[tuple[str, str]]) -> str:
        """Show a menu and return the chosen option key.

        *options* is a list of (key, description) tuples. The renderer is free
        to display any of: keystroke shortcut, arrow-key navigation, both.
        Returns the key string of the chosen option, or empty string on quit.
        """
        ...

    def prompt(self, message: str) -> str: ...

    def warn(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def status_line(
        self, done: int, total: int, running: int, queued: int
    ) -> None:
        """Render the parallel-pipeline status line above the review prompt.

        Format: ``[done/total] running=R queued=Q``. Renderers may use Rich
        Live or fall back to plain stdout.
        """
        ...
