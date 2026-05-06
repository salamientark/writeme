# Go Port — Documentation Plan & Remarks

Reference doc for reimplementing `writeme` (Python) in Go. Use as input to a brainstorming session before writing any code.

## Domain / Field

- **Software re-engineering** — cross-language port (Python → Go).
- **Behavior-preserving migration** — output parity with reference implementation.
- **Spec-driven development** — write specs first, then implement.
- Sub-areas: **CLI/TUI design**, **developer tooling**, **systems programming**.

## Assessment of Proposed 3-Doc Approach

Three docs (design, architecture, UI) is a solid base but **not sufficient on its own** for a clean port. Gaps:

- No explicit user-facing contract (flags, exit codes, IO).
- No concrete data model / file formats — Go needs typed structs upfront.
- No test plan to verify parity with the Python reference.
- "Features list" alone is too thin for acceptance criteria.

## Recommended Document Set

### 1. `design.md` (was: design)
- Project description, goals, non-goals.
- Feature list with **user stories** + **acceptance criteria**.
- Edge cases and error scenarios.
- Out-of-scope items.

### 2. `architecture.md` (was: architecture)
- Module / package layout (`cmd/`, `internal/`, `pkg/`).
- Dependency graph between packages.
- Concurrency model (goroutines, channels, cancellation).
- External integrations (git, file system, terminal).
- Error handling strategy (sentinel errors, wrapping).
- Build / release toolchain.

### 3. `ui.md` (was: UI)
- Screens / modes with ASCII mockups.
- Keybindings table (per mode).
- Render states (loading, empty, error, filtered).
- Terminal capability assumptions (TTY detect, color, mouse, resize).
- Accessibility (plain mode, ASCII-only fallback).

### 4. `spec.md` *(NEW — required)*
- CLI flags, subcommands, exit codes.
- stdin / stdout / stderr contracts.
- Config file schema and discovery rules.
- Environment variables.
- File formats produced / consumed.

### 5. `data-model.md` *(NEW — required)*
- Core entities as Go-style struct sketches.
- Invariants per type.
- Serialization formats (JSON, TOML, plaintext).
- State transitions where relevant (e.g. selection state machine).

### 6. `test-plan.md` *(NEW — required)*
- Golden tests captured from the **Python reference** (run Python, snapshot output, assert in Go).
- Unit test targets per package.
- Integration tests for CLI end-to-end.
- TUI tests (driven by scripted key sequences).
- Coverage target (≥80%).

### 7. `task-list.md` *(NEW — recommended)*
- Phased breakdown (skeleton → core → TUI → polish).
- Dependencies between phases.
- Parity checkpoints.

## Skills / Agents to Use (in order)

| Phase | Tool | Purpose |
|-------|------|---------|
| Requirements | `brainstorming` skill | Lock intent before writing docs |
| Stress-test | `grill-me` skill | Surface unstated assumptions |
| Architecture | `architect` agent | Module/package layout, package boundaries |
| Planning | `planner` agent or `claude-mem:make-plan` | Phased task list |
| Go idioms | `golang-patterns` skill | Idiomatic target code |
| Testing | `golang-testing` skill + `tdd-workflow` skill | Table-driven tests, golden tests |
| Implementation | `tdd` / `go-test` slash | Enforce TDD per phase |
| Build issues | `go-build` slash → `go-build-resolver` agent | Fix compile errors |
| Review | `go-review` slash → `go-reviewer` agent | Per-package review |
| Docs | `create-readme` skill, `update-docs` slash | Final user docs |

## Suggested Workflow

1. **Brainstorm** with `brainstorming` skill — produce `design.md`.
2. **Grill** the design with `grill-me` — refine.
3. **Spec** the CLI/IO contract — produce `spec.md`.
4. **UI** mockups — produce `ui.md`.
5. **Data model** — produce `data-model.md`.
6. **Architecture** with `architect` agent — produce `architecture.md`.
7. **Test plan** — capture golden outputs from current Python — produce `test-plan.md`.
8. **Task list** with `planner` — produce `task-list.md`.
9. **Implement** phase by phase via TDD, with `go-test` and `go-review` between phases.

## Port-Specific Risks to Address in Docs

- **TUI parity**: Python uses Rich; Go equivalents (`bubbletea`, `tview`, `lipgloss`) have different render models. Pick early, document tradeoffs.
- **Terminal input**: Python `termios` handling (escape sequences, mouse) needs careful mapping. Reference current `read_key_raw` / `read_key` split (see `keys.py`, `review.py`).
- **Async / concurrency**: Python is mostly sync; idiomatic Go often introduces goroutines. Decide: literal port vs. idiomatic.
- **Distribution**: Single static binary is a Go win — document release matrix (linux/mac/windows, amd64/arm64).
- **Config compatibility**: If existing users have config files, decide on backward compatibility.

## Reference: Current Python Implementation Anchors

Capture these before porting (read source + run to snapshot behavior):

- Entry point and CLI parsing.
- `selection.py` — selection state machine, filter, navigation, paging.
- `rich_ui.py` — render layer.
- `review.py` — review screen, key handling, mouse.
- `keys.py` — symbolic key mapping, escape sequences.
- `diff.py` — diff rendering, fallback behavior.
- Test suites under `tests/` — port to Go as golden tests where possible.

## Verdict

Three docs is a starting outline, not a complete spec. Add **spec**, **data-model**, **test-plan** at minimum. Without those, the port will drift from the Python reference and parity bugs will surface late.
