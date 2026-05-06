"""Storage paths and state persistence for gh-readme-pipeline.

Addresses: H1 (resume), H7 (summary aggregation), M2 (XDG paths).

Public API:
    xdg_cache_dir() -> Path
    xdg_state_dir() -> Path
    StateStore(user, state_dir=None)
        .record(repo_name, status, mode=None, error=None, pr_url=None)
        .load_processed() -> set[str]
        .summary() -> dict
    prompt_resume(processed_count: int) -> str
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

# RT-L1: GitHub username regex (1-39 chars, alnum or hyphen, no leading/trailing/double hyphen).
_GH_USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


# ---------------------------------------------------------------------------
# XDG path helpers
# ---------------------------------------------------------------------------

APP_NAME = "gh-readme-pipeline"

_PROCESSED_STATUSES = frozenset({"pushed", "pr_opened", "commit_only"})


def xdg_cache_dir() -> Path:
    """Return the application cache directory, honoring XDG_CACHE_HOME.

    Falls back to ``~/.cache/gh-readme-pipeline`` if XDG_CACHE_HOME is unset.
    The directory is NOT created; callers are responsible for mkdir.
    """
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".cache" / APP_NAME


def xdg_state_dir() -> Path:
    """Return the application state directory, honoring XDG_STATE_HOME.

    Falls back to ``~/.local/state/gh-readme-pipeline`` if XDG_STATE_HOME
    is unset.  The directory is NOT created; callers are responsible for mkdir.
    """
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "state" / APP_NAME


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class StateStore:
    """Append-only JSONL state file for tracking processed repositories.

    Each call to ``record()`` appends one line.  ``load_processed()`` and
    ``summary()`` scan the whole file on each call (file is ≤1000 lines).

    Args:
        user:       GitHub username — used as part of the state filename.
        state_dir:  Directory for the state file.  Defaults to
                    ``xdg_state_dir()``.  Useful for testing.
    """

    def __init__(self, user: str, state_dir: Path | None = None) -> None:
        # RT-L1: validate GH username — prevents path traversal via state filename.
        if not _GH_USER_RE.match(user):
            raise ValueError(f"invalid GitHub username: {user!r}")
        self._user = user
        self._state_dir = state_dir if state_dir is not None else xdg_state_dir()
        self._state_file = self._state_dir / f"state-{user}.jsonl"
        # P8: serialise writes within a process; parallel WorkerPool threads
        # call record() concurrently.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        repo_name: str,
        status: str,
        mode: str | None = None,
        error: str | None = None,
        pr_url: str | None = None,
    ) -> None:
        """Append one record to the state file.

        The record is a JSON object with at minimum ``repo``, ``status``, and
        ``ts`` fields.  Optional fields (``mode``, ``error``, ``pr_url``) are
        included only when non-None.

        The file is opened in append mode and flushed after each write to
        ensure atomicity on a single line.
        """
        entry: dict = {
            "repo": repo_name,
            "status": status,
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }
        if mode is not None:
            entry["mode"] = mode
        if error is not None:
            entry["error"] = error
        if pr_url is not None:
            entry["pr_url"] = pr_url

        self._state_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._state_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
                fh.flush()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def has_prior_state(self) -> bool:
        """Return True if the state file exists on disk (CR-LOW-1)."""
        return self._state_file.exists()

    def _read_all(self) -> list[dict]:
        """Return all records from the state file; empty list if no file."""
        if not self._state_file.exists():
            return []
        records = []
        with self._state_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # skip malformed lines
        return records

    def load_processed(self) -> set[str]:
        """Return the set of repo names that completed successfully.

        A repo is considered processed if its last recorded status is one of:
        ``pushed``, ``pr_opened``, ``commit_only``.

        Duplicate records for the same repo are deduplicated (set semantics).
        """
        return {
            record["repo"]
            for record in self._read_all()
            if record.get("status") in _PROCESSED_STATUSES
        }

    def summary(self) -> dict:
        """Return an aggregation dict with:

        - Per-status counts (keys are status strings, values are int counts).
        - ``pr_urls``:      list of PR URLs for ``pr_opened`` records.
        - ``failed_repos``: list of repo names with ``failed`` status.
        """
        records = self._read_all()
        counts: dict[str, int] = {}
        pr_urls: list[str] = []
        failed_repos: list[str] = []

        for rec in records:
            status = rec.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
            if status == "pr_opened" and rec.get("pr_url"):
                pr_urls.append(rec["pr_url"])
            if status == "failed":
                failed_repos.append(rec["repo"])

        return {
            **counts,
            "pr_urls": pr_urls,
            "failed_repos": failed_repos,
        }


# ---------------------------------------------------------------------------
# Resume prompt
# ---------------------------------------------------------------------------

_RESUME_CHOICES = {
    "r": "resume",
    "a": "all",
    "s": "fresh",
    "q": "quit",
}


def prompt_resume(processed_count: int) -> str:
    """Prompt the user for how to handle a prior state file.

    Displays the number of already-processed repos and asks:
        [r]esume (skip processed)
        [a]ll incl. failed
        [s]tart fresh
        [q]uit

    Re-prompts on invalid input until a valid choice is entered.

    Returns one of: ``"resume"``, ``"all"``, ``"fresh"``, ``"quit"``.
    """
    prompt_text = (
        f"Found {processed_count} repos already processed. "
        f"[r]esume (skip processed) / [a]ll incl. failed / "
        f"[s]tart fresh / [q]uit: "
    )
    while True:
        raw = input(prompt_text).strip().lower()
        if raw in _RESUME_CHOICES:
            return _RESUME_CHOICES[raw]
        # Invalid input: loop and re-prompt
