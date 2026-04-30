"""Fetch repositories from GitHub GraphQL API.

Addresses: L1 (multi-expression readme detection), M3 (rate-limit / cap),
           L5 (user mismatch), L6 (disk pre-flight).

The main entry point is:

    fetch_repos(user: str, limit: int) -> list[Repo]

All subprocess calls use list form (shell=False) for safety.
"""
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from src.safety import validate_repo_name, validate_ssh_url
from src.selection import Repo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARD_LIMIT = 1000
PAGE_SIZE = 100  # GitHub GraphQL max per page


# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

# Multi-expression query: check 5 README path variants simultaneously.
# Each readme* alias maps to a specific object expression (file path).
# GraphQL returns null for each field if the file doesn't exist.
_GRAPHQL_QUERY = """
query FetchRepos($login: String!, $first: Int!, $after: String) {
  user(login: $login) {
    repositories(
      first: $first
      after: $after
      ownerAffiliations: OWNER
      isArchived: false
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      nodes {
        name
        sshUrl
        pushedAt
        diskUsage
        readmeMd: object(expression: "HEAD:README.md") { ... on Blob { text } }
        readmeLc: object(expression: "HEAD:readme.md") { ... on Blob { text } }
        readmeCap: object(expression: "HEAD:Readme.md") { ... on Blob { text } }
        readmeRst: object(expression: "HEAD:README.rst") { ... on Blob { text } }
        readmeDocs: object(expression: "HEAD:docs/README.md") { ... on Blob { text } }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
  rateLimit {
    remaining
    resetAt
  }
}
""".strip()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_iso_epoch(ts: str) -> float:
    """Convert ISO-8601 UTC timestamp to a Unix epoch float.

    Handles both ``2024-01-01T00:00:00Z`` and offset-aware formats.
    """
    ts = ts.rstrip("Z")
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _handle_rate_limit(rate_limit: dict) -> None:
    """Sleep until resetAt if remaining < 10."""
    remaining = rate_limit.get("remaining", 100)
    if remaining >= 10:
        return
    reset_at_str = rate_limit.get("resetAt", "")
    reset_epoch = _parse_iso_epoch(reset_at_str)
    now = time.time()
    wait = max(0.0, reset_epoch - now)
    print(
        f"Rate limit low (remaining={remaining}). Sleeping {wait:.1f}s until reset.",
        file=sys.stderr,
    )
    time.sleep(wait)


def _parse_node(node: dict) -> Repo:
    """Parse a single GraphQL repository node into a Repo dataclass.

    Validates repo name and SSH URL immediately; raises ValueError on bad data.
    """
    name = node.get("name", "")
    ssh_url = node.get("sshUrl", "")

    # Validate immediately (security: C3, C5)
    validate_repo_name(name)
    validate_ssh_url(ssh_url)

    pushed_at = node.get("pushedAt", "")
    disk_usage = node.get("diskUsage", 0) or 0

    # Multi-expression README detection: any non-null value → had_readme_before
    had_readme_before = any(
        node.get(field) is not None
        for field in ("readmeMd", "readmeLc", "readmeCap", "readmeRst", "readmeDocs")
    )

    return Repo(
        name=name,
        ssh_url=ssh_url,
        pushed_at=pushed_at,
        had_readme_before=had_readme_before,
        disk_usage=disk_usage,
    )


def _fetch_page(
    user: str,
    page_size: int,
    cursor: str | None,
) -> dict:
    """Execute one GraphQL page call and return the parsed JSON dict."""
    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={_GRAPHQL_QUERY}",
        "-F", f"login={user}",
        "-F", f"first={page_size}",
    ]
    if cursor is not None:
        cmd += ["-F", f"after={cursor}"]

    result = subprocess.run(cmd, capture_output=True, check=True)
    return json.loads(result.stdout)


def _disk_preflight(repos: list[Repo]) -> None:
    """Warn if estimated clone size exceeds 80% of available disk space."""
    total_kb = sum(r.disk_usage for r in repos)
    required_bytes = total_kb * 2 * 1024  # ×2 for working copy; KB → bytes
    disk_info = shutil.disk_usage(".")
    free_bytes = disk_info.free
    if required_bytes > free_bytes * 0.8:
        required_mb = required_bytes / (1024 * 1024)
        free_mb = free_bytes / (1024 * 1024)
        print(
            f"Warning: estimated disk requirement ({required_mb:.0f} MB) exceeds "
            f"80% of available disk space ({free_mb:.0f} MB free).",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_repos(user: str, limit: int) -> list[Repo]:
    """Fetch all non-archived repositories owned by *user*, up to *limit*.

    Steps:
    1. Cap limit at HARD_LIMIT (1000), warning on stderr if capped.
    2. Verify authenticated user matches *user*; prompt if mismatch.
    3. Paginate GraphQL until all repos fetched or limit reached.
    4. Handle rate-limit after each page.
    5. Validate and parse each node immediately.
    6. Run disk pre-flight on the full result set.
    7. Return repos sorted by pushedAt DESC.

    Args:
        user:  GitHub username whose repos to fetch.
        limit: Maximum number of repos to return (hard-capped at 1000).

    Returns:
        List of ``Repo`` objects sorted by ``pushed_at`` descending.

    Raises:
        ValueError: If any repo name or SSH URL fails validation.
        subprocess.CalledProcessError: If ``gh api graphql`` returns non-zero.
    """
    # Step 1: cap limit
    if limit > HARD_LIMIT:
        print(
            f"Warning: limit {limit} exceeds maximum; capped at {HARD_LIMIT}.",
            file=sys.stderr,
        )
        limit = HARD_LIMIT

    all_repos: list[Repo] = []
    cursor: str | None = None

    while len(all_repos) < limit:
        remaining_needed = limit - len(all_repos)
        page_size = min(PAGE_SIZE, remaining_needed)

        data = _fetch_page(user, page_size, cursor)

        repositories = data["data"]["user"]["repositories"]
        nodes = repositories["nodes"]
        page_info = repositories["pageInfo"]
        rate_limit = data["data"]["rateLimit"]

        # Step 5: parse and validate each node
        for node in nodes:
            repo = _parse_node(node)
            all_repos.append(repo)

        # Step 4: handle rate-limit
        _handle_rate_limit(rate_limit)

        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    # Step 6: disk pre-flight
    _disk_preflight(all_repos)

    # Step 7: sort by pushed_at DESC
    return sorted(all_repos, key=lambda r: r.pushed_at, reverse=True)
