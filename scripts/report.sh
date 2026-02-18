#!/usr/bin/env bash
# Parse the most recent benchmark output and evaluate against go/no-go thresholds.
# Thresholds:
#   BenchmarkStdioRoundtrip/medium  < 20ms per op
#   BenchmarkStdioRoundtrip/large   < 100ms per op
#   BenchmarkSerialization (any)    < 10% overhead vs raw marshal (not applicable here;
#                                    proxy: serialization time < 10ms per op for medium)
#   BenchmarkEngineStartup          < 10ms per op
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"

# Accept an explicit file or use the most recent result.
if [[ $# -eq 1 ]]; then
  RESULT_FILE="$1"
else
  RESULT_FILE="$(ls -t "${RESULTS_DIR}"/bench-*.txt 2>/dev/null | head -1)"
  if [[ -z "${RESULT_FILE}" ]]; then
    echo "error: no result files found in ${RESULTS_DIR}. Run scripts/run-bench.sh first." >&2
    exit 1
  fi
fi

echo "==> Parsing: ${RESULT_FILE}"
echo ""

# Extract ns/op for a named benchmark (average across -count runs).
# Output is in nanoseconds.
get_ns_per_op() {
  local pattern="$1"
  awk -v pat="$pattern" '
    $0 ~ pat {
      # Benchmark line format: BenchmarkName-N   iterations   ns/op ...
      # Field 3 is ns/op
      sum += $3; count++
    }
    END {
      if (count > 0) printf "%.0f", sum / count
      else print "N/A"
    }
  ' "${RESULT_FILE}"
}

ns_to_ms() {
  awk -v ns="$1" 'BEGIN { printf "%.3f", ns / 1000000 }'
}

PASS=0
FAIL=0

check() {
  local label="$1"
  local ns="$2"
  local threshold_ms="$3"

  if [[ "${ns}" == "N/A" ]]; then
    echo "  [SKIP] ${label}: no data found"
    return
  fi

  local actual_ms
  actual_ms="$(ns_to_ms "${ns}")"
  local ok
  ok="$(awk -v a="${actual_ms}" -v t="${threshold_ms}" 'BEGIN { print (a < t) ? "yes" : "no" }')"

  if [[ "${ok}" == "yes" ]]; then
    echo "  [PASS] ${label}: ${actual_ms}ms  (threshold: <${threshold_ms}ms)"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] ${label}: ${actual_ms}ms  (threshold: <${threshold_ms}ms)"
    FAIL=$((FAIL + 1))
  fi
}

echo "--- Go/No-Go Report ---"
echo ""

# Roundtrip latency
RT_MEDIUM_NS="$(get_ns_per_op 'BenchmarkStdioRoundtrip/medium')"
RT_LARGE_NS="$(get_ns_per_op 'BenchmarkStdioRoundtrip/large')"

check "StdioRoundtrip/medium" "${RT_MEDIUM_NS}" "20"
check "StdioRoundtrip/large"  "${RT_LARGE_NS}"  "100"

# Serialization overhead (medium as proxy, threshold <10ms)
SER_MEDIUM_NS="$(get_ns_per_op 'BenchmarkSerialization/medium')"
SER_LARGE_NS="$(get_ns_per_op 'BenchmarkSerialization/large')"

check "Serialization/medium"  "${SER_MEDIUM_NS}" "10"
check "Serialization/large"   "${SER_LARGE_NS}"  "100"

# Engine startup
STARTUP_NS="$(get_ns_per_op 'BenchmarkEngineStartup')"
check "EngineStartup"          "${STARTUP_NS}"   "10"

echo ""
echo "--- Summary: ${PASS} passed, ${FAIL} failed ---"
echo ""

if [[ ${FAIL} -gt 0 ]]; then
  exit 1
fi
