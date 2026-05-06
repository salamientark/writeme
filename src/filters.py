"""Pure predicate filters over Repo records.

Phase 1 of parallel-readme-and-solo-filter plan: independent predicate bits
that compose with AND on top of the existing `/`-text filter.

All functions are pure — no I/O, no globals — so they unit-test trivially.
"""
from __future__ import annotations

from src.selection import Repo


def is_solo(repo: Repo) -> bool:
    """True if the repo is single-author / empty.

    `contributors` is the tuple of human logins after bot-strip
    (see ``src/contributors.py``):
      * ``None`` — REST data not yet available; conservative answer is False.
      * ``()``   — empty repo (0 contributors), counted as solo per F3.
      * 1 entry  — single human author.
      * >1       — collaborative repo.
    """
    if repo.contributors is None:
        return False
    return len(repo.contributors) <= 1


def is_fork(repo: Repo) -> bool:
    return repo.is_fork


def has_readme(repo: Repo) -> bool:
    return repo.had_readme_before


def apply_filters(
    repos: list[Repo],
    *,
    solo_only: bool = False,
    exclude_forks: bool = False,
    exclude_existing_readme: bool = False,
) -> list[Repo]:
    """Return repos passing every enabled toggle (AND composition).

    Each toggle is independent (F6) and additional predicates can be added
    without rewriting callers.
    """
    def keep(r: Repo) -> bool:
        if solo_only and not is_solo(r):
            return False
        if exclude_forks and is_fork(r):
            return False
        if exclude_existing_readme and has_readme(r):
            return False
        return True

    return [r for r in repos if keep(r)]
