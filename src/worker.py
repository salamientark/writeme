"""Parallel WorkerPool for README generation.

Plan: parallel-readme-and-solo-filter Phase 2 (P1, P2, P5, P10).

Wraps ``concurrent.futures.ThreadPoolExecutor`` with two extras:

* a FIFO completion iterator (yields results in the order they finish), and
* a ``drain()`` switch that prevents not-yet-started jobs from running.

Each worker invokes a caller-supplied ``generate_fn(repo) -> Any`` that does
the slow work (clone + claude). Exceptions are converted to
``("failed", str(exc))`` so a single bad repo never poisons the queue.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterator

from src.selection import Repo

MAX_PARALLEL_CAP = 8


class WorkerPool:
    def __init__(
        self,
        max_workers: int,
        generate_fn: Callable[[Repo], Any],
    ) -> None:
        self.max_workers = max(1, min(int(max_workers), MAX_PARALLEL_CAP))
        self._fn = generate_fn
        self._exec: ThreadPoolExecutor | None = None
        self._futures: list[Future] = []
        self._draining = threading.Event()
        self._submitted = False

    def submit_all(self, repos: list[Repo]) -> None:
        """Submit one job per repo. Idempotent — extra calls do nothing."""
        if self._submitted:
            return
        self._submitted = True
        if not repos:
            return
        self._exec = ThreadPoolExecutor(max_workers=self.max_workers)
        for repo in repos:
            self._futures.append(self._exec.submit(self._run, repo))

    def _run(self, repo: Repo) -> Any:
        if self._draining.is_set():
            return ("drained", repo.name)
        try:
            return self._fn(repo)
        except Exception as exc:  # noqa: BLE001 — isolate worker failures
            return ("failed", f"{type(exc).__name__}: {exc}")

    def completed(self) -> Iterator[Any]:
        """Yield results in completion (FIFO) order, then shut down the pool."""
        if not self._futures:
            return
        try:
            for fut in as_completed(self._futures):
                if fut.cancelled():
                    continue
                try:
                    result = fut.result()
                except Exception as exc:  # noqa: BLE001
                    yield ("failed", f"{type(exc).__name__}: {exc}")
                    continue
                if isinstance(result, tuple) and result and result[0] == "drained":
                    continue
                yield result
        finally:
            if self._exec is not None:
                self._exec.shutdown(wait=False, cancel_futures=True)

    def drain(self) -> None:
        """Stop scheduling new jobs; in-flight ones finish."""
        self._draining.set()
        # Best-effort cancel of unscheduled futures.
        for fut in self._futures:
            if not fut.running() and not fut.done():
                fut.cancel()
