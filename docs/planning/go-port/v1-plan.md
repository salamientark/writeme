# v1-plan.md — Go Port V1 Implementation Plan

V1 = phases 1, 2, 3, 6 of [`task-list.md`](task-list.md). TUI phases 4 & 5 deferred to v1.1 per [`decisions.md`](decisions.md) D2. Phase 0 is already complete (scaffolding + goldens captured under `go/`).

This document supersedes per-phase task expansion in `task-list.md` for v1 scope. It locks the design decisions resolved in the 2026-05-07 grill session and lays out the TDD-driven implementation order.

---

## 1. Decisions resolved in this session

Extends [`decisions.md`](decisions.md). Append these as G1–G11 to the locked-decisions table.

| # | Topic | Decision | Implication |
|---|-------|----------|-------------|
| G1 | V1 scope confirm | Phases 1, 2, 3, 6 only. Phases 4 & 5 (TUI) ship in v1.1. | Plain-mode UI is the only UI surface in v1. `internal/selection` stays render-free so v1.1 can wrap it in `tea.Model.Update` with no refactor. |
| G2 | SIGINT model | `signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)` at top of `main`. Ctx threaded through fetch, workers, subprocesses. `defer` summary print + `os.Exit(130)` when `ctx.Err() == context.Canceled`. | Single code path. `exec.CommandContext` kills children on cancel. State writes are mutex-guarded and synchronous, so no separate flush step. |
| G3 | Clock injection | `type Clock interface { Now() time.Time }` injected into `StateStore`. Production wires `realClock{}` (`time.Now().UTC()`); tests wire `fixedClock{ts}`. | State JSONL `ts` field is byte-reproducible in goldens (D1, D6). Touches only `internal/state`. |
| G4 | Fake binaries | Single Go test helper binary built via `TestMain`; dispatches on `filepath.Base(os.Args[0])` to fake `gh` / fake `claude` behavior. Fixtures driven by env vars (`WRITEME_FAKE_GH_FIXTURE`, `WRITEME_FAKE_CLAUDE_OUTCOME`, etc.). Tests symlink the test binary into a tmp dir prepended to `PATH`. | Replaces `testdata/fakegh.sh` (task-list.md Phase 2 task 5). Pure Go, debuggable, captures invocation argv to a log file for assertions. |
| G5 | Subprocess kill | `cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}`; on ctx cancel, `syscall.Kill(-cmd.Process.Pid, SIGKILL)`. Implemented in build-tagged `subproc_unix.go` (`//go:build linux \|\| darwin`). | Reaps `claude` + child node/MCP procs. V1 platforms = linux/darwin only — Windows build tag returns `errors.New("unsupported on windows")` from the helper; cmd never reaches it because release matrix excludes Windows in v1. |
| G6 | Plain-mode selection | Numbered list rendered to stdout; prompt: `Select repos (e.g. 1,3-5,8 or 'all'): `. Range parser ported from `tests/test_range_parser.py` cases. | Stateless, scriptable, CI-friendly. Empty input = `Nothing selected.` and `os.Exit(0)` (matches Python). |
| G7 | Plain-mode review serialization | One consumer goroutine drains the result channel (size = `len(jobs)`); per result, prints diff + `[a]ccept/[r]edo/[d]iscard/[q]uit` prompt; blocks on stdin until valid keypress; only then dequeues next. Workers continue producing in parallel. | Strict serial UI; throughput preserved by buffered chan. Matches Python single-threaded UI. |
| G8 | E2E parity check | Pre-recorded Python goldens only, captured once in Phase 0 against `v0-python-final` tag. Go e2e diffs Go output against committed fixtures. | No Python on CI. Re-record only on spec change. Matches D3, D6. |
| G9 | Coverage gate | Per-package gate enforced in CI: any `go/internal/*` package <80% line coverage fails the build. `cmd/writeme` excluded (thin wiring). | Phase exit criteria are per-package; aggregate-only gate would let weak packages hide. Implemented as awk script over `go test -coverprofile=cover.out ./...`. |
| G10 | Sandbox cleanup | Per-job XDG sandbox (`<repos-dir>/.sandbox/claude-jobs/<repo>/`) removed via `defer` after each repo regardless of outcome. Repo clone in `<repos-dir>/<repo>/` preserved across runs. Failure log written **before** cleanup. | `NUKE_ON_FAIL` is launcher-only per `spec.md` §5 — pipeline does not implement it. |
| G11 | Phase ordering | Strict sequential 1 → 2 → 3 → 6. No interleaving. | Each phase has a parity checkpoint, exit-criteria gate, and TDD loop (test → impl → `/go-test` → `/go-build` → `/go-review`). Clean review boundaries. |

---

## 2. V1 scope confirmed

**Ships:**

- CLI parsing, env binding, exit codes (`0` / `1` / `2` / `130`)
- State store (`state-<user>.jsonl`), resume, lock file
- Sandbox (per-repo XDG dirs), secrets scanner, safety (blast-radius, ssh-url validation, repo-name validation, `ensure_clean`)
- `gh` fetch (GraphQL repo paging), contributor enrichment, filters, unpushed-commit detector
- Worker pool (parallel `claude` invocation, `--parallel` flag clamped `[1,8]`)
- Commit / push / PR / direct / commit-only / dry-run modes
- Plain-mode UI: index-range selection, `a/r/d/q` review prompt, summary block
- Diff parser (plain text output only — no color)
- Failure-only `run.log`
- E2E test with fake `gh` + fake `claude` + real `git` on tmp repo
- Linux + macOS binaries (amd64 + arm64)

**Defers to v1.1:**

- Bubbletea TUI (selection + review)
- Diff color rendering, long-diff paging
- Windows binary
- TUI escape-sequence / raw-mode handling (`internal/keys`)

---

## 3. Package responsibilities (V1)

```
go/
├── cmd/writeme/main.go              # parse → init → pipeline.Run
└── internal/
    ├── cli/         # flag parsing, env binding, precedence rules
    ├── state/       # JSONL store, Clock, lock file, resume aggregation
    ├── sandbox/     # XDG path resolution, per-job sandbox tree, cleanup
    ├── secrets/     # text scanner (regex set) + risky-file glob walker
    ├── safety/      # validate_repo_name, validate_ssh_url, ensure_clean, acquire_lock, blast-radius
    ├── fetch/       # gh GraphQL paging, repo decode, LIMIT cap+warning
    ├── filters/     # name/regex/date/has-readme/is-solo predicates, range parser
    ├── contributors/# parallel REST enrichment via errgroup, on-disk cache
    ├── unpushed/    # git log @{u}..HEAD scanner, dirty-tree detector, exit-2 driver
    ├── worker/      # bounded errgroup+sema pool, FIFO result chan, panic recovery
    ├── commit/      # clone/fetch/branch/commit/push/PR; verb auto-pick; gpgsign warn
    ├── review/      # claude subproc invocation, env scrubbing, embedded SKILL.md, pgid kill
    ├── diff/        # parse `git diff`, plain text render
    ├── selection/   # render-free state machine: numbered list, range parser dispatch
    └── pipeline/    # orchestrator: fetch → select → worker→review→ship loop → cleanup
```

`internal/keys` and TUI render packages are **not** created in v1.

---

## 4. Phase 1 — Core skeleton (no UI yet)

**Goal:** All non-UI primitives. Pipeline can `go build` end-to-end but the orchestrator stub returns `ErrNotImplemented`.

**Packages:** `cli`, `state`, `sandbox`, `secrets`, `safety`.

### Phase 1 task list

1. **`internal/cli`**
   - `Config` struct mirrors `spec.md` §1 flags + `LIMIT`, `GH_USER`, `COMMIT_MESSAGE` env-only options.
   - `Parse(args []string, env Env) (Config, error)` returns config + error; pure, no globals.
   - Helper `envOr[T any](flagSet *flag.FlagSet, name, envVar string, parse func(string) (T, error), defaultVal T) T` — implements precedence (flag wins when explicitly set; else env when valid; else default).
   - `--parallel` clamp `[1,8]`; `LIMIT` cap `1000` with silent fallback to `500` on invalid env (per spec §1).
   - Tests: cover every row of the precedence table.

2. **`internal/state`**
   - `Clock` interface (G3); `realClock` + `fixedClock` test helper.
   - `Store` struct: `New(user string, dir string, clock Clock) (*Store, error)` validates user against GH regex.
   - `Record(repo, status string, opts RecordOpts) error` — append-only, mutex-serialized, `mkdir -p` on first write, `flush` after `write`. No fsync, no rename.
   - `LoadProcessed() (map[string]Record, error)` — last-record-wins; malformed lines silently skipped.
   - `Summary() Summary` — counts per status + PR URLs + failure list.
   - `PromptResume(stdin io.Reader, stdout io.Writer, processedCount int) (ResumeChoice, error)` — `r/a/s/q`, loops on invalid.
   - Goldens: replay Phase 0 captured `state-testuser.jsonl` round-trip + diff.

3. **`internal/sandbox`**
   - `Paths` struct: `XDGCacheDir()`, `XDGStateDir()`, `ReposDir(cfg)`, `LockFile(stateDir)`, `JobDir(reposDir, repo)` — pure path functions.
   - `JobSandbox(reposDir, repo string) (*Job, error)` creates `config/data/cache/state` subdirs and returns a `Cleanup() error` closer.
   - `EnvFor(job *Job) []string` returns `XDG_*` overrides for claude subprocess (per `spec.md` §5).
   - Tests: `XDG_*HOME` set / unset matrix; permission errors propagate.

4. **`internal/secrets`**
   - `Scan(content string) []Finding` — regex set from `spec.md` §5; table-driven.
   - `WalkRiskyFiles(repoDir string) ([]string, error)` — glob patterns from `spec.md` §5.
   - Tests: ports `tests/test_secrets.py` cases verbatim into table form.

5. **`internal/safety`**
   - `ValidateRepoName(name string) error`, `ValidateSSHURL(url string) error` — regex per `spec.md` §7.
   - `EnsureClean(ctx, repoDir string) error` — runs `git reset --hard HEAD`, `git clean -fd`, removes `MERGE_HEAD`/`CHERRY_PICK_HEAD`/`REBASE_HEAD`.
   - `AcquireLock(path string) (release func() error, err error)` — `syscall.Flock(LOCK_EX|LOCK_NB)`; `errors.Is(err, ErrLocked)` exposed.
   - `BlastRadius(ctx, repoDir string) ([]string, error)` — parses `git status --porcelain -z`; returns sorted list of touched paths excluding `README.md`. Empty result = clean to ship.
   - Tests: ports `tests/test_safety.py` + a fake-git harness for `EnsureClean`.

6. **`cmd/writeme/main.go`**
   - `signal.NotifyContext` wiring (G2).
   - Resolve user → init store → acquire lock → call `pipeline.Run(ctx, cfg, store)` (currently returns `ErrNotImplemented`).
   - Defer summary print + `os.Exit` mapping (status → exit code).

### Phase 1 parity checkpoint

- `writeme --help` byte-equivalent against captured Python `--help` golden (allow trailing-whitespace + line-wrap deltas, documented in goldens README).
- Bad-flag exit code = `2`; help exit code = `0`.
- State JSONL round-trip: write 4 records via fixed clock → read back via `LoadProcessed` → re-emit → byte-diff against golden.

### Phase 1 exit criteria

- All Phase 1 packages ≥80% coverage (G9).
- `go vet ./...` + `golangci-lint run` clean.
- `go test -race ./...` green.

---

## 5. Phase 2 — Data fetch

**Goal:** Repo + contributor data via `gh` shell-out. Filtering. Unpushed-commit detection.

**Packages added:** `fetch`, `contributors`, `filters`, `unpushed`.

### Phase 2 task list

1. **`internal/fetch`**
   - `Fetcher` interface: `ListRepos(ctx, user string, limit int) ([]Repo, error)`.
   - `GHFetcher` impl: shells out to `gh api graphql -f query=<...> -F login=... -F first=... [-F after=...]`; loops on `pageInfo.endCursor`; decodes via `encoding/json` into typed structs.
   - LIMIT re-cap inside `ListRepos` with stderr warning, matching `src/fetch.py:203-208`.
   - Disk-budget warning at 80% threshold (matches Python).
   - Rate-limit sleep: parses `X-RateLimit-Remaining` from `gh api` errors and sleeps until reset (matches Python).
   - `--depth=1 --filter=blob:none` clone happens in commit pkg, not here.

2. **`internal/contributors`**
   - `Enricher` interface; `GHEnricher` impl uses `errgroup` with bounded concurrency (default 4).
   - On-disk cache `<repos-dir>/.contributors.json` keyed by `name@pushed_at`; format JSON `map[string][]string`.
   - Cache hit short-circuits REST call; miss → `gh api repos/<owner>/<repo>/contributors` → filter bots → write back.

3. **`internal/filters`**
   - `Predicate func(Repo) bool` composition: `And`, `Or`, `Not`.
   - Concrete predicates: `ByName(pattern)`, `ByRegex(re)`, `ByDateAfter(t)`, `HasReadme()`, `IsSolo()`, `Limit(n)`.
   - `ParseRange(input string, total int) ([]int, error)` — port of `tests/test_range_parser.py`. Used by selection too.

4. **`internal/unpushed`**
   - `Scan(ctx, reposDir string) ([]Finding, error)` — for each subdir with `.git/`, run `git log @{u}..HEAD --oneline` (count) + `git status --porcelain` (dirty check). Fan-out via errgroup.
   - Returns sorted findings; consumer maps to exit code 2 + stderr block per `spec.md` §3.

5. **Fake gh testbinary**
   - Build helper: `TestMain` in `internal/fetch/fake_gh_test.go` checks `os.Getenv("WRITEME_FAKE_GH")` and dispatches.
   - Fixtures: GraphQL response JSON files under `internal/fetch/testdata/gh/`.
   - Logs argv to `WRITEME_FAKE_GH_LOG` for assertion.

### Phase 2 parity checkpoint

- Fixture-driven integration: same repo set + same ordering as Python golden on the captured GraphQL response.
- Filter cases from `tests/test_filters.py` ported green.
- Range parser: every case from `tests/test_range_parser.py` green.

### Phase 2 exit criteria

- All Phase 2 packages ≥80%.
- Race-clean.

---

## 6. Phase 3 — Worker pool, commit, review

**Goal:** Parallel `claude` execution, isolated sandbox per worker, blast-radius gate, commit/push/PR.

**Packages added:** `worker`, `commit`, `review`, `diff`.

### Phase 3 task list

1. **`internal/worker`**
   - `Pool[Job, Result any]` with `errgroup.Group` + `semaphore.Weighted`.
   - `Submit(jobs []Job, fn func(ctx, Job) Result) <-chan Result` — buffered chan size `len(jobs)`; emits in finish-order; per-worker `defer recover()` converts panic → `Result` with `err = PanicErr`.
   - Cancellation: external ctx cancellation drains in-flight goroutines; chan closes after all return.
   - Tests: race-clean with `-race`; cancellation deterministic (use `make(chan struct{})` to gate).

2. **`internal/review`**
   - `//go:embed embedded/SKILL.md` (D10).
   - `StageSkill(repoDir string) (cleanup func(), err error)` — writes embedded blob to `<repoDir>/.claude/skills/create-readme/SKILL.md`.
   - `Run(ctx, repoDir string, sandboxEnv []string, timeout time.Duration) (Outcome, error)` — invokes `claude -p /create-readme --permission-mode acceptEdits`; sets `Setpgid: true`; on `ctx.Done()` or timeout, `syscall.Kill(-pid, SIGKILL)` (G5).
   - Env scrubbing: allowlist from `spec.md` §5.
   - On nonzero / timeout / blast-radius: write `<state_dir>/failures/<repo>-<unix>.log` with stdout+stderr+timing (D9).

3. **`internal/diff`**
   - `Plain(ctx, repoDir string) (string, error)` — `git diff --no-color README.md`.
   - V1 = no color, no paging.

4. **`internal/commit`**
   - `Clone(ctx, sshURL, dir string) error` — `git clone --depth=1 --filter=blob:none`.
   - `Fetch(ctx, dir string) error` — `git fetch --depth=1` for existing clones.
   - `Commit(ctx, dir, msg string, hadReadme bool) error` — verb = `update`/`add`; rejects CR/LF in `COMMIT_MESSAGE`.
   - `PushDirect(ctx, dir string) error`, `PushBranch(ctx, dir, branch string) error`.
   - `OpenPR(ctx, dir, title string) (string, error)` — `gh pr create`; returns trimmed stdout as URL.
   - `BranchName(now time.Time) string` — `docs/readme-pipeline-<unix>`.
   - GPG-sign warning probe via `git config commit.gpgsign` → stderr.
   - Pre-ship blast-radius gate: calls `safety.BlastRadius`; non-empty (excluding `README.md`) → `claude_touched_other_files` failure.

5. **Fake claude testbinary**
   - Same dispatch pattern as fake `gh`; outcomes via `WRITEME_FAKE_CLAUDE_OUTCOME=success|nonzero|timeout|secret|other_files`.
   - Fixtures write a deterministic README.md (or other files for the bad cases).

### Phase 3 parity checkpoint

- Synthetic 10-repo batch with `--parallel=3` produces same state-file output as Python `--parallel=1` golden when run with deterministic fake claude (assert on set equality + sorted summary; finish-order non-deterministic per D6).
- SIGINT mid-run: state file consistent (no torn lines), exit 130, summary printed.

### Phase 3 exit criteria

- All Phase 3 packages ≥80%.
- `go test -race ./...` green.
- Cancellation tests deterministic.

---

## 7. Phase 6 — Pipeline glue

**Goal:** End-to-end `Run(ctx, cfg, store)` orchestrator wired in `cmd/writeme/main.go`.

**Packages added:** `pipeline`, `selection`.

### Phase 6 task list

1. **`internal/selection`**
   - `RenderPlain(w io.Writer, repos []Repo)` — numbered list.
   - `Prompt(stdin io.Reader, stdout io.Writer, total int) ([]int, error)` — `1,3-5,8,all,quit`. Reuses `filters.ParseRange`.
   - Pure state-machine; no TTY assumption. v1.1 will wrap this in bubbletea.

2. **`internal/pipeline`**
   - `Run(ctx, cfg Config, store *state.Store) (Summary, error)` — full lifecycle:
     1. Resolve user (`gh api user --jq .login` vs `GH_USER` env; mismatch prompt → exit 1 if not `y`).
     2. Acquire lock; defer release.
     3. Fetch repos (filters applied).
     4. Enrich contributors (parallel).
     5. If `--resume` and prior state exists → `state.PromptResume`.
     6. Render selection → prompt user.
     7. Spawn worker pool sized to `cfg.Parallel`; submit selected repos.
     8. Single consumer goroutine drains result chan; for each result, prints diff, prompts review (`a/r/d/q`), dispatches ship action (`commit.PushDirect` / `commit.PushBranch` + `commit.OpenPR` / commit-only / discard).
     9. After all results consumed → run `unpushed.Scan` → if findings, exit 2.
     10. Print `--- Summary ---` block.
   - `--dry-run`: skip `git push` and `gh pr create`; everything else runs.
   - `--clean`: `os.RemoveAll(reposDir)`; interactive `[y/N]` confirm before; exit 0.
   - Mode prompt (`--mode` unset, no UI): `[p]/[m]/[c]/[n]` per repo from stdin.

3. **`cmd/writeme/main.go` final wiring**
   - All flags routed to `cli.Parse`.
   - Exit code mapping: `pipeline.Run` returns typed errors → `errors.Is` switch → exit code.

4. **E2E test**
   - `go/internal/pipeline/e2e_test.go` — sets up tmp repos-dir, fake `gh` + fake `claude` on PATH, real `git` on tmp bare repo as origin. Drives full pipeline end-to-end. Asserts:
     - State JSONL byte-equal to golden.
     - Summary block byte-equal to golden.
     - Commits land in tmp bare repo with expected messages.
     - PR-mode produces branch `docs/readme-pipeline-<unix>` (regex match on unix portion).

### Phase 6 parity checkpoint

- Full e2e goldens match Python on shared fixture (state JSONL byte-exact; summary block byte-exact, modulo finish-order in parallel mode → re-record at `--parallel=1`).
- Exit codes match `spec.md` §2 across all paths: success, no-user, fetch-error, unpushed-dirty, SIGINT.

### Phase 6 exit criteria

- E2E test green on linux + macOS CI.
- `--resume` idempotent (run twice produces same state).
- `--dry-run` writes zero outside `<repos-dir>` and `<state-dir>` (verified by snapshotting tmpdirs).
- Coverage ≥80% on `pipeline` and `selection`.

---

## 8. Cross-cutting concerns

### Logging

- No structured logger in v1. `log.SetFlags(0)` + write directly to stderr for warnings (matches Python).
- Failure-only `run.log` per D9 lives at `<state_dir>/failures/<repo>-<unix>.log`.

### Error types

- Each package defines a small set of sentinel errors (`var ErrFoo = errors.New("...")`).
- Pipeline maps sentinels to exit codes via `errors.Is`.

### Environment scrubbing

- `internal/review.Run` allowlists `PATH HOME USER LOGNAME SHELL LANG TERM TMPDIR` + prefixes `CLAUDE_`, `LC_`, `XDG_` (per `spec.md` §5).
- All other env vars dropped before invoking `claude`.

### Goroutine ownership

- Lifecycle owner = `pipeline.Run`. All goroutines spawned via `errgroup.WithContext` rooted at the top-level ctx.
- Per-repo subprocesses inherit ctx; `Setpgid` ensures kill on cancel.

### Test hygiene

- Every test that touches process state uses `t.TempDir()` and `t.Setenv()`.
- No reliance on real `gh`, real `claude`, or network.
- Fake binaries built once in `TestMain`; symlinked into per-test PATH dirs.

### CI matrix (v1)

| OS | Arch | Job |
|----|------|-----|
| ubuntu-latest | amd64 | `go test -race -cover` + lint + coverage gate |
| macos-latest | arm64 | `go test -race -cover` |

Windows excluded in v1 (G5, scope D2).

---

## 9. Implementation order (TDD per phase)

For each package within a phase, the loop is:

1. Write failing table-driven test.
2. Implement minimal code.
3. `/go-test` (coverage gate).
4. `/go-build` (vet + lint).
5. `/go-review` (idiomatic Go, concurrency, error handling).
6. Commit.

No phase exits without:

- Green parity checkpoint.
- ≥80% per-package coverage.
- `-race` clean.
- Lint clean.

---

## 10. Risks tracked into v1

| Risk | Phase | Mitigation |
|------|-------|------------|
| Goldens drift between Phase 0 capture and v1 ship | All | Re-snapshot at start of each phase if Python freeze breaks (D3 says it won't). |
| `gh` JSON shape changes | 2 | Defensive decoding; explicit error on unknown shape; minimum gh version pinned in README. |
| `claude` orphan procs after kill | 3 | Setpgid + pgid kill (G5); test with fake claude that spawns child sleep. |
| State file torn writes under SIGINT | 1, 3, 6 | Single `Write([]byte(json+"\n"))` is atomic on POSIX for sub-PIPE_BUF sizes; lines are well below. Tested via fault-injection test. |
| Plain-mode UX regression vs Rich UI | 6 | D2 explicitly drops Rich parity in v1; stakeholder = solo (Jay Moker) accepts. |
| Disk leak in per-job XDG sandbox | 3 | Always-cleanup (G10) verified by tmpdir snapshot test. |

---

## 11. Out of scope for v1

- Bubbletea TUI (selection + review screens).
- `internal/keys` package.
- Diff coloring, paging, mouse support.
- Windows binaries.
- Manpage generation (mango).
- `goreleaser` config (deferred to v1.1 release prep).
- `install.sh` rewrite — Python launcher remains the install path until v1.1 cutover (D8).

---

## 12. v1 ship gate

- All four phases (1, 2, 3, 6) at exit criteria.
- E2E goldens green on linux + macOS CI.
- `go build ./cmd/writeme` produces a single static binary on both platforms.
- Manual smoke run on a real GitHub account against ≥3 repos with `--dry-run`, then 1 repo without.
- Tag `v1.0.0-go.1` off `feat-go-port` per D8. Python `install.sh` remains primary distribution until v1.1.
