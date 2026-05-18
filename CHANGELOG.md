# Changelog

All notable changes to writeme.

## [v1.0.0-go.1] — Initial Go Release

### Added

- Full Go port of the writeme pipeline, replacing the Python implementation with a single static binary.
- **TUI selection screen** — interactive repo picker with filter, paging, multi-select, powered by Bubble Tea + Lipgloss.
- **TUI review screen** — side-by-side diff view, markdown preview, scroll, accept/redo/discard per repo.
- **Parallel generation** — configurable worker pool (`--parallel`) for concurrent Claude invocations via goroutines and errgroup.
- **Pipeline orchestrator** — end-to-end flow: fetch → select → worker → review → ship, with resume, dry-run, and cancellation support.
- **Contributor enrichment** — parallel `gh api` calls with caching for contributor metadata.
- **Golden parity** — byte-identical state file output and summary format with the Python reference.
- **Multi-platform builds** — Linux, macOS, Windows × amd64, arm64 via goreleaser.
- **SHA256-pinned install** — `install.sh` downloads and verifies the platform binary.
- CI: Go test matrix (Linux + macOS), race detector, coverage gate (80%), golangci-lint, goreleaser release workflow.

### Changed

- **Runtime**: single Go binary replaces `uv run gh_readme_pipeline.py`. No Python, uv, or runtime dependencies.
- **Installer**: downloads pre-built binary instead of cloning the repo and running via `uv`.
- **XDG paths**: state consolidated under cache root so `--clean` wipes everything.
- **TUI**: replaced Rich-based terminal UI with Bubble Tea + Lipgloss (Elm architecture, better testability).

### Removed

- Python runtime and all Python dependencies (`uv`, `rich`, etc.).
- `gh_readme_pipeline.py` entrypoint (superseded by Go binary).
- `src/` Python package tree (superseded by `go/internal/` packages).

---

## [v0.1.2] — Python GA

Last Python release. See [release/v0.1.2](https://github.com/salamientark/writeme/tree/release/v0.1.2).
