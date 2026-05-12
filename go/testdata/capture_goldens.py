#!/usr/bin/env python3
"""Capture byte-exact goldens from Python implementation.

Decisions ref: D6. Records a deterministic StateStore sequence with frozen
timestamps, then prints the summary block via the Python pipeline's
_print_summary path. Outputs:

    go/internal/state/testdata/golden/state-testuser.jsonl
    go/internal/pipeline/testdata/golden/summary.txt

Re-run via: make golden-update (from go/).
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src import state as state_mod  # noqa: E402
from gh_readme_pipeline import _print_summary  # noqa: E402

GOLDEN_STATE = REPO_ROOT / "go/internal/state/testdata/golden/state-testuser.jsonl"
GOLDEN_SUMMARY = REPO_ROOT / "go/internal/pipeline/testdata/golden/summary.txt"

# Deterministic clock: each call to datetime.now() returns FROZEN_TS.
FROZEN_TS = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D401
        return FROZEN_TS if tz is None else FROZEN_TS.astimezone(tz)


def main() -> int:
    GOLDEN_STATE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_SUMMARY.parent.mkdir(parents=True, exist_ok=True)

    if GOLDEN_STATE.exists():
        GOLDEN_STATE.unlink()

    state_dir = GOLDEN_STATE.parent
    # StateStore writes to <state_dir>/state-<user>.jsonl directly.
    with patch.object(state_mod, "datetime", _FrozenDatetime):
        store = state_mod.StateStore("testuser", state_dir=state_dir)
        store.record("alpha-repo", "pr_opened", mode="pr",
                     pr_url="https://github.com/testuser/alpha-repo/pull/1")
        store.record("beta-repo", "pushed", mode="direct")
        store.record("gamma-repo", "commit_only", mode="commit_only")
        store.record("delta-repo", "skipped")
        store.record("epsilon-repo", "failed", error="claude timeout")

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_summary(store)
    GOLDEN_SUMMARY.write_text(buf.getvalue(), encoding="utf-8")

    print(f"wrote {GOLDEN_STATE.relative_to(REPO_ROOT)}")
    print(f"wrote {GOLDEN_SUMMARY.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
