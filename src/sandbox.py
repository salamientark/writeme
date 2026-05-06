"""Per-job XDG sandbox dir helper.

Plan: parallel-readme-and-solo-filter Phase 2 (P7).

Each parallel claude job gets its own ``$SANDBOX/claude-jobs/<repo>/{config,data,cache,state}``
tree so concurrent runs don't race on the claude session DB.
"""
from __future__ import annotations

from pathlib import Path

from src import safety

_SUBDIRS = ("config", "data", "cache", "state")


def sandbox_for(base: Path, repo_name: str) -> dict[str, Path]:
    """Return ``{name: path}`` for the four XDG subdirs, creating them on disk.

    Repo name is validated to prevent path traversal.
    """
    safety.validate_repo_name(repo_name)
    root = base / "claude-jobs" / repo_name
    paths = {n: root / n for n in _SUBDIRS}
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def sandbox_env(paths: dict[str, Path]) -> dict[str, str]:
    """Return env-var dict mapping XDG_*_HOME → sandbox subdir path strings."""
    return {
        "XDG_CONFIG_HOME": str(paths["config"]),
        "XDG_DATA_HOME": str(paths["data"]),
        "XDG_CACHE_HOME": str(paths["cache"]),
        "XDG_STATE_HOME": str(paths["state"]),
    }
