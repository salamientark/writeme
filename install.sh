#!/usr/bin/env bash
# writeme launcher: downloads the Go binary, runs in an ephemeral sandbox.
# No persistent install — everything lives under a mktemp sandbox.
set -euo pipefail

NUKE_ON_FAIL="${NUKE_ON_FAIL:-0}"
REPO_URL="${REPO_URL:-https://github.com/salamientark/writeme}"
VERSION="${VERSION:-latest}"
EXPECTED_SHA="${EXPECTED_SHA:-0000000000000000000000000000000000000000}"
SKIP_DEP_CHECK="${SKIP_DEP_CHECK:-0}"

# `latest` uses the /releases/latest/download/ path; tags use /releases/download/<tag>/.
if [[ "$VERSION" == "latest" ]]; then
  REL_PATH="releases/latest/download"
else
  REL_PATH="releases/download/${VERSION}"
fi
CHECKSUM_URL="${REPO_URL}/${REL_PATH}/checksums.txt"

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
  require_dep uname  "(coreutils)"                        || fail=1
  require_dep tr     "(coreutils)"                        || fail=1
  if [[ "$fail" == "1" ]]; then
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "gh auth: not authenticated. Run: gh auth login" >&2
    exit 1
  fi
fi

# Resolve platform/arch (after the dependency gate so missing uname/tr
# exit via the controlled path, not 127).
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

# Resolve a sha256 implementation (linux: sha256sum, macOS: shasum -a 256).
if command -v sha256sum >/dev/null 2>&1; then
  sha256_of() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "missing dependency: sha256sum or shasum" >&2
  exit 1
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

# Fetch the release checksum manifest first — it resolves the exact
# (versioned) archive name even when VERSION=latest.
echo "Downloading writeme ${VERSION} (${OS}/${ARCH})..." >&2
BIN_DIR="$WORKDIR/bin"
mkdir -p "$BIN_DIR"

if ! curl -fsSL -o "$WORKDIR/checksums.txt" "$CHECKSUM_URL"; then
  echo "failed to download $CHECKSUM_URL" >&2
  EXIT_CODE=1
  exit 1
fi

ARCHIVE_NAME=$(grep -E "_${OS}_${ARCH}\.tar\.gz\$" "$WORKDIR/checksums.txt" | awk '{print $NF}' | head -n1)
if [[ -z "$ARCHIVE_NAME" ]]; then
  echo "no release asset for ${OS}/${ARCH} in checksums.txt" >&2
  EXIT_CODE=4
  exit 4
fi
DOWNLOAD_URL="${REPO_URL}/${REL_PATH}/${ARCHIVE_NAME}"

if ! curl -fsSL -o "$WORKDIR/${ARCHIVE_NAME}" "$DOWNLOAD_URL"; then
  echo "failed to download $DOWNLOAD_URL" >&2
  EXIT_CODE=1
  exit 1
fi

# Integrity: the downloaded archive must match the release manifest hash.
MANIFEST_SHA=$(grep -E " [*]?${ARCHIVE_NAME}\$" "$WORKDIR/checksums.txt" | awk '{print $1}' | head -n1)
ACTUAL_SHA=$(sha256_of "$WORKDIR/${ARCHIVE_NAME}")
if [[ -z "$MANIFEST_SHA" || "$ACTUAL_SHA" != "$MANIFEST_SHA" ]]; then
  echo "SHA256 mismatch vs checksums.txt: manifest=$MANIFEST_SHA actual=$ACTUAL_SHA" >&2
  EXIT_CODE=3
  exit 3
fi

# Optional out-of-band pin: a real 64-hex EXPECTED_SHA must also match.
if [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]]; then
  if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
    echo "SHA256 pin mismatch: expected $EXPECTED_SHA, got $ACTUAL_SHA" >&2
    EXIT_CODE=3
    exit 3
  fi
  echo "✓ checksum verified (pinned)" >&2
elif [[ -z "$EXPECTED_SHA" || "$EXPECTED_SHA" =~ ^0+$ ]]; then
  echo "✓ checksum verified against release manifest (unpinned — set EXPECTED_SHA to pin)" >&2
else
  echo "warning: EXPECTED_SHA not 64-hex; verified against release manifest only" >&2
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

# When this script is run via `curl ... | bash`, bash reads the script
# body from stdin. writeme's interactive TUI would otherwise consume the
# remaining script lines as keystrokes. Bind its stdin to the controlling
# terminal instead; fall back to inherited stdin when no tty (CI/pipes).
set +e
if [[ -e /dev/tty ]]; then
  "$BIN_DIR/writeme" "$@" < /dev/tty
else
  "$BIN_DIR/writeme" "$@"
fi
EXIT_CODE=$?
set -e
exit "$EXIT_CODE"
