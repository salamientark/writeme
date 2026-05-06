# Parallel README Generation + Solo-Repo Filter

Status: planned
Owner: damien@jiliac.com
Created: 2026-05-06

## Goals

1. Filter repo list to repos where user is sole author / only contributor (incl. fork exclusion).
2. Generate READMEs in parallel — clone + claude run concurrently, review remains sequential.

## Design decisions (resolved via grill-me)

### Filter

| # | Decision |
|---|----------|
| F1 | Two filter sources: GraphQL `isFork`/`OWNER` (free) + REST contributor count (paid). |
| F2 | Solo check uses `GET /repos/{owner}/{repo}/contributors?per_page=2`; len == 1 after bot strip. |
| F3 | Bot strip: drop logins matching `*[bot]`, `dependabot*`, `github-actions*`. Empty repo (0 contributors) counts as solo. |
| F4 | Always fetch contributor data on startup, parallel REST (10 workers). |
| F5 | Cache `$GH_README_REPOS_DIR/.contributors.json` keyed by `repo_name + pushed_at`. Stale entries ignored. |
| F6 | TUI filter toggles (independent bits, header reflects state): |
|    | • `s` — solo-only on/off |
|    | • `F` — exclude forks on/off |
|    | • `r` — exclude repos that already have README on/off |
| F7 | Existing `/` text-search unchanged; predicate filters compose AND with text. |
| F8 | Filter applied to visible list; selection state preserved across toggles. |

### Parallel generation

| # | Decision |
|---|----------|
| P1 | `concurrent.futures.ThreadPoolExecutor`, workers do clone + `claude /create-readme`. |
| P2 | CLI flag `--parallel N`, env `WRITEME_PARALLEL`, default **3**, hard cap **8**. |
| P3 | `--parallel 1` preserves sequential semantics; no separate code path. |
| P4 | Pool starts only after user confirms selection + mode (no speculative work). |
| P5 | Review remains sequential, interactive. FIFO completion queue — first-ready, first-shown. |
| P6 | Status line via Rich `Live` above review prompt: `[done/total] [running] [queued]`. |
| P7 | Per-job XDG sandbox: `$SANDBOX/claude-jobs/<repo>/{config,data,cache,state}`. Avoids claude session DB races. |
| P8 | `threading.Lock` around state.json read/write. Single-process, no fs locking needed. |
| P9 | Failure isolation: mark repo `failed` in state, others continue. One retry on `subprocess.TimeoutExpired`. |
| P10 | `q` in review = graceful drain (no new starts, finish running, exit). |
| P11 | Ctrl+C = SIGTERM all running claude subprocs, mark in-flight as `pending` (resumable via `--resume`). |
| P12 | `--dry-run` orthogonal: parallel generation, skip push. |
| P13 | Per-repo `run.log` unchanged (each job writes own file in repo dir). |

## Implementation phases

### Phase 1 — Solo filter (no parallelism yet)

1. `src/fetch.py`: extend GraphQL with `isFork`. Add field to `Repo` dataclass.
2. New `src/contributors.py`: REST contributor fetch + bot filter + cache I/O.
3. New `src/filters.py`: pure predicates `is_solo(repo)`, `is_fork(repo)`, `has_readme(repo)`.
4. `src/selection.py`: filter state struct, key bindings (`s`/`F`/`r`), header rendering.
5. Tests:
   - Unit: bot regex, cache invalidation, predicate composition.
   - Integration: mocked GraphQL + REST, full pipeline yields filtered list.

### Phase 2 — Parallel pipeline

1. New `src/worker.py`: `WorkerPool` wrapping `ThreadPoolExecutor`. Submits `(clone, claude)` jobs, exposes completion queue.
2. `src/state.py`: add `threading.Lock` to `StateStore`. Audit all writers.
3. New `src/sandbox.py` (or extend launcher): per-job XDG dir helper.
4. `gh_readme_pipeline.py`:
   - Add `--parallel` flag, env override.
   - Replace serial loop with: pool.submit_all() → drain completion queue → review one-by-one.
   - Wire `q` (drain) and SIGINT (kill+pending-mark) handlers.
5. `src/ui/`: Rich `Live` status component above review prompt.
6. Tests:
   - Unit: pool order, queue FIFO, lock contention, retry on timeout, cancel-on-SIGINT.
   - Mock claude subprocess with `sleep + write stub README`.
   - Manual smoke: 3 real repos, `--parallel 3 --dry-run`.

## Files touched (estimate)

New:
- `src/contributors.py`
- `src/filters.py`
- `src/worker.py`
- `src/sandbox.py`
- `tests/test_contributors.py`
- `tests/test_filters.py`
- `tests/test_worker.py`

Modified:
- `src/fetch.py` — add `isFork`, contributor wiring
- `src/selection.py` — Repo dataclass fields, filter keys
- `src/state.py` — lock
- `src/review.py` — accept pre-generated draft instead of running claude inline
- `gh_readme_pipeline.py` — orchestrator rewrite
- `src/ui/*` — status line component
- `README.md` — flag docs, TUI key docs

## Open questions (deferred)

- Cache TTL upper bound? Currently keyed by `pushed_at` only; if user re-runs after stale push, contributor data ages. Acceptable for MVP.
- Anthropic rate-limit telemetry: surface 429 from claude subprocess output? Defer until first user hits it.
