#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT="${RESULTS_DIR}/bench-${TIMESTAMP}.txt"

mkdir -p "${RESULTS_DIR}"

echo "==> Building engine binary..."
make -C "${REPO_ROOT}" engine

echo "==> Warmup run (discarded)..."
cd "${REPO_ROOT}/engine"
go test ./internal/protocol/ -run='^$' -bench=. -benchtime=1s -count=1 -benchmem > /dev/null

echo "==> Production run (count=10, cpu=1)..."
go test ./internal/protocol/ -run='^$' -bench=. -benchtime=3s -count=10 -cpu=1 -benchmem \
  | tee "${OUTPUT}"

echo ""
echo "==> Results written to: ${OUTPUT}"
