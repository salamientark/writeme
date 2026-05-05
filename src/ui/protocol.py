"""UI protocol for writeme pipeline.

Pipeline code (gh_readme_pipeline.py, src/review.py) imports only this module.
Concrete renderers (RichUI, PlainUI) implement the Protocol so the renderer is
swappable. See docs/UI-REDESIGN.md.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal, Protocol


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
    def show_intro(self) -> None: ...

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]: ...

    def show_review(self, ctx: ReviewContext) -> str:
        """Display review screen. Returns user choice: 'accept'|'redo'|'discard'|'quit'."""
        ...

    def show_summary(self, rows: list[SummaryRow]) -> None: ...

    def prompt(self, message: str) -> str: ...

    def warn(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...
