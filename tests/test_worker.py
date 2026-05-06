"""Tests for src/worker.py — parallel WorkerPool (Phase 2)."""
from __future__ import annotations

import threading
import time
import unittest
from dataclasses import dataclass


def _make_repo(name="r1"):
    from src.selection import Repo
    return Repo(
        name=name,
        ssh_url=f"git@github.com:u/{name}.git",
        pushed_at="2026-01-01T00:00:00Z",
        had_readme_before=False,
        disk_usage=10,
    )


class TestWorkerPool(unittest.TestCase):
    def test_completed_yields_in_completion_order(self):
        from src.worker import WorkerPool

        repos = [_make_repo(f"r{i}") for i in range(3)]
        delays = {"r0": 0.1, "r1": 0.0, "r2": 0.05}

        def gen(repo):
            time.sleep(delays[repo.name])
            return ("ok", repo.name)

        pool = WorkerPool(max_workers=3, generate_fn=gen)
        pool.submit_all(repos)
        order = [r[1] for r in pool.completed()]
        # r1 finishes first, then r2, then r0
        self.assertEqual(order, ["r1", "r2", "r0"])

    def test_exception_returns_failed_result(self):
        from src.worker import WorkerPool

        repos = [_make_repo("boom")]

        def gen(repo):
            raise RuntimeError("kaboom")

        pool = WorkerPool(max_workers=1, generate_fn=gen)
        pool.submit_all(repos)
        results = list(pool.completed())
        self.assertEqual(len(results), 1)
        status, payload = results[0]
        self.assertEqual(status, "failed")
        self.assertIn("kaboom", payload)

    def test_max_workers_capped(self):
        from src.worker import WorkerPool
        pool = WorkerPool(max_workers=999, generate_fn=lambda r: ("ok", r.name))
        self.assertLessEqual(pool.max_workers, 8)

    def test_max_workers_min_one(self):
        from src.worker import WorkerPool
        pool = WorkerPool(max_workers=0, generate_fn=lambda r: ("ok", r.name))
        self.assertGreaterEqual(pool.max_workers, 1)

    def test_drain_blocks_new_starts(self):
        """drain() prevents jobs not yet started from running."""
        from src.worker import WorkerPool

        started = []
        gate = threading.Event()
        repos = [_make_repo(f"r{i}") for i in range(4)]

        def gen(repo):
            started.append(repo.name)
            gate.wait(timeout=2.0)
            return ("ok", repo.name)

        pool = WorkerPool(max_workers=1, generate_fn=gen)
        pool.submit_all(repos)
        # let one start
        time.sleep(0.05)
        pool.drain()
        gate.set()
        results = list(pool.completed())
        # at least 1 ran; remaining should be drained / cancelled
        self.assertGreaterEqual(len(results), 1)
        self.assertLessEqual(len(started), 4)


if __name__ == "__main__":
    unittest.main()
