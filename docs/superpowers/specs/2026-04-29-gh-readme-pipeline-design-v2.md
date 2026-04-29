# gh-readme-pipeline — Design v2

**Date:** 2026-04-29
**Status:** Approved (revised after design-flaws review)
**Supersedes:** `2026-04-29-gh-readme-pipeline-design.md`

## Purpose

Interactive CLI tool that helps a GitHub user generate `README.md` files for their repositories using Claude. User selects repos via a TUI, reviews each AI-generated draft, and optionally commits + pushes via PR (default), direct push, or commit-only.

## Distribution

- One-line install: `curl -fsSL https://raw.githubusercontent.com/<owner>/gh-readme-pipeline/<TAG>/install.sh | bash`.
  - URL pinned to a tagged release (never `main`).
  - `install.sh` and `gh_readme_pipeline.py` published with `.sha256` companion files. README documents recommended verify-then-bash flow:
    ```
    curl -fsSL <url>/<TAG>/install.sh -o install.sh
    echo "<sha256>  install.sh" | sha256sum -c
    bash install.sh
    ```
- `install.sh` verifies external deps, downloads the script + thin wrapper to `~/.local/bin/gh-readme-pipeline`, prints PATH hint if needed.
- Wrapper invokes via `uv run` (PEP 723 inline metadata for future deps). v1 stdlib only.

## External Dependencies

Required at install time:
- `uv`, `gh` (authenticated), `git`, `claude` (with `/create-readme` skill)

Optional (warned if missing, not blocking):
- `less` (pager fallback to direct print)
- `gpg` (only if `commit.gpgsign=true`)

## Components

| Component | Responsibility |
|-----------|----------------|
| `install.sh` | Dep checks, download script + wrapper, place in `~/.local/bin/`, PATH hint. |
| `fetch_repos()` | Paginated `gh api graphql` call w/ rate-limit + progress. Returns `[Repo(...)]`. |
| `SelectionState` | Pure immutable dataclass: cursor, selected set, viewport. Unit-tested. |
| `tui_select(repos)` | Thin curses shim around `SelectionState`. |
| `process_repo(repo)` | Clone-or-fetch, run review loop, run commit/push prompt. Wrapped in try/finally cleanup. |
| `review_loop(repo_path)` | Invoke Claude w/ timeout, show diff/full, accept/redo/discard. |
| `commit_and_push(repo_path)` | Per-repo mode prompt: PR / direct / commit-only / skip. |
| `state_store` | JSONL persistence for resume + summary. |
| `secret_scan` | Pre-Claude risky-file warn, post-Claude regex scan. |
| `main()` | Orchestrates above + flock + flag parsing. |

## Storage Layout

| Path | Contents |
|------|----------|
| `${XDG_CACHE_HOME:-~/.cache}/gh-readme-pipeline/repos/<name>/` | Throwaway clones. |
| `${XDG_STATE_HOME:-~/.local/state}/gh-readme-pipeline/state-<user>.jsonl` | Resume + summary records. |
| `${XDG_STATE_HOME:-~/.local/state}/gh-readme-pipeline/lock` | flock to prevent concurrent runs. |
| `<repo_dir>/.pipeline/run.log` | Per-repo claude/git stdout+stderr. |

Override paths: `--repos-dir <path>`, `GH_README_REPOS_DIR` env.

## CLI Flags & Env Vars

| Flag | Env | Effect |
|------|-----|--------|
| `--mode pr\|direct\|commit-only` | — | Skip per-repo mode prompt. Default: ask. |
| `--dry-run` | — | Run full loop incl. commit, never push. |
| `--repos-dir <path>` | `GH_README_REPOS_DIR` | Override cache dir. |
| `--claude-timeout <sec>` | `CLAUDE_TIMEOUT` | Claude subprocess timeout (default 300). |
| `--resume` | — | Skip already-processed repos from state file. |
| `--clean` | — | Remove cache dir, exit. |
| `--skip-ci` | `SKIP_CI` | Append `[skip ci]` to commit message. |
| — | `LIMIT` | Repo cap (capped at hard `1000`). |
| — | `GH_USER` | Override authed user. |
| — | `COMMIT_MESSAGE` | Override commit message template. |

## Repo Selection Scope

GraphQL: `isArchived: false`, `ownerAffiliations: OWNER`, `pushedAt DESC`. Owner = `gh api user --jq .login` or `GH_USER`. Page size 100; default 500; hard cap 1000.

Startup check: if `GH_USER != gh api user --jq .login`, prompt `Operating on <X>'s repos as <Y>. Continue? [y/N]`.

`had_readme_before` detected via multi-expression GraphQL query covering: `README.md`, `readme.md`, `Readme.md`, `README.rst`, `docs/README.md`. True if any non-null. Pipeline always writes canonical `README.md` at root.

Pre-flight disk check: sum `diskUsage` for selected repos × 2; if > available × 0.8, warn before cloning. Clones use `git clone --depth 1 --filter=blob:none` to minimize size.

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
    ensure repo cloned/fetched at <cache>/repos/<name>
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
Dry-run: skip `git push` and `gh pr create`; record what would have been pushed.

GPG check at startup: if `commit.gpgsign=true` and no `user.signingkey`, warn (don't block).

## State Persistence

Per repo, append to JSONL state file:
```json
{"repo": "foo", "status": "pushed|pr_opened|commit_only|skipped|failed",
 "mode": "pr|direct|commit-only", "error": "...", "pr_url": "...", "ts": "2026-04-29T20:13:00Z"}
```

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

Advisory `flock $XDG_STATE_HOME/gh-readme-pipeline/lock` at startup. Second concurrent run exits with clear message.

## Error Handling

| Failure | Behavior |
|---------|----------|
| Missing required dep | Print which + install hint, exit 1. |
| `gh` not authenticated | Print "run `gh auth login`", exit 1. |
| GraphQL error / rate-limit | Print payload; rate-limit sleeps or exits cleanly. |
| Clone fails | Log to run.log, mark `failed`, continue. |
| Claude timeout | Prompt retry/skip/quit. |
| Claude touched non-README | Abort repo, `ensure_clean`, mark `failed`, continue. |
| Secret detected in README | Force discard or typed override. |
| Push rejected | Capture stderr, mark `failed`, surface in summary. |
| Ctrl+C | try/finally cleanup per repo + curses restore + state flushed + summary printed. |

## Testing

Stdlib `unittest`, run via `uv run -m unittest`.

- `test_fetch_repos`: GraphQL fixture parsing, pagination, rate-limit handling, multi-expression readme detection.
- `test_input_validation`: malicious repo names + ssh_urls rejected.
- `test_selection_state`: pure dataclass — toggle, move, viewport, select-all, immutability.
- `test_review_loop`: state-machine w/ mocked subprocess + input — accept, redo×N, discard, timeout, non-zero exit, blast-radius guard, secret-scan trip, baseline-restore invariant.
- `test_commit_and_push`: PR / direct / commit-only / skip branches; verb selection; `[skip ci]` flag.
- `test_state_store`: append, resume filter, summary aggregation.
- `test_secret_scan`: known-positive and known-negative samples.

Coverage target: 80% on non-curses code (curses shim excluded).

## File Layout

```
github-readme-pipeline/
├── install.sh
├── install.sh.sha256
├── gh_readme_pipeline.py
├── gh_readme_pipeline.py.sha256
├── src/
│   ├── fetch.py
│   ├── selection.py        # SelectionState
│   ├── tui.py              # curses shim
│   ├── review.py           # review_loop + invariants
│   ├── commit.py           # commit_and_push + modes
│   ├── state.py            # JSONL store, resume, summary
│   ├── secrets.py          # pre/post scans
│   └── safety.py           # validation, ensure_clean, flock
├── tests/
│   └── test_*.py
├── docs/superpowers/specs/
│   ├── 2026-04-29-gh-readme-pipeline-design.md         (v1, superseded)
│   ├── 2026-04-29-gh-readme-pipeline-design-v2.md      (this file)
│   └── design-flaws.md
└── README.md
```

## Out of Scope (v1)

- Multi-account / org-only browsing UI (env var override is the only knob).
- Custom branch naming UI (timestamp-based default only).
- Feedback-driven redo (passing user hint to Claude).
- Caching past drafts.
- Streaming TUI render during fetch (load-then-render is fine ≤1000).
- Windows support (curses + bash installer is POSIX).
- Third-party secret scanners (`trufflehog`/`gitleaks`) — regex set only in v1.
