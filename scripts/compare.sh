#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"

if ! command -v benchstat &>/dev/null; then
  echo "error: benchstat not found. Install with: go install golang.org/x/perf/cmd/benchstat@be2c69fb417e" >&2
  exit 1
fi

# Accept explicit file arguments or discover the two most recent result files.
if [[ $# -eq 2 ]]; then
  OLD="$1"
  NEW="$2"
elif [[ $# -eq 0 ]]; then
  mapfile -t FILES < <(ls -t "${RESULTS_DIR}"/bench-*.txt 2>/dev/null)
  if [[ ${#FILES[@]} -lt 2 ]]; then
    echo "error: need at least 2 result files in ${RESULTS_DIR}. Run scripts/run-bench.sh first." >&2
    exit 1
  fi
  OLD="${FILES[1]}"
  NEW="${FILES[0]}"
else
  echo "usage: compare.sh [old.txt new.txt]" >&2
  exit 1
fi

echo "==> Comparing:"
echo "    old: ${OLD}"
echo "    new: ${NEW}"
echo ""
benchstat "${OLD}" "${NEW}"
