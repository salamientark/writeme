#!/usr/bin/env bash
# RED-first test for coverage_gate.sh. Exit 0 if all assertions pass.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/coverage_gate.sh"

if [[ ! -x "$GATE" ]]; then
  echo "FAIL: $GATE missing or not executable"
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Case 1: all internal packages >= 80% -> pass.
cat >"$tmp/pass.txt" <<'EOF'
ok  	writeme/cmd/writeme	0.012s	coverage: 12.3% of statements
ok  	writeme/internal/cli	0.045s	coverage: 95.2% of statements
ok  	writeme/internal/state	0.030s	coverage: 80.0% of statements
ok  	writeme/internal/safety	0.020s	coverage: 88.4% of statements
EOF
if ! "$GATE" "$tmp/pass.txt" >"$tmp/pass.out" 2>&1; then
  echo "FAIL: gate rejected passing input"
  cat "$tmp/pass.out"
  exit 1
fi

# Case 2: one internal package below 80% -> fail.
cat >"$tmp/fail.txt" <<'EOF'
ok  	writeme/internal/cli	0.045s	coverage: 95.2% of statements
ok  	writeme/internal/state	0.030s	coverage: 79.9% of statements
EOF
if "$GATE" "$tmp/fail.txt" >"$tmp/fail.out" 2>&1; then
  echo "FAIL: gate accepted sub-80 package"
  cat "$tmp/fail.out"
  exit 1
fi
grep -q "internal/state" "$tmp/fail.out" || { echo "FAIL: gate did not name failing pkg"; cat "$tmp/fail.out"; exit 1; }

# Case 3: cmd/writeme excluded even when low.
cat >"$tmp/cmd.txt" <<'EOF'
ok  	writeme/cmd/writeme	0.012s	coverage: 5.0% of statements
ok  	writeme/internal/cli	0.045s	coverage: 95.2% of statements
EOF
if ! "$GATE" "$tmp/cmd.txt" >"$tmp/cmd.out" 2>&1; then
  echo "FAIL: gate did not exclude cmd/writeme"
  cat "$tmp/cmd.out"
  exit 1
fi

# Case 4: package with [no test files] is ignored (Go prints no coverage line).
cat >"$tmp/notest.txt" <<'EOF'
?   	writeme/internal/version	[no test files]
ok  	writeme/internal/cli	0.045s	coverage: 95.2% of statements
EOF
if ! "$GATE" "$tmp/notest.txt" >"$tmp/notest.out" 2>&1; then
  echo "FAIL: gate failed on [no test files] line"
  cat "$tmp/notest.out"
  exit 1
fi

# Case 5: package with 0.0% -> fail.
cat >"$tmp/zero.txt" <<'EOF'
ok  	writeme/internal/foo	0.001s	coverage: 0.0% of statements [no tests to run]
EOF
if "$GATE" "$tmp/zero.txt" >"$tmp/zero.out" 2>&1; then
  echo "FAIL: gate accepted 0.0% pkg"
  exit 1
fi

echo "OK: all coverage_gate.sh cases passed"
