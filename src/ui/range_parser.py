"""Range parser for PlainUI repo selection.

Parses user input like ``1,3,5-7`` (1-indexed) into a 0-indexed frozenset of
positions. Also recognizes the ``a`` (all) and ``q`` (quit) keywords.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParseResult:
    """Outcome of parsing a selection string.

    kind:
        "ok"    → indices populated, 0-indexed.
        "all"   → user typed ``a`` / ``A``.
        "quit"  → user typed ``q`` / ``Q`` or empty/whitespace input.
        "error" → message populated.
    """
    kind: Literal["ok", "all", "quit", "error"]
    indices: frozenset[int] = frozenset()
    message: str = ""

    @classmethod
    def ok(cls, indices: frozenset[int]) -> "ParseResult":
        return cls(kind="ok", indices=indices)

    @classmethod
    def all_(cls) -> "ParseResult":
        return cls(kind="all")

    @classmethod
    def quit_(cls) -> "ParseResult":
        return cls(kind="quit")

    @classmethod
    def error(cls, message: str) -> "ParseResult":
        return cls(kind="error", message=message)


def parse_selection(raw: str, total: int) -> ParseResult:
    """Parse a selection string. *total* is the number of available repos."""
    s = raw.strip().lower()
    if s == "" or s == "q":
        return ParseResult.quit_()
    if s == "a":
        return ParseResult.all_()

    indices: set[int] = set()
    for token in s.split(","):
        t = token.strip()
        if not t:
            return ParseResult.error(f"empty token in {raw!r}")
        if "-" in t:
            parts = t.split("-")
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                return ParseResult.error(f"bad range {t!r}")
            try:
                lo = int(parts[0].strip())
                hi = int(parts[1].strip())
            except ValueError:
                return ParseResult.error(f"bad range {t!r}")
            if lo < 1 or hi > total or lo > hi:
                return ParseResult.error(f"range {t!r} out of bounds (1..{total})")
            indices.update(range(lo - 1, hi))
        else:
            try:
                n = int(t)
            except ValueError:
                return ParseResult.error(f"bad token {t!r}")
            if n < 1 or n > total:
                return ParseResult.error(f"index {n} out of bounds (1..{total})")
            indices.add(n - 1)

    return ParseResult.ok(frozenset(indices))
