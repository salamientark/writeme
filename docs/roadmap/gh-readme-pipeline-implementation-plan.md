# gh-readme-pipeline — Implementation Plan

**Date:** 2026-04-29
**Spec:** `2026-04-29-gh-readme-pipeline-design-v2.md`
**Approach:** TDD per phase. Each phase = tests first (RED), then implementation (GREEN), then refactor.

---

## Phase 0 — Repo skeleton

- [ ] Create `src/`, `tests/`, `__init__.py` files.
- [ ] Add `pyproject.toml` w/ PEP 723 inline metadata in `gh_readme_pipeline.py` entrypoint.
- [ ] CI stub: `uv run -m unittest discover` on push.
- [ ] `.gitignore` for `.cache/`, `repos/`, `.pipeline/`, `*.pyc`.

**Exit:** empty test run passes.

---

## Phase 1 — Safety primitives (`src/safety.py`)

Addresses: **C3, C5, H5, M4**.

Tests first:
- [ ] `validate_repo_name` accepts `foo`, `foo-bar.baz_1`; rejects `..`, `foo/bar`, `foo;rm`, empty.
- [ ] `validate_ssh_url` accepts `git@github.com:x/y.git`, `https://github.com/x/y`; rejects `ssh://evil`, `--upload-pack=...`.
- [ ] `ensure_clean(tmp_repo)` resets dirty tree; removes `MERGE_HEAD`.
- [ ] `acquire_lock` raises if held by another process (use second `subprocess` to test).

Impl:
- [ ] `validate_repo_name(name) -> None | raises`
- [ ] `validate_ssh_url(url) -> None | raises`
- [ ] `ensure_clean(repo_dir: Path) -> None`
- [ ] `@contextmanager acquire_lock(path: Path)` using `fcntl.flock`.

---

## Phase 2 — `SelectionState` (`src/selection.py`)

Addresses: **M1**.

Tests first:
- [ ] Construct from `[Repo, ...]`; `cursor=0`, `selected=set()`.
- [ ] `toggle()` flips current cursor index in `selected`.
- [ ] `move(+1)` clamps at `len-1`; `move(-1)` clamps at 0.
- [ ] Viewport: cursor below viewport scrolls down; above scrolls up.
- [ ] `select_all/none`.
- [ ] `visible_slice()` returns `(repo, selected, is_cursor)` tuples for window.
- [ ] All methods return new instance — original unchanged.

Impl:
- [ ] `@dataclass(frozen=True)` `SelectionState` with above methods.
- [ ] `handle_key(c: int)` dispatcher returning new state.

---

## Phase 3 — `fetch_repos` (`src/fetch.py`)

Addresses: **L1, M3, L5, L6**.

Tests first:
- [ ] Fixture w/ single page → list of `Repo`.
- [ ] Two-page fixture → merged list, ordered by `pushedAt`.
- [ ] Multi-expression readme detection: any of 5 paths non-null = `had_readme_before=True`.
- [ ] `LIMIT=2000` → capped at 1000, warning printed.
- [ ] Rate-limit `remaining=5` → sleeps until `resetAt` (mock `time.sleep`).
- [ ] User mismatch (`GH_USER != gh user`) → prompts (mock `input`).
- [ ] Disk pre-flight: sum diskUsage compared to `shutil.disk_usage`; warn if > 80%.
- [ ] Validation: GraphQL response w/ malicious repo name raises.

Impl:
- [ ] `Repo(name, ssh_url, pushed_at, had_readme_before, disk_usage)` dataclass.
- [ ] `fetch_repos(user, limit) -> list[Repo]` calling `subprocess.run(['gh','api','graphql',...], list-form)`.
- [ ] Multi-expression GraphQL query string.
- [ ] Pagination loop w/ `pageInfo.endCursor`.
- [ ] Rate-limit handler.

---

## Phase 4 — Storage paths + state store (`src/state.py`)

Addresses: **H1, H7, M2**.

Tests first:
- [ ] `xdg_cache_dir()` honors `XDG_CACHE_HOME`, falls back to `~/.cache`.
- [ ] `xdg_state_dir()` similar.
- [ ] `record(repo, status, ...)` appends valid JSONL.
- [ ] `load_processed()` returns set of repo names with `status in {pushed, pr_opened, commit_only}`.
- [ ] `summary()` aggregates counts + URL list.

Impl:
- [ ] Path helpers.
- [ ] `StateStore.record(...)` (atomic append).
- [ ] `StateStore.load_processed()`, `StateStore.summary()`.
- [ ] Resume prompt (`prompt_resume(processed_count)`).

---

## Phase 5 — Secret scan (`src/secrets.py`)

Addresses: **M5**.

Tests first:
- [ ] `scan_repo_for_risky_files` returns list of paths matching glob set.
- [ ] `scan_text_for_secrets` matches AWS key, GH token, OpenAI key, private key header, generic api_key=.
- [ ] No false-positive on prose containing word "token".

Impl:
- [ ] Glob list + `Path.rglob`.
- [ ] Regex set + `scan_text_for_secrets(s) -> list[str]`.

---

## Phase 6 — Review loop (`src/review.py`)

Addresses: **C1 (clean baseline), C4 (blast guard), H2, H3, H6, M5**.

Tests first:
- [ ] Baseline restore invariant: each step-2 entry runs `git checkout -- README.md && git clean -f README.md` (assert call sequence).
- [ ] Claude success → blast guard passes → secret scan passes → accept prompt shown.
- [ ] Claude non-zero exit → redo/discard prompt only.
- [ ] Claude timeout → retry/skip/quit prompt; retry triggers baseline restore + re-invoke.
- [ ] Blast guard: `git status --porcelain` returns 2 files → abort, mark failed.
- [ ] Secret detected → force discard or typed `yes-i-checked`.
- [ ] Accept w/ `had_readme_before=True` → typed `yes` required.
- [ ] View toggle: `v/V/o` re-display + re-prompt.
- [ ] Redo loop N times, then accept.
- [ ] Discard restores baseline.

Impl:
- [ ] `review_loop(repo_dir, had_readme_before, claude_timeout) -> ReviewResult`.
- [ ] Pure prompt state machine; subprocess + input mockable.
- [ ] Pager fallback (`less -R` if isatty + `which less`, else print).

---

## Phase 7 — Commit & push (`src/commit.py`)

Addresses: **H4, H7, M6, L2**.

Tests first:
- [ ] Mode prompt returns `pr/direct/commit-only/skip`; `--mode` flag bypasses.
- [ ] Verb selection: `add` if no prior README, `update` if prior.
- [ ] `SKIP_CI=1` appends `[skip ci]`.
- [ ] PR mode: branch creation, push, `gh pr create` invocation captured.
- [ ] Direct mode: no branch, push to current default.
- [ ] Commit-only: no push, no PR.
- [ ] `--dry-run`: commits but skips `git push` + `gh pr create`.
- [ ] Push rejection: stderr captured; status=`failed`.
- [ ] GPG warn at startup when `commit.gpgsign=true` + no signingkey.

Impl:
- [ ] `commit_and_push(repo_dir, mode, had_readme_before, dry_run) -> CommitResult`.
- [ ] All `subprocess.run` list-form, `check=False`, capture output.

---

## Phase 8 — TUI shim (`src/tui.py`)

Addresses: **TUI spec**.

- [ ] Manual smoke test only (documented in README).
- [ ] Implementation: thin `curses.wrapper` calling `SelectionState.handle_key`.
- [ ] Resize handler.
- [ ] Empty selection → exit message.

---

## Phase 9 — Orchestration (`gh_readme_pipeline.py` entrypoint)

Addresses: glue + **M2, M4**.

Tests first:
- [ ] Flag parsing: `--mode`, `--dry-run`, `--repos-dir`, `--claude-timeout`, `--resume`, `--clean`, `--skip-ci`.
- [ ] `--clean` removes cache dir, exits.
- [ ] User-mismatch warning at startup.
- [ ] flock acquired before any work.

Impl:
- [ ] PEP 723 metadata block.
- [ ] `argparse` setup.
- [ ] `main()`: flock → fetch → tui → for each repo `process_repo` → summary.
- [ ] SIGINT handler: flush state, print partial summary, restore terminal.

---

## Phase 10 — Install script (`install.sh`)

Addresses: **C2**.

- [ ] Dep checks: `uv`, `gh`, `git`, `claude`. Each missing = exit 1 + install hint.
- [ ] `gh auth status` check.
- [ ] Download `gh_readme_pipeline.py` from pinned tag URL.
- [ ] Verify SHA-256 against pinned constant.
- [ ] Place script + wrapper in `~/.local/bin/`.
- [ ] PATH hint if missing.
- [ ] Companion `install.sh.sha256` published in release.

Manual test:
- [ ] Curl-pipe-bash on clean VM; verified-flow on same.

---

## Phase 11 — Docs

- [ ] `README.md`: install (one-liner + verified flow), usage, flags, env vars, storage paths, troubleshooting.
- [ ] Document Claude blast-radius guard, secret scan limitations.
- [ ] Document resume + state file location.
- [ ] Manual TUI smoke test steps.

---

## Phase 12 — Release

- [ ] Tag `v0.1.0`.
- [ ] GitHub Release w/ `install.sh`, `install.sh.sha256`, `gh_readme_pipeline.py`, `gh_readme_pipeline.py.sha256`.
- [ ] README install URL points to `v0.1.0` tag.

---

## Cross-Cutting Verification Checklist (pre-release)

Map every fix back to a test or smoke test:

| Issue | Verified by |
|-------|-------------|
| C1 | Phase 6 baseline-restore test |
| C2 | Phase 10 manual verify-flow |
| C3 | Phase 1 `validate_repo_name` tests |
| C4 | Phase 6 blast-guard test |
| C5 | Phase 1 `validate_ssh_url` + grep for `shell=True` (none allowed) |
| H1 | Phase 4 resume tests |
| H2 | Phase 6 baseline invariant test |
| H3 | Phase 6 view-toggle + typed-yes test |
| H4 | Phase 7 mode tests |
| H5 | Phase 1 `ensure_clean` test |
| H6 | Phase 6 timeout test |
| H7 | Phase 4 summary aggregation test |
| M1 | Phase 2 `SelectionState` tests |
| M2 | Phase 4 path tests |
| M3 | Phase 3 cap + rate-limit tests |
| M4 | Phase 1 flock test |
| M5 | Phase 5 + Phase 6 secret tests |
| M6 | Phase 7 verb + skip-ci tests |
| L1 | Phase 3 multi-expression test |
| L4 | Phase 6 run.log capture (assert tee) |
| L5 | Phase 3 user-mismatch test |
| L6 | Phase 3 disk pre-flight test |

---

## Phase ordering rationale

1-2 first: pure helpers, zero deps, fast feedback.
3-5: data + I/O units, mockable.
6-7: orchestration units depending on 1-5.
8-9: glue + entrypoint.
10-12: ship.

Each phase ships a green test suite before moving on.
