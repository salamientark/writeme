# writeme

Interactive CLI to draft `README.md` files across all your GitHub repos using Claude Code's `/create-readme` skill — running in an **ephemeral sandbox** with zero persistent install.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/claude--code-required-8A2BE2.svg)](https://claude.com/claude-code)

Pick repos from a TUI, let Claude draft a README for each, review the diff, and ship via PR or direct commit. Nothing is written to your `$HOME` — the launcher runs from a `mktemp` sandbox and wipes itself on success.

## Features

- **TUI repo picker** — paginated list of all your repos (sorted by recent activity), with bulk select.
- **Per-repo review loop** — `accept / redo / discard / view / quit` before any push.
- **Three ship modes** — `pr` (branch + `gh pr create`), `direct` (commit on default branch), or `commit-only`.
- **Blast-radius guard** — Claude is only allowed to touch `README.md`; any other modified file aborts the run.
- **Secret scanner** — flags AWS keys, GitHub tokens, OpenAI keys, and private-key headers in generated drafts.
- **Resumable** — `--resume` skips repos already processed in the state file.
- **SHA-pinned install** — `EXPECTED_SHA` rejects mutated refs before any code runs.
- **Zero footprint** — no `~/.local/bin`, no `PATH` mutation, no shell config touched.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/main/install.sh | bash
```

> [!TIP]
> For reproducible installs, pin a commit:
> ```bash
> EXPECTED_SHA=<40-char-sha> \
>   curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/<sha>/install.sh | bash
> ```
> SHA mismatch → exit `3` before any code runs.

The launcher checks dependencies, clones a pinned commit into a fresh sandbox, sets `XDG_*` to sandbox subdirs, runs the pipeline, and cleans up on exit.

## Requirements

| Tool | Purpose |
|------|---------|
| `bash` (>= 4) | Launcher shell |
| `git` | Clone the program + target repos |
| `gh` (authenticated) | Repo listing (GraphQL), PR creation |
| `claude` | `/create-readme` skill execution |
| `python` (>= 3.11) | Pipeline runtime |
| `uv` | Python script runner |

Run `gh auth login` first if `gh auth status` fails.

## Usage

```
uv run gh_readme_pipeline.py [FLAGS]
```

| Flag | Env | Effect |
|------|-----|--------|
| `--mode pr\|direct\|commit-only` | — | Skip per-repo mode prompt. |
| `--dry-run` | — | Run full loop, never push. |
| `--repos-dir <path>` | `GH_README_REPOS_DIR` | Override repo-clone dir. |
| `--claude-timeout <sec>` | `CLAUDE_TIMEOUT` | Claude subprocess timeout (default 300). |
| `--resume` | — | Skip already-processed repos from state file. |
| `--skip-ci` | `SKIP_CI` | Append `[skip ci]` to commit message. |
| — | `LIMIT` | Repo cap (hard max 1000). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |

Launcher-only env vars: `NUKE_ON_FAIL=1` wipes sandbox on failure; `REPO_URL`/`REF` override program source; `EXPECTED_SHA` pins commit; `SKIP_DEP_CHECK=1` bypasses dep gating (testing only).

### TUI controls

```
↑/↓  move        space  toggle        a  all
n    none        enter  confirm       q  quit
```

Header shows `(N selected of M)`. Each row: `[x] [HAS README] <name>  <pushed_at>`.

## Per-repo pipeline

For each selected repo:

1. **Clone** — `git clone --depth 1 --filter=blob:none` into `$GH_README_REPOS_DIR/<name>/`.
2. **Generate** — `claude /create-readme` with timeout. Output captured to `run.log`.
3. **Blast-radius guard** — `git status --porcelain` must show only `README.md`. Anything else → abort, mark `failed`, restore baseline.
4. **Secret scan** — flagged drafts require typed `yes-i-checked` to override.
5. **Review** — `accept / redo / discard / view / quit`. Overwriting an existing README requires typed `yes`.
6. **Ship** — `pr` (branch + push + PR), `direct` (commit on default branch), `commit-only`, or `skip`.

Verb is chosen automatically: `add` if no prior README, `update` otherwise.

## Storage layout

Inside the sandbox (default):

| Path | Contents |
|------|----------|
| `$WORKDIR/repo/<name>/` | Target-repo clones |
| `$WORKDIR/state/gh-readme-pipeline/state-<user>.jsonl` | Resume + summary records |
| `$WORKDIR/state/gh-readme-pipeline/lock` | flock — one run at a time |
| `$WORKDIR/cache/` | Reserved for future use |

Outside the launcher (direct dev invocation), paths fall back to `${XDG_STATE_HOME:-~/.local/state}` and `${XDG_CACHE_HOME:-~/.cache}`. `--resume` is meaningful only across direct invocations or when a failed launcher run preserved the sandbox — clean launcher runs always start fresh.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean success — sandbox wiped. |
| `1` | Missing dep, gh auth, GraphQL/clone fatal, generic error. |
| `2` | Final scan found dirty tree or unpushed commits — sandbox preserved. |
| `3` | Launcher-only: `EXPECTED_SHA` mismatch, no code executed. |
| `130` | Ctrl+C — state flushed, summary printed. |

## Security

> [!IMPORTANT]
> Always review the generated diff before accepting. The secret scanner is best-effort, not authoritative.

- All `subprocess` calls use list form, `shell=False`. No string interpolation.
- Repo names validated `^[A-Za-z0-9._-]+$`; clone URLs restricted to `git@github.com:` or `https://github.com/`.
- Blast-radius guard prevents Claude from touching anything except `README.md`.
- SHA pinning protects against ref-mutation, **not** against repo takeover. Verify `EXPECTED_SHA` out-of-band against a release tag.

## Development

```bash
git clone https://github.com/salamientark/writeme
cd writeme
python -m unittest discover -s tests
```

Run the pipeline directly (skips the launcher sandbox):

```bash
uv run gh_readme_pipeline.py --dry-run
```

State falls back to `~/.local/state/gh-readme-pipeline/` and `~/.cache/`.

### TUI smoke test

1. `uv run gh_readme_pipeline.py --dry-run` against a test account.
2. Verify arrows move the cursor, space toggles `[x]`, `a`/`n` bulk-select, resize keeps the viewport coherent, `q` aborts cleanly.

## Troubleshooting

- **Sandbox preserved after failure** — stderr prints `kept /tmp/writeme.XXXXXX (exit=N)`. Inspect, then `rm -rf` manually.
- **`SHA pin mismatch`** — the pinned commit is not fetchable from `REPO_URL`. Verify the SHA matches the release tag.
- **`gh auth: not authenticated`** — run `gh auth login`, retry.
- **Stuck lock** — another process holds `$XDG_STATE_HOME/gh-readme-pipeline/lock`. Identify with `fuser`; remove only if no live pipeline.
- **Rate-limited** — GraphQL `remaining < 10` triggers a sleep up to 60s; longer waits abort. Wait for `resetAt` and re-run.
