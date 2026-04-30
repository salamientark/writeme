"""Safety primitives: input validation, repo cleanup, and advisory locking.

Addresses: C3 (repo name injection), C5 (shell=True prohibition),
           H5 (ensure_clean invariant), M4 (flock concurrency guard).
"""
import fcntl
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

_REPO_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')
_RESERVED_NAMES = frozenset({".", ".."})

# CR-MED-4: strict github URL match — no extra path, no query, no whitespace.
_HTTPS_URL_RE = re.compile(r'^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$')
_SSH_URL_RE = re.compile(r'^git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$')


def validate_repo_name(name: str) -> None:
    """Raise ValueError if *name* is not a safe, single-component repository name.

    Accepted: strings matching ``^[A-Za-z0-9._-]+$`` that are not ``.`` or ``..``.
    Rejected: empty strings, path separators, shell metacharacters, reserved names.
    """
    if not name:
        raise ValueError(f"repo name must not be empty")
    if name in _RESERVED_NAMES:
        raise ValueError(f"unsafe repo name (reserved): {name!r}")
    if not _REPO_NAME_RE.match(name):
        raise ValueError(f"unsafe repo name (invalid characters): {name!r}")


def validate_ssh_url(url: str) -> None:
    """Raise ValueError if *url* is not an allowed GitHub clone URL.

    Accepted:
    - ``git@github.com:<owner>/<repo>[.git]``
    - ``https://github.com/<owner>/<repo>``

    All other schemes, hosts, or injected flags are rejected.
    """
    if not url:
        raise ValueError("clone URL must not be empty")
    if _HTTPS_URL_RE.match(url) or _SSH_URL_RE.match(url):
        return
    raise ValueError(f"unexpected clone URL: {url!r}")


def ensure_clean(repo_dir: Path) -> None:
    """Reset *repo_dir* to a clean state, removing all local modifications.

    Steps:
    1. ``git reset --hard HEAD`` — restores tracked files to HEAD state.
    2. ``git clean -fd`` — removes untracked files and directories.
    3. Deletes ``MERGE_HEAD``, ``CHERRY_PICK_HEAD``, ``REBASE_HEAD`` if present,
       so git does not consider the repo mid-operation.

    All subprocess calls use list form with ``shell=False``.
    """
    subprocess.run(
        ["git", "reset", "--hard", "HEAD"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clean", "-fd"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
    )
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD"):
        (repo_dir / ".git" / marker).unlink(missing_ok=True)


@contextmanager
def acquire_lock(path: Path) -> Generator[None, None, None]:
    """Advisory exclusive lock on *path* using ``fcntl.flock``.

    Raises ``BlockingIOError`` immediately if another process holds the lock
    (``LOCK_NB`` — non-blocking). The lock file is created if it does not exist.
    The lock is released when the context exits, even if an exception is raised.

    Usage::

        with acquire_lock(Path("/run/myapp/lock")):
            do_work()
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()
