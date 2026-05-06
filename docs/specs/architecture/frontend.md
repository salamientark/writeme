<!-- Generated: 2026-05-06 | Files scanned: 8 | Token estimate: ~600 -->

# UI Layer (TUI)

No web frontend. "Frontend" = terminal UI in `src/ui/`. Rich-native after curses removal (commit e75cca5).

## Selector
```
make_ui(plain, isatty) → UI
  plain=True or non-tty → PlainUI (line-based prompts)
  else                  → RichUI  (Rich Live + raw key input)
```

## UI Protocol — `src/ui/protocol.py`
```python
class UI(Protocol):
    show_repo_select(repos) -> list[Repo]
    show_review(ctx: ReviewContext) -> str   # accept|redo|discard|view|quit
    show_summary(rows: list[SummaryRow]) -> None
    clear() -> None
```
Dataclasses: `ReviewContext`, `SummaryRow`.

## Renderers
| File | Lines | Notes |
|------|-------|-------|
| `rich_ui.py`  | 469 | Rich Live, mouse wheel, raw-key keymap |
| `plain_ui.py` | 110 | stdin/stdout fallback, used for `--plain` and pipes |
| `logo.py`     |  17 | ASCII banner |

## Key handling — `src/ui/keys.py`
```
open_tty_rd()         → file obj (cbreak via termios)
read_key_raw(rd)      → str  (raw ESC seq, for mouse decode)
read_key(rd)          → str  (symbolic name: "up","esc","enter",…)
_decode(seq)          → symbolic name
```
Escape disambiguation uses select() timeout (commit 5614b6f area).

## Selection state — `src/selection.py`
```
class Repo(name, owner, ssh_url, pushed_at, …)
class VisibleRow(NamedTuple)            # (display_idx, repo)
class SelectionState:
  toggle / select_all / clear
  filter_set(text)        # live substring filter
  cursor_up / cursor_down / page_up / page_down
  jump(idx)               # numeric jump
  visible_rows(viewport)  # pagination + filter + viewport scroll
```
Filter auto-scrolls viewport so cursor stays visible (mem 1749).

## Range parser — `src/ui/range_parser.py`
```
parse_selection(raw, total) → ParseResult(indices, errors)
# accepts "1,3-5,7", validates bounds
```

## Diff — `src/ui/diff.py`
```
unified(old, new, fromfile, tofile) → str
diff_vs_head(head, current)         → str   # explicit None → fallback
diff_vs_prev(prev, current)         → str
```

## Modes
- Default: Rich TUI
- `--plain`: line-mode (CI / pipes)
- `WRITEME_RICH_SELECT=1`: legacy gate (now default-on path)
