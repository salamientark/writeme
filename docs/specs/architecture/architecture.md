<!-- Generated: 2026-05-06 | Files scanned: 18 | Token estimate: ~700 -->

# Architecture

Single-binary Python CLI. Entry: `gh_readme_pipeline.py` (uv inline-script header). Imports `src/` package lazily inside functions to keep cold-start cheap.

## Project type
CLI tool, no server, no DB. Persistent state = JSON in XDG dirs. Ephemeral sandbox install via `install.sh`.

## Top-level flow
```
parse_args → _resolve_user → fetch_repos (gh GraphQL)
  → make_ui → SelectionState (TUI pick)
    → for repo: _clone_or_fetch → process_repo
        → review_loop (claude subprocess, diff, secrets)
        → commit_and_push (pr | direct | commit-only)
  → _print_summary  → StateStore.save
```

## Module boundaries
| Layer | Module | Role |
|-------|--------|------|
| Entry | `gh_readme_pipeline.py` | argparse, orchestration, per-repo loop |
| Data  | `src/fetch.py`           | GitHub GraphQL + rate-limit + disk preflight |
| Data  | `src/state.py`           | XDG paths, `StateStore` JSON persistence |
| Domain| `src/selection.py`       | `Repo`, `SelectionState` (filter/jump/page) |
| Domain| `src/review.py`          | claude invocation, blast-radius, diff, prompts |
| Domain| `src/commit.py`          | git/gh wrappers, PR/direct/commit-only modes |
| Safety| `src/safety.py`          | repo-name + ssh-url validation, lock, clean check |
| Safety| `src/secrets.py`         | secret regex scan, risky-file scan |
| Safety| `src/unpushed.py`        | warn on dirty/unpushed cache repos |
| UI    | `src/ui/`                | `protocol.UI` + `RichUI`/`PlainUI` (`make_ui` TTY-aware factory); helpers: `diff`, `keys`, `logo`, `range_parser` |

## Sandbox / install
`install.sh` → `mktemp` dir → `EXPECTED_SHA` verify → `uv run gh_readme_pipeline.py`. No HOME pollution.

## External processes
- `gh` CLI (auth + GraphQL + PR creation)
- `git` (clone, status, commit, push)
- `claude` (subprocess; env scrubbed via `_scrub_env_for_claude`)
- `uv` (script runner)
