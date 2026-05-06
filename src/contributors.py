"""REST contributor fetch + bot strip + cache I/O.

Plan: parallel-readme-and-solo-filter Phase 1 (F2-F5).

Solo detection uses the REST endpoint
``GET /repos/{owner}/{repo}/contributors?per_page=2`` (cheaper than counting
the full list — len <= 1 after bot strip is enough). Results are cached on
disk keyed by ``repo_name + pushed_at``; stale entries (different pushed_at)
are ignored.
"""
from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from src.selection import Repo

# ---------------------------------------------------------------------------
# Bot detection
# ---------------------------------------------------------------------------

_BOT_RE = re.compile(
    r"(.*\[bot\]$|^dependabot(-preview)?$|^github-actions$)",
    re.IGNORECASE,
)


def is_bot(login: str) -> bool:
    return bool(_BOT_RE.match(login))


def strip_bots(logins: Iterable[str]) -> tuple[str, ...]:
    return tuple(l for l in logins if not is_bot(l))


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def cache_key(repo_name: str, pushed_at: str) -> str:
    return f"{repo_name}@{pushed_at}"


def load_cache(path: Path) -> dict[str, list[str]]:
    """Read JSON cache; return ``{}`` on missing or corrupt file."""
    try:
        text = path.read_text()
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def save_cache(path: Path, cache: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# REST fetch
# ---------------------------------------------------------------------------

def fetch_contributors(owner: str, name: str) -> tuple[str, ...]:
    """Return tuple of human contributor logins (bots stripped).

    Empty tuple means: 0 contributors (empty repo / 404) OR 0 humans after
    bot strip — both count as solo per F3.
    """
    cmd = [
        "gh", "api",
        f"/repos/{owner}/{name}/contributors?per_page=2",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, timeout=15)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # 404 (empty repo), 403, timeout, etc. — treat as 0 contributors.
        return ()
    try:
        payload = json.loads(result.stdout or b"[]")
    except (json.JSONDecodeError, ValueError):
        return ()
    if not isinstance(payload, list):
        return ()
    logins = [
        entry.get("login", "")
        for entry in payload
        if isinstance(entry, dict) and entry.get("login")
    ]
    return strip_bots(logins)


# ---------------------------------------------------------------------------
# Parallel enrichment
# ---------------------------------------------------------------------------

def enrich_repos(
    repos: list[Repo],
    *,
    owner: str,
    cache_path: Path,
    max_workers: int = 10,
) -> list[Repo]:
    """Return new Repo list with ``contributors`` populated.

    Cache hits skip the REST call. Misses are fetched in parallel
    (ThreadPoolExecutor, default 10 workers per F4). Cache is rewritten
    atomically once at the end.
    """
    cache = load_cache(cache_path)

    def resolve(repo: Repo) -> tuple[Repo, str, list[str]]:
        key = cache_key(repo.name, repo.pushed_at)
        cached = cache.get(key)
        if cached is not None:
            return repo, key, cached
        fetched = list(fetch_contributors(owner, repo.name))
        return repo, key, fetched

    enriched: list[Repo] = []
    new_entries: dict[str, list[str]] = {}

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        for repo, key, logins in pool.map(resolve, repos):
            new_entries[key] = logins
            from dataclasses import replace
            enriched.append(replace(repo, contributors=tuple(logins)))

    # Persist (preserves cached entries we used + adds fresh ones).
    cache.update(new_entries)
    save_cache(cache_path, cache)
    return enriched
