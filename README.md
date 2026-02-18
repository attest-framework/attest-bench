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

## Specification

See [docs/protocol-benchmark-spec.md](docs/protocol-benchmark-spec.md) for the full benchmark specification, architecture, go/no-go criteria, and baseline results.
