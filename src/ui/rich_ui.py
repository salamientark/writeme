"""RichUI — TTY renderer using `rich`.

See docs/UI-REDESIGN.md for surfaces (intro, spinner, review, summary) and
color palette. Imports `rich` lazily; the factory in __init__ falls back to
PlainUI when rich is unavailable.
"""
from __future__ import annotations

import os
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


def _open_tty():
    """Return /dev/tty file pair (rd, wr) or (sys.stdin, sys.stderr) fallback."""
    try:
        rd = open("/dev/tty", "rb", buffering=0)
        wr = open("/dev/tty", "w")
        return rd, wr
    except OSError:
        return None, None


def _read_key(rd) -> str:
    """Read a single key (with arrow-key escape handling) from rd in cbreak."""
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
        body.append(LOGO + "\n\n", style="cyan")
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
        # raw
        return Text(ctx.current_draft or "(empty)")

    def _render_panel(self, view: str, ctx: ReviewContext) -> Panel:
        title = f"[{ctx.index}/{ctx.total}] {ctx.repo_name}"
        subtitle = (
            f"view: {_VIEW_LABELS[view]} · tab cycle · 1 diff/HEAD · 2 diff/prev · "
            "v raw · a accept · r redo · d discard · q quit"
        )
        return Panel(
            self._render_view(view, ctx),
            title=title,
            subtitle=subtitle,
            border_style="cyan",
        )

    def show_review(self, ctx: ReviewContext) -> str:
        rd, _wr = _open_tty()
        if rd is None or not sys.stdout.isatty():
            # Fallback to a non-interactive print + line input.
            self.console.print(self._render_panel("README", ctx))
            try:
                raw = input("[a]ccept / [r]edo / [d]iscard / [q]uit > ").strip().lower()
            except EOFError:
                return "discard"
            return {"a": "accept", "r": "redo", "d": "discard", "q": "quit"}.get(raw, "discard")

        view_idx = 0
        try:
            while True:
                self.console.clear()
                self.console.print(self._render_panel(_VIEWS[view_idx], ctx))
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
                elif key in ("q", "\x03"):  # q or Ctrl-C
                    return "quit"
                # ignore other keys
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
