<div align="center">

<img src="assets/banner.svg" alt="writeme" width="640">

**Auto-generate `README.md` files across all your GitHub repos.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Go](https://img.shields.io/badge/go-1.25%2B-00ADD8.svg)](https://go.dev/)
[![Claude Code](https://img.shields.io/badge/claude--code-required-8A2BE2.svg)](https://claude.com/claude-code)

</div>

Interactive CLI that drafts READMEs for your GitHub repos using Claude Code's `/create-readme` skill — running in an **ephemeral sandbox** with zero persistent install. Pick repos from a TUI, let Claude draft, review the diff, and ship via PR or direct commit. Nothing touches your `$HOME`: the launcher runs from a `mktemp` sandbox and wipes itself on success.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/main/install.sh | bash
```

The launcher checks dependencies, downloads the platform binary, verifies its checksum, runs the pipeline in a sandbox, and cleans up on exit.

## Features

- **TUI repo picker** — paginated list of all your repos (sorted by recent activity), filter, bulk select.
- **TUI review screen** — side-by-side diff, markdown preview, scroll, accept/redo/discard per repo.
- **Three ship modes** — `pr` (branch + `gh pr create`), `direct` (commit on default branch), or `commit-only`.
- **Blast-radius guard** — Claude may only touch `README.md`; any other modified file aborts the run.
- **Secret scanner** — flags AWS keys, GitHub tokens, OpenAI keys, and private-key headers in drafts.
- **Safe & fast** — resumable runs, parallel generation, SHA-pinned binary, zero footprint (single static binary, no shell config touched).

## Requirements

| Tool | Purpose |
|------|---------|
| `bash` (>= 4) | Launcher shell |
| `git` | Clone target repos |
| `gh` (authenticated) | Repo listing (GraphQL), PR creation |
| `claude` | `/create-readme` skill execution |
| `curl` | Binary download |
| `tar` | Archive extraction |

Run `gh auth login` first if `gh auth status` fails. The `writeme` binary itself is a standalone Go executable — no Python, uv, or runtime needed.

## How it works

For each selected repo:

1. **Clone** — `git clone --depth 1 --filter=blob:none` into `$GH_README_REPOS_DIR/<name>/`.
2. **Generate** — `claude /create-readme` with timeout. Output captured to `run.log`.
3. **Blast-radius guard** — `git status --porcelain` must show only `README.md`. Anything else → abort, mark `failed`, restore baseline.
4. **Secret scan** — flagged drafts require typed `yes-i-checked` to override.
5. **Review** — TUI or plain-text: `accept / redo / discard / quit`. Overwriting an existing README requires typed `yes`.
6. **Ship** — `pr`, `direct`, `commit-only`, or `skip`. Commit verb is `add` if no prior README, `update` otherwise.

## Usage

```
writeme [FLAGS]
```

| Flag | Effect |
|------|--------|
| `--mode pr\|direct\|commit-only` | Skip per-repo mode prompt. |
| `--dry-run` | Run full loop, never push. |
| `--resume` | Skip already-processed repos from state file. |
| `--parallel <n>` | Parallel Claude workers (1–8, default 3). |
| `--plain` | Disable TUI (plain-text mode). |
| `--version` | Print version and exit. |

Run `writeme --help` for the full flag and environment-variable reference. TUI key hints are shown in the on-screen footer.

## Storage layout

Inside the sandbox (default):

| Path | Contents |
|------|----------|
| `$WORKDIR/repo/<name>/` | Target-repo clones |
| `$WORKDIR/state/state-<user>.jsonl` | Resume + summary records |
| `$WORKDIR/state/lock` | flock — one run at a time |
| `$WORKDIR/cache/` | Contributor cache |

Outside the launcher (direct binary invocation), paths fall back to `${XDG_CACHE_HOME:-~/.cache}/gh-readme-pipeline/`.

## Security

> [!IMPORTANT]
> Always review the generated diff before accepting. The secret scanner is best-effort, not authoritative.

- All subprocess calls use list form, no string interpolation.
- Repo names validated `^[A-Za-z0-9._-]+$`; clone URLs restricted to `git@github.com:` or `https://github.com/`.
- Blast-radius guard prevents Claude from touching anything except `README.md`.
- Checksum pinning protects against binary tampering. Verify `EXPECTED_SHA` out-of-band against the release checksums.

## Troubleshooting

- **Sandbox preserved after failure** — stderr prints `kept /tmp/writeme.XXXXXX (exit=N)`. Inspect, then `rm -rf` manually. Exit `2` means a dirty tree or unpushed commits were left behind.
- **Checksum mismatch** — downloaded binary doesn't match the release checksum (exit `3`, no code ran). Verify the SHA256 against the release page.
- **`gh auth: not authenticated`** — run `gh auth login`, retry.
- **Stuck lock** — another process holds the run lock. Identify with `fuser`; remove only if no live pipeline.
- **Rate-limited** — GraphQL `remaining < 10` triggers a sleep up to 60s; longer waits abort. Wait for `resetAt` and re-run.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for build, test, and local-run instructions.
