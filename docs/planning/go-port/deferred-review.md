# Deferred Review Findings — feat-go-port

Tracked from internal review pass on 2026-05-07. Each entry: severity, location, summary, suggested approach.

## MEDIUM

### #15 — `promptReview` / `promptMode` misplaced
- **File**: `go/internal/pipeline/pipeline.go` (bottom of file)
- **Issue**: Inline prompt helpers belong in `internal/review` (review prompts) and `internal/commit` (mode prompt) per Python module layout (`src/review.py`, `src/commit.py`).
- **Approach**: Move during #4 review FSM rework — moving now produces throwaway code.

### #12 — SIGINT not honored during interactive prompts
- **File**: `go/internal/pipeline/pipeline.go` review loop (`promptReview`, `promptMode`)
- **Issue**: `bufio.Reader.ReadString` on `os.Stdin` blocks indefinitely. `signal.NotifyContext` cancels `ctx` but the prompt never wakes up — user must press Enter or type `q`/EOF.
- **Approach**: Run prompt read in goroutine; main loop `select`s on result chan vs `ctx.Done()`. Bundle with #4 review FSM rework (prompts will be moved to `internal/review` then anyway).

## HIGH

### #9 — StageSkill no path-traversal guard
- **File**: `go/internal/review/review.go:57`
- **Issue**: `StageSkill(repoDir)` accepts arbitrary string, has no internal assertion that `repoDir` falls under the configured `ReposDir`. Currently safe via caller (pipeline.go:204 + `fetch.decodeNode` validates repo name) but defense-in-depth missing.
- **Approach**: Thread `cfg.ReposDir` (or general allowed base) into `StageSkill` signature. Reject if `filepath.Clean(repoDir)` does not have base prefix. Cannot be solved by inline check alone — needs API change. Land alongside any review FSM refactor (#4).

### #4 — Review FSM stub (Phase 5)
- **File**: `go/internal/pipeline/pipeline.go:267-280`, `:206`
- **Issue**: `promptReview` only handles `a/r/d/q`. Missing: timeout retry, nonzero redo, blast-radius prompt, typed `yes` / `yes-i-checked` confirms, `PrevDraft` propagation across redo iterations. `pipeline.go:206` records `redo_unsupported_v1` — explicit gap.
- **Spec ref**: `docs/planning/go-port/data-model.md` §8
- **Approach**: New FSM in `internal/review` (~200 LOC + tests). Move `promptReview`/`promptMode` out of `pipeline.go`. Add `PrevDraft` field to `GenerationResult`. Land as standalone PR.
