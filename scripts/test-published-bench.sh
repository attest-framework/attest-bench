#!/usr/bin/env bash
# Fixture tests for the pure functions in scripts/published-bench.sh:
# gate_regressions, sort_key and previous_tag. No network, no gh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/published-bench.sh
source "$SCRIPT_DIR/published-bench.sh"
export RELEASE_REPO=test/repo

failures=0
check() { # check NAME EXPECTED ACTUAL
  if [[ "$2" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: expected [$2] got [$3]" >&2; failures=$((failures + 1)); fi
}

# benchstat-shaped table: SEC_ROW is placed in the sec/op table, BYTES_ROW in B/op.
table() { # table SEC_ROW [BYTES_ROW]
  printf '%s\n' \
    '                       │ old.txt │ new.txt │' \
    '                       │ sec/op  │ sec/op  vs base │' \
    "$1" \
    'geomean                   5.0m      9.0m      +80.00%' \
    '' \
    '                       │ old.txt │ new.txt │' \
    '                       │  B/op   │  B/op   vs base │' \
    "${2:-PublishedEngineStartup   1.0Mi ± 0%   1.0Mi ± 0%   ~ (p=1.000 n=10)}" \
    'geomean                   1.0Mi     1.0Mi     +0.00%'
}
gate() { gate_regressions <<<"$1"; }

check "gate: insignificant row (~) passes" "" "$(gate "$(table 'PublishedEngineStartup   10m ± 5%   30m ± 5%   ~ (p=0.400 n=10)')")"
check "gate: +15.00% passes" "" "$(gate "$(table 'PublishedEngineStartup   10m ± 5%   11.5m ± 5%   +15.00% (p=0.002 n=10)')")"
check "gate: +15.01% fails" "PublishedEngineStartup +15.01%" "$(gate "$(table 'PublishedEngineStartup   10m ± 5%   11.5m ± 5%   +15.01% (p=0.002 n=10)')")"
check "gate: -40% improvement passes" "" "$(gate "$(table 'PublishedEngineStartup   10m ± 5%   6m ± 5%   -40.00% (p=0.002 n=10)')")"
check "gate: geomean row alone is ignored" "" "$(gate "$(table 'PublishedEngineEvaluate/10step_5assert   1m ± 5%   1m ± 5%   ~ (p=1.000 n=10)')")"
check "gate: B/op +25% does not fail" "" "$(gate "$(table 'PublishedEngineStartup   10m ± 5%   10m ± 5%   ~ (p=1.000 n=10)' 'PublishedEngineStartup   1.0Mi ± 0%   1.3Mi ± 0%   +25.00% (p=0.000 n=10)')")"
check "gate: only the regressed sec/op row is named" "PublishedEngineEvaluate/100step_10assert +20.00%" \
  "$(gate "$(table $'PublishedEngineStartup   10m ± 5%   10m ± 5%   ~ (p=1.000 n=10)\nPublishedEngineEvaluate/100step_10assert   5m ± 5%   6m ± 5%   +20.00% (p=0.001 n=10)')")"

check "sort_key: rc.2 < rc.10" "yes" "$([[ "$(sort_key v1.0.0-rc.2)" < "$(sort_key v1.0.0-rc.10)" ]] && echo yes || echo no)"
check "sort_key: rc.5 < 1.0.0" "yes" "$([[ "$(sort_key v1.0.0-rc.5)" < "$(sort_key v1.0.0)" ]] && echo yes || echo no)"
check "sort_key: 0.9.0 < 1.0.0-rc.1" "yes" "$([[ "$(sort_key v0.9.0)" < "$(sort_key v1.0.0-rc.1)" ]] && echo yes || echo no)"
check "sort_key: leading zero is decimal" "00000001.00000008.00000000.01000000" "$(sort_key v1.08.0)"

# shellcheck disable=SC2329 # called by previous_tag
list_release_tags() { printf '%s\n' v0.9.0 v1.0.0-rc v1.0.0-rc.1 v1.0.0-rc.5 v1.0.0-rc.4 v1.0.0-rc.10 v0.8.0 not-a-tag; }
check "previous_tag: rc.5 -> rc.4" "v1.0.0-rc.4" "$(previous_tag v1.0.0-rc.5)"
check "previous_tag: 1.0.0 -> rc.10" "v1.0.0-rc.10" "$(previous_tag v1.0.0)"
check "previous_tag: rc.1 -> 0.9.0 (bare rc ignored)" "v0.9.0" "$(previous_tag v1.0.0-rc.1)"
check "previous_tag: nothing below fails" "fail" "$( (previous_tag v0.8.0 >/dev/null 2>&1) && echo ok || echo fail)"
# shellcheck disable=SC2329 # called by previous_tag
list_release_tags() { return 1; }
check "previous_tag: gh failure fails loudly" "listing releases of test/repo failed" "$(previous_tag v1.0.0 2>&1 >/dev/null | sed 's/^error: //')"

(( failures == 0 )) || { echo "$failures failure(s)" >&2; exit 1; }
echo "all published-bench script tests passed"
