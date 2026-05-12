# Go Port — Task List

Phased implementation plan for porting `writeme` (Python) to Go. Each phase is gated by a parity checkpoint against the Python reference. TDD throughout.

---

## Phase 0 — Pre-port

**Goal:** Lock toolchain, capture reference behavior, scaffold repo. No production code yet.

**Deliverables:**
- `docs/planning/go-port/golden/` — captured stdout/stderr/state-file fixtures from Python `writeme`.
- `docs/planning/go-port/decisions.md` — TUI lib choice, CLI lib choice, Go version, module path.
- Scaffolded Go module: `cmd/writeme/`, `internal/`, `go.mod`, `Makefile`, `.golangci.yml`, GH Actions skeleton.

**Tasks:**
1. Pin Go version (`1.23+`); set `go.mod` module `github.com/salamientark/writeme`.
2. Capture golden fixtures: run Python `writeme` with `--dry-run`, `--help`, `--resume`, mocked `gh`; snapshot stdout/stderr/exit codes/state JSON.
3. Decide TUI lib (see Risks); document tradeoffs; commit `decisions.md`.
4. Decide CLI lib: **`spf13/cobra`** (subcommand growth, env binding via `viper` optional) vs `flag` (stdlib, fewer deps). Recommend `cobra` only if subcommands appear; else stdlib `flag` + small env-binding helper.
5. Scaffold dirs: `cmd/writeme/main.go` (stub), `internal/{cli,state,sandbox,secrets,fetch,filters,worker,sandbox,selection,review,ui,diff,keys,pipeline}`.
6. Set up `golangci-lint`, `gofumpt`, `staticcheck`; CI workflow runs `go test ./... -race -cover` + lint.
7. Add `Makefile` targets: `test`, `lint`, `build`, `golden-update`, `release-snapshot`.
8. Decide config-file compat policy: env-var parity required, no TOML config in v1 (matches Python).

**Dependencies:** none.

**Parity checkpoint:** Golden fixtures committed; reproducible.

**Exit criteria:** `go build ./...` succeeds on stub; CI green; decisions doc merged.

---

## Phase 1 — Core skeleton (no TUI)

**Goal:** CLI surface, state store, sandbox paths, secrets redaction — everything that does not need a TTY.

**Deliverables:**
- `internal/cli` — flag parsing, env binding, exit codes.
- `internal/state` — JSON state file (resume support).
- `internal/sandbox` — XDG path layout, temp dirs, cleanup.
- `internal/secrets` — regex scanner (AWS/GH/OpenAI/private-key headers).
- `cmd/writeme` — wired entrypoint (TUI stubs return ErrNotImplemented).

**Tasks:**
1. Define `internal/cli.Config` struct + parser; mirror flags (`--mode`, `--dry-run`, `--repos-dir`, `--claude-timeout`, `--resume`, `--skip-ci`) and env vars (`LIMIT`, `GH_USER`, `COMMIT_MESSAGE`, `GH_README_REPOS_DIR`, `CLAUDE_TIMEOUT`, `SKIP_CI`).
2. Exit-code constants: `0 ok`, `1 generic`, `2 usage`, `3 sha-mismatch`, etc. — port from Python.
3. Port `state.py` → `internal/state`: load/save JSON, mark repo `processed|failed|skipped`, atomic write via tmp+rename.
4. Port `sandbox.py` → `internal/sandbox`: temp root, `XDG_*` overrides, cleanup hooks, signal trap.
5. Port `secrets.py` → `internal/secrets`: regex set + `Scan(content) []Finding` table-driven.
6. Port `safety.py` → `internal/safety`: blast-radius check via `git status --porcelain` parser.
7. Wire `cmd/writeme/main.go`: parse → init sandbox → init state → dispatch (TUI stubbed).
8. Table-driven unit tests for each package; port test cases from `tests/test_state.py`, `test_sandbox.py`, `test_secrets.py`, `test_safety.py`, `test_main.py`.

**Dependencies:** Phase 0.

**Parity checkpoint:**
- Golden: `writeme --help` byte-equivalent (or close + diff justified).
- Golden: `writeme --version`, exit codes for bad flags.
- Unit suites green: state, sandbox, secrets, safety.

**Exit criteria:** ≥80% coverage on Phase 1 packages; `go vet` + lint clean.

---

## Phase 2 — Data fetch

**Goal:** Repo + Contributor data via `gh` shell-out, with filters.

**Deliverables:**
- `internal/fetch` — `gh` wrapper, GraphQL repo listing, contributor enrichment.
- `internal/contributors` — model + parsing.
- `internal/filters` — name/regex/date/has-readme filters.
- `internal/unpushed` — local unpushed-commit detector.

**Tasks:**
1. Port `fetch.py` → `internal/fetch`: exec `gh` with timeout, parse JSON, typed `Repo` struct.
2. Port `contributors.py` → `internal/contributors`: parallel enrichment via `errgroup` (cap concurrency).
3. Port `filters.py` → `internal/filters`: predicate composition; range parser tests from `test_range_parser.py`.
4. Port `unpushed.py` → `internal/unpushed`: `git log @{u}..HEAD` wrapper.
5. Mock `gh` via PATH-injection test helper (`testdata/fakegh.sh`) for integration tests.
6. Port test suites: `test_fetch.py`, `test_contributors.py`, `test_filters.py`, `test_unpushed.py`, `test_range_parser.py`.

**Dependencies:** Phase 1.

**Parity checkpoint:**
- Mock-`gh` integration: same repo set + ordering as Python on identical fixture.
- Filter parity: every `test_filters.py` case ports green.

**Exit criteria:** All Phase 2 unit + integration tests green; coverage ≥80%.

---

## Phase 3 — Worker pool & sandbox isolation

**Goal:** Parallel review/generation workers, isolated git worktrees, cancellation.

**Deliverables:**
- `internal/worker` — bounded worker pool, task queue, result chan.
- `internal/sandbox` (extension) — per-repo worktree allocator.
- `internal/commit` — clone, commit, push, PR creation.

**Tasks:**
1. Port `worker.py` → `internal/worker`: `Pool` with `context.Context` cancellation, configurable concurrency, panic recovery.
2. Per-repo isolated dir under sandbox root; clean on success, retain on failure (gated by `NUKE_ON_FAIL`).
3. Port `commit.py` → `internal/commit`: clone (`--depth 1 --filter=blob:none`), branch, commit (verb auto-pick), push, `gh pr create`.
4. Claude subprocess invocation: `os/exec` with timeout (`CLAUDE_TIMEOUT`), capture to `run.log`.
5. Blast-radius gate wired into worker pre-ship.
6. Port test suites: `test_worker.py`, `test_commit.py`.

**Dependencies:** Phase 2.

**Parity checkpoint:**
- N parallel workers complete a 10-repo synthetic batch with matching state-file output vs Python.
- SIGINT mid-run leaves state file consistent (no partial entries).

**Exit criteria:** Race detector clean (`go test -race`); cancellation tests deterministic.

---

## Phase 4 — TUI selection screen

**Goal:** Interactive repo picker with filters, paging, multi-select.

**Deliverables:**
- `internal/keys` — symbolic key parsing, escape-sequence map.
- `internal/ui` — render layer (chosen TUI lib).
- `internal/selection` — selection state machine.

**Tasks:**
1. Port `keys.py` → `internal/keys`: `ReadKey` + `ReadKeyRaw`, escape-seq table (arrows, F-keys, mouse), terminal raw-mode toggle.
2. Port `selection.py` → `internal/selection`: cursor, page, filter, toggle, all/none — pure state machine, no IO.
3. Port `rich_ui.py` → `internal/ui`: render selection screen (header, rows, footer); chosen lib (bubbletea recommended — see Risks).
4. Filter input mode (`/` prefix → live filter) — port from `test_selection_filters.py`.
5. Plain-mode fallback (no TTY / `--no-tui`) → port from `test_plain_ui_select.py`.
6. Scripted-key TUI tests: feed key sequences, assert screen buffer (`vt10x` or string-buffer harness).
7. Port test suites: `test_selection.py`, `test_selection_filters.py`, `test_plain_ui_select.py`.

**Dependencies:** Phase 1 (state), Phase 2 (data).

**Parity checkpoint:**
- Scripted session: same final selection set as Python on identical input + repo fixture.
- Filter, paging, all/none verbs match.

**Exit criteria:** TUI tests green on Linux + macOS CI; manual smoke on real terminal.

---

## Phase 5 — TUI review screen

**Goal:** Per-repo diff review with mouse + chord keys.

**Deliverables:**
- `internal/diff` — diff render, fallback (no-color, no-pager).
- `internal/review` — review screen + key handling.

**Tasks:**
1. Port `diff.py` → `internal/diff`: parse `git diff`, color render, plain fallback.
2. Port `review.py` → `internal/review`: `accept/redo/discard/view/quit` keys, typed `yes` confirm for overwrite, typed `yes-i-checked` for secret override.
3. Mouse scroll handling (escape sequences from Phase 4 keys).
4. Long-diff paging.
5. Port test suites: `test_review.py`, `test_ui_diff.py`.

**Dependencies:** Phase 4.

**Parity checkpoint:**
- Diff render byte-identical (stripped of ANSI) on golden fixture.
- Key-sequence script reaches same review verdict as Python.

**Exit criteria:** Review tests green; mouse + resize handled without panic.

---

## Phase 6 — Pipeline glue

**Goal:** End-to-end flow combining fetch → select → worker → review → ship.

**Deliverables:**
- `internal/pipeline` — orchestration of all phases.
- Full `cmd/writeme` wiring: `pr`, `direct`, `commit-only`, `--resume`, `--clean`, `--dry-run`.

**Tasks:**
1. Top-level `Run(ctx, cfg)` orchestrator; lifecycle = init → fetch → select → loop(worker→review→ship) → cleanup.
2. `--resume`: skip repos already in state file with terminal status.
3. `--clean`: wipe sandbox + state file (interactive confirm).
4. `--dry-run`: no push/PR; everything else runs.
5. Mode prompt when `--mode` not provided (TTY only; error in non-TTY).
6. End-to-end integration test: fake `gh`, fake `claude`, real git on a tmp repo; assert state file + commits + PRs (via fake `gh`).
7. Port `test_e2e.py`, `test_main.py`.

**Dependencies:** Phases 1–5.

**Parity checkpoint:**
- Full e2e against Python: identical state file output, commit messages, PR titles/bodies on shared fixture.
- Exit codes match across all error paths.

**Exit criteria:** `test_e2e.py` ports green; `--resume` is idempotent; `--dry-run` performs zero writes outside sandbox.

---

## Phase 7 — Polish & release

**Goal:** Cross-platform binaries, docs, install path.

**Deliverables:**
- `goreleaser` config: linux/darwin/windows × amd64/arm64.
- `install.sh` updated for Go binaries (or kept as-is if launcher contract unchanged).
- `README.md` updated.
- `CHANGELOG.md`.

**Tasks:**
1. `.goreleaser.yaml`: archives, checksums, SBOM, signed releases.
2. CI release workflow: tag → build matrix → publish.
3. Update `install.sh` to download binary (replaces `uv run`); preserve `EXPECTED_SHA` SHA-pin contract.
4. Update README usage section; flag table; TUI controls; trim Python-specific bits.
5. Manpage generation (cobra has built-in, else `mango`).
6. Final `go-review` pass per package; address findings.
7. Smoke tests on Windows (TUI escape-seq is the risk surface).
8. Tag `v1.0.0-go.1`; ship.

**Dependencies:** Phase 6.

**Parity checkpoint:** All golden fixtures pass on all 6 platform/arch combos.

**Exit criteria:** Release artifacts published; `install.sh | bash` works on linux/mac fresh box; README accurate.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| TUI parity drift (Rich → bubbletea/tview) | Visual regressions, user friction | Pick **bubbletea + lipgloss** — Elm-arch + style primitives, best test story; capture Python ANSI fixtures in Phase 0; render-buffer assertions in tests. |
| Terminal escape sequences (mouse, resize, F-keys) on Windows | Crashes / dead keys | Use `golang.org/x/term` + bubbletea's input parser; explicit Windows smoke test in Phase 7; document plain-mode fallback. |
| Concurrency model differences (Python sync → Go goroutines) | Hidden races, surprising ordering | Default literal port (sequential where Python is sequential); add concurrency only in `internal/contributors` enrichment + `internal/worker`; `-race` mandatory in CI. |
| State-file format compat with existing Python users | Resume breaks | Same JSON shape, same field names; Phase 1 fixture-driven tests; doc-level statement of compat. |
| `gh` JSON shape changes between versions | Fetch breaks | Pin minimum `gh` version; defensive decoding with explicit error on unknown shape. |
| Claude subprocess timeout/cancellation semantics | Hangs, orphan processes | `exec.CommandContext` + process-group kill on Unix; Windows uses `Job` object; tested in Phase 3. |
| Goldens drift from Python over port duration | Late-stage parity surprises | Re-snapshot at start of each phase; CI job that re-runs Python and diffs (optional). |
| Single static binary expectation conflicts with `gh`/`claude`/`git` deps | User confusion | Doc clearly: writeme = single binary, but still requires `gh`, `claude`, `git` on PATH (same as Python). |

---

## TUI library choice (Phase 0 decision)

| Lib | Pros | Cons | Verdict |
|-----|------|------|---------|
| **bubbletea + lipgloss** | Elm arch → easy unit tests; large ecosystem (bubbles); active. | Re-render model differs from Rich; learning curve. | **Recommended.** Best test story for scripted-key parity tests. |
| tview | Widget-based, closer mental model to ncurses; built-in Form/List. | Harder to unit-test; less idiomatic Go state. | Fallback if bubbletea blocks. |
| lipgloss-only (custom loop) | Max control. | Re-implement input/redraw loop. | Reject — too much yak-shaving. |

---

## Skill / Agent usage per phase

| Phase | Primary skills | Slash / agents |
|-------|----------------|----------------|
| 0 Pre-port | `golang-patterns`, `brainstorming` | `architect`, `plan` |
| 1 Skeleton | `golang-patterns`, `golang-testing`, `tdd-workflow` | `tdd`, `go-test`, `go-build`, `go-review` |
| 2 Fetch | `golang-patterns`, `golang-testing` | `tdd`, `go-test`, `go-review` |
| 3 Workers | `golang-patterns` (concurrency), `golang-testing` | `tdd`, `go-test`, `go-review`, `go-build` |
| 4 Selection TUI | `golang-patterns`, `golang-testing` | `tdd`, `go-test`, `go-review` |
| 5 Review TUI | `golang-patterns`, `golang-testing` | `tdd`, `go-test`, `go-review` |
| 6 Pipeline | `golang-testing`, `e2e-testing` | `tdd`, `go-test`, `verify` |
| 7 Release | `create-readme`, `update-docs` | `go-review`, `security-review`, `open-pr` |

Per-phase loop: write failing test → implement → `/go-test` (coverage gate) → `/go-build` (lint/vet) → `/go-review` → commit. No phase exits without green parity checkpoint.
