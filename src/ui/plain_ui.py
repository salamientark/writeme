"""PlainUI — non-TTY / --plain renderer.

Thin wrapper around stdlib print() preserving the pre-redesign behavior so
existing pipeline tests that capture stdout keep passing.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from src.selection import Repo

from .protocol import ReviewContext, SummaryRow
from . import diff as _diff
from .range_parser import parse_selection


class PlainUI:
    def show_intro(self) -> None:
        print("writeme — generating READMEs…")

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        print(label)
        yield

    def select_repos(self, repos: list[Repo]) -> list[Repo]:
        if not repos:
            return []
        print("Available repos:")
        for i, r in enumerate(repos, start=1):
            badge = "  [HAS README]" if r.had_readme_before else ""
            print(f"  {i:>3}) {r.name:<30} {r.pushed_at}{badge}")
        while True:
            try:
                raw = input("Select (e.g. 1,3,5-7, a=all, q=quit): ")
            except EOFError:
                return []
            result = parse_selection(raw, len(repos))
            if result.kind == "quit":
                return []
            if result.kind == "all":
                return list(repos)
            if result.kind == "ok":
                return [repos[i] for i in sorted(result.indices)]
            print(f"error: {result.message}")

    def show_review(self, ctx: ReviewContext) -> str:
        """Plain-text review: print current draft + diff vs HEAD, then prompt.

        Returns 'accept' | 'redo' | 'discard' | 'quit'.
        """
        header = f"\n--- [{ctx.index}/{ctx.total}] {ctx.repo_name} ---"
        print(header)
        print(ctx.current_draft)
        print()
        print(_diff.diff_vs_head(ctx.head_readme, ctx.current_draft))
        while True:
            try:
                raw = input("[a]ccept / [r]edo / [d]iscard / [q]uit > ").strip().lower()
            except EOFError:
                return "discard"
            if raw == "a":
                return "accept"
            if raw == "r":
                return "redo"
            if raw == "d":
                return "discard"
            if raw == "q":
                return "quit"

    def menu(self, title: str, options: list[tuple[str, str]]) -> str:
        print(f"\n{title}")
        for key, desc in options:
            print(f"  [{key}] {desc}")
        valid = {k.lower(): k for k, _ in options}
        while True:
            try:
                raw = input("> ").strip().lower()
            except EOFError:
                return ""
            if raw in valid:
                return valid[raw]

    def show_summary(self, rows: list[SummaryRow]) -> None:
        if not rows:
            print("\n(no repos processed)")
            return
        print("\n--- Summary ---")
        for row in rows:
            url = row.pr_url or "—"
            print(f"  {row.repo:<30} {row.outcome:<10} {url}")

    def prompt(self, message: str) -> str:
        try:
            return input(message)
        except EOFError:
            return ""

    def warn(self, message: str) -> None:
        print(f"warning: {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(f"error: {message}", file=sys.stderr)
