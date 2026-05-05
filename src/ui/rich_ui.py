"""RichUI — TTY renderer using `rich`.

Interactive surfaces (review, menus) run inside the terminal's alternate
screen via `Console.screen()`, so they do not pollute scrollback. View toggles
redraw in place via `ScreenContext.update()`. Non-interactive surfaces (intro,
summary) print to the normal terminal so the user can re-read them after exit.

See docs/UI-REDESIGN.md.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import diff as _diff
from .logo import LOGO, STEPS, TAGLINE
from .protocol import ReviewContext, SummaryRow


_VIEWS = ("README", "diff_head", "diff_prev", "raw")
_VIEW_LABELS = {
    "README": "README",
    "diff_head": "diff vs HEAD",
    "diff_prev": "diff vs prev draft",
    "raw": "raw markdown",
}


def _open_tty_rd():
    """Return a raw-bytes file for /dev/tty or None if unavailable."""
    try:
        return open("/dev/tty", "rb", buffering=0)
    except OSError:
        return None


def _read_key(rd) -> str:
    """Read a single key (arrow-key escape sequences included) in cbreak mode."""
    import termios
    import tty
    fd = rd.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = rd.read(1)
        if not ch:
            return ""
        if ch == b"\x1b":
            seq = rd.read(2)
            return "\x1b" + seq.decode("ascii", "ignore")
        return ch.decode("utf-8", "ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class RichUI:
    def __init__(self) -> None:
        self.console = Console()

    # -- intro -------------------------------------------------------------
    def show_intro(self) -> None:
        body = Text()
        body.append(LOGO, style="bold cyan")
        body.append("\n")
        body.append(TAGLINE + "\n\n", style="bold")
        body.append(STEPS, style="dim")
        self.console.print(Panel(body, border_style="cyan", padding=(1, 2)))

    # -- spinner -----------------------------------------------------------
    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        spin = Spinner("dots", text=Text(label, style="cyan"))
        with Live(spin, console=self.console, refresh_per_second=12, transient=True):
            yield

    # -- review ------------------------------------------------------------
    def _render_view(self, view: str, ctx: ReviewContext):
        if view == "README":
            return Markdown(ctx.current_draft or "(empty)")
        if view == "diff_head":
            return Syntax(
                _diff.diff_vs_head(ctx.head_readme, ctx.current_draft),
                "diff",
                theme="ansi_dark",
                word_wrap=True,
            )
        if view == "diff_prev":
            return Syntax(
                _diff.diff_vs_prev(ctx.prev_draft, ctx.current_draft),
                "diff",
                theme="ansi_dark",
                word_wrap=True,
            )
        return Text(ctx.current_draft or "(empty)")

    def _render_review_panel(self, view: str, ctx: ReviewContext) -> Panel:
        title = f"[{ctx.index}/{ctx.total}] {ctx.repo_name}"
        subtitle = (
            f"view: {_VIEW_LABELS[view]}  ·  tab cycle  ·  1 diff/HEAD  "
            "·  2 diff/prev  ·  v raw  ·  a accept  ·  r redo  ·  d discard  ·  q quit"
        )
        return Panel(
            self._render_view(view, ctx),
            title=title,
            subtitle=subtitle,
            border_style="cyan",
        )

    def show_review(self, ctx: ReviewContext) -> str:
        rd = _open_tty_rd()
        if rd is None or not sys.stdout.isatty():
            self.console.print(self._render_review_panel("README", ctx))
            try:
                raw = input("[a]ccept / [r]edo / [d]iscard / [q]uit > ").strip().lower()
            except EOFError:
                return "discard"
            return {"a": "accept", "r": "redo", "d": "discard", "q": "quit"}.get(raw, "discard")

        view_idx = 0
        try:
            with self.console.screen() as screen:
                while True:
                    screen.update(self._render_review_panel(_VIEWS[view_idx], ctx))
                    key = _read_key(rd)
                    if key == "\t":
                        view_idx = (view_idx + 1) % len(_VIEWS)
                    elif key == "1":
                        view_idx = _VIEWS.index("diff_head")
                    elif key == "2":
                        view_idx = _VIEWS.index("diff_prev")
                    elif key == "v":
                        view_idx = _VIEWS.index("raw")
                    elif key == "a":
                        return "accept"
                    elif key == "r":
                        return "redo"
                    elif key == "d":
                        return "discard"
                    elif key in ("q", "\x03"):
                        return "quit"
        finally:
            try:
                rd.close()
            except OSError:
                pass

    # -- menu --------------------------------------------------------------
    def _render_menu_panel(self, title: str, options: list[tuple[str, str]], cursor: int) -> Panel:
        body = Text()
        for i, (key, desc) in enumerate(options):
            marker = "▸" if i == cursor else " "
            row_style = "bold cyan" if i == cursor else ""
            body.append(f" {marker} ", style=row_style)
            body.append(f"[{key}] ", style="bold yellow" if i == cursor else "yellow")
            body.append(f"{desc}\n", style=row_style)
        body.append("\n")
        body.append("↑/↓ move · enter select · letter shortcut · q quit", style="dim")
        return Panel(body, title=title, border_style="cyan", padding=(1, 2))

    def menu(self, title: str, options: list[tuple[str, str]]) -> str:
        if not options:
            return ""
        rd = _open_tty_rd()
        if rd is None or not sys.stdout.isatty():
            # Fallback: line-based prompt
            self.console.print(Panel(title, border_style="cyan"))
            for key, desc in options:
                self.console.print(f"  [{key}] {desc}")
            try:
                raw = input("> ").strip().lower()
            except EOFError:
                return ""
            keys = {k.lower(): k for k, _ in options}
            return keys.get(raw, "")

        cursor = 0
        keys = [k for k, _ in options]
        try:
            with self.console.screen() as screen:
                while True:
                    screen.update(self._render_menu_panel(title, options, cursor))
                    key = _read_key(rd)
                    if key in ("\x1b[A",):  # up
                        cursor = (cursor - 1) % len(options)
                    elif key in ("\x1b[B",):  # down
                        cursor = (cursor + 1) % len(options)
                    elif key in ("\r", "\n"):
                        return keys[cursor]
                    elif key in ("q", "\x03"):
                        return ""
                    elif key and key.lower() in (k.lower() for k in keys):
                        for k in keys:
                            if k.lower() == key.lower():
                                return k
        finally:
            try:
                rd.close()
            except OSError:
                pass

    # -- summary -----------------------------------------------------------
    def show_summary(self, rows: list[SummaryRow]) -> None:
        table = Table(title="Summary", border_style="cyan", show_lines=False)
        table.add_column("Repo", style="bold")
        table.add_column("Outcome")
        table.add_column("PR URL")

        outcome_styles = {
            "accepted": "green",
            "redone": "yellow",
            "skipped": "dim",
            "failed": "red",
        }
        totals = {"accepted": 0, "redone": 0, "skipped": 0, "failed": 0}
        for row in rows:
            totals[row.outcome] = totals.get(row.outcome, 0) + 1
            style = outcome_styles.get(row.outcome, "")
            url_cell = self._osc8(row.pr_url) if row.pr_url else "—"
            table.add_row(row.repo, Text(row.outcome, style=style), url_cell)

        self.console.print(table)
        footer = Text()
        footer.append(f"accepted:{totals['accepted']} ", style="green")
        footer.append(f"redone:{totals['redone']} ", style="yellow")
        footer.append(f"failed:{totals['failed']} ", style="red")
        footer.append(f"skipped:{totals['skipped']}", style="dim")
        self.console.print(footer)

    def _osc8(self, url: str) -> Text:
        text = Text(url, style="cyan underline")
        text.stylize(f"link {url}")
        return text

    # -- prompts -----------------------------------------------------------
    def prompt(self, message: str) -> str:
        try:
            return input(message)
        except EOFError:
            return ""

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]warning:[/yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[bold red]error:[/bold red] {message}")
