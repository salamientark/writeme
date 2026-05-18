# Contributing

## Build & test

```bash
git clone https://github.com/salamientark/writeme
cd writeme/go

make build              # build binary
make test               # run tests
make test-race          # race detector
make lint vet           # lint + vet
make coverage-gate      # 80% coverage gate
make release-snapshot   # build release snapshot
```

## Run the binary directly

Skips the launcher sandbox; state falls back to `~/.cache/gh-readme-pipeline/`:

```bash
go run ./cmd/writeme --dry-run
```

## TUI smoke test

Run `--dry-run` against a test account; verify:

- arrows move the cursor, space toggles `[x]`, `a`/`n` bulk-select
- resize keeps the viewport coherent, `q` aborts cleanly
- on the review screen, scroll the diff and cycle accept/redo/discard

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean success — sandbox wiped. |
| `1` | Missing dep, gh auth, GraphQL/clone fatal, generic error. |
| `2` | Final scan found dirty tree or unpushed commits — sandbox preserved. |
| `3` | Launcher-only: checksum mismatch, no code executed. |
| `130` | Ctrl+C — state flushed, summary printed. |

## Full flag & env reference

| Flag | Env | Effect |
|------|-----|--------|
| `--mode pr\|direct\|commit-only` | — | Skip per-repo mode prompt. |
| `--dry-run` | — | Run full loop, never push. |
| `--repos-dir <path>` | `GH_README_REPOS_DIR` | Override repo-clone dir. |
| `--claude-timeout <sec>` | `CLAUDE_TIMEOUT` | Claude subprocess timeout (default 300). |
| `--resume` | — | Skip already-processed repos from state file. |
| `--skip-ci` | `SKIP_CI` | Append `[skip ci]` to commit message. |
| `--clean` | — | Remove cache dir and exit. |
| `--plain` | — | Disable TUI (plain-text mode). |
| `--parallel <n>` | `WRITEME_PARALLEL` | Parallel Claude workers (1–8, default 3). |
| `--version` | — | Print version and exit. |
| — | `LIMIT` | Repo cap (hard max 1000). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |

Launcher-only env vars: `NUKE_ON_FAIL=1` wipes sandbox on failure; `VERSION` selects binary version; `EXPECTED_SHA` pins checksum; `SKIP_DEP_CHECK=1` bypasses dep gating (testing only).
