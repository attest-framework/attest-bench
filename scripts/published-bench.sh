#!/usr/bin/env bash
# Benchmark published attest-engine releases and report the delta.
#
# Usage: scripts/published-bench.sh --tag vX.Y.Z[-rc.N] [--base-tag vX.Y.Z[-rc.N]]
#                                   [--platform linux-amd64] [--out DIR]
#
# For each tag: download the platform binary and checksums-sha256.txt from the
# attest GitHub release, verify the sha256 (fail closed on a missing entry, a
# duplicate entry or a mismatch), then run the published-engine benchmarks in
# engine/internal/protocol against the binary. benchstat compares base -> tag.
#
# Gate: exits 1 when the benchstat delta of --tag against --base-tag shows a
# significant regression above REGRESSION_THRESHOLD_PCT (15). The delta is
# always written to DIR/summary.md first, so a failing run is still a report.
#
# Environment: GH_TOKEN (read-only is enough), BENCH_TIME (default 5s),
# BENCH_COUNT (default 5), RELEASE_REPO (default attest-framework/attest).
set -euo pipefail

readonly TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$'
readonly REGRESSION_THRESHOLD_PCT=15
readonly RELEASE_REPO="${RELEASE_REPO:-attest-framework/attest}"
readonly BENCH_TIME="${BENCH_TIME:-5s}"
readonly BENCH_COUNT="${BENCH_COUNT:-5}"
readonly BENCH_PATTERN='^BenchmarkPublished'

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
tag=""
base_tag=""
platform="linux-amd64"
out=""

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) tag="${2:-}"; shift 2 ;;
    --base-tag) base_tag="${2:-}"; shift 2 ;;
    --platform) platform="${2:-}"; shift 2 ;;
    --out) out="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$tag" ]] || die "--tag is required"
[[ "$tag" =~ $TAG_RE ]] || die "tag '$tag' does not match $TAG_RE"
[[ -z "$base_tag" || "$base_tag" =~ $TAG_RE ]] || die "base tag '$base_tag' does not match $TAG_RE"
[[ "$platform" =~ ^(linux|darwin)-(amd64|arm64)$ ]] || die "unsupported platform '$platform'"
[[ "$BENCH_TIME" =~ ^[0-9]+(s|x)$ ]] || die "BENCH_TIME '$BENCH_TIME' must look like 5s or 200x"
[[ "$BENCH_COUNT" =~ ^[0-9]+$ ]] || die "BENCH_COUNT '$BENCH_COUNT' must be an integer"
[[ -n "$out" ]] || out="${REPO_ROOT}/results/published"
command -v gh >/dev/null || die "gh not found"
command -v benchstat >/dev/null || die "benchstat not found"

# Sort key: semver with a release ordered after its release candidates.
sort_key() {
  local t="${1#v}" core rc
  core="${t%%-*}"
  rc=1000000
  [[ "$t" == *-rc.* ]] && rc="${t##*-rc.}"
  IFS=. read -r major minor patch <<<"$core"
  printf '%08d.%08d.%08d.%08d' "$major" "$minor" "$patch" "$rc"
}

# Previous published release (rc tags count) strictly below $1.
previous_tag() {
  local want_key candidate best="" best_key="" key
  want_key="$(sort_key "$1")"
  while IFS= read -r candidate; do
    [[ "$candidate" =~ $TAG_RE ]] || continue
    key="$(sort_key "$candidate")"
    [[ "$key" < "$want_key" ]] || continue
    if [[ -z "$best" || "$key" > "$best_key" ]]; then best="$candidate"; best_key="$key"; fi
  done < <(gh release list -R "$RELEASE_REPO" --limit 100 --json tagName --jq '.[].tagName')
  [[ -n "$best" ]] || die "no published release below $1"
  printf '%s' "$best"
}

sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# fetch_verified TAG DIR: leaves DIR/attest-engine verified against the release checksums.
fetch_verified() {
  local t="$1" dir="$2" asset="attest-engine-${platform}" want got matches
  mkdir -p "$dir"
  [[ -z "$(ls -A "$dir")" ]] || die "download dir $dir is not empty"
  gh release download "$t" -R "$RELEASE_REPO" -D "$dir" -p "$asset" -p checksums-sha256.txt
  [[ -f "$dir/$asset" ]] || die "$t: asset $asset missing"
  [[ -f "$dir/checksums-sha256.txt" ]] || die "$t: checksums-sha256.txt missing"
  matches="$(awk -v a="$asset" '$2 == a' "$dir/checksums-sha256.txt" | wc -l | tr -d ' ')"
  [[ "$matches" == "1" ]] || die "$t: expected exactly one checksum entry for $asset, found $matches"
  want="$(awk -v a="$asset" '$2 == a {print $1}' "$dir/checksums-sha256.txt")"
  [[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "$t: malformed checksum entry for $asset"
  got="$(sha256_of "$dir/$asset")"
  [[ "$got" == "$want" ]] || die "$t: sha256 mismatch for $asset (expected $want, got $got)"
  mv "$dir/$asset" "$dir/attest-engine"
  chmod +x "$dir/attest-engine"
  echo "$t: $asset sha256 verified ($got)"
}

run_bench() {
  local t="$1" bin="$2" dest="$3"
  (cd "$REPO_ROOT/engine" && ATTEST_BENCH_PUBLISHED_ENGINE="$bin" go test ./internal/protocol/ \
    -run='^$' -bench="$BENCH_PATTERN" -benchmem -benchtime="$BENCH_TIME" -count="$BENCH_COUNT" \
    -cpu=1 -timeout=30m) | tee "$dest"
  grep -q '^BenchmarkPublished' "$dest" || die "$t: benchmark produced no BenchmarkPublished results"
}

[[ -n "$base_tag" ]] || base_tag="$(previous_tag "$tag")"
[[ "$base_tag" != "$tag" ]] || die "base tag equals tag ($tag)"

mkdir -p "$out"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fetch_verified "$base_tag" "$work/base"
fetch_verified "$tag" "$work/new"
run_bench "$base_tag" "$work/base/attest-engine" "$out/bench-${base_tag}.txt"
run_bench "$tag" "$work/new/attest-engine" "$out/bench-${tag}.txt"

delta="$(benchstat "$out/bench-${base_tag}.txt" "$out/bench-${tag}.txt" 2>&1)"
{
  echo "## Published engine benchmarks: ${base_tag} -> ${tag} (${platform})"
  echo
  echo "Gate: a significant regression of ${tag} over ${base_tag} above ${REGRESSION_THRESHOLD_PCT}% fails the run."
  echo
  echo '```text'
  echo "$delta"
  echo '```'
} | tee "$out/summary.md"

regressed="$(awk -v limit="$REGRESSION_THRESHOLD_PCT" '
  /^[A-Za-z]/ && $1 != "geomean" {
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^\+[0-9]+\.?[0-9]*%$/) {
        v = $i; gsub(/[+%]/, "", v)
        if (v + 0 > limit) printf "%s +%s%%\n", $1, v
      }
    }
  }' <<<"$delta")"
if [[ -n "$regressed" ]]; then
  echo "$regressed" | sed 's/^/REGRESSION: /' >&2
  die "${tag} regressed more than ${REGRESSION_THRESHOLD_PCT}% against ${base_tag}"
fi
echo "No regression above ${REGRESSION_THRESHOLD_PCT}% (${tag} vs ${base_tag})"
