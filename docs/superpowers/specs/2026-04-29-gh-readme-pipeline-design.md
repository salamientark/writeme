# gh-readme-pipeline — Design

**Date:** 2026-04-29
**Status:** Approved

## Purpose

Interactive CLI tool that helps a GitHub user generate `README.md` files for their repositories using Claude. User selects repos via a TUI, reviews each AI-generated draft, and optionally commits + pushes.

## Distribution

- One-line install: `curl -fsSL <url>/install.sh | bash`.
- `install.sh` verifies external dependencies, downloads `gh_readme_pipeline.py` and a thin wrapper to `~/.local/bin/gh-readme-pipeline`, and prints a PATH instruction if the directory is not on `$PATH`.
- The wrapper invokes the script via `uv run` so future Python deps can be added through PEP 723 inline metadata without changing the install flow. v1 uses stdlib only.

## External Dependencies

Must be present on the user's machine before install:

- `uv` (Python execution / future dep management)
- `gh` (authenticated; checked via `gh auth status`)
- `git`
- `claude` (Claude Code CLI, must have `/create-readme` skill available)

`install.sh` checks each and exits with a clear message if missing.

## Components

| Component | Responsibility |
|-----------|----------------|
| `install.sh` | Dep checks, download script + wrapper, place in `~/.local/bin/`, PATH hint. |
| `fetch_repos()` | Paginated `gh api graphql` call. Returns list of `Repo(name, ssh_url, pushed_at, has_readme)`. |
| `tui_select(repos)` | Curses multi-select. Returns the user's chosen subset. |
| `process_repo(repo)` | Clone-or-fetch into `./repos/<name>`, then run review loop, then commit prompt. |
| `review_loop(repo_path)` | Invoke Claude, show draft, accept/redo/discard. |
| `commit_and_push(repo_path)` | Single y/n prompt, performs add+commit+push on yes. |
| `main()` | Orchestrates the above. |

## Data Flow

```
install.sh  →  ~/.local/bin/gh-readme-pipeline + gh_readme_pipeline.py
                       ↓ user runs
              fetch_repos()  →  [Repo, ...]
                       ↓
              tui_select()   →  [selected Repo, ...]
                       ↓ for each selected
              clone-or-fetch into ./repos/<name>
                       ↓
              review_loop:
                claude -p /create-readme  →  README.md on disk
                       ↓ show preview
                [a]ccept   → commit_and_push prompt → next repo
                [r]edo     → loop back to claude invocation
                [d]iscard  → restore prior state → next repo
```

## TUI Specification

- Library: Python stdlib `curses`.
- Header line: `Select repos for /create-readme  (N selected of M)`.
- Help line: `↑/↓ move   space toggle   enter confirm   q quit`.
- Each row: `[x] [HAS README] <name>  <pushed_at>` or `[ ] [no readme] <name>  <pushed_at>`.
- Highlighted row: reverse video.
- Scrolling: viewport keeps cursor in view; window resize handled.
- `enter` returns the selected list. Empty selection exits with message "nothing selected".
- `q` aborts with no action.

## Repo Selection Scope

Pulled via GraphQL: `isArchived: false`, `ownerAffiliations: OWNER`, ordered by `pushedAt DESC`. Default owner is the authenticated user (`gh api user --jq .login`); overridable via `GH_USER` env var. Page size 100; cap 500 (`LIMIT` env var override).

`has_readme` is determined by querying `object(expression: "HEAD:README.md")` — non-null `byteSize` = README present.

## Repos Directory

- Created at `./repos/` relative to current working directory (the directory where the user invoked `gh-readme-pipeline`).
- Per-repo path: `./repos/<repo-name>/`.
- If the directory already contains a clone, run `git fetch --quiet origin` and reuse it. Otherwise `git clone <ssh_url>`.
- Pipeline never deletes `./repos/` — user owns cleanup.

## Review Loop

For each selected repo:

1. Record `had_readme_before = (README.md exists)` and back up its current content if so.
2. Run `claude -p "/create-readme" --permission-mode acceptEdits` with cwd = `./repos/<name>`.
3. If the command exits non-zero or `README.md` is missing/empty after the run: print the error, offer `[r]edo / [d]iscard` only (no accept).
4. Otherwise print the new `README.md` to stdout (paged via `less -R` if available, else direct print).
5. Prompt: `[a]ccept / [r]edo / [d]iscard`.
   - **accept** → proceed to commit prompt.
   - **redo** → restore the backed-up content (or delete file if it didn't exist) and return to step 2.
   - **discard** → restore prior state, skip to next repo.

Redo means a plain re-invocation of the skill — no extra user-supplied prompt in v1.

## Commit & Push

On accept, prompt: `commit + push? [y/n]`.

- **y** → `git add README.md && git commit -m "docs: add README" && git push` against the current default branch (whatever HEAD points to after clone; no branch creation).
- **n** → leave the working tree dirty and proceed to next repo.

Commit message is fixed in v1. Power users can amend afterward.

## Error Handling

| Failure | Behavior |
|---------|----------|
| Missing external dep | Print which one + install hint, exit 1 at startup. |
| `gh` not authenticated | Print "run `gh auth login`", exit 1. |
| GraphQL error | Print error payload, exit 1. |
| Clone fails | Print error, skip repo, continue loop. |
| `claude -p` non-zero / no README produced | Print error, offer redo/discard. |
| Commit fails (nothing to commit, push rejected, etc.) | Print error, leave dirty, continue. |
| Ctrl+C | Curses cleanup via `try/finally`, restore terminal, exit cleanly. |

## Testing

Stdlib `unittest`, run via `uv run -m unittest`.

- `fetch_repos`: parse fixture GraphQL JSON → expected `Repo` list. Pagination handling tested with two-page fixture.
- `review_loop`: state-machine test with mocked `subprocess.run` (claude) and mocked input — covers accept, redo×N then accept, discard, claude failure paths.
- `commit_and_push`: y and n branches with mocked git calls; verify command sequence and that `n` performs no git operations.
- TUI: not automated. Manual smoke test documented in README: launch, navigate, toggle, confirm, abort.

Coverage target: 80% on non-curses code.

## File Layout (in repo)

```
github-readme-pipeline/
├── install.sh
├── gh_readme_pipeline.py
├── tests/
│   ├── test_fetch_repos.py
│   ├── test_review_loop.py
│   └── test_commit_and_push.py
├── docs/superpowers/specs/
│   └── 2026-04-29-gh-readme-pipeline-design.md   (this file)
└── README.md
```

## Out of Scope (v1)

- Multi-account / org-only browsing UI (env var override is the only knob).
- Custom commit messages or branch creation / PR opening.
- Feedback-driven redo (passing user hint to Claude).
- Caching past drafts.
- Windows support (curses + bash installer is POSIX).
