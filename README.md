# writeme

Interactive CLI to draft `README.md` files across all your GitHub repos using Claude Code's `/create-readme` skill — running in an **ephemeral sandbox** with zero persistent install.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Go](https://img.shields.io/badge/go-1.25%2B-00ADD8.svg)](https://go.dev/)
[![Claude Code](https://img.shields.io/badge/claude--code-required-8A2BE2.svg)](https://claude.com/claude-code)

Pick repos from a TUI, let Claude draft a README for each, review the diff, and ship via PR or direct commit. Nothing is written to your `$HOME` — the launcher runs from a `mktemp` sandbox and wipes itself on success.

## Features

- **TUI repo picker** — paginated list of all your repos (sorted by recent activity), with bulk select.
- **TUI review screen** — side-by-side diff, markdown preview, scroll, accept/redo/discard per repo.
- **Three ship modes** — `pr` (branch + `gh pr create`), `direct` (commit on default branch), or `commit-only`.
- **Blast-radius guard** — Claude is only allowed to touch `README.md`; any other modified file aborts the run.
- **Secret scanner** — flags AWS keys, GitHub tokens, OpenAI keys, and private-key headers in generated drafts.
- **Resumable** — `--resume` skips repos already processed in the state file.
- **Parallel generation** — configurable worker pool (`--parallel`) for concurrent Claude invocations.
- **SHA-pinned install** — `EXPECTED_SHA` verifies the binary checksum before any code runs.
- **Zero footprint** — single static binary, no runtime dependencies, no shell config touched.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/latest/install.sh | bash
```

> [!TIP]
> The `latest` branch always points at the most recent published release.
>
> For a specific version:
> ```bash
> VERSION=v1.0.0-go.1 \
>   curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/release/v1.0.0-go.1/install.sh | bash
> ```
>
> For maximum reproducibility, pin the SHA256 checksum:
> ```bash
> EXPECTED_SHA=<64-char-sha256> \
> VERSION=v1.0.0-go.1 \
>   curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/release/v1.0.0-go.1/install.sh | bash
> ```

The launcher checks dependencies, downloads the platform binary, verifies the checksum, runs the pipeline in a sandbox, and cleans up on exit.

## Requirements

| Tool | Purpose |
|------|---------|
| `bash` (>= 4) | Launcher shell |
| `git` | Clone target repos |
| `gh` (authenticated) | Repo listing (GraphQL), PR creation |
| `claude` | `/create-readme` skill execution |
| `curl` | Binary download |
| `tar` | Archive extraction |

Run `gh auth login` first if `gh auth status` fails.

> The `writeme` binary itself is a standalone Go executable — no Python, uv, or runtime needed.

## Usage

```
writeme [FLAGS]
```

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
| `--parallel <n>` | `WRITEME_PARALLEL` | Number of parallel Claude workers (1–8, default 3). |
| `--version` | — | Print version and exit. |
| — | `LIMIT` | Repo cap (hard max 1000). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |

Launcher-only env vars: `NUKE_ON_FAIL=1` wipes sandbox on failure; `VERSION` selects binary version; `EXPECTED_SHA` pins checksum; `SKIP_DEP_CHECK=1` bypasses dep gating (testing only).

### TUI controls

**Selection screen:**

```
↑/↓  move        space  toggle        a  all
n    none        enter  confirm       q  quit
/    filter      esc   clear filter
```

Header shows `(N selected of M)`. Each row: `[x] [HAS README] <name>  <pushed_at>`.

**Review screen:**

```
a/d        accept / discard
r          redo (re-generate)
q          quit
↑/↓        scroll diff
```

## Per-repo pipeline

For each selected repo:

1. **Clone** — `git clone --depth 1 --filter=blob:none` into `$GH_README_REPOS_DIR/<name>/`.
2. **Generate** — `claude /create-readme` with timeout. Output captured to `run.log`.
3. **Blast-radius guard** — `git status --porcelain` must show only `README.md`. Anything else → abort, mark `failed`, restore baseline.
4. **Secret scan** — flagged drafts require typed `yes-i-checked` to override.
5. **Review** — TUI or plain-text: `accept / redo / discard / quit`. Overwriting an existing README requires typed `yes`.
6. **Ship** — `pr` (branch + push + PR), `direct` (commit on default branch), `commit-only`, or `skip`.

Verb is chosen automatically: `add` if no prior README, `update` otherwise.

## Storage layout

Inside the sandbox (default):

| Path | Contents |
|------|----------|
| `$WORKDIR/repo/<name>/` | Target-repo clones |
| `$WORKDIR/state/state-<user>.jsonl` | Resume + summary records |
| `$WORKDIR/state/lock` | flock — one run at a time |
| `$WORKDIR/cache/` | Contributor cache |

Outside the launcher (direct binary invocation), paths fall back to `${XDG_CACHE_HOME:-~/.cache}/gh-readme-pipeline/` and state lives under `${XDG_CACHE_HOME:-~/.cache}/gh-readme-pipeline/state/`.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean success — sandbox wiped. |
| `1` | Missing dep, gh auth, GraphQL/clone fatal, generic error. |
| `2` | Final scan found dirty tree or unpushed commits — sandbox preserved. |
| `3` | Launcher-only: checksum mismatch, no code executed. |
| `130` | Ctrl+C — state flushed, summary printed. |

## Security

> [!IMPORTANT]
> Always review the generated diff before accepting. The secret scanner is best-effort, not authoritative.

- All subprocess calls use list form, no string interpolation.
- Repo names validated `^[A-Za-z0-9._-]+$`; clone URLs restricted to `git@github.com:` or `https://github.com/`.
- Blast-radius guard prevents Claude from touching anything except `README.md`.
- Checksum pinning protects against binary tampering. Verify `EXPECTED_SHA` out-of-band against the release checksums.

## Development

```bash
git clone https://github.com/salamientark/writeme
cd writeme/go

# Build
make build

# Run tests
make test
make test-race

# Lint + vet
make lint
make vet

# Coverage gate (80% min)
make coverage-gate

# Build release snapshot
make release-snapshot
```

Run the binary directly (skips the launcher sandbox):

```bash
go run ./cmd/writeme --dry-run
```

State falls back to `~/.cache/gh-readme-pipeline/`.

### TUI smoke test

1. `go run ./cmd/writeme --dry-run` against a test account.
2. Verify arrows move the cursor, space toggles `[x]`, `a`/`n` bulk-select, resize keeps the viewport coherent, `q` aborts cleanly.
3. On the review screen: scroll diff, accept/redo/discard cycle.

## Troubleshooting

- **Sandbox preserved after failure** — stderr prints `kept /tmp/writeme.XXXXXX (exit=N)`. Inspect, then `rm -rf` manually.
- **Checksum mismatch** — the downloaded binary doesn't match `EXPECTED_SHA`. Verify the SHA256 against the release page.
- **`gh auth: not authenticated`** — run `gh auth login`, retry.
- **Stuck lock** — another process holds `$XDG_CACHE_HOME/gh-readme-pipeline/state/lock`. Identify with `fuser`; remove only if no live pipeline.
- **Rate-limited** — GraphQL `remaining < 10` triggers a sleep up to 60s; longer waits abort. Wait for `resetAt` and re-run.
