# Self-Destruct Plan — gh-readme-pipeline

Date: 2026-04-29
Status: design locked, pending implementation

## Goal

Make pipeline leave zero trace after successful run. Program file + cache + clones + state all gone. Failure preserves work for debugging unless explicitly overridden.

## Architecture

Single `mktemp -d` sandbox owned by a bash launcher. Launcher creates dir, populates it, execs Python, deletes dir on exit per policy. Python is unaware of sandbox — relies on standard XDG env vars + `GH_README_REPOS_DIR`.

```
$TMPDIR/writeme.XXXXXX/
├── program/    # git clone --depth=1 of this repo (REF=main by default)
├── repo/       # target repo clones (GH_README_REPOS_DIR)
├── state/      # XDG_STATE_HOME
└── cache/      # XDG_CACHE_HOME
```

User shell env never mutated — exports live only inside launcher subshell, which dies with `curl | bash`.

## Cleanup Policy

| Exit code | `NUKE_ON_FAIL` | Action |
|-----------|----------------|--------|
| 0         | any            | wipe sandbox |
| non-zero  | 0 (default)    | keep sandbox, print path to stderr |
| non-zero  | 1              | wipe sandbox |

Unpushed work in target clones triggers non-zero exit (code 2), so default behavior preserves Claude-generated work when push fails. `NUKE_ON_FAIL=1` is the single nuclear override.

## Decisions Locked (Q1–Q16)

- **Q1** Trigger: opt-in style → user opted for ephemeral default + sandbox model (Q-redesign).
- **Q2** Scope of "everything": program dir + XDG state + cache + clones, all inside sandbox.
- **Q3** Default-mode wipe: clones (resolved by sandbox model — every run is ephemeral).
- **Q4** Partial success: end-of-run selective preserve (Q10 implements via non-zero exit).
- **Q5** Force override: `NUKE_ON_FAIL=1` env var.
- **Q6** Mechanism: bash launcher owns wipe (not Python `shutil.rmtree`).
- **Q7** Safety guards: trivially satisfied — sandbox path is mktemp-unique, cannot collide with `$HOME` or `/`.
- **Q8** Bootstrap fetch: `git clone --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"`.
- **Q9** Cleanup trigger: `trap cleanup EXIT` with exit-code branch.
- **Q10** Unpushed-work handling: pipeline exits non-zero → launcher keeps dir.
- **Q11** Python changes: zero — env vars (XDG + `GH_README_REPOS_DIR`) drive paths.
- **Q12** Pre-existing user state at `~/.local/state/gh-readme-pipeline/`: ignored.
- **Q13** Sandbox location: `$TMPDIR` (default `/tmp`).
- **Q14** Drop `--clean` flag; never add `--ephemeral` flag (sandbox is implicit).
- **Q15** Replace `run.sh` with `install.sh` at repo root.
- **Q16** Tests: pytest + subprocess against stub `program/`.

## `install.sh` (Reference Implementation)

```bash
#!/usr/bin/env bash
set -euo pipefail

NUKE_ON_FAIL="${NUKE_ON_FAIL:-0}"
REPO_URL="${REPO_URL:-https://github.com/<owner>/github-readme-pipeline}"
REF="${REF:-main}"

WORKDIR="$(mktemp -d -t writeme.XXXXXX)"
EXIT_CODE=1
cleanup() {
  if [[ "$EXIT_CODE" == "0" || "$NUKE_ON_FAIL" == "1" ]]; then
    rm -rf "$WORKDIR"
  else
    echo "kept $WORKDIR (exit=$EXIT_CODE) — rm -rf to clean" >&2
  fi
}
trap cleanup EXIT

git clone --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"
mkdir -p "$WORKDIR/repo" "$WORKDIR/state" "$WORKDIR/cache"

export GH_README_REPOS_DIR="$WORKDIR/repo"
export XDG_STATE_HOME="$WORKDIR/state"
export XDG_CACHE_HOME="$WORKDIR/cache"

python "$WORKDIR/program/gh_readme_pipeline.py" "$@"
EXIT_CODE=$?
```

## Python Changes

1. Remove `--clean` flag from `gh_readme_pipeline.py` docstring + arg parser.
2. Verify `src/state.py` honors `XDG_STATE_HOME` (already done in Phase 4 per memory; reconfirm).
3. Add end-of-run scan of `$GH_README_REPOS_DIR/*/`:
   - For each clone, run `git status --porcelain` and `git rev-list @{u}..HEAD`.
   - If any clone has dirty tree OR unpushed commits → log paths + `sys.exit(2)`.
   - Otherwise `sys.exit(0)`.

## Test Plan (`tests/test_install.py`)

pytest + `subprocess.run(["bash", "install.sh"], env=...)` against a stub `program/gh_readme_pipeline.py` whose exit code + side effects are controllable via test env vars.

- `test_clean_exit_wipes_workdir` — stub exits 0; assert mktemp path gone.
- `test_failure_keeps_workdir` — stub exits 1; assert dir survives + stderr contains path.
- `test_nuke_on_fail_overrides` — stub exits 1, `NUKE_ON_FAIL=1`; assert dir gone.
- `test_env_vars_set` — stub writes `os.environ` snapshot; assert `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `GH_README_REPOS_DIR` all point inside workdir.
- `test_user_env_untouched` — parent shell's `XDG_STATE_HOME` unchanged after launcher exits.
- `test_unpushed_work_exits_nonzero` — stub creates dirty git tree under `repo/`; assert exit 2 + dir kept.

## Implementation Phases (TDD)

1. **RED** — write `tests/test_install.py` against not-yet-existing `install.sh`.
2. **GREEN** — write `install.sh`. Iterate to green.
3. **Python cleanup** — drop `--clean`, add unpushed-work scan, update Python tests.
4. **Cleanup repo** — delete `run.sh`, update `README.md` with `curl | bash` invocation, document `NUKE_ON_FAIL` toggle.

## Files Touched

- `install.sh` (new, repo root)
- `run.sh` (deleted)
- `gh_readme_pipeline.py` (drop `--clean`, update docstring)
- `src/main.py` (or wherever main loop lives — add unpushed-work scan + exit code)
- `tests/test_install.py` (new)
- `README.md` (curl|bash invocation + `NUKE_ON_FAIL` doc)

## Out of Scope

- Install URL pinning + SHA verification — handled in a separate session.
- Multi-arch / multi-OS testing — Linux-only for now.
- Logging/telemetry of wiped runs — none; zero-trace by design.
