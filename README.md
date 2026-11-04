# attest-bench

Benchmark harness for the Attest protocol engine. Phase 0 validation gate for Attest protocol performance and stability.

## Purpose

attest-bench is a dedicated repository for performance testing and validation of the Attest protocol engine. It serves as the gating criteria for Phase 1 SDK work and ensures protocol implementations meet performance targets before being integrated into the main Attest codebase.

For the main Attest framework, see [github.com/attest-framework/attest](https://github.com/attest-framework/attest).

## Quick Start

```bash
make bench-all
```

This runs the complete benchmark suite with synthetic traces and reports results to `results/$(date +%Y-%m-%d-%H%M).txt`.

## Go/No-Go Criteria

| Benchmark | Steps | Assertions | Target | Hard Ceiling | Actual | Status |
|-----------|-------|------------|--------|-------------|--------|--------|
| Small EvaluateBatch | 10 | 5 | <3ms | 5ms | 0.07ms | PASS |
| Medium EvaluateBatch | 50 | 10 | <5ms | 10ms | 0.42ms | PASS |
| Large EvaluateBatch | 100 | 10 | <5ms | 10ms | 1.19ms | PASS |
| XL EvaluateBatch | 500 | 20 | <15ms | 30ms | 10.46ms | PASS |
| XL Subprocess Roundtrip | 500 | 20 | <15ms | 30ms | 15.35ms | MONITOR |
| Engine cold start | — | — | <500ms | 1000ms | 3.23ms | PASS |

## Benchmarking published engine releases

The `benchmark-regression` workflow also benchmarks the released `attest-engine` binary from an [attest](https://github.com/attest-framework/attest) GitHub release and reports the delta against the previous published release:

```bash
gh workflow run benchmark-regression.yml -f tag=v1.0.0-rc.5
gh workflow run benchmark-regression.yml -f tag=v1.0.0 -f base_tag=v1.0.0-rc.5
```

`tag` and `base_tag` must match `vX.Y.Z` or `vX.Y.Z-rc.N`. `base_tag` defaults to the previous published `v*` release by semver order (rc tags count). Without `tag`, the workflow keeps its source-built mode against `results/baselines/ci-linux-amd64.txt`.

For each tag the job downloads `attest-engine-linux-amd64` and `checksums-sha256.txt` with the read-only workflow token, verifies the sha256, and fails closed on a missing entry, a duplicate entry or a mismatch. The checksums file and the binary come from the same release, so this detects corruption and mismatched uploads, not a compromised release; releases carry no build attestations yet. The binary runs with an allowlisted environment (no token) in an empty working directory. It then runs `BenchmarkPublishedEngine*` (process start plus `initialize`, and `evaluate_batch` round-trips) against each binary and compares them with benchstat. The delta is written to the job summary and uploaded as the `published-engine-benchmarks` artifact.

Gate: the job fails only when `tag` shows a significant regression above 15% against `base_tag`; improvements and non-significant deltas pass. The comparison is always reported first, so a failing run still carries the full delta.

To run it locally (needs `gh`, `benchstat` and Go):

```bash
scripts/published-bench.sh --tag v1.0.0-rc.5 --platform darwin-arm64 --out /tmp/published-bench
```

## Project Structure

- `engine/` — Minimal engine implementation for benchmarking
  - `cmd/attest-engine/` — CLI entry point (`serve` subcommand)
  - `internal/protocol/` — JSON-RPC codec, stdio message loop, benchmarks
  - `internal/trace/` — Trace types and synthetic data generation
- `docs/` — Specifications and architecture decisions
- `results/baselines/` — Committed benchmark baselines for regression detection
- `scripts/` — Benchmark utilities (run, compare, report)

## Usage

```bash
make bench-full                   # Full suite with percentiles, saves timestamped results
make bench-all                    # Legacy: full suite, saves timestamped results
make bench-serial                 # Serialization benchmarks only
make bench-protocol               # Stdio roundtrip benchmarks only
make bench-startup                # Engine cold start benchmarks only
make bench-init                   # Initialize method benchmarks
make bench-shutdown               # Shutdown method benchmarks
make bench-subprocess             # Subprocess lifecycle roundtrip
make bench-concurrent             # Concurrent session contention test (2 sessions)
make bench-concurrent-scaled      # Scaled concurrency (2, 5, 10 sessions)
make bench-scaling                # Serialization scaling across step counts
make bench-latency                # Percentile latency collection (p50/p95/p99)
make bench-sustained              # Sustained load GC pressure test
make bench-codec                  # Codec comparison (stdlib, json-iterator, segmentio)
make bench-profile-allocs         # Allocation profiling for serialization benchmarks
make bench-report                 # Generate structured markdown report from latest results
```

## Approach Comparison (Python)

A Python benchmark comparing 3 evaluation approaches across 50 customer support scenarios:

- **All LLM Judge** — broad judge calls for every evaluation dimension (~175 judge calls for 50 scenarios)
- **Graduated** — deterministic layers (schema, constraints, trace, content) + judge for subjective criteria only
- **Pure Deterministic** — deterministic assertions only, zero judge calls, zero API cost

```bash
make setup-approaches                        # install dependencies (uv sync)
make bench-approaches-dry                    # dry-run: no engine, no API calls
make bench-approaches                        # full run (fresh engine per trial)
make bench-approaches-single SCENARIO=SC-001 # run a single scenario ID
```

Each trial starts a fresh engine with an isolated cache directory for experimental reproducibility. Pass `--use-cache` to reuse cached judge/embedding results across trials for faster iteration during development.

Requirements: Python 3.12+, `uv`, `ATTEST_OPENAI_API_KEY` for full runs (not needed for `--dry-run`).

Results are written to `approach-comparison/results/benchmark-<timestamp>.json`.

### Results (50 scenarios × 3 trials, gpt-4.1 judge)

| Metric | All LLM Judge | Graduated | Pure Deterministic |
|--------|--------------|-----------|-------------------|
| Total Cost (USD) | $0.5571 | $0.2659 | $0.0000 |
| Wall Clock (s) | 573.6s | 303.9s | 0.4s |
| Consistency | 96.5% | 99.0% | 100.0% |
| Judge Calls | 600 | 330 | 0 |
| Total Assertions | 600 | 2466 | 2436 |
| Pass Rate | 442/600 (74%) | 2431/2466 (99%) | 2388/2436 (98%) |

**Key findings:**
- Graduated achieves 99% pass rate at 48% of the all-judge cost and 53% of the wall clock time
- Pure deterministic covers 98% of assertions at zero cost in under 1 second
- All-judge has the lowest pass rate (74%) — broad judge calls without deterministic grounding are less reliable
- Consistency tracks inversely with LLM dependency: 100% → 99% → 96.5%

## Specification

See [docs/protocol-benchmark-spec.md](docs/protocol-benchmark-spec.md) for the full benchmark specification, architecture, go/no-go criteria, and baseline results.
