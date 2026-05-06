# gh-readme-pipeline — Design Flaws

**Date:** 2026-04-29
**Source spec:** `2026-04-29-gh-readme-pipeline-design.md`
**Reviewers:** architect-review agent + security-reviewer (red team)

---

## CRITICAL

### C1. In-memory README backup → data loss on crash
Spec records `had_readme_before` and backs up content in process memory before invoking Claude with `--permission-mode acceptEdits`. If the process is killed (Ctrl+C, OOM, terminal close, claude hang) between backup and restore, the original README is gone — Claude will have already overwritten it.

**Fix:** Use `git stash push -- README.md` before invocation, or write `.gh-readme-pipeline.bak` to disk. Restore = `git checkout -- README.md` (works for both pre-existing and new-file cases). Makes redo/discard idempotent.

### C2. `curl | bash` install with no integrity verification
`curl -fsSL <url>/install.sh | bash` executes arbitrary remote code. Compromised CDN, DNS hijack, or MITM delivers malicious code that runs as the user. No checksum, signature, or pinned commit.

**Fix:** Publish SHA-256 alongside each release; document download-then-verify pattern (`curl … -o install.sh && sha256sum -c install.sh.sha256 && bash install.sh`). At minimum pin a tagged release URL with embedded checksum verifying the downloaded `.py`.

### C3. Path traversal via repo name → `./repos/<name>`
GraphQL `repo.name` is trusted as-is when constructing `./repos/<name>/`. A malicious or unexpected name (`../../../.bashrc`, names with `/`) writes outside the intended directory.

**Fix:** Validate `re.match(r'^[A-Za-z0-9_.-]+$', name)` and reject names containing `..` or `/` before path construction.

### C4. `acceptEdits` blast radius — Claude can write anywhere in repo
`claude -p "/create-readme" --permission-mode acceptEdits` lets Claude create/modify/delete any file in the working tree, not just `README.md`. A confused or prompt-injected invocation could overwrite `Makefile`, CI workflows, or inject code.

**Fix:** Constrain Claude's write scope (bare clone + worktree limited to `README.md`), or document the risk explicitly and verify only `README.md` changed before accept (`git status --porcelain` — abort if other files touched).

### C5. Command injection via `ssh_url`
GraphQL `ssh_url` passed to `git clone`. With `shell=True` or sloppy quoting, a malicious URL (`ssh://host/repo && evil`) executes arbitrary commands.

**Fix:** Always `subprocess.run(['git', 'clone', '--', ssh_url, dest], shell=False)`. Validate `ssh_url` starts with `git@github.com:` or `https://github.com/`.

---

## HIGH

### H1. No resume / no checkpoint
500-repo cap × ~90s per repo = 12+ hours of blocking interactive flow. If user quits at repo 200, accepted/skipped state is lost.

**Fix:** Persist `./repos/.pipeline-state.jsonl` recording `{repo, status, timestamp}`. On startup, offer "resume previous run? skip N already-processed."

### H2. Review-loop FSM under-specified for claude-fail-with-partial-write
Step 3 (claude exits non-zero) offers redo/discard, but doesn't define behavior when claude exited non-zero AND wrote a partial `README.md`. Re-entry to step 2 must always restore-to-original.

**Fix:** Document invariant: *every entry to step 2 starts from the original pre-pipeline state*. Make exit code authoritative; always restore-to-backup on entry, regardless of prior path.

### H3. No diff shown before overwriting hand-written README
Repos already marked `[HAS README]` are silently replaced after accept. User sees only the new content, not what changed.

**Fix:** Show `diff -u` between old and new before accept prompt. Require explicit confirmation when `had_readme_before = True`.

### H4. Pushes directly to default branch, no PR, no `--dry-run`
Spec says "push against current default branch" with fixed `"docs: add README"` message. No PR mode, no dry-run. Branch protection rejection is swallowed silently into "continue loop." User won't know which repos succeeded vs failed.

**Fix:** Default to creating a feature branch and opening a PR (via `gh pr create`); add `--dry-run` flag; capture per-repo result and print summary table at end.

### H5. Ctrl+C mid-git leaves repo in bad state
Spec covers curses cleanup but not git interruption (partial commit, `MERGE_HEAD` left behind, staged-but-not-committed).

**Fix:** Wrap git ops in try/finally that runs `git status` and prints recovery hint. Never run `git commit` without verifying clean index.

### H6. `claude` subprocess has no timeout
Stalled claude blocks pipeline indefinitely with no feedback.

**Fix:** `subprocess.run(..., timeout=300)` (env-var configurable). On `TimeoutExpired`, prompt `[k]ill / [r]etry`.

### H7. Branch-protection / push-rejection silently swallowed
Push fails → "continue loop" with no surfaced summary. User doesn't know which repos didn't land.

**Fix:** Capture `(repo, status)` for every iteration. Print final summary table: pushed / commit-only / skipped / failed.

---

## MEDIUM

### M1. Curses logic conflates state with rendering → untestable
Spec acknowledges TUI is not automated, but selection logic (toggle, move, viewport math) lives inside the curses callback.

**Fix:** Extract pure `SelectionState` class — 100% covered. `tui.py` is a thin render+input shim.

### M2. `./repos/` in CWD is surprising
Most CLIs use `$XDG_CACHE_HOME` or `~/.cache/`. Running from `~` clones into `~/repos/` — collides with common conventions.

**Fix:** Default to `${XDG_CACHE_HOME:-~/.cache}/gh-readme-pipeline/repos/`. Allow `--repos-dir` override.

### M3. Pagination → memory blow-up if `LIMIT` overridden
`LIMIT` env var has no hard ceiling. User with thousands of repos loads all into memory before TUI renders.

**Fix:** Hard cap (e.g., 500) that env var cannot exceed. Show progress (`fetched 200/500…`). Respect rate-limit headers.

### M4. TOCTOU on README backup/restore
Concurrent process / git hook / `git fetch` could modify file between backup and restore; restore clobbers newer version silently.

**Fix:** Store backup as temp outside working tree. Hash-compare before restore.

### M5. Secret leakage into generated README
Claude cwd is the full repo clone, which may contain `.env`, private keys, internal config. `/create-readme` skill could embed snippets in the README.

**Fix:** Document the risk. Consider restricting Claude's context to `*.md`, `*.py`, source files only (if the CLI supports it). Scan output for likely secrets before accept.

### M6. Fixed commit message conflicts with CI conventions
`"docs: add README"` is wrong when `had_readme_before=True` (should be "update"). Triggers CI on every push. No GPG-signing check.

**Fix:** Branch on `had_readme_before` for verb. Optional `[skip ci]` flag. Detect `gpg.signingkey` and warn if signing required.

---

## LOW

- **L1.** `has_readme` only checks `HEAD:README.md` — misses `readme.md`, `Readme.md`, `README.rst`, `docs/README.md`. Use REST `/readme` endpoint or multi-expression query.
- **L2.** No `--dry-run` mode (does everything except `git push`).
- **L3.** `less -R` fallback to direct print dumps 500-line README into terminal. Use `isatty()` + terminal size check.
- **L4.** No run log. Per-repo `run.log` (stdout+stderr) aids debugging.
- **L5.** `GH_USER` scope creep — can enumerate another user's repos. Warn if `GH_USER != gh api user --jq .login`.
- **L6.** Disk exhaustion from 500 clones with no size warning.

---

## Top overlap (must-fix before v1)

Findings raised by both reviewers:

1. **Backup safety** (C1 / M4)
2. **`curl|bash` integrity** (C2)
3. **Path/cmd injection** on repo name + `ssh_url` (C3, C5)
4. **Claude blast radius + timeout** (C4, H6)
5. **No diff before overwrite** (H3)
6. **No `--dry-run` / direct push to default** (H4)

## Recommended v1.1 changes

- Replace in-memory backup with `git stash` / on-disk `.bak`.
- Validate repo name + `ssh_url`; `shell=False` everywhere.
- Show unified diff before accept; abort if non-README files modified.
- Default to feature-branch + PR; add `--dry-run`.
- Add `subprocess.run(..., timeout=...)` on Claude invocation.
- Persist run state for resume.
- Move `./repos/` to `$XDG_CACHE_HOME`.
- Print final summary table.
- Publish SHA-256 with install one-liner; pin release tag.
- Extract `SelectionState` from curses for testability.
