"""Pure diff computation for the review screen.

Extracted from src/review.py per docs/UI-REDESIGN.md so the rendered diff views
(diff vs HEAD, diff vs previous draft) can be unit-tested without touching the
Rich-based renderer.
"""
from __future__ import annotations

import difflib

NO_HEAD_DIFF = "(no diff — first draft, no prior README)"
NO_PREV_DIFF = "(no diff — this is the first draft)"
NO_CHANGES = "(no changes)"

_DRAFT_LABEL = "README.md (draft)"
_HEAD_LABEL = "README.md (HEAD)"
_PREV_LABEL = "README.md (prev draft)"


def unified(old: str, new: str, *, fromfile: str, tofile: str) -> str:
    """Return a unified diff between *old* and *new*, or NO_CHANGES sentinel."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    out = "".join(
        difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile)
    )
    return out or NO_CHANGES


def diff_vs_head(head: str | None, current: str) -> str:
    """Diff committed README against current draft. Fallback if no HEAD README."""
    if head is None:
        return NO_HEAD_DIFF
    return unified(head, current, fromfile=_HEAD_LABEL, tofile=_DRAFT_LABEL)


def diff_vs_prev(prev: str | None, current: str) -> str:
    """Diff previous Claude draft against current. Fallback on first iteration."""
    if prev is None:
        return NO_PREV_DIFF
    return unified(prev, current, fromfile=_PREV_LABEL, tofile=_DRAFT_LABEL)
