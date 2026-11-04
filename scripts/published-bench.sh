#!/usr/bin/env bash
# Benchmark published attest-engine releases and report the delta.
#
# Usage:
#   scripts/published-bench.sh --tag vX.Y.Z[-rc.N] [--base-tag vX.Y.Z[-rc.N]]
#                              [--platform linux-amd64] [--out DIR]
#   scripts/published-bench.sh --fetch-only --tag T [--base-tag B] --dest DIR
#   scripts/published-bench.sh --bench-only --tag T --base-tag B --dest DIR \
#                              --tag-sha H --base-sha H [--out DIR]
#
# Without a mode flag both phases run in one process (local use). CI runs them
# as two steps so the download token never exists in the benchmark step:
#   --fetch-only  resolves the base tag, downloads attest-engine-<platform> and
#                 checksums-sha256.txt for each tag into DEST/<tag>/, verifies
#                 the sha256 (fail closed on a missing asset, a missing or
#                 duplicate entry, or a mismatch) and prints
#                 base_tag=, tag_sha= and base_sha= on stdout for $GITHUB_OUTPUT.
#   --bench-only  re-verifies each binary against the hashes it was given, then
#                 runs the published-engine benchmarks in
#                 engine/internal/protocol, alternating base and tag sample by
#                 sample, and compares them with benchstat.
#
# Gate: exits 1 when a sec/op row of the benchstat delta for --tag against
# --base-tag shows a significant regression above REGRESSION_THRESHOLD_PCT
# (15). B/op and allocs/op measure the Go client and are reported, not gated.
# The delta is written to OUT/summary.md first, so a failing run is a report.
#
# Trust limit: the checksums file and the binary come from the same release, so
# the sha256 check detects corruption and mismatched uploads, not a compromised
# release. Releases carry no build attestations today. The engine runs with an
# allowlisted environment in an empty directory; that guards against accidental
# leaks and is not a sandbox.
#
# Environment: GH_TOKEN (read-only is enough; fetch phase only),
# BENCH_TIME (default 200x, fixed iterations), BENCH_COUNT (default 10, at
# least 6 so benchstat can compute intervals), RELEASE_REPO (default
# attest-framework/attest).
set -euo pipefail

readonly TAG_RE='^v[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}(-rc\.[0-9]{1,6})?$'
readonly SHA_RE='^[0-9a-f]{64}$'
readonly REGRESSION_THRESHOLD_PCT=15
readonly BENCH_PATTERN='^BenchmarkPublished'
readonly BENCH_ROWS=3
readonly MIN_BENCH_COUNT=6

die() { echo "error: $*" >&2; exit 1; }

# Sort key: semver with a release ordered after its release candidates.
sort_key() {
  local t="${1#v}" core rc major minor patch
  core="${t%%-*}"
  rc=1000000
  [[ "$t" == *-rc.* ]] && rc="${t##*-rc.}"
  IFS=. read -r major minor patch <<<"$core"
  printf '%08d.%08d.%08d.%08d' "$((10#$major))" "$((10#$minor))" "$((10#$patch))" "$((10#$rc))"
}

# Published, non-draft release tags of the attest repo, one per line.
list_release_tags() {
  gh release list -R "$RELEASE_REPO" --limit 100 --exclude-drafts --json tagName --jq '.[].tagName'
}

# Previous published release (rc tags count) strictly below $1.
previous_tag() {
  local want_key candidate best="" best_key="" key tags
  want_key="$(sort_key "$1")"
  tags="$(list_release_tags)" || die "listing releases of $RELEASE_REPO failed"
  while IFS= read -r candidate; do
    [[ "$candidate" =~ $TAG_RE ]] || continue
    key="$(sort_key "$candidate")"
    [[ "$key" < "$want_key" ]] || continue
    if [[ -z "$best" || "$key" > "$best_key" ]]; then best="$candidate"; best_key="$key"; fi
  done <<<"$tags"
  [[ -n "$best" ]] || die "no published release below $1"
  printf '%s' "$best"
}

# Reads benchstat output on stdin and prints "<row> +<pct>%" for each sec/op row
# whose delta exceeds the threshold. The unit comes from the table header.
gate_regressions() {
  awk -v limit="$REGRESSION_THRESHOLD_PCT" '
    /│/ && /sec\/op/ { unit = "sec"; next }
    /│/ && /B\/op/ { unit = "B"; next }
    /│/ && /allocs\/op/ { unit = "allocs"; next }
    unit == "sec" && /^[A-Za-z]/ && $1 != "geomean" {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^\+[0-9]+\.?[0-9]*%$/) {
          v = $i; gsub(/[+%]/, "", v)
          if (v + 0 > limit) printf "%s +%s%%\n", $1, v
        }
      }
    }'
}

sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# fetch_verified TAG DIR: leaves DIR/attest-engine verified; prints the sha256.
fetch_verified() {
  local t="$1" dir="$2" asset="attest-engine-${platform}" want got matches
  mkdir -p "$dir"
  [[ -z "$(ls -A "$dir")" ]] || die "download dir $dir is not empty"
  gh release download "$t" -R "$RELEASE_REPO" -D "$dir" -p "$asset" -p checksums-sha256.txt >&2
  [[ -f "$dir/$asset" ]] || die "$t: asset $asset missing"
  [[ -f "$dir/checksums-sha256.txt" ]] || die "$t: checksums-sha256.txt missing"
  matches="$(awk -v a="$asset" '$2 == a' "$dir/checksums-sha256.txt" | wc -l | tr -d ' ')"
  [[ "$matches" == "1" ]] || die "$t: expected exactly one checksum entry for $asset, found $matches"
  want="$(awk -v a="$asset" '$2 == a {print $1}' "$dir/checksums-sha256.txt")"
  [[ "$want" =~ $SHA_RE ]] || die "$t: malformed checksum entry for $asset"
  got="$(sha256_of "$dir/$asset")"
  [[ "$got" == "$want" ]] || die "$t: sha256 mismatch for $asset (expected $want, got $got)"
  mv "$dir/$asset" "$dir/attest-engine"
  chmod 0500 "$dir/attest-engine"
  echo "$t: $asset sha256 verified ($got)" >&2
  printf '%s' "$got"
}

# verify_binary TAG BIN EXPECTED_SHA: fail unless BIN still has the verified hash.
verify_binary() {
  [[ "$3" =~ $SHA_RE ]] || die "$1: malformed expected sha256"
  [[ -f "$2" ]] || die "$1: binary $2 missing"
  [[ "$(sha256_of "$2")" == "$3" ]] || die "$1: binary changed after verification"
}

# run_bench TAG BIN SHA DEST: one benchmark sample (-count=1) appended to DEST.
run_bench() {
  local t="$1" bin="$2" sha="$3" dest="$4" sample rows
  # The binary is untrusted: re-check it right before it runs and keep any
  # token out of the benchmark process and of the engine it spawns.
  verify_binary "$t" "$bin" "$sha"
  sample="$(cd "$REPO_ROOT/engine" && env -u GH_TOKEN -u GITHUB_TOKEN ATTEST_BENCH_PUBLISHED_ENGINE="$bin" go test ./internal/protocol/ \
    -run='^$' -bench="$BENCH_PATTERN" -benchmem -benchtime="$BENCH_TIME" -count=1 \
    -cpu=1 -timeout=30m)" || { printf '%s\n' "$sample" >&2; die "$t: benchmark run failed"; }
  rows="$(grep -c '^BenchmarkPublished' <<<"$sample" || true)"
  [[ "$rows" == "$BENCH_ROWS" ]] || { printf '%s\n' "$sample" >&2; die "$t: sample has $rows BenchmarkPublished rows, want $BENCH_ROWS"; }
  printf '%s\n' "$sample" | tee -a "$dest"
}

parse_args() {
  mode="all"; tag=""; base_tag=""; platform="linux-amd64"; out=""; dest=""; tag_sha=""; base_sha=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fetch-only) mode="fetch"; shift ;;
      --bench-only) mode="bench"; shift ;;
      --tag) tag="${2:-}"; shift 2 ;;
      --base-tag) base_tag="${2:-}"; shift 2 ;;
      --platform) platform="${2:-}"; shift 2 ;;
      --out) out="${2:-}"; shift 2 ;;
      --dest) dest="${2:-}"; shift 2 ;;
      --tag-sha) tag_sha="${2:-}"; shift 2 ;;
      --base-sha) base_sha="${2:-}"; shift 2 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
}

validate_args() {
  [[ -n "$tag" ]] || die "--tag is required"
  [[ "$tag" =~ $TAG_RE ]] || die "tag '$tag' does not match $TAG_RE"
  [[ -z "$base_tag" || "$base_tag" =~ $TAG_RE ]] || die "base tag '$base_tag' does not match $TAG_RE"
  [[ "$platform" =~ ^(linux|darwin)-(amd64|arm64)$ ]] || die "unsupported platform '$platform'"
  [[ "$BENCH_TIME" =~ ^[0-9]+(s|x)$ ]] || die "BENCH_TIME '$BENCH_TIME' must look like 5s or 200x"
  [[ "$BENCH_COUNT" =~ ^[0-9]+$ ]] || die "BENCH_COUNT '$BENCH_COUNT' must be an integer"
  (( BENCH_COUNT >= MIN_BENCH_COUNT )) || die "BENCH_COUNT $BENCH_COUNT is below $MIN_BENCH_COUNT; benchstat needs $MIN_BENCH_COUNT+ samples"
  if [[ "$mode" != "bench" ]]; then command -v gh >/dev/null || die "gh not found"; fi
  if [[ "$mode" != "fetch" ]]; then command -v benchstat >/dev/null || die "benchstat not found"; fi
  if [[ "$mode" != "all" ]]; then [[ -n "$dest" ]] || die "--dest is required with --fetch-only/--bench-only"; fi
}

resolve_base() {
  [[ -n "$base_tag" ]] || base_tag="$(previous_tag "$tag")"
  [[ "$base_tag" != "$tag" ]] || die "base tag equals tag ($tag)"
}

bench_and_report() {
  local bin_base="$1" bin_new="$2" delta regressed line i
  mkdir -p "$out"
  : >"$out/bench-${base_tag}.txt"
  : >"$out/bench-${tag}.txt"
  # Alternate the engines sample by sample so runner drift hits both equally.
  for ((i = 1; i <= BENCH_COUNT; i++)); do
    run_bench "$base_tag" "$bin_base" "$base_sha" "$out/bench-${base_tag}.txt"
    run_bench "$tag" "$bin_new" "$tag_sha" "$out/bench-${tag}.txt"
  done

  delta="$(benchstat "$out/bench-${base_tag}.txt" "$out/bench-${tag}.txt" 2>&1)" || { printf '%s\n' "$delta" >&2; die "benchstat failed"; }
  [[ "$delta" == *"sec/op"* ]] || die "benchstat output has no sec/op table; refusing to pass the gate"
  {
    echo "## Published engine benchmarks: ${base_tag} -> ${tag} (${platform})"
    echo
    echo "Gate: a significant sec/op regression of ${tag} over ${base_tag} above ${REGRESSION_THRESHOLD_PCT}% fails the run. B/op and allocs/op are reported, not gated."
    echo
    echo '```text'
    echo "$delta"
    echo '```'
  } | tee "$out/summary.md"

  regressed="$(gate_regressions <<<"$delta")"
  if [[ -n "$regressed" ]]; then
    while IFS= read -r line; do echo "REGRESSION: $line" >&2; done <<<"$regressed"
    die "${tag} regressed more than ${REGRESSION_THRESHOLD_PCT}% against ${base_tag}"
  fi
  echo "No sec/op regression above ${REGRESSION_THRESHOLD_PCT}% (${tag} vs ${base_tag})"
}

main() {
  RELEASE_REPO="${RELEASE_REPO:-attest-framework/attest}"
  BENCH_TIME="${BENCH_TIME:-200x}"
  BENCH_COUNT="${BENCH_COUNT:-10}"
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  parse_args "$@"
  validate_args
  [[ -n "$out" ]] || out="${REPO_ROOT}/results/published"

  case "$mode" in
    fetch)
      resolve_base
      mkdir -p "$dest"
      base_sha="$(fetch_verified "$base_tag" "$dest/$base_tag")"
      tag_sha="$(fetch_verified "$tag" "$dest/$tag")"
      printf 'base_tag=%s\nbase_sha=%s\ntag_sha=%s\n' "$base_tag" "$base_sha" "$tag_sha"
      ;;
    bench)
      [[ -n "$base_tag" ]] || die "--base-tag is required with --bench-only"
      [[ "$base_tag" != "$tag" ]] || die "base tag equals tag ($tag)"
      bench_and_report "$dest/$base_tag/attest-engine" "$dest/$tag/attest-engine"
      ;;
    all)
      resolve_base
      dest="$(mktemp -d)"
      trap 'rm -rf "$dest"' EXIT
      base_sha="$(fetch_verified "$base_tag" "$dest/$base_tag")"
      tag_sha="$(fetch_verified "$tag" "$dest/$tag")"
      bench_and_report "$dest/$base_tag/attest-engine" "$dest/$tag/attest-engine"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
