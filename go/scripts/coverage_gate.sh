#!/usr/bin/env bash
# Per-package coverage gate (G9). Reads `go test -cover ./...` output from
# arg1 (or stdin) and fails if any internal/* package is <80%.
# `cmd/writeme` is excluded as thin wiring (per v1-plan §3 G9).
set -euo pipefail

THRESHOLD=80.0
INPUT="${1:-/dev/stdin}"

awk -v threshold="$THRESHOLD" '
  /coverage: [0-9.]+% of statements/ {
    pkg = ""
    for (i = 1; i <= NF; i++) {
      if ($i == "ok" && (i+1) <= NF) { pkg = $(i+1); break }
    }
    if (pkg == "") next
    if (pkg ~ /\/cmd\/writeme$/) next
    if (pkg !~ /\/internal\//) next

    pct = ""
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^[0-9.]+%$/) { pct = $i; sub(/%$/, "", pct); break }
    }
    if (pct == "") next

    if (pct + 0.0 < threshold + 0.0) {
      printf("FAIL: %s coverage %s%% < %.1f%%\n", pkg, pct, threshold) > "/dev/stderr"
      bad++
    } else {
      printf("ok:   %s %s%%\n", pkg, pct)
    }
  }
  END {
    if (bad > 0) {
      printf("\n%d package(s) below %.1f%% coverage\n", bad, threshold) > "/dev/stderr"
      exit 1
    }
  }
' "$INPUT"
