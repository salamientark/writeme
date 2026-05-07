# decisions.md — Go Port Locked Decisions

Outcome of grill-me session against [`go-port-plan.md`](../go-port-plan.md). Each row is binding for implementation; revisit only with explicit decision overturning the entry.

Reference contract docs: [`spec.md`](spec.md), [`data-model.md`](data-model.md), [`task-list.md`](task-list.md).

---

## Locked decisions

| # | Topic | Decision | Implication |
|---|-------|----------|-------------|
| D1 | Parity bar | **Functional + state-file byte-exact.** State JSONL (`state-<user>.jsonl`) and stdout `--- Summary ---` block must diff-clean vs Python on identical input. Everything else (warnings, prompts, TUI rendering) is functional only. | Resume compatibility preserved for existing users. TUI free to redesign in v1.1. Goldens captured for the two byte-exact surfaces only. |
| D2 | TUI scope & sequencing | **v1 = plain-mode only. v1.1 = bubbletea TUI** (selection + review). | Cuts ~30% of v1 work. Phases 4 & 5 of `task-list.md` deferred to v1.1. Pipeline interfaces designed so TUI is a presentation layer over the plain-mode core — no refactor required to bolt on bubbletea. |
| D3 | Python coexistence | **Freeze Python at commit `f1b156c`. Tag `v0-python-final`.** No further Python features or bugfixes during the port (solo project; no active blocked users). | Goldens captured once and stable. CI does not need Python after Phase 0 fixture capture. Re-thaw only if Go port abandoned. |
| D4 | Repo layout | **Go lives in `go/` subdir.** Module path `github.com/salamientark/writeme` (matches origin). Python stays untouched at root until v1.1 merge. | Build command: `cd go && go build ./cmd/writeme`. CI runs both Python tests (pinned, unchanged) and Go tests until cutover. Single `git rm -r src/ tests/ gh_readme_pipeline.py pyproject.toml` at v1.1 merge. |
| D5 | CLI library | **Stdlib `flag`** + small env-binding helper. No cobra/urfave. | Spec §1 has no subcommands and 8 flags. Env precedence rule ("flag wins when not nil; env wins over default; invalid env → fall back to default") implemented in helper: `envOr(flagSet, name, envVar, defaultVal)`. Manpages deferred (mango if ever wanted). |
| D6 | Golden fixture mechanism | **Hybrid, per-package testdata.** Record state JSONL + stdout summary block from Python *once* in Phase 0 → commit as static fixtures under `go/internal/<pkg>/testdata/golden/`. Everything else hand-written from spec citations. | Avoids Python-on-CI dep. Re-record only on spec change. Timestamps normalized via injected clock in Go (`time.Now` → `clock.Now()` interface). Parallel-mode goldens captured at `--parallel=1` only; race tests assert set-equality not order. Fake `gh` via `testdata/fakegh.sh` injected on `PATH`. |
| D7 | Worker pool primitives | **`golang.org/x/sync/errgroup` + bounded semaphore + bounded result chan.** No custom pool struct. | ~30 lines vs ~80. Cancellation = `errgroup` ctx. Per-worker `defer recover()` for panic → FailedTuple. Result chan size = `len(jobs)`; consumer reads in finish-order (FIFO) per `data-model.md` §6 contract. |
| D8 | Cutover timing | **Merge `feat-go-port` → `main` at v1.1 release** (TUI parity complete). Tag `v1.0.0-go.1` (plain) and `v1.1.0-go.1` (TUI) off the branch via GitHub Releases for early adopters. | `install.sh` stays on Python `uv run` path until v1.1 merge — existing users unaffected. No merge drift risk because main is feature-frozen (D3). |
| D9 | Claude subprocess logging | **Failure-only `run.log`.** On `nonzero` / `timeout` / `blast_radius` outcomes, dump captured stdout+stderr+timing to `<state_dir>/failures/<repo>-<unix>.log`. Success runs write nothing (Python parity). | Diverges from Python by adding the failure log file; not part of contract per D1. No retention policy — user manages cache. State JSONL `error` field stays the one-line summary; the log is the long-form companion. |
| D10 | Embedded SKILL.md | **Canonical source moves to `go/internal/review/embedded/SKILL.md`.** During freeze period, repo-root `.claude/skills/create-readme/SKILL.md` is a symlink → `../../go/internal/review/embedded/SKILL.md`. Embed via `//go:embed embedded/SKILL.md`. | At v1.1 merge, drop the symlink + Python — file already canonical under `go/`. Zero drift, zero build choreography, single-binary distribution preserved. |
| D11 | TUI library (v1.1) | **`bubbletea` + `lipgloss`.** Locked now in Phase 0 even though not used until Phase 4–5 in v1.1 cycle. | `internal/selection` package MUST stay render-free in v1. Plain-mode v1 calls state-machine functions directly; v1.1 wraps the same functions in a `tea.Model.Update`. No state-machine refactor on the v1→v1.1 hop. |
| D12 | Go version | **Pin Go `1.23`.** | Broadest install footprint. Bump only when a 1.24+ feature is actually needed. |
| D13 | Module path identity | **`github.com/salamientark/writeme`.** Confirmed: `salamientark` GH owner = Jay Moker (origin remote, sole committer). | All package imports `github.com/salamientark/writeme/internal/...`. |
| D14 | Test port style | **Go-idiomatic table-driven.** Cover the same cases as the Python pytest suites, rewrite into table-driven `t.Run(name, ...)` form. No 1:1 file-shape preservation. | `tests/test_*.py` → `go/internal/<pkg>/<feature>_test.go` with `cases := []struct{...}{...}`. Coverage gate ≥80% per Phase exit criteria. |

---

## v1 scope (definitive)

**Ships in v1** (phases 0, 1, 2, 3, 6 of `task-list.md`):

- CLI parsing, env binding, exit codes (`0`/`1`/`2`/`130`)
- State store (`state-<user>.jsonl`), resume, lock file
- Sandbox (per-repo XDG dirs), secrets scanner, safety (blast-radius, ssh-url validation)
- `gh` fetch (GraphQL repo paging), contributor enrichment, filters
- Worker pool (parallel `claude` invocation, `--parallel` flag clamped `[1,8]`)
- Commit / push / PR / direct / commit-only / dry-run modes
- Plain-mode UI: index-range selection, `a/r/d/q` review prompt, summary block
- Diff parser (plain text output only — no color)
- Failure-only `run.log`
- E2E test with fake `gh` + fake `claude` + real `git` on tmp repo
- Linux + macOS binaries (amd64 + arm64)

**Defers to v1.1** (phases 4, 5):

- Bubbletea TUI selection screen (cursor, paging, multi-select, live filter, toggles)
- Bubbletea TUI review screen (diff viewer, mouse scroll, chord keys)
- Diff color rendering, long-diff paging
- Windows binary
- TUI escape-sequence/raw-mode handling (`internal/keys`)

---

## Phase 0 deliverables (immediately actionable)

1. Tag `v0-python-final` at `f1b156c` on `main`. (D3)
2. Create `go/` subdir; `go mod init github.com/salamientark/writeme`; pin Go `1.23`. (D4, D12, D13)
3. Scaffold `go/cmd/writeme/main.go` (stub `os.Exit(0)`); `go/internal/{cli,state,sandbox,secrets,safety,fetch,filters,contributors,worker,commit,review,selection,diff,pipeline}` empty packages. (D4)
4. Move `.claude/skills/create-readme/SKILL.md` → `go/internal/review/embedded/SKILL.md`; replace original path with symlink. (D10)
5. Capture goldens via Python on synthetic fixture: state JSONL + summary block at `--parallel=1`. Commit under `go/internal/<pkg>/testdata/golden/`. (D6)
6. `go/Makefile`: `test`, `lint`, `build`, `golden-update`. CI workflow runs `go test ./... -race -cover` + `golangci-lint`. (D6)
7. `decisions.md` (this file) committed.

Exit Phase 0 when: `go build ./...` green on stub; CI green; goldens reproducible from `make golden-update`.
