# gh-readme-pipeline

Interactive CLI to draft `README.md` files for your GitHub repos via Claude Code's
`/create-readme` skill. Runs in an **ephemeral sandbox** — no persistent install.

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/jiliac/github-readme-pipeline/main/install.sh | bash
```

`install.sh` is a launcher, not an installer. It:

1. Creates a unique sandbox under `$TMPDIR` via `mktemp -d -t writeme.XXXXXX`.
2. Clones a pinned commit of this repo into the sandbox.
3. Sets `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `GH_README_REPOS_DIR` to sandbox subdirs.
4. Execs `python gh_readme_pipeline.py "$@"`.
5. On clean exit (`0`), wipes the sandbox; on failure, preserves it for debugging.

Nothing is written to `~/.local/bin/`, `PATH` is not modified, no shell config touched.

### Verified install (recommended)

Pin a specific commit:

```bash
EXPECTED_SHA=<40-char-sha> \
  curl -fsSL https://raw.githubusercontent.com/jiliac/github-readme-pipeline/<sha>/install.sh | bash
```

Mismatch → exit `3` before any code runs.

## Dependencies

Checked by `install.sh` at startup; missing one → exit `1` with install hint.

| Tool | Purpose |
|------|---------|
| `bash` (>= 4) | Launcher shell |
| `git` | Clone program + target repos |
| `gh` (authenticated) | GraphQL repo list, PR creation |
| `claude` | `/create-readme` skill execution |
| `python` (>= 3.11) | Pipeline runtime |
| `uv` | Python script runner |
| `mktemp`, `rm` | Sandbox lifecycle |

`gh auth status` must succeed. Run `gh auth login` if not.

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
| — | `LIMIT` | Repo cap (hard-capped at 1000). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |

Launcher-only env vars: `NUKE_ON_FAIL=1` wipes sandbox on failure;
`REPO_URL` / `REF` override program source; `EXPECTED_SHA` pins commit;
`SKIP_DEP_CHECK=1` bypasses dep gating (testing only).

## TUI Controls

```
↑/↓  move        space  toggle        a  all
n    none        enter  confirm       q  quit
```

Header shows `(N selected of M)`. Each row: `[x] [HAS README] <name>  <pushed_at>`.

## Per-Repo Pipeline

For each selected repo:

1. Clone (`git clone --depth 1 --filter=blob:none`) into `$GH_README_REPOS_DIR/<name>/`.
2. Run `claude /create-readme` with timeout. Output captured to `run.log`.
3. **Blast-radius guard:** `git status --porcelain` must show only `README.md`. Any
   other touched file → abort, mark `failed`, restore baseline.
4. **Secret scan:** generated README scanned for AWS keys, GitHub tokens, OpenAI
   keys, private-key headers, generic `api_key=` patterns. Match → force discard
   or typed `yes-i-checked` override.
5. **Review prompt:** `accept / redo / discard / view / quit`. If repo had a prior
   README, accept requires typed `yes`.
6. **Commit & push:** mode `pr` (branch + push + `gh pr create`), `direct`
   (commit on default branch), `commit-only` (no push), or `skip`.

Verb chosen automatically: `add` if no prior README, `update` if prior.

## Storage

Inside the sandbox (default):

| Path | Contents |
|------|----------|
| `$WORKDIR/repo/<name>/` | Target-repo clones |
| `$WORKDIR/state/gh-readme-pipeline/state-<user>.jsonl` | Resume + summary records |
| `$WORKDIR/state/gh-readme-pipeline/lock` | flock — one run at a time |
| `$WORKDIR/cache/` | (Reserved for future use.) |

When run **outside** the launcher (development / direct invocation), paths fall
back to `${XDG_STATE_HOME:-~/.local/state}` and `${XDG_CACHE_HOME:-~/.cache}`.

`--resume` is meaningful only across direct invocations or after a failure
preserved the sandbox; clean launcher runs always start from scratch.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Clean success — sandbox wiped. |
| `1` | Missing dep, gh auth, GraphQL/clone fatal, generic error. |
| `2` | Final scan found dirty tree or unpushed commits — sandbox preserved. |
| `3` | Launcher-only: `EXPECTED_SHA` mismatch, no code executed. |
| `130` | Ctrl+C — state flushed, summary printed. |

## Security Notes

- All `subprocess` calls use list form, `shell=False`. No string interpolation.
- Repo names validated `^[A-Za-z0-9._-]+$`; clone URLs restricted to
  `git@github.com:` or `https://github.com/`.
- Blast-radius guard prevents Claude from modifying anything except `README.md`.
- Secret scan is best-effort — review the diff before accepting.
- SHA-pin protects against ref-mutation attacks; not against repo-takeover.
  Verify the `EXPECTED_SHA` out-of-band against the release.

## Development

```bash
git clone https://github.com/jiliac/github-readme-pipeline
cd github-readme-pipeline
python -m unittest discover -s tests
```

Direct (non-launcher) runs:

```bash
uv run gh_readme_pipeline.py --dry-run
```

Falls back to `~/.local/state/gh-readme-pipeline/` and `~/.cache/`.

### Manual TUI smoke test

1. `uv run gh_readme_pipeline.py --dry-run` against a test account.
2. Verify arrows move cursor, space toggles `[x]`, `a`/`n` bulk-select,
   resize keeps viewport coherent, `q` aborts cleanly.

## Troubleshooting

- **Sandbox preserved after failure:** stderr prints `kept /tmp/writeme.XXXXXX
  (exit=N)`. Inspect, then `rm -rf` manually.
- **`SHA pin mismatch`:** the pinned commit is not fetchable from `REPO_URL`.
  Verify the SHA matches the release tag.
- **`gh auth: not authenticated`:** run `gh auth login`, retry.
- **Stuck lock:** another process holds `$XDG_STATE_HOME/gh-readme-pipeline/lock`.
  Identify with `fuser`; remove only if no live pipeline.
- **Rate-limited:** GraphQL `remaining < 10` triggers a sleep up to 60s; longer
  waits abort. Wait for `resetAt` and re-run.

## License

MIT — see `LICENSE`.
