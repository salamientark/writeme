#!/usr/bin/env bash
# gh-readme-pipeline launcher: ephemeral mktemp sandbox, no persistent install.
# See docs/superpowers/specs/2026-04-29-gh-readme-pipeline-design-v2.md
set -euo pipefail

NUKE_ON_FAIL="${NUKE_ON_FAIL:-0}"
REPO_URL="${REPO_URL:-https://github.com/salamientark/writeme}"
REF="${REF:-main}"
EXPECTED_SHA="${EXPECTED_SHA:-0000000000000000000000000000000000000000}"
SKIP_DEP_CHECK="${SKIP_DEP_CHECK:-0}"

require_dep() {
  local cmd="$1" hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing dependency: $cmd" >&2
    [[ -n "$hint" ]] && echo "  install: $hint" >&2
    return 1
  fi
}

if [[ "$SKIP_DEP_CHECK" != "1" ]]; then
  fail=0
  require_dep git    "https://git-scm.com/downloads"            || fail=1
  require_dep mktemp "(coreutils)"                              || fail=1
  require_dep gh     "https://cli.github.com/"                  || fail=1
  require_dep claude "https://claude.com/claude-code"           || fail=1
  require_dep uv     "https://docs.astral.sh/uv/"               || fail=1
  require_dep python "https://www.python.org/downloads/"        || fail=1
  if [[ "$fail" == "1" ]]; then
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "gh auth: not authenticated. Run: gh auth login" >&2
    exit 1
  fi
fi

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

if [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] && [[ "$EXPECTED_SHA" != "0000000000000000000000000000000000000000" ]]; then
  git -C "$WORKDIR" init -q program
  git -C "$WORKDIR/program" remote add origin "$REPO_URL"
  if ! git -C "$WORKDIR/program" fetch -q --depth=1 origin "$EXPECTED_SHA" 2>/dev/null; then
    echo "SHA pin mismatch: cannot fetch $EXPECTED_SHA from $REPO_URL" >&2
    EXIT_CODE=3
    exit 3
  fi
  git -C "$WORKDIR/program" -c advice.detachedHead=false checkout -q FETCH_HEAD
  ACTUAL_SHA="$(git -C "$WORKDIR/program" rev-parse HEAD)"
  if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
    echo "SHA pin mismatch: expected $EXPECTED_SHA, got $ACTUAL_SHA" >&2
    EXIT_CODE=3
    exit 3
  fi
else
  if [[ "$EXPECTED_SHA" != "0000000000000000000000000000000000000000" && -n "$EXPECTED_SHA" ]]; then
    echo "warning: EXPECTED_SHA invalid format, falling back to ref=$REF" >&2
  fi
  git clone -q --depth=1 --branch "$REF" "$REPO_URL" "$WORKDIR/program"
fi

mkdir -p "$WORKDIR/repo" "$WORKDIR/state" "$WORKDIR/cache"

export GH_README_REPOS_DIR="$WORKDIR/repo"
export XDG_STATE_HOME="$WORKDIR/state"
export XDG_CACHE_HOME="$WORKDIR/cache"

set +e
if [[ ! -t 0 ]] && (exec </dev/tty) 2>/dev/null; then
  python "$WORKDIR/program/gh_readme_pipeline.py" "$@" < /dev/tty
else
  python "$WORKDIR/program/gh_readme_pipeline.py" "$@"
fi
EXIT_CODE=$?
set -e
exit "$EXIT_CODE"
