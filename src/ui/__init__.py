"""UI layer for writeme — protocol + renderers (Rich/Plain).

See docs/UI-REDESIGN.md.
"""
from __future__ import annotations

import sys

from .protocol import UI, ReviewContext, SummaryRow

__all__ = ["UI", "ReviewContext", "SummaryRow", "make_ui"]


def make_ui(plain: bool = False, isatty: bool | None = None) -> UI:
    """Return a UI renderer.

    Returns RichUI when stdout is a TTY, *plain* is False, and `rich` is
    importable. Otherwise returns PlainUI (preserves pre-redesign behavior).
    """
    if isatty is None:
        isatty = sys.stdout.isatty()
    if plain or not isatty:
        from .plain_ui import PlainUI
        return PlainUI()
    try:
        from .rich_ui import RichUI
        return RichUI()
    except ImportError:
        from .plain_ui import PlainUI
        return PlainUI()
