# gh-readme-pipeline — Design

**Date:** 2026-04-29
**Status:** Approved
**Companion:** `docs/specs/features/self-destruct.md` (lifecycle source of truth)

## Purpose

Interactive CLI tool that helps a GitHub user generate `README.md` files for their repositories using Claude. User selects repos via a TUI, reviews each AI-generated draft, and optionally commits + pushes via PR (default), direct push, or commit-only.

The pipeline is **ephemeral by default**: every invocation runs inside an mktemp'd sandbox that is destroyed on success. There is no persistent install on disk, no long-lived cache, no mutated user shell environment. Failure preserves the sandbox so the user can debug; a single env-var flag overrides this.

## Distribution

One-line invocation:

```
curl -fsSL https://raw.githubusercontent.com/<owner>/github-readme-pipeline/<REF>/install.sh | bash
```

`install.sh` is **not** a traditional installer — it is a launcher. It does not write to `~/.local/bin/`, does not modify `PATH`, and does not leave anything behind on success. It:

1. Creates a unique sandbox under `$TMPDIR` via `mktemp -d -t writeme.XXXXXX`.
2. Bootstraps the program into the sandbox with `git clone --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"`.
3. Creates `repo/`, `state/`, `cache/` subdirectories.
4. Exports `GH_README_REPOS_DIR`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` (subshell only — parent shell untouched).
5. `exec`s Python on `$WORKDIR/program/gh_readme_pipeline.py "$@"`.
6. Cleans up via `trap cleanup EXIT` per the policy below.

Commit SHA pinning is in scope (see "Commit SHA Pinning"). Signature verification of `install.sh` itself is out of scope.

## External Dependencies

Required at run time (checked by `install.sh` and/or Python early-fail):

- `bash` (>= 4), `mktemp`, `rm`, `git`, `gh` (authenticated), `claude` (with `/create-readme` skill), `python` (>=3.11), `uv`

Optional (warned, not blocking):

- `less` (pager fallback to direct print)
- `gpg` (only if `commit.gpgsign=true`)

## Sandbox Model (Lifecycle)

### Layout

Every run constructs a fresh sandbox:

```
$TMPDIR/writeme.XXXXXX/
├── program/    # git clone --depth=1 of github-readme-pipeline (REF=main by default)
├── repo/       # target-repo clones (exported as GH_README_REPOS_DIR)
├── state/      # exported as XDG_STATE_HOME — JSONL state file + flock live here
└── cache/      # exported as XDG_CACHE_HOME
```

Sandbox path is mktemp-unique, so it cannot collide with `$HOME`, `/`, or any pre-existing user state. Pre-existing data in the user's real `~/.local/state/gh-readme-pipeline/` (from prior tool versions) is **ignored** — the sandbox model never reads outside its own root.

### Cleanup Policy

Cleanup is owned by the bash launcher's `trap cleanup EXIT`, not by Python `shutil.rmtree`. This guarantees cleanup fires even if Python crashes, segfaults, or is killed.

| Python exit code | `NUKE_ON_FAIL` | Launcher action                                |
|------------------|----------------|------------------------------------------------|
| `0`              | any            | `rm -rf "$WORKDIR"` (wipe, zero trace)         |
| non-zero         | `0` (default)  | keep sandbox, print path to stderr             |
| non-zero         | `1`            | `rm -rf "$WORKDIR"` (nuclear override)         |

Rationale: a non-zero exit means there is potentially un-pushed user-visible work (Claude-generated READMEs, dirty trees, half-completed pushes). Default behavior preserves it. `NUKE_ON_FAIL=1` is the single nuclear override for users who want strict zero-trace regardless of outcome.

### Reference `install.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

NUKE_ON_FAIL="${NUKE_ON_FAIL:-0}"
REPO_URL="${REPO_URL:-https://github.com/<owner>/github-readme-pipeline}"

EXPECTED_SHA="${EXPECTED_SHA:-0000000000000000000000000000000000000000}"
REF="${REF:-main}"

WORKDIR="$(mktemp -d -t writeme.XXXXXX)"
EXIT_CODE=1
cleanup() {
  if [[ "$EXIT_CODE" == "0" || "$NUKE_ON_FAIL" == "1" ]]; then
    rm -rf "$WORKDIR"
  else
    echo "kept $WORKDIR (exit=$EXIT_CODE) — rm -rf to clean" >&2
  fi
}
trap cleanup EXIT

if [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] && [[ "$EXPECTED_SHA" != "0000000000000000000000000000000000000000" ]]; then
  git -C "$WORKDIR" init -q program
  git -C "$WORKDIR/program" remote add origin "$REPO_URL"
  git -C "$WORKDIR/program" fetch --depth=1 origin "$EXPECTED_SHA"
  git -C "$WORKDIR/program" -c advice.detachedHead=false checkout -q FETCH_HEAD
  [[ "$(git -C "$WORKDIR/program" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || {
    echo "SHA pin mismatch" >&2; exit 3; }
else
  git clone --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"
fi
mkdir -p "$WORKDIR/repo" "$WORKDIR/state" "$WORKDIR/cache"

export GH_README_REPOS_DIR="$WORKDIR/repo"
export XDG_STATE_HOME="$WORKDIR/state"
export XDG_CACHE_HOME="$WORKDIR/cache"

python "$WORKDIR/program/gh_readme_pipeline.py" "$@"
EXIT_CODE=$?
```

### What Python Knows

Python is **unaware** of the sandbox. It honors standard env vars (`XDG_STATE_HOME`, `XDG_CACHE_HOME`, `GH_README_REPOS_DIR`) that the launcher happens to point at sandbox subdirs. Running Python directly outside the launcher still works — it just falls back to the user's real XDG dirs (suitable for development and unit tests).

### Unpushed-Work Scan (Exit Code 2)

Just before normal termination, Python scans `$GH_README_REPOS_DIR/*/`:

- For each clone, run `git status --porcelain` and `git rev-list @{u}..HEAD` (skip clones with no upstream).
- If any clone has a dirty working tree OR unpushed commits → log paths to stderr and `sys.exit(2)`.
- Otherwise `sys.exit(0)`.

Exit code 2 triggers the launcher's "keep sandbox" branch by default, preserving user-visible work for inspection.

### Commit SHA Pinning

Launcher fetches a pinned 40-char commit SHA instead of a mutable branch ref.

**Mechanism.** Each released `install.sh` hardcodes `EXPECTED_SHA`. At run time:

1. Valid 40-char hex (and not all-zeros): `git init` → `git fetch --depth=1 origin "$EXPECTED_SHA"` → `checkout FETCH_HEAD` → verify `rev-parse HEAD == EXPECTED_SHA`. Mismatch → `exit 3`.
2. Empty / all-zeros / invalid: fall back to `git clone --depth=1 --branch "$REF"` (dev mode, prints one-line warning).

**Release.** CI rewrites `EXPECTED_SHA` to the tagged commit on each release tag. `main`-branch copy keeps the all-zeros placeholder.

## Components

| Component | Responsibility |
|-----------|----------------|
| `install.sh` | Sandbox launcher: mktemp, clone program, set XDG/repos env, exec Python, trap-cleanup. |
| `fetch_repos()` | Paginated `gh api graphql` call w/ rate-limit + progress. Returns `[Repo(...)]`. |
| `SelectionState` | Pure immutable dataclass: cursor, selected set, viewport. Unit-tested. |
| `tui_select(repos)` | Thin curses shim around `SelectionState`. |
| `process_repo(repo)` | Clone-or-fetch, run review loop, run commit/push prompt. Wrapped in try/finally cleanup. |
| `review_loop(repo_path)` | Invoke Claude w/ timeout, show diff/full, accept/redo/discard. |
| `commit_and_push(repo_path)` | Per-repo mode prompt: PR / direct / commit-only / skip. |
| `state_store` | JSONL persistence for resume + summary (under `XDG_STATE_HOME`). |
| `secret_scan` | Pre-Claude risky-file warn, post-Claude regex scan. |
| `unpushed_scan` | End-of-run dirty/unpushed check; raises exit 2 when triggered. |
| `main()` | Orchestrates above + flock + flag parsing + final exit-code selection. |

## Storage Layout

All paths resolve through XDG env vars set by the launcher; under the sandbox they all live inside `$WORKDIR/...`.

| Path | Contents |
|------|----------|
| `$GH_README_REPOS_DIR/<name>/` | Target-repo clones (the launcher points this at `$WORKDIR/repo/`). |
| `$XDG_STATE_HOME/gh-readme-pipeline/state-<user>.jsonl` | Resume + summary records. |
| `$XDG_STATE_HOME/gh-readme-pipeline/lock` | flock to prevent concurrent runs. |
| `$XDG_CACHE_HOME/gh-readme-pipeline/` | Reserved for future caches; unused in v1. |
| `<repo_dir>/.pipeline/run.log` | Per-repo claude/git stdout+stderr. |

When run outside the launcher, defaults fall back to `${XDG_STATE_HOME:-~/.local/state}` and `${XDG_CACHE_HOME:-~/.cache}` per XDG spec.

## CLI Flags & Env Vars

| Flag | Env | Effect |
|------|-----|--------|
| `--mode pr\|direct\|commit-only` | — | Skip per-repo mode prompt. Default: ask. |
| `--dry-run` | — | Run full loop incl. commit, never push. |
| `--repos-dir <path>` | `GH_README_REPOS_DIR` | Override repo-clone dir (set by launcher to `$WORKDIR/repo`). |
| `--claude-timeout <sec>` | `CLAUDE_TIMEOUT` | Claude subprocess timeout (default 300). |
| `--resume` | — | Skip already-processed repos from state file. |
| `--skip-ci` | `SKIP_CI` | Append `[skip ci]` to commit message. |
| — | `LIMIT` | Repo cap (capped at hard `1000`). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |
| — | `XDG_STATE_HOME` | Standard XDG; honored for state + lock. |
| — | `XDG_CACHE_HOME` | Standard XDG; honored for cache. |
| — | `NUKE_ON_FAIL` | Launcher-only: `1` = wipe sandbox even on non-zero exit. |
| — | `REPO_URL` / `REF` | Launcher-only: override program source / git ref (REF used only when no SHA pin). |
| — | `EXPECTED_SHA` | Launcher-only: 40-char commit SHA pin. Hardcoded per release; override for dev. Empty/zeros = unpinned dev mode. |

**Removed since prior v2:** `--clean`. Cleanup is the launcher's job; resetting state means re-running the launcher (every run starts clean by construction).

**Not added:** `--ephemeral`. The sandbox model makes ephemerality implicit and unconditional.

## Repo Selection Scope

GraphQL: `isArchived: false`, `ownerAffiliations: OWNER`, `pushedAt DESC`. Owner = `gh api user --jq .login` or `GH_USER`. Page size 100; default 500; hard cap 1000.

Startup check: if `GH_USER != gh api user --jq .login`, prompt `Operating on <X>'s repos as <Y>. Continue? [y/N]`.

`had_readme_before` detected via multi-expression GraphQL query covering: `README.md`, `readme.md`, `Readme.md`, `README.rst`, `docs/README.md`. True if any non-null. Pipeline always writes canonical `README.md` at root.

Pre-flight disk check: sum `diskUsage` for selected repos × 2; if > available × 0.8 in `$TMPDIR`, warn before cloning. Clones use `git clone --depth 1 --filter=blob:none` to minimize size.

Rate-limit: read `rateLimit { remaining, resetAt }` from each GraphQL response. If `remaining < 10`, sleep until `resetAt` (max 60s) or abort with clear message.

## Input Validation (Security)

Applied immediately on GraphQL response:

```python
if not re.match(r'^[A-Za-z0-9._-]+$', repo.name) or repo.name in ('.', '..'):
    raise ValueError(f"unsafe repo name: {repo.name!r}")
if not (repo.ssh_url.startswith('git@github.com:')
        or repo.ssh_url.startswith('https://github.com/')):
    raise ValueError(f"unexpected clone URL: {repo.ssh_url!r}")
```

All subprocess calls use list form + `shell=False` + `--` sentinel where applicable. No string interpolation into shell commands.

## TUI Specification

- Backed by `SelectionState` (pure, immutable, unit-tested).
- Header: `Select repos for /create-readme  (N selected of M)`.
- Help: `↑/↓ move  space toggle  a all  n none  enter confirm  q quit`.
- Row: `[x] [HAS README] <name>  <pushed_at>` (reverse video on cursor).
- Resize, scroll, viewport math live in `SelectionState.move/toggle/visible_slice`. `tui.py` only does curses I/O.
- `enter` returns selection. Empty = "nothing selected", exit. `q` = abort.

## Per-Repo Pipeline

```
process_repo(repo):
    flock
    ensure repo cloned/fetched at $GH_README_REPOS_DIR/<name>
    open <repo_dir>/.pipeline/run.log (tee claude+git stdout/stderr)
    try:
        review_loop(repo_dir)        # accept | discard
        if accepted:
            commit_and_push(repo_dir)
    except KeyboardInterrupt:
        ensure_clean(repo_dir); raise
    finally:
        ensure_clean(repo_dir)
        record_state(repo, status, mode, error, pr_url)
```

`ensure_clean(repo_dir)`:
```python
subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=repo_dir, check=False)
subprocess.run(['git', 'clean', '-fd'], cwd=repo_dir, check=False)
for f in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REBASE_HEAD'):
    (repo_dir / '.git' / f).unlink(missing_ok=True)
```

Note: `ensure_clean` runs only after a *successful* per-repo flow (push/PR/commit-only/skip). When the per-repo flow fails — e.g., push rejected — the dirty state is intentionally left in place so the unpushed-work scan can detect it and trigger exit 2.

## Review Loop (FSM)

**Invariant:** every entry to step 2 starts from clean baseline (`git checkout -- README.md && git clean -f README.md`).

1. Pre-Claude: scan clone for risky files (`.env`, `*.pem`, `*.key`, `credentials.json`, `.aws/`, `.ssh/`). If found, warn + prompt `[c]ontinue / [s]kip`.
2. Restore baseline. Invoke:
   ```
   subprocess.run(['claude', '-p', '/create-readme', '--permission-mode', 'acceptEdits'],
                  cwd=repo_dir, timeout=CLAUDE_TIMEOUT, check=False)
   ```
   - Timeout → prompt `[r]etry / [s]kip / [q]uit`.
   - Non-zero exit → treat as no-write; prompt `[r]edo / [d]iscard`.
3. **Blast-radius guard:** `git status --porcelain` must equal `['README.md']`. Otherwise abort, run `ensure_clean`, mark `failed: claude_touched_other_files`, continue loop.
4. **Secret scan** on new README content (regex set: API keys, AWS, GitHub tokens, private key headers, OpenAI-style). On match: loud warning, force `[d]iscard` or typed `yes-i-checked` to override.
5. **Accept prompt** with view toggle:
   ```
   [a]ccept / [r]edo / [d]iscard / [v]iew diff / [V]iew full new / [o]ld README
   ```
   Default first view: diff if `had_readme_before`, full content if new file. `v/V/o` re-display, then re-prompt. When `had_readme_before=True`, accept requires typed `yes`.
   - **redo** → step 2 (baseline restored automatically).
   - **discard** → mark `skipped`, exit loop.

## Commit & Push

On accept, per-repo mode prompt (skipped if `--mode` set):
```
Push mode?
  [p] PR (feature branch + gh pr create)   ← default
  [m] direct to main/default branch
  [c] commit only (no push)
  [n] no commit (skip)
```

Commit message:
```python
verb = 'update' if had_readme_before else 'add'
msg = os.environ.get('COMMIT_MESSAGE', f'docs: {verb} README')
if SKIP_CI: msg += ' [skip ci]'
```

PR mode:
```
git checkout -b docs/readme-pipeline-<unix-ts>
git add README.md
git commit -m "<msg>"
git push -u origin <branch>
gh pr create --title "<msg>" --body "Generated by gh-readme-pipeline."
```

Direct mode: same minus branch + PR.
Dry-run: skip `git push` and `gh pr create`; record what would have been pushed. Note: dry-run leaves a dirty/unpushed local state that the end-of-run scan will detect → exit 2 → sandbox preserved.

GPG check at startup: if `commit.gpgsign=true` and no `user.signingkey`, warn (don't block).

## State Persistence

Per repo, append to JSONL state file (under `$XDG_STATE_HOME/gh-readme-pipeline/`):
```json
{"repo": "foo", "status": "pushed|pr_opened|commit_only|skipped|failed",
 "mode": "pr|direct|commit-only", "error": "...", "pr_url": "...", "ts": "2026-04-29T20:13:00Z"}
```

Inside the sandbox, this file lives at `$WORKDIR/state/gh-readme-pipeline/state-<user>.jsonl` and is wiped with the rest of the sandbox on success. `--resume` is therefore meaningful only for non-launcher invocations or during a single run after a partial failure preserved the sandbox.

Startup with `--resume` (or auto-detect prior state file):
```
Found N repos already processed. [r]esume (skip processed) / [a]ll incl. failed / [s]tart fresh / [q]uit
```

End-of-run summary table to stdout:
```
Pushed (PR):       12   [PR URLs listed below]
Pushed (direct):    3
Commit only:        2
Skipped:            5
Failed:             1   [paths to run.log listed]
```

Same summary printed on SIGINT exit.

## Concurrency

Advisory `flock $XDG_STATE_HOME/gh-readme-pipeline/lock` at startup. Inside the sandbox the lock path is unique per run (each sandbox has its own state dir), so concurrent launcher runs do not collide. The lock still defends against accidental concurrent invocations of Python against the same `XDG_STATE_HOME` (e.g., direct invocation outside the launcher).

## Error Handling & Exit Codes

| Failure | Behavior | Exit |
|---------|----------|------|
| Missing required dep | Print which + install hint, exit. | `1` |
| `gh` not authenticated | Print "run `gh auth login`", exit. | `1` |
| GraphQL error / rate-limit | Print payload; rate-limit sleeps or exits cleanly. | `0` or `1` |
| Clone fails | Log to run.log, mark `failed`, continue. | (final scan decides) |
| Claude timeout | Prompt retry/skip/quit. | (per choice) |
| Claude touched non-README | Abort repo, `ensure_clean`, mark `failed`, continue. | (final scan decides) |
| Secret detected in README | Force discard or typed override. | (final scan decides) |
| Push rejected | Capture stderr, mark `failed`, surface in summary. Leaves dirty/unpushed state. | `2` (via final scan) |
| Dirty tree or unpushed commits at end-of-run | Print paths, fail loud. | `2` |
| Ctrl+C | try/finally cleanup per repo + curses restore + state flushed + summary printed. | `130` |
| Clean success, no unpushed work | Summary printed. | `0` |
| **Launcher: SHA pin mismatch** | Print expected vs actual; abort before exec. | `3` |

The launcher's `trap cleanup EXIT` consumes these exit codes per the cleanup-policy table above. Exit `3` (SHA mismatch) is a launcher-only code — Python never produces it.

## Testing

Stdlib `unittest` (Python) + `pytest` (launcher integration), run via `uv run`.

Python tests:
- `test_fetch_repos`: GraphQL fixture parsing, pagination, rate-limit handling, multi-expression readme detection.
- `test_input_validation`: malicious repo names + ssh_urls rejected.
- `test_selection_state`: pure dataclass — toggle, move, viewport, select-all, immutability.
- `test_review_loop`: state-machine w/ mocked subprocess + input — accept, redo×N, discard, timeout, non-zero exit, blast-radius guard, secret-scan trip, baseline-restore invariant.
- `test_commit_and_push`: PR / direct / commit-only / skip branches; verb selection; `[skip ci]` flag.
- `test_state_store`: append, resume filter, summary aggregation; honors `XDG_STATE_HOME`.
- `test_secret_scan`: known-positive and known-negative samples.
- `test_unpushed_scan`: clean clones → exit 0; dirty tree → exit 2; unpushed commits → exit 2; clones without upstream skipped.

Launcher tests (`tests/test_install.py`, pytest + `subprocess.run(["bash", "install.sh"], env=...)` against a stub `program/gh_readme_pipeline.py`):

- `test_clean_exit_wipes_workdir` — stub exits 0; assert mktemp path gone.
- `test_failure_keeps_workdir` — stub exits 1; assert dir survives + stderr contains path.
- `test_nuke_on_fail_overrides` — stub exits 1, `NUKE_ON_FAIL=1`; assert dir gone.
- `test_env_vars_set` — stub writes `os.environ` snapshot; assert `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `GH_README_REPOS_DIR` all point inside workdir.
- `test_user_env_untouched` — parent shell's `XDG_STATE_HOME` unchanged after launcher exits.
- `test_unpushed_work_exits_nonzero` — stub creates dirty git tree under `repo/`; assert exit 2 + dir kept.
- `test_sha_pin_match` — point `EXPECTED_SHA` at a real local fixture commit; assert successful boot.
- `test_sha_pin_mismatch` — set `EXPECTED_SHA` to a known wrong SHA; assert exit `3` and sandbox cleaned (no Python ran).
- `test_sha_pin_unset_dev_mode` — empty/zeros `EXPECTED_SHA`; assert fallback `git clone --branch $REF` path is taken (verify via stub network shim or local file:// remote).
- `test_sha_pin_invalid_format` — non-hex / wrong length `EXPECTED_SHA`; assert dev-mode fallback (treated as unset).

Coverage target: 80% on non-curses Python code (curses shim excluded).

## File Layout

```
github-readme-pipeline/
├── install.sh                      # sandbox launcher (replaces run.sh)
├── gh_readme_pipeline.py
├── src/
│   ├── fetch.py
│   ├── selection.py        # SelectionState
│   ├── tui.py              # curses shim
│   ├── review.py           # review_loop + invariants
│   ├── commit.py           # commit_and_push + modes
│   ├── state.py            # JSONL store, resume, summary; honors XDG_STATE_HOME
│   ├── secrets.py          # pre/post scans
│   ├── unpushed.py         # end-of-run dirty/unpushed scan
│   └── safety.py           # validation, ensure_clean, flock
├── tests/
│   ├── test_install.py     # launcher integration tests
│   └── test_*.py           # Python unit tests
├── docs/specs/features/
│   ├── gh-readme-pipeline.md           (this file)
│   └── self-destruct.md                (lifecycle source of truth)
├── docs/roadmap/
│   └── gh-readme-pipeline-implementation-plan.md
└── README.md                       # documents `curl | bash` invocation + NUKE_ON_FAIL
```

`run.sh` is **deleted** in this revision. All of its functionality (and much more) lives in `install.sh` plus the existing Python pipeline.

## Usage

Standard ephemeral run:
```
curl -fsSL https://raw.githubusercontent.com/<owner>/github-readme-pipeline/main/install.sh | bash
```

With pipeline flags:
```
curl -fsSL .../install.sh | bash -s -- --mode pr --dry-run
```

Strict zero-trace (wipe even on failure):
```
NUKE_ON_FAIL=1 curl -fsSL .../install.sh | bash
```

Pin to a specific ref:
```
REF=v0.3.1 curl -fsSL .../install.sh | bash
```

Direct (development) invocation, no sandbox:
```
uv run gh_readme_pipeline.py --mode pr
```

## Out of Scope (v1)

- SHA pinning / signature verification of `install.sh` (separate spec).
- Multi-account / org-only browsing UI (env var override is the only knob).
- Custom branch naming UI (timestamp-based default only).
- Feedback-driven redo (passing user hint to Claude).
- Caching past drafts.
- Streaming TUI render during fetch (load-then-render is fine ≤1000).
- Windows / non-POSIX support (curses + bash launcher are POSIX).
- Third-party secret scanners (`trufflehog`/`gitleaks`) — regex set only in v1.
- Logging/telemetry of wiped runs — none; zero-trace by design.
- Cross-platform sandbox path validation beyond `mktemp -d` uniqueness.
