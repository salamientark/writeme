# Security Fix Plan — release/v0.1.1

Agreed remediations for issues in `docs/security/security-review-v0.1.1.md`.
Order: critical → high → medium → low. Each item: file/lines, action, rationale.

---

## CRITICAL

### CRIT-1 — `REF` argument injection (install.sh:69)
- Validate `REF` against `^[A-Za-z0-9._/-]+$` immediately after env defaulting (near line 8).
- On mismatch: stderr message + `exit 4`.
- Switch line 69 to `--branch=$REF` single-token form (belt-and-braces).

### CRIT-2 — `COMMIT_MESSAGE` newline injection (commit.py)
- In `commit_and_push`, before mode dispatch: if `commit_message` contains `\n` or `\r`, return `CommitResult(status="failed", error="commit_message must be single line")`.

---

## HIGH

### CR-HIGH-1 / RT-H4 — User-mismatch confirm discarded (fetch.py)
- Delete `_check_user_mismatch` (fetch.py:156–171) and its call at fetch.py:226.
- `gh_readme_pipeline.py:_resolve_user` (lines 160–170) is the single source of truth.
- Side effect: kills CR-LOW-2 (func-scope `import os`).

### CR-HIGH-2 — Silent git add/commit failures (commit.py:177-231)
- Add helper `_check_git(result, op: str) -> CommitResult | None` returning failed result on non-zero.
- Apply after `git checkout` (PR mode), `git add`, and `git commit` in all three modes (`_run_pr_mode`, `_run_direct_mode`, `_run_commit_only_mode`).
- On failure return `CommitResult(status="failed", mode=..., pr_url=None, error=stderr_or_rc)`.

### CR-HIGH-3 — Raw traceback on fetch failure (gh_readme_pipeline.py:422)
- Wrap `fetch_repos(user, limit)` in `try/except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e`.
- Print human-readable error to stderr; `return 1`.
- Keep `check=True` in `_fetch_page`.

### RT-H1 — Unpinned fallback branch (install.sh:65–69)
- Before fallback `git clone`, print loud warning: branch fetch is unverified, repo writer can serve arbitrary code.
- Read confirmation from `/dev/tty`; require literal `yes`; abort otherwise.
- Skip prompt only if `WRITEME_ALLOW_UNPINNED=1` (explicit dev override).

### RT-H2 — Credential exfil via claude subprocess (review.py:_invoke_claude + pipeline)
- **Env scrub (allowlist):** build minimal env dict for `claude` subprocess with only:
  `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `LANG`, `LC_*`, `TERM`, `TMPDIR`, `XDG_*`, `CLAUDE_*`.
  Drop `GH_TOKEN`, `GITHUB_TOKEN`, `AWS_*`, `ANTHROPIC_API_KEY`, generic `*_TOKEN`, `*_KEY`, `*_SECRET`, `*_PASSWORD`.
  Pass via `subprocess.run(..., env=scrubbed_env)`.
- **Owner warning:** before per-repo processing in pipeline, if `repo.owner != authenticated_user`, print warning + tty confirm.
- Document: users relying solely on `ANTHROPIC_API_KEY` env must `claude login` once into `~/.claude/`.

### RT-H3 / CR-MED-2 — Blast-radius bypass (review.py:_blast_radius_ok)
- Replace `git status --porcelain` text parse with two NUL-delim queries:
  - `git diff --name-only -z --diff-filter=ACMRT HEAD`
  - `git ls-files -z --others --exclude-standard`
- Combine outputs, split on `\0`, drop empties, set-compare to `{"README.md"}`.

---

## MEDIUM

### CR-MED-1 — Double `ensure_clean` (gh_readme_pipeline.py:303)
- Delete `safety.ensure_clean(repo_dir)` from `except KeyboardInterrupt` block. Keep `_record` + `raise`. `finally` block handles cleanup.

### CR-MED-3 — Bare `git push` in direct mode (commit.py:213)
- Replace `git push` with `git push origin HEAD`. Mirrors PR-mode explicitness.

### CR-MED-4 / RT-M2 — Loose URL validation (safety.py:31–46)
- Replace prefix checks with strict regex matches:
  - HTTPS: `^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$`
  - SSH:   `^git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$`
- Reject anything else with `ValueError`.

### RT-M1 — `/tmp` artifacts on SIGKILL (install.sh:38)
- `BASE_DIR="${XDG_RUNTIME_DIR:-/tmp}"`
- `WORKDIR="$(mktemp -d -p "$BASE_DIR" writeme.XXXXXX)"`
- `chmod 700 "$WORKDIR"` (belt-and-braces).
- Document: SIGKILL/poweroff still leaves dir; prefer XDG runtime dir to bound exposure.

### RT-M3 — ANSI escape via pager (review.py:87)
- Drop `-R` from `subprocess.run(["less", "-R"], ...)` → `subprocess.run(["less"], ...)`.
- README is markdown; no legitimate ANSI.

---

## LOW

### CR-LOW-1 — Private attr access (gh_readme_pipeline.py:426)
- Add method `StateStore.has_prior_state(self) -> bool` returning `self._state_file.exists()`.
- Replace `state_store._state_file.exists()` → `state_store.has_prior_state()`.

### CR-LOW-2 — Func-scope `import os` (fetch.py:158)
- Removed by CR-HIGH-1 (entire function deleted).

### RT-L1 — Path traversal via `GH_USER` (state.py:72)
- Validate `user` in `StateStore.__init__` against GitHub username regex:
  `^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$`.
- Raise `ValueError` on mismatch.

---

## Implementation Order

1. CRIT-1, CRIT-2 — block injection vectors first.
2. RT-H1, RT-H2 — supply chain + credential scrub.
3. RT-H3 / CR-MED-2 — blast radius hardening.
4. CR-HIGH-1, CR-HIGH-2, CR-HIGH-3 — correctness.
5. CR-MED-1, CR-MED-3, CR-MED-4 / RT-M2 — cleanup.
6. RT-M1, RT-M3 — defense in depth.
7. CR-LOW-1, RT-L1 — polish.

## Test Coverage Targets

- Unit: regex validators (REF, URL, GH_USER), `_check_git` helper, `_blast_radius_ok` with NUL-delim fixtures.
- Integration: env-scrub assertion (spawn dummy claude that dumps env, assert allowlist), commit-mode failure paths (mock failing `git commit`).
- Manual: install.sh fallback prompt (interactive + override env), pager rendering of crafted README.
