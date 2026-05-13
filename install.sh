#!/usr/bin/env bash
# writeme launcher: downloads the Go binary, runs in an ephemeral sandbox.
# No persistent install — everything lives under a mktemp sandbox.
set -euo pipefail

NUKE_ON_FAIL="${NUKE_ON_FAIL:-0}"
REPO_URL="${REPO_URL:-https://github.com/salamientark/writeme}"
VERSION="${VERSION:-latest}"
EXPECTED_SHA="${EXPECTED_SHA:-0000000000000000000000000000000000000000}"
SKIP_DEP_CHECK="${SKIP_DEP_CHECK:-0}"

# Resolve platform/arch for binary download.
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
  arm64)   ARCH="arm64" ;;
  *)
    echo "unsupported architecture: $ARCH" >&2
    exit 4
    ;;
esac
case "$OS" in
  linux|darwin) ;;
  *)
    echo "unsupported OS: $OS (use Windows binary directly)" >&2
    exit 4
    ;;
esac

BIN_NAME="writeme_${VERSION}_${OS}_${ARCH}"
ARCHIVE_NAME="${BIN_NAME}.tar.gz"
DOWNLOAD_URL="${REPO_URL}/releases/download/${VERSION}/${ARCHIVE_NAME}"
CHECKSUM_URL="${REPO_URL}/releases/download/${VERSION}/checksums.txt"

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
  require_dep git    "https://git-scm.com/downloads"     || fail=1
  require_dep mktemp "(coreutils)"                        || fail=1
  require_dep gh     "https://cli.github.com/"            || fail=1
  require_dep claude "https://claude.com/claude-code"     || fail=1
  require_dep curl   "https://curl.se/"                   || fail=1
  require_dep tar    "(coreutils)"                        || fail=1
  if [[ "$fail" == "1" ]]; then
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "gh auth: not authenticated. Run: gh auth login" >&2
    exit 1
  fi
fi

# Ephemeral sandbox.
BASE_DIR="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}"
WORKDIR="$(mktemp -d -p "$BASE_DIR" writeme.XXXXXX)"
chmod 700 "$WORKDIR"
EXIT_CODE=1

cleanup() {
  if [[ "$EXIT_CODE" == "0" || "$NUKE_ON_FAIL" == "1" ]]; then
    rm -rf "$WORKDIR"
  else
    echo "kept $WORKDIR (exit=$EXIT_CODE) — rm -rf to clean" >&2
  fi
}
trap cleanup EXIT

# Download and extract binary.
echo "Downloading writeme ${VERSION} (${OS}/${ARCH})..." >&2
BIN_DIR="$WORKDIR/bin"
mkdir -p "$BIN_DIR"

if ! curl -fsSL -o "$WORKDIR/${ARCHIVE_NAME}" "$DOWNLOAD_URL"; then
  echo "failed to download $DOWNLOAD_URL" >&2
  EXIT_CODE=1
  exit 1
fi

# Refuse empty or all-zero placeholder — must supply real SHA256.
if [[ -z "$EXPECTED_SHA" || "$EXPECTED_SHA" =~ ^0+$ ]]; then
  echo "EXPECTED_SHA is empty or all zeros. Set EXPECTED_SHA to the 64-char SHA256 from checksums.txt." >&2
  EXIT_CODE=1
  exit 1
fi

# Verify checksum if EXPECTED_SHA is a full 64-char hex (sha256).
if [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]]; then
  if ! curl -fsSL -o "$WORKDIR/checksums.txt" "$CHECKSUM_URL"; then
    echo "failed to download checksums" >&2
    EXIT_CODE=1
    exit 1
  fi
  EXPECTED=$(grep "$ARCHIVE_NAME" "$WORKDIR/checksums.txt" | awk '{print $1}')
  if [[ "$EXPECTED" != "$EXPECTED_SHA" ]]; then
    echo "SHA256 mismatch: expected $EXPECTED_SHA, got $EXPECTED" >&2
    EXIT_CODE=3
    exit 3
  fi
  echo "✓ checksum verified" >&2
elif [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] && [[ "$EXPECTED_SHA" != "0000000000000000000000000000000000000000" ]]; then
  echo "warning: EXPECTED_SHA looks like a git SHA (40 hex). Use the 64-char SHA256 from checksums.txt for binary verification." >&2
elif [[ "$EXPECTED_SHA" != "0000000000000000000000000000000000000000" && -n "$EXPECTED_SHA" ]]; then
  echo "warning: EXPECTED_SHA format not recognized, skipping verification" >&2
fi

tar -xzf "$WORKDIR/${ARCHIVE_NAME}" -C "$BIN_DIR"
chmod +x "$BIN_DIR/writeme"

mkdir -p "$WORKDIR/repo" "$WORKDIR/state" "$WORKDIR/cache"

export GH_README_REPOS_DIR="$WORKDIR/repo"
export XDG_STATE_HOME="$WORKDIR/state"
export XDG_CACHE_HOME="$WORKDIR/cache"

if [[ -t 1 ]]; then
  clear
fi

set +e
"$BIN_DIR/writeme" "$@"
EXIT_CODE=$?
set -e
exit "$EXIT_CODE"
