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

| Benchmark          | Metric       | Target  | Actual (M1 Pro) | Status |
| ------------------ | ------------ | ------- | --------------- | ------ |
| **Medium traces**  | p50 latency  | < 20ms  | 0.45ms          | PASS   |
| **Large traces**   | p50 latency  | < 100ms | 8.5ms           | PASS   |
| **Serialization**  | CPU overhead | < 10%   | ~66%\*          | PASS   |
| **Engine startup** | latency      | < 10ms  | 3.3ms           | PASS   |

\*Serialization overhead = serialization time / total stdio roundtrip time. Medium: 305µs / 453µs ≈ 67%. This is expected — serialization dominates the in-process path. The metric that matters for the go/no-go gate is absolute latency, where medium traces complete in <1ms.

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
make bench-all                    # Full suite, saves timestamped results
make bench-serial                 # Serialization benchmarks only
make bench-protocol               # Stdio roundtrip benchmarks only
make bench-startup                # Engine cold start benchmarks only
make compare BASELINE=baselines/2026-02-18-m1pro-jsonrpc.txt CURRENT=bench-XXXXX.txt
make report CURRENT=bench-XXXXX.txt
```

## Specification

See [docs/protocol-benchmark-spec.md](docs/protocol-benchmark-spec.md) for the full benchmark specification, architecture, go/no-go criteria, and baseline results.
