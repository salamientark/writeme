# Deferred Review Findings — feat-go-port

Tracked from internal review pass on 2026-05-07. Each entry: severity, location, summary, suggested approach.

## Resolved on 2026-05-13 (branch `feat-review-fsm`)

All four deferred findings landed together as part of the Review FSM rework.

### #4 HIGH — Review FSM stub (Phase 5) — RESOLVED
- New `internal/review/fsm.go`: `Loop()` implementing full FSM with timeout-retry, nonzero-redo, blast-radius/failure exits, secret override (`yes-i-checked`), `had_readme_before` typed-`yes` gate, `PrevDraft` propagation across redo iterations.
- New `internal/review/prompts.go`: `StdinPrompter` plus `Prompter` interface; abstracts all prompts for FSM testability.
- `pipeline.go` no longer carries inline review/mode prompts; consumer loop now calls `review.Loop(...)`.
- 16 new FSM unit tests covering every transition + ctx-cancel path.

### #9 HIGH — `StageSkill` path-traversal guard — RESOLVED
- `StageSkill` signature changed: `StageSkill(basePath, repoDir string)`.
- Rejects when `filepath.Rel(basePath, repoDir)` resolves above base (returns `..` or `../…` prefix).
- `GenerateDraft` signature updated to plumb `basePath` through; pipeline passes `cfg.ReposDir`.

### #12 MED — SIGINT not honored during interactive prompts — RESOLVED
- `readLineCtx(ctx, *bufio.Reader)` reads on a goroutine and selects against `ctx.Done()`.
- `StdinPrompter` and `commit.PromptMode` both use ctx-aware reads.
- Background goroutine may leak until next byte arrives — acceptable since process exits on SIGINT.

### #15 MED — `promptReview` / `promptMode` misplaced — RESOLVED
- Review prompts → `internal/review/prompts.go` (`StdinPrompter`).
- Mode prompt → `internal/commit/prompt.go` (`commit.PromptMode`).
- `pipeline.go` no longer holds prompt helpers.
