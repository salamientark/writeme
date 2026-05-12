# test-plan.md — Go Port of `writeme`

Parity target: byte-equivalence with Python reference where feasible; semantic equivalence elsewhere.
Coverage gate: **≥80% per package** (`go test -cover`), enforced in CI.

---

## 1. Test Taxonomy

| Tier | Scope | Tooling | Location |
|------|-------|---------|----------|
| Unit | Pure functions, single struct, no IO | `go test`, table-driven, `testify` optional | `internal/<pkg>/*_test.go` |
| Integration | Cross-package; touches fs, git via stub `PATH`, fakes for `gh` | `go test`, `httptest` | `internal/<pkg>/*_integration_test.go` (build tag `integration`) |
| Golden | Snapshot stdout/stderr/state.json against Python reference | `goldie` or hand-rolled `-update` flag, `cmp.Diff` | `testdata/golden/<scenario>/` |
| CLI E2E | Full binary, real flags, exit codes, env vars | `rsc.io/script/scripttest` (testscript) | `cmd/writeme/testdata/script/*.txtar` |
| TUI | Scripted key sequences against selection/review screens | `github.com/charmbracelet/x/exp/teatest` (or equivalent for chosen TUI lib); for non-Bubble Tea path: `vt10x` + `expect` | `internal/ui/*_tui_test.go` |
| Concurrency | Race detector mandatory | `go test -race` | applies to all tiers; specific stress tests under `internal/state`, `internal/worker` |

Build tags: `// +build integration`, `// +build e2e`, `// +build tui` to keep `go test ./...` fast.

---

## 2. Per-Package Unit Test Targets

Mapping: `tests/test_X.py` → `internal/<pkg>/<file>_test.go`.

### `internal/selection` ← `src/selection.py`
Source map: `tests/test_selection.py` (553), `tests/test_selection_filters.py` (110), `tests/test_plain_ui_select.py` (92).

| Python class | Go test file | Behaviors |
|---|---|---|
| `TestRepoDataclass` | `repo_test.go` | constructor, default fields, immutability (struct copy semantics) |
| `TestSelectionStateConstruction` | `state_test.go` | initial cursor=0, no selections, viewport bounds |
| `TestToggle` | `state_test.go` | toggle add/remove, idempotence, returns new state (no mutation of input) |
| `TestMove` | `state_test.go` | up/down clamp, wrap policy if any, viewport scroll on edge |
| `TestSelectAllNone` | `state_test.go` | all/none operate on filtered set only |
| `TestVisibleSlice` | `viewport_test.go` | slice math against viewport_height, cursor_visible invariant |
| `TestHandleKey` | `keys_test.go` | every key dispatched correctly; unknown keys no-op |
| `TestImmutabilityInvariant` | `state_test.go` | every transition returns new value; deep equality of input preserved |
| `TestFilterAndJump` | `filter_test.go` | text filter narrows visible list, cursor jumps to first match, scroll viewport |
| `TestPredicateFilterFields` / `TestToggleSolo/Forks/Readme` | `filter_test.go` | solo/forks/readme predicates compose with text filter |
| `TestKeyDispatch` | `keys_test.go` | 's' / 'f' / 'r' toggle predicates |
| `TestSelectionPreservedAcrossToggles` | `filter_test.go` | toggling a filter never drops selections of hidden repos |
| `TestComposesWithTextFilter` | `filter_test.go` | AND semantics |
| `TestPlainUISelect` | `plain_test.go` | range parsing input, "all"/"none", invalid input rejected |
| `TestPlainUIStatusLine` | `plain_test.go` | status string format (selected/total/filters) |

### `internal/filters` ← `src/filters.py`
`tests/test_filters.py` (119) → `filters_test.go`: `IsSolo`, `IsFork`, `HasReadme`, `Apply` table-driven.

### `internal/state` ← `src/state.py`
`tests/test_state.py` (468) → `state_test.go`, `paths_test.go`, `concurrent_test.go`.
- `TestXdgCacheDir`/`TestXdgStateDir`: env precedence (`XDG_*`, `HOME` fallback).
- `TestStateStoreRecord`: append JSONL, fsync, line format.
- `TestStateStoreLoadProcessed`: dedup by repo name, last-wins.
- `TestStateStoreSummary`: counts by status.
- `TestPromptResume`: prompt text vs processed_count.
- `TestHasPriorState`: file existence + non-empty.
- `TestGhUserValidation`: stored user mismatch rejection.
- `TestStateStoreConcurrent`: **`go test -race`**, N goroutines `Record()` concurrently, all lines present, no truncation, valid JSON per line. Goroutine count ≥ 32.

### `internal/worker` ← `src/worker.py`
`tests/test_worker.py` (91) → `pool_test.go`.
- Submit/run/result ordering (stable per-input).
- Bounded concurrency (semaphore enforced — counter via atomic, max-in-flight ≤ N).
- Cancellation via `context.Context`; pending tasks not started, in-flight observe ctx.Done.
- Panic in worker → recovered, propagated as error result, pool keeps draining.

### `internal/safety` ← `src/safety.py`
`tests/test_safety.py` (268) → `safety_test.go`.
- `ValidateRepoName`: reject `..`, `/`, leading dash, length cap.
- `ValidateSSHURL`: only `git@host:owner/name.git` shape; reject shell metachars.
- `EnsureClean`: detects dirty worktree via `git status --porcelain`.
- `AcquireLock`: `flock` on lockfile; second call EAGAIN; release on close. Race test with two goroutines.

### `internal/secrets` ← `src/secrets.py`
`tests/test_secrets.py` (297) → `scan_test.go`.
- `ScanRepoForRiskyFiles`: matches `.env`, `*.pem`, `id_rsa`, `*.key`; respects `.gitignore` (if implemented).
- `ScanTextForSecrets`: regex matrix (AWS keys, GH PAT, generic high-entropy strings).
- Negative cases: docstrings, base64 not flagged unless entropy threshold.

### `internal/fetch` ← `src/fetch.py`
`tests/test_fetch.py` (648) → `fetch_test.go`, `pagination_test.go`.
- Single page: parse GraphQL response, build `Repo` slice.
- Pagination: cursor advance, stop on `hasNextPage=false`.
- Rate limit: respect `X-RateLimit-Remaining` / retry-after.
- README detection: presence of `README.md` node.
- Limit cap.
- User mismatch (token user ≠ requested).
- Disk preflight (free-space check).
- Repo name validation passes through to `safety`.
- Use **`httptest.Server`** to replay recorded `gh api graphql` responses.

### `internal/contributors` ← `src/contributors.py`
`tests/test_contributors.py` (155) → `contributors_test.go`.
- `IsBot` predicate matrix (dependabot, renovate, app suffix `[bot]`).
- `StripBots`.
- Cache roundtrip (gob/json on disk) keyed by repo+pushed_at.
- `FetchContributors` shells `gh` via injected runner; mock with fake binary on `PATH` or function var.
- `EnrichRepos` integrates fetch + cache.

### `internal/unpushed` ← `src/unpushed.py`
`tests/test_unpushed.py` (122) → `unpushed_test.go`.
- Real-git fixture: create repo, commit, set remote, scan; assert `unpushed=true` until `git push`.

### `internal/review` ← `src/review.py`
`tests/test_review.py` (931) → split into `review_test.go`, `pager_test.go`, `claude_test.go`, `redo_test.go`.
- Happy path: claude invoked, README written, accept prompt, baseline restored on discard.
- Non-zero exit / timeout from `claude` CLI.
- Blast radius guard (>N files modified → abort).
- Secret scan in generated README.
- Accept prompt accepts only typed `yes`.
- View toggle (diff vs README).
- Redo loop preserves baseline.
- Skill staging (copy CLAUDE skill files into worktree).
- **Env scrub**: process env passed to claude has secrets removed (golden-snapshot the resulting env map redacted).
- Pregenerated review path.

### `internal/commit` ← `src/commit.py`
`tests/test_commit.py` (882) → `commit_test.go`, `mode_test.go`, `push_test.go`.
- Mode prompt parsing (`pr` / `direct` / `commit-only` / `skip`).
- Verb selection (initial vs update README).
- `[skip ci]` flag injection.
- Commit message override + newline rejection.
- PR mode: `gh pr create` invocation, branch name template.
- Direct mode: push to default branch.
- Dry run: no git side effects (assert subprocess never called with mutating verbs).
- Push rejection handling.
- GPG signing warning emitted when configured.
- `CommitResult` field shape.

### `cmd/writeme` ← `tests/test_main.py` (892)
- `TestArgParsing` → flag tests using `flag.NewFlagSet`.
- `TestCleanFlag`, `TestUserMismatch`, `TestFlockBeforeWork`, `TestLimitCap`, `TestResumeIntegration`, `TestEmptySelectionShortCircuit`, `TestProcessRepo`, `TestMainOrchestration`, `TestFetchFailureHandling` → orchestration_test.go with stubbed deps via interfaces.

### `internal/ui/diff` ← `src/ui/diff.py`
`tests/test_ui_diff.py` (81) → `diff_test.go`: unified diff format, vs HEAD, vs prev.

### `internal/ui/range` ← `src/ui/range_parser.py`
`tests/test_range_parser.py` (88) → `range_test.go`: `1,3-5,7`, `all`, `none`, error cases.

### `cmd/writeme-install` ← `tests/test_install.py` (357)
Launcher/installer parity if shipped. Script tests under `cmd/writeme-install/testdata/script/`.

### `internal/sandbox` ← `src/sandbox.py`
`tests/test_sandbox.py` (57) → `sandbox_test.go`: `SandboxFor`, env var allowlist.

---

## 3. Golden Tests From Python Reference

### Procedure
1. Run Python with frozen fixtures (commit-pinned `tests/fixtures/`).
2. Capture: stdout, stderr, `state.json`/`state.jsonl`, generated README, redacted env.
3. Normalize non-deterministic fields with a documented filter (see Normalization).
4. Snapshot under `testdata/golden/<scenario>/{stdout,stderr,state.jsonl,...}`.
5. Go test runs same fixture through Go binary, applies same normalization, asserts byte-equality via `cmp.Diff`. `-update` flag re-records.

### Normalization Filters
- Timestamps → `<TS>` (regex `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z`).
- Tempdir paths → `<TMP>`.
- PIDs → `<PID>`.
- ANSI colour codes stripped for plain-stdout goldens; preserved for TUI render goldens.
- Hashes (commit SHAs from synthetic repos): `<SHA>`.

### Scenarios
| ID | Description | Inputs | Capture |
|----|-------------|--------|---------|
| `g-select-render-empty` | Selection screen, 0 repos | `repos.json` empty | TUI frame snapshot |
| `g-select-render-mixed` | 5 repos, one fork, one solo, one no-readme | `repos.json` | initial frame + after `f`, `s`, `r` toggle |
| `g-select-filter-text` | text filter "foo" narrows list | as above | frame post-filter |
| `g-select-multiselect` | space toggles, status line | as above | final frame |
| `g-state-after-run` | one success, one skip, one fail | recorded | `state.jsonl` byte-equal |
| `g-commit-msg-initial` | first README, default verb | repo fixture | rendered commit msg |
| `g-commit-msg-update` | existing README, update verb | repo fixture | rendered commit msg |
| `g-redacted-env` | env passed to claude with secrets present | env map | redacted dump |
| `g-readme-pager` | pager output for diff view | repo fixture | rendered text |
| `g-resume-prompt` | prompt text at N=3 processed | n=3 | stdout |
| `g-range-parser` | `1,3-5,all,none` cases | strings | parsed slices |

Recording script: `scripts/record-goldens.sh` (creates Python venv, runs scenarios, writes `testdata/golden/`).

---

## 4. CLI Integration Tests

Tooling: `rsc.io/script/scripttest`. One `.txtar` per scenario in `cmd/writeme/testdata/script/`.

Scenarios:
- `flags-help.txtar` — `--help` exit 0, snapshot.
- `flags-unknown.txtar` — unknown flag exit 2, message format.
- `env-precedence.txtar` — `WRITEME_*` env vs flag; flag wins.
- `dry-run.txtar` — `--dry-run` makes no fs/git mutations (assert via post-state diff).
- `resume.txtar` — pre-seed `state.jsonl`, `--resume` skips processed entries.
- `clean.txtar` — `--clean` removes cache + state, exits 0.
- `lock-busy.txtar` — second concurrent invocation exits with lock-held code.
- `gh-auth-missing.txtar` — friendly error, exit 1.
- `user-mismatch.txtar` — exit code distinct from auth error.

Exit code matrix documented in `spec.md`; tests assert each.

`PATH` is set to a shim dir (mirrors `tests/test_e2e.py::_make_shim_dir`) providing fake `git`, `gh`, `claude` binaries that read scripted responses.

---

## 5. TUI Tests

Driver: `teatest` if Bubble Tea is chosen, else PTY harness (`creack/pty` + `vt10x` terminal emulator) for byte-level frame assertions.

Coverage:
- Selection screen
  - `↓`/`↑` / `j`/`k` navigation; cursor stays in viewport.
  - `space` toggle; `a` all; `n` none.
  - `/` enter filter, type, `Esc` exit, results restored.
  - `s`/`f`/`r` predicate filters; status line update.
  - `PgUp`/`PgDn` scroll; cursor invariant.
  - `Enter` proceed → emits selection slice.
  - `q`/`Ctrl-C` cancel → exit 130.
  - Resize: SIGWINCH, viewport recomputes, no panic.
  - Mouse wheel (if supported) — same as PgUp/PgDn.
- Review screen
  - `v` view toggle (diff ↔ README).
  - `y` accept prompt requires typed `yes`.
  - `r` redo, `d` discard restores baseline.
  - Pager paging keys.

Each test: feed key script, assert final frame matches golden, OR assert state-machine output (preferred — frame goldens are brittle, use sparingly).

Escape sequence handling: include test for split CSI bytes across reads (split `\x1b` and `[A`).

---

## 6. Concurrency Tests

`go test -race` is mandatory in CI; failure blocks merge.

- `internal/state.StateStore`
  - 64 goroutines × 100 records each → 6400 valid JSON lines, no torn writes.
  - Mixed `Record` + `LoadProcessed` interleaved.
- `internal/worker.Pool`
  - Cancel mid-run: ctx cancelled at random offsets, all in-flight return ctx.Err, no goroutine leak (`goleak.VerifyNone`).
  - Bounded parallelism: atomic max-in-flight counter ≤ configured N over 10k tasks.
- `internal/safety.AcquireLock`
  - Two goroutines → exactly one acquires; second observes lock-busy.
- Cancelled-future analogue: a worker result that arrives after ctx cancel is dropped, not delivered to caller.

Tooling: `go.uber.org/goleak` for goroutine leak detection in TestMain.

---

## 7. Coverage Enforcement

```
go test -race -coverprofile=cover.out -covermode=atomic ./...
go tool cover -func=cover.out
```

CI gate (shell):
- Per-package threshold ≥80% via `gocover-cobertura` or custom script that fails on any package below threshold.
- Excluded: `cmd/*/main.go` (entrypoint glue), generated code, `testdata/`.
- Trend: HTML report uploaded as artifact on every PR.

---

## 8. Parity Checkpoints (gates between phases — phases defined in `task-list.md`)

| After phase | Gate (must pass) |
|---|---|
| P1 skeleton (cmd, flags, config) | CLI E2E `flags-help`, `flags-unknown`, `env-precedence` golden |
| P2 state + safety | `g-state-after-run` golden; `internal/state` race tests; lock tests |
| P3 fetch + contributors | `internal/fetch` httptest replay covers all paginated fixtures; user-mismatch path |
| P4 selection (headless) | `g-select-*` goldens via plain-UI driver; range parser tests |
| P5 review + commit | `g-commit-msg-*`, `g-redacted-env`, `g-readme-pager` goldens; review unit tests |
| P6 TUI | TUI tests green; resize + escape-sequence tests |
| P7 polish | All E2E txtar scenarios green; coverage ≥80% per package; `-race` clean |

A gate failing blocks the next phase from merging.

---

## 9. Fixtures

Committed under `testdata/` (small, deterministic):

- `testdata/repos/tiny-git/` — bare git repo bundle (`git bundle create`) loadable in tests; one commit, README absent.
- `testdata/repos/with-readme/` — bundle with existing README.
- `testdata/repos/with-unpushed/` — bundle simulating unpushed commits via two-bundle setup.
- `testdata/gh/graphql/single-page.json` — captured `gh api graphql` response.
- `testdata/gh/graphql/page-{1,2,3}.json` — paginated capture for cursor tests.
- `testdata/gh/contributors/*.json` — captured contributor responses incl. bot accounts.
- `testdata/state/seeded.jsonl` — preseeded state for resume tests.
- `testdata/env/with-secrets.env` — env map for redaction golden.
- `testdata/golden/<scenario>/...` — see §3.
- `cmd/writeme/testdata/script/*.txtar` — scripttest scenarios.
- `testdata/shims/{git,gh,claude}.sh` — fake binaries (mirrors `tests/test_e2e.py::_make_shim_dir`).

`gh` API replay: `httptest.NewServer` reading from `testdata/gh/`; client is constructed with a base URL injected via interface so tests swap it without env-poking.

Bundles unpacked into `t.TempDir()` per test; never mutate fixtures in place.
