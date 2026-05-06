# UI Redesign V2 — Selection + Commit Menu Rich Rework

Status: stages 1–4 shipped; stage 5 partial (review scroll done, intro morph deferred).
Owner: damien@jiliac.com
Date: 2026-05-05 (design) · 2026-05-06 (impl sync)
Supersedes selection-related "out of scope" notes in `docs/UI-REDESIGN.md`.

## Implementation status (2026-05-06)

Reality vs. design after merge of `feat-pipeline`:

- Stage 1 ✅ — protocol `select_repos`, `range_parser`, `PlainUI.select_repos`, caller switch.
- Stage 2 ✅ — `keys.py`, `SelectionState` filter/jump/page, Rich selection screen. `WRITEME_RICH_SELECT` gate **removed** (flipped to default in stage 3, no transitional flag in tree).
- Stage 3 ✅ — `src/tui.py` and `tests/test_tui.py` deleted; no `curses` references remain.
- Stage 4 ✅ — `menu()` reimplemented as centered `Align.center` + `Panel(width=40)` modal driven by `read_key`.
- Stage 5 ⚠️ partial — review screen gained scroll/mouse-wheel support (with per-view offsets), but the **intro morph** (single `Live(screen=True)` wrapping `show_intro` + first `select_repos`) was **not** implemented. `show_intro` remains a one-shot `console.print`; selection opens its own `Live(screen=True, transient=True)` afterwards.

Behavioural deltas from the locked design:

- **Glyphs** are ASCII `[x]`/`[ ]`, not `■`/`□`. Selection row uses Rich `reverse` + `bold` styling for the cursor line. Done deliberately for terminal-compat (see commit `e75cca5`).
- **Review scroll** is always-on (`j`/`k`/`g`/`G`/`PgUp`/`PgDn`/space/`b`), not the opt-in `s`-to-enter mode the design proposed. The line-buffered concern was sidestepped by running review entirely under `console.screen()` with `read_key_raw`.
- **Mouse wheel** scrolls the review screen. Not in original design (added post-design — memory 1697, 1700). Click/drag are ignored.
- **Per-view scroll offsets** in review preserve position when toggling README / diff / raw via `tab` / `1` / `2` / `v`.
- **`RichUI.clear()`** exists and still calls `console.clear()` — used outside the intro→selection transition. The "no `console.clear()` between intro and selection" goal is moot until stage 5's intro morph lands.
- Selection screen uses `Live(..., transient=True, screen=True, refresh_per_second=20)`.

## Goal

Unify writeme on Rich. Replace curses selection TUI and existing commit menu with Rich-native screens. Add filter + jump keys. Keep palette + review screen architecture from V1.

## Non-goals

- Textual / prompt_toolkit framework.
- Split-pane diff in review.
- CLI `--repos a,b,c` flag.
- Sort toggle, invert selection.
- Snapshot tests for Rich rendering.
- Animations (logo fade, etc).

## Architecture changes

### Protocol additions (`src/ui/protocol.py`)

```python
def select_repos(self, repos: list[Repo]) -> list[Repo]: ...
```

Returns chosen subset (ascending index order). Empty list = user quit. Both `RichUI` and `PlainUI` implement.

### Module changes

- Delete `src/tui.py` (curses) at end of stage 3.
- `src/ui/rich_ui.py` gains `select_repos` + private helpers.
- `src/ui/plain_ui.py` gains `select_repos` + private range parser.
- `gh_readme_pipeline.py:485` switches `tui_mod.tui_select(...)` → `ui.select_repos(...)`.
- `SelectionState` (`src/selection.py`) extended: `filter: str` field, derived `visible_repos`, `apply_filter()`, `jump_top()`, `jump_bottom()`, `page_up()`, `page_down()`, `clear_filter()`.

### Key handling

Reuse existing `_tty_input` raw-key infra (currently in pipeline/commit). Extract to `src/ui/keys.py`:
```python
def read_key() -> str: ...   # returns 'up','down','enter','space','/','esc','pgup','pgdn','j','k','a','n','g','G','q', or single char
```

Used by: selection screen, commit menu modal, review screen scroll keys.

## Surfaces

### Selection screen

```
┌─ writeme — select repos ─────────────────────────────────┐
│  ■ repo-a               2026-04-30   HAS README          │
│  □ repo-b               2026-04-29                       │
│  ▌□ repo-c (cursor)     2026-04-28   HAS README          │  <- reverse video
│  ■ repo-d               2026-04-27                       │
│  …                                                        │
├──────────────────────────────────────────────────────────┤
│  ↑/↓ move · space toggle · / filter · enter confirm    12/47 selected
│  a all · n none · g/G top/bottom · q quit                 │
└──────────────────────────────────────────────────────────┘
```

Filter mode (active when `/` pressed):
```
│ filter: my-█                                              │
```
- Live narrows table.
- `esc` closes, restores full list (selection preserved).
- Footer adds `(filtered: 5 of 47, 3 selected hidden)`.

Glyphs (as shipped): `[x]` selected, `[ ]` unselected — ASCII for terminal-compat. Cursor row = `"reverse bold"`.

Palette: cyan accent border, green for HAS README badge, dim grey for date, yellow for filter prompt.

### Commit menu modal

```
        ┌─ commit-mode for my-repo ────────┐
        │                                  │
        │   ▸ commit & push                │
        │     commit only                  │
        │     skip                         │
        │     abort                        │
        │                                  │
        │  ↑/↓ select · enter confirm · q  │
        └──────────────────────────────────┘
```

`Align.center(vertical="middle")` over dimmed parent. Width ≈40, height auto. Arrow + enter.

### Intro morph (deferred — not in tree)

Designed but not yet implemented. `show_intro` currently does a one-shot `console.print(Panel(...))`; the selection screen opens its own `Live(screen=True, transient=True)` afterwards, so there is a brief plain-print frame between intro and selection. Re-open if/when the morph is prioritised.

Originally specced: single `Live(layout, screen=True)` started before `gh` fetch. Layout root:
```
Layout
├── logo_panel    (visible during fetch)
└── content       (spinner during fetch → selection panel after)
```

On fetch complete, `layout["logo_panel"].visible = False`, `layout["content"].update(selection_panel)`. No `console.clear()`. `Live` continues until selection done, then exits.

### Review screen patch (as shipped)

Whole review runs under `console.screen()` with `read_key_raw`. No `input()` fallback for TTY path; non-TTY falls back to a single panel print + `input()` prompt.

Keys (always-on, not opt-in):
- `j` / `down` — line down · `k` / `up` — line up
- `g` top · `G` bottom · `PgUp` / `b` page up · `PgDn` / space page down
- `tab` cycle view · `1` diff/HEAD · `2` diff/prev · `v` raw
- `a` accept · `r` redo · `d` discard · `q` / Ctrl-C quit
- Mouse wheel scrolls (3 lines/tick); other mouse events ignored.

Per-view `offsets[view_idx]` array preserves scroll across view toggles. Window size = `console.size.height - 4`.

## Non-TTY (`PlainUI.select_repos`)

```
Available repos:
  1) repo-a    2026-04-30  [HAS README]
  2) repo-b    2026-04-29
  3) repo-c    2026-04-28  [HAS README]
  …
Select (e.g. 1,3,5-7, a=all, q=quit): _
```

Range parser (`src/ui/range_parser.py`):
- `1,3,5-7` → `{1,3,5,6,7}` (1-indexed → 0-indexed).
- `a` → all.
- `q` → empty / abort.
- Whitespace tolerant.
- Invalid → reprompt with error line.

## Selection state extensions

`src/selection.py` `SelectionState`:
```python
@dataclass(frozen=True)
class SelectionState:
    repos: tuple[Repo, ...]
    cursor: int
    selected: frozenset[int]
    viewport_start: int
    viewport_height: int
    filter: str = ""              # NEW

    def apply_filter(self, q: str) -> SelectionState: ...
    def clear_filter(self) -> SelectionState: ...
    def jump_top(self) -> SelectionState: ...
    def jump_bottom(self) -> SelectionState: ...
    def page_up(self) -> SelectionState: ...
    def page_down(self) -> SelectionState: ...

    @property
    def visible_indices(self) -> tuple[int, ...]:
        """Indices into self.repos matching current filter."""

    @property
    def hidden_selected_count(self) -> int:
        """Count of selected repos not in current visible_indices."""
```

Filter match: case-insensitive substring on `repo.name`. Cursor clamps to filtered range. `selected` set is preserved across filter changes (indices into full `repos` tuple, never remapped).

`a`/`n` (select-all/none) operate on `visible_indices` only.

## Migration plan

Five stages. Each green tests + manually smoke-tested before next.

### Stage 1 — Protocol + PlainUI selection (no UX change)

Files:
- `src/ui/protocol.py` — add `select_repos`.
- `src/ui/range_parser.py` — new, pure.
- `src/ui/plain_ui.py` — add `select_repos`.
- `src/ui/rich_ui.py` — add `select_repos` shimming to `tui_mod.tui_select` (curses).
- `gh_readme_pipeline.py:485` — switch caller to `ui.select_repos`.
- `tests/test_range_parser.py` — new.
- `tests/test_plain_ui_select.py` — new (stdin/stdout).

Acceptance: existing test suite green; new parser + PlainUI tests green; curses behavior unchanged at runtime.

### Stage 2 — RichUI selection behind env flag

Files:
- `src/ui/keys.py` — extract raw-key reader.
- `src/selection.py` — add `filter`, jump/page methods.
- `src/ui/rich_ui.py` — implement Rich selection screen. Gate via `os.environ.get("WRITEME_RICH_SELECT") == "1"`; else fall through to curses shim.
- `tests/test_selection.py` — extend for filter/jump/page (TDD: tests first, RED → GREEN).

Acceptance: with env flag = curses still default; tests green; manual smoke on TTY (50+ repos) confirms filter, jump, paging, resize.

### Stage 3 — Flip default, delete curses

Files:
- `src/ui/rich_ui.py` — drop env flag gate.
- `src/tui.py` — delete.
- `tests/test_tui.py` — delete (covered by `SelectionState` tests + manual).
- `gh_readme_pipeline.py` — drop `tui_mod` import.

Acceptance: `grep -r curses src/ tests/` empty; suite green; manual smoke.

### Stage 4 — Commit-menu modal

Files:
- `src/ui/rich_ui.py` — `menu()` reimpl as centered modal w/ `Align.center` + `Panel(width≈40)`. Reuse `read_key()`.
- No protocol change (signature already exists).
- Manual smoke via `commit.py` flow.

Acceptance: existing `commit_and_push` tests green; manual visual check.

### Stage 5 — Intro morph + review scroll parity

Status: **partial**. Review scroll shipped; intro morph deferred.

Shipped:
- `src/ui/rich_ui.py` `show_review` — full-screen `console.screen()` loop, always-on `j/k/g/G/PgUp/PgDn` + mouse wheel, per-view scroll offsets.

Deferred:
- Wrapping `show_intro` + first `select_repos` in a single `Live(screen=True)` — `show_intro` still does a one-shot print.

Acceptance (revised): review screen scrolls long READMEs without leaving review ✅; "no `console.clear()` between intro and selection" — pending intro morph.

## Test plan

Per stage, all TDD where logic exists:

- **Stage 1:** `test_range_parser.py` (10+ cases incl. invalid), `test_plain_ui_select.py` (4+ flows: all, range, quit, invalid retry).
- **Stage 2:** `test_selection.py` adds: filter narrows, filter preserves selected, cursor clamps on filter, jump_top/bottom, page_up/down at boundaries, `a`/`n` operate on visible only, hidden_selected_count.
- **Stage 3:** delete `test_tui.py`. No new tests.
- **Stage 4:** none new (visual).
- **Stage 5:** none new (visual).

Coverage gate: `pytest --cov=src --cov-report=term-missing` ≥80% maintained.

## Risk register

| Risk | Mitigation |
|------|-----------|
| Rich `Live` flicker on slow terms | Use `screen=True` (alt buffer), `refresh_per_second=10`. |
| Raw-key reader breaks on Windows | Out of scope — writeme already POSIX-only via `gh`/`tty`. |
| Filter perf w/ 1000 repos | Substring match O(n) per keystroke; trivial at 1000. |
| Selected indices invalid after fetch refresh | Selection happens once per pipeline run; fetch is single-shot. No stale-set issue. |
| Resize during filter mode | `Live` re-renders on `SIGWINCH`; viewport recompute already in state. |
| Ctrl+C mid-selection | Trap `KeyboardInterrupt` in `select_repos`, return `[]`. |

## Open questions

None. All design branches resolved in grill session 2026-05-05.

## File touch list (final)

New:
- `src/ui/keys.py`
- `src/ui/range_parser.py`
- `tests/test_range_parser.py`
- `tests/test_plain_ui_select.py`

Modified:
- `src/ui/protocol.py`
- `src/ui/rich_ui.py`
- `src/ui/plain_ui.py`
- `src/selection.py`
- `gh_readme_pipeline.py`
- `tests/test_selection.py`

Deleted (stage 3):
- `src/tui.py`
- `tests/test_tui.py`
