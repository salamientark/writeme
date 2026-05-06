<!-- Generated: 2026-05-06 | Files scanned: 4 | Token estimate: ~350 -->

# Dependencies

## Runtime

| Dep | Version | Why |
|-----|---------|-----|
| Python | >=3.11 | declared in script header (`# /// script`) |
| rich | >=13.7.0 | only PyPI dep — TUI rendering (`src/ui/rich_ui.py`) |
| uv | any recent | runs the inline-script header |
| git | any | clone/commit/push |
| gh | any | auth, GraphQL repo list, PR creation |
| claude | Claude Code CLI | drafts README via `/create-readme` skill |

Stdlib only inside `src/`: `argparse, json, os, shutil, signal, subprocess, sys, pathlib, fcntl, termios, tty, select, dataclasses, typing, contextlib, re, difflib, textwrap`.

No HTTP libs — all network via `gh` subprocess. No DB driver.

## Install / launch
- `install.sh` — bash, validates REF regex, verifies `EXPECTED_SHA`, creates `mktemp` sandbox, invokes `uv run gh_readme_pipeline.py`.
- CI installs uv via `astral-sh/setup-uv@v3` (mem 1719).

## External services

| Service | Used for | Module |
|---------|----------|--------|
| GitHub GraphQL | repo listing, rate limit | `src/fetch.py` |
| GitHub REST (via gh) | PR creation, user lookup | `src/commit.py`, pipeline |
| Claude Code CLI | README generation | `src/review.py` |

## Test deps
- `pytest` (per `tests/`) — see `test_*.py`. No mocks for git/gh outside of subprocess monkeypatching.

## Skill payload
`/create-readme` skill copied into target repo `.claude/skills/` during `_stage_skill`, removed in `_unstage_skill`. Source under `docs/superpowers/` and project tree.
