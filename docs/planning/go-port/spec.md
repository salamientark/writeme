# spec.md — CLI / IO Contract for `writeme` Go Port

Acceptance contract for a Go reimplementation. Source of truth = current Python implementation.
Where this doc cites Python, the citation is the binding behavior.

Program name: `gh-readme-pipeline` (argparse `prog`, see `gh_readme_pipeline.py:64`).
The Go binary should keep the same invocation surface.

---

## 1. CLI — Subcommands & Flags

No subcommands. Single-command invocation. All flags are optional.

Reference: `gh_readme_pipeline.py:57-161`.

| Flag | Type | Default | Env fallback | Hard cap | Semantics |
|------|------|---------|--------------|----------|-----------|
| `--mode` | enum `{pr,direct,commit-only}` | `nil` (prompt per repo) | — | — | Skip per-repo mode prompt; apply to every selected repo. (`:68-73`) |
| `--dry-run` | bool | `false` | — | — | Run full loop incl. local commits, but never `git push` or `gh pr create`. (`:74-79`) |
| `--repos-dir` | path | `xdg_cache_dir()/repos` | `GH_README_REPOS_DIR` | — | Override clone-cache directory. (`:80-85`, `:129-135`) |
| `--claude-timeout` | int (seconds) | `300` (`DEFAULT_TIMEOUT`) | `CLAUDE_TIMEOUT` | — | Per-repo `claude` subprocess timeout. Invalid env value → falls back to default. (`:86-91`, `:137-145`) |
| `--resume` | bool | `false` | — | — | When prior state exists, prompt resume/all/fresh/quit. (`:92-97`, `:594-604`) |
| `--clean` | bool | `false` | — | — | `rmtree(repos-dir)` and `sys.exit(0)`. No other work performed. (`:98-103`, `:525-527`) |
| `--skip-ci` | bool | `false` | `SKIP_CI` (truthy = any non-empty string) | — | Append ` [skip ci]` to commit message. (`:104-108`, `:147-148`) |
| `--parallel` | int | `3` (`DEFAULT_PARALLEL`) | `WRITEME_PARALLEL` | clamped to `[1, 8]` (`PARALLEL_CAP`) | Number of parallel `claude` workers. `1` = sequential. Invalid env value → default. (`:110-118`, `:150-159`) |
| `--plain` | bool | `false` | — | — | Disable Rich UI. Force plain prints (non-TTY/CI). (`:119-124`) |

### Flag/env precedence

Flag value (when explicitly set, i.e. not `None`) wins over env var. Env var wins over built-in default.
Implementation pattern: `if ns.flag is None: read env, else fallback`. Apply same precedence in Go.

### Hard caps

- `LIMIT` (env): capped at `1000` via `min(int(raw_limit), HARD_LIMIT)`. Invalid value → silent fallback to `500`. (`:540-544`, `HARD_LIMIT=1000` at `:46`)
- `--parallel`: `max(1, min(parallel, 8))`. (`:159`, `PARALLEL_CAP=8` at `:49`)
- `LIMIT` is also re-capped inside `fetch_repos` (`src/fetch.py:203-208`); a stderr warning is printed when the cap triggers there.

### env-only options (no flag)

- `LIMIT` — repo cap, default `500`, hard cap `1000`. (`:540-544`)
- `GH_USER` — override authenticated user; mismatch with `gh api user` triggers interactive y/N confirm; `n` → `sys.exit(1)`. (`:175-201`)
- `COMMIT_MESSAGE` — override default commit message template. Single-line only; CR/LF rejected and produce a `failed` result. (`:547`, `src/commit.py:284-291`)

---

## 2. Exit Codes

Reference: `README.md:113-122`, `gh_readme_pipeline.py:525-657`.

| Code | Cause |
|------|-------|
| `0`  | Clean success. Also: `--clean` flag, no repos selected, user picked `quit` at resume prompt. |
| `1`  | Could not determine GH user; `gh` GraphQL fetch error (`CalledProcessError` / `JSONDecodeError` / `KeyError`); `_resolve_user` mismatch + user typed not-`y`. (`:534-537`, `:576-578`, `:198-199`) |
| `2`  | Final `scan_unpushed` found dirty trees or unpushed commits in any clone under `repos_dir`. Sandbox is preserved by the launcher. (`:647-657`) |
| `3`  | Launcher-only (`install.sh`): `EXPECTED_SHA` mismatch. Pipeline binary itself never returns 3. |
| `130`| `SIGINT` (Ctrl-C). Handler prints `Interrupted. Flushing state...` to stderr, prints summary to stdout, then `sys.exit(130)`. Single-fire (re-entrant guard via `_sigint_fired`). (`:553-562`) |

### SIGINT handling contract

- Installed once at start of `main` after state-store init. (`:562`)
- First SIGINT: print interruption notice (stderr) → print summary (stdout) → exit 130.
- Re-entrancy: subsequent SIGINTs while the handler is running are still `sys.exit(130)` (no special suppression beyond the `_sigint_fired` guard preventing double-summary).
- `KeyboardInterrupt` raised from inside `process_repo` records `failed`/`KeyboardInterrupt` to state, runs `safety.ensure_clean`, then propagates. (`:345-348`)

Go port: install `signal.Notify` for `os.Interrupt`; wire to a context cancel; flush state, print summary, `os.Exit(130)`.

---

## 3. stdin / stdout / stderr Contracts

### stdout (human-readable; not machine-parseable)

- Rich UI banner, spinner, repo TUI, status lines (when TTY + not `--plain`).
- `--- Summary ---` block at end of run. Format (`:478-500`):
  ```
  --- Summary ---
    Pushed (PR)          <count>
    Pushed (direct)      <count>
    Commit only          <count>
    Skipped              <count>
    Failed               <count>

  PR URLs:
    <url>
    ...

  Failed repos:
    <name>
    ...
  ```
  Width-aligned via `f"{label:<20}"`. The `PR URLs` and `Failed repos` sections are emitted only when non-empty.
- `Nothing selected.` when user confirms with empty selection. (`:609`)

### stderr (warnings, errors, prompts-context)

- `WARNING: GH_USER=... but authenticated as ...` (`:191-194`)
- `ERROR: could not determine GitHub user. Set GH_USER or run 'gh auth login'.` (`:535`)
- `WARNING: GPG signing is enabled ...` (`src/commit.py:79-83`)
- `Warning: limit N exceeds maximum; capped at 1000.` (`src/fetch.py:204-207`)
- `Rate limit low (remaining=N). Sleeping Xs until reset.` (`src/fetch.py:101-104`)
- `Warning: estimated disk requirement (X MB) exceeds 80% ...` (`src/fetch.py:167-172`)
- `Interrupted. Flushing state...` (`:558`)
- `Unpushed/dirty work detected:` block on exit 2; one line per finding `  <path>: dirty, N unpushed commit(s)`. (`:649-656`)
- UI `warn`/`error` (`ui.warn(...)`, `ui.error(...)`) routes here in `--plain` mode.

### stdin

- Interactive prompts via Python `input()`:
  - User mismatch confirm: `[y/N]`. (`:195-199`)
  - Resume prompt: `[r]esume / [a]ll incl. failed / [s]tart fresh / [q]uit:`; loops until valid. (`src/state.py:200-223`)
  - Push-mode prompt (when `--mode` not set and no UI): `[p]/[m]/[c]/[n]`; loops until valid. (`src/commit.py:98-114`)
  - Overwrite-existing-README confirm: typed `yes` literal.
  - Secret-scan override: typed `yes-i-checked` literal.
- TUI mode: raw stdin read from controlling TTY, not the inherited stdin.
- When `--plain` or no TTY: prompts read from stdin via `input()`.

### Machine-parseable surfaces

None. The state JSONL file is the only machine-readable artifact (see §6). Stdout/stderr are human-only.

---

## 4. Config & State Files

No config file. State only.

### XDG path discovery

Reference: `src/state.py:34-55`, `src/sandbox.py`.

| Purpose | Var | Fallback |
|---------|-----|----------|
| State dir | `$XDG_STATE_HOME/gh-readme-pipeline` | `~/.local/state/gh-readme-pipeline` |
| Cache dir | `$XDG_CACHE_HOME/gh-readme-pipeline`  | `~/.cache/gh-readme-pipeline` |
| Repos dir | `--repos-dir` flag → `GH_README_REPOS_DIR` env → `<cache>/repos` | — |
| Per-job sandbox | `<repos-dir>/.sandbox/claude-jobs/<repo>/{config,data,cache,state}` | created on demand |

`APP_NAME = "gh-readme-pipeline"` (`src/state.py:29`). Directories are NOT auto-created by the path helpers; `StateStore.record` and `sandbox_for` mkdir-on-write.

### Lock file

Path: `<state_dir>/lock`. Acquired via `safety.acquire_lock(...)` as a context manager around the entire run after state-dir resolution. Advisory; one pipeline at a time. (`gh_readme_pipeline.py:565-567`)

### State file: `state-<user>.jsonl`

Reference: `src/state.py:62-185`.

- Path: `<state_dir>/state-<user>.jsonl`.
- Format: append-only JSONL (one JSON object per line).
- Username validated against `^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$` before use as a path component (`:22`).
- Write path: `mkdir -p` parent → open `"a"` → `write(json + "\n")` → `flush()`. No fsync. Single line considered atomic.
- Concurrency: `threading.Lock` serialises writes within one process. The advisory `lock` file blocks cross-process concurrency.
- Reads: `_read_all` re-scans the entire file each call; malformed lines silently skipped.

#### Record schema

Required keys (always present):
```json
{ "repo": "<name>", "status": "<status>", "ts": "<iso8601 utc seconds>" }
```
`ts` produced by `datetime.now(tz=UTC).isoformat(timespec="seconds")`.

Optional keys (omitted entirely when `None`):
- `mode`: `"pr" | "direct" | "commit-only"`
- `error`: human-readable string (e.g. `"KeyboardInterrupt"`, `"user_quit"`, `"claude_touched_other_files"`, raw stderr)
- `pr_url`: URL string (only set on `pr_opened` mode)

#### `status` enum

Values written by the pipeline (`src/commit.py:CommitResult` + ad hoc records):
- `pushed` — direct mode push succeeded.
- `pr_opened` — PR mode succeeded; `pr_url` populated.
- `commit_only` — commit-only mode succeeded.
- `skipped` — user picked skip / `user_quit` / review status `skipped`.
- `failed` — review/commit/push failure; `error` populated.

For summary/resume aggregation, `pushed | pr_opened | commit_only` count as "processed" (`_PROCESSED_STATUSES` at `src/state.py:31`).
Last record per repo wins (`gh_readme_pipeline.py:451-471`).

### Atomicity guarantees

- Per-record atomicity: single `write()` of `json + "\n"` followed by `flush()`. No torn writes for typical JSON sizes on POSIX.
- No rename-into-place. No fsync. A crash between flush and OS sync may lose the most recent record.
- No schema migration; new fields are additive and old readers ignore unknown keys.

### Repos cache

`<repos-dir>/<name>/` — shallow clone (`--depth=1 --filter=blob:none`). Re-fetched on subsequent runs if `.git` exists. (`gh_readme_pipeline.py:223-244`)

Auxiliary files in `<repos-dir>`:
- `.contributors.json` — REST-enriched contributor cache (`gh_readme_pipeline.py:584`).
- `.sandbox/claude-jobs/<repo>/{config,data,cache,state}/` — per-job XDG sandbox tree.

---

## 5. Environment Variables (Full List)

| Var | Read by | Default | Precedence |
|-----|---------|---------|------------|
| `LIMIT` | main | `500` (cap `1000`) | env-only; no flag |
| `GH_USER` | `_resolve_user` | `gh api user` result | env wins on agreement; mismatch prompts |
| `COMMIT_MESSAGE` | main | `docs: <verb> README` template | env-only; no flag |
| `GH_README_REPOS_DIR` | `parse_args` | `xdg_cache_dir()/repos` | flag wins |
| `CLAUDE_TIMEOUT` | `parse_args` | `300` | flag wins; invalid → default |
| `SKIP_CI` | `parse_args` | unset | flag OR env (any non-empty) |
| `WRITEME_PARALLEL` | `parse_args` | `3` | flag wins; clamped `[1,8]` |
| `XDG_STATE_HOME` | `xdg_state_dir` | `~/.local/state` | std XDG semantics |
| `XDG_CACHE_HOME` | `xdg_cache_dir` | `~/.cache` | std XDG semantics |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME` | per-job sandbox env (`src/sandbox.py:30-37`) | sandbox subdirs | injected into claude subprocess only |

### Launcher-only (not the pipeline binary; documented for parity awareness)

`NUKE_ON_FAIL`, `REPO_URL`, `REF`, `EXPECTED_SHA`, `SKIP_DEP_CHECK`. (See `README.md:76`.) The Go port replaces the Python launcher; map these onto the Go binary install/wrapper if and only if a launcher is reimplemented.

### env passed to `claude` subprocess (allowlist)

Reference: `src/review.py:45-61`.

Allowlisted exact keys: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `LANG`, `TERM`, `TMPDIR`.
Allowlisted prefixes: `CLAUDE_`, `LC_`, `XDG_`.
All other env vars are dropped (defense vs leaking tokens/keys/secrets to the model subprocess).

### Secret-scan patterns (text)

Reference: `src/secrets.py:82-101`. Applied to generated README text only:
- `AKIA[0-9A-Z]{16}` (AWS access key)
- `gh[pousr]_[A-Za-z0-9]{36,}` (GitHub tokens)
- `sk-[A-Za-z0-9\-]{20,}` (OpenAI keys)
- `-----BEGIN [A-Z ]*PRIVATE KEY-----`
- `(?i)(api[_-]?key|secret|token)\s*[=:]\s*['"][A-Za-z0-9_\-]{16,}['"]`

Risky-file globs (filesystem scan of clone): `.env`, `.env.*`, `*.pem`, `*.key`, `credentials.json`, `.aws/**`, `.ssh/**`. (`src/secrets.py:32-40`)

---

## 6. File Formats

### Produced

#### Commit message

Template (`src/commit.py:122-136`):
```
docs: <verb> README
```
- `<verb>` = `update` if `had_readme_before`, else `add`.
- Override: `COMMIT_MESSAGE` env or `--commit-message`-equivalent. CR/LF in override → `failed` result; reject before any git op (`src/commit.py:284-291`).
- `--skip-ci` / `SKIP_CI` env → append literal ` [skip ci]` (one leading space).
- The same message is used as the PR title.

#### PR body

Hardcoded literal (`src/commit.py:213`):
```
Generated by gh-readme-pipeline.
```
PR URL parsed from `gh pr create`'s stdout (entire trimmed stdout treated as the URL).

#### Branch name (PR mode)

```
docs/readme-pipeline-<unix-epoch-seconds>
```
`int(time.time())`. (`src/commit.py:190`)

#### README artifact

`README.md` at repo root. Generated by `claude /create-readme`. Blast-radius guard requires `git status --porcelain` to show only `README.md` modified/added; any other path → abort with `claude_touched_other_files`.

### Consumed

- `state-<user>.jsonl` — schema in §4.
- `.contributors.json` — internal cache; not part of the user-facing contract. Schema is implementation-defined; Go port may use any equivalent format.
- `.claude/skills/create-readme/SKILL.md` — staged from `<program-root>/.claude/skills/create-readme/SKILL.md` into each clone before `claude` invocation, removed after. (`src/review.py:42-80`) The Go port must ship this SKILL.md as an embedded asset.

---

## 7. External Tool Dependencies

All subprocess calls use list form, `shell=False`, `check=False`, `capture_output=True`, `text=True` (except the GraphQL fetch which uses `check=True`). Go port should match: `exec.Command(...).Run()` with separate stdout/stderr buffers.

### `gh` (GitHub CLI)

- `gh api user --jq .login` → resolve authenticated username. Stdout = login string. (`gh_readme_pipeline.py:179-185`)
- `gh api graphql -f query=<query> -F login=<user> -F first=<n> [-F after=<cursor>]` → repo paging. Stdin = none. Returns full GraphQL JSON on stdout. Query body in `src/fetch.py:37-70` (multi-expression README detection across 5 paths). (`src/fetch.py:140-156`)
- `gh pr create --title <msg> --body "Generated by gh-readme-pipeline."` → run inside the clone's cwd. Stdout = PR URL. (`src/commit.py:211-215`)
- REST contributor enrichment via `gh api ...` (see `src/contributors.py`).

### `git`

Run with `cwd=<repo_dir>`. All list-form invocations:

- `git clone --depth=1 --filter=blob:none <ssh_url> <repo_dir>` (`gh_readme_pipeline.py:233-244`)
- `git fetch --depth=1` (refresh existing clone) (`:225-231`)
- `git checkout -b <branch>` (PR mode)
- `git add README.md`
- `git commit -m <msg>`
- `git push -u origin <branch>` (PR mode) / `git push origin HEAD` (direct mode)
- `git config commit.gpgsign` / `git config user.signingkey` (warning probe)
- `git status --porcelain` (and `-z` variants) — blast-radius guard
- `git diff --name-only -z` and `git ls-files --others --exclude-standard -z` — change enumeration

URL validation before clone: `safety.validate_ssh_url` restricts to `git@github.com:` or `https://github.com/`.
Repo-name validation: `^[A-Za-z0-9._-]+$`.

### `claude`

Single invocation per repo (`src/review.py:254-263`):

```
claude -p /create-readme --permission-mode acceptEdits
```

- `cwd` = `<repo_dir>`.
- `stdin` = `subprocess.DEVNULL`.
- `timeout` = `--claude-timeout` seconds (default 300).
- `env` = scrubbed allowlist (see §5) + per-job XDG sandbox overrides (parallel mode).
- TTY attrs saved/restored around the call to survive `claude` mutating the controlling terminal.
- `TimeoutExpired` → returned as `None`; surfaced to user as a retry/skip/quit prompt.
- Non-zero exit → returned as a `failed` `GenerationResult`; surfaced to user as redo/discard prompt.

### Optional / probe-only

- `gh auth status` — only invoked by the launcher; pipeline does not probe.

---

## Appendix — Acceptance hooks for the Go port

A Go reimplementation passes the contract iff, for the same inputs:

1. Flag/env parsing matches the precedence table in §1, including the `--parallel` clamp and the `LIMIT` cap+fallback.
2. Exit codes match §2 (esp. `2` for unpushed/dirty work, `130` for SIGINT).
3. State file is byte-compatible JSONL with the schema in §4 (additive fields permitted; existing fields must match names & semantics).
4. Subprocess command shapes match §7 verbatim — same argv, same cwd, same env scrubbing.
5. Commit message, branch name pattern, and PR body match §6.
6. Stdout summary block matches the literal format in §3.
