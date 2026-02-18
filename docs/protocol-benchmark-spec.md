# Protocol Benchmark Specification

Phase 0 performance validation for the Attest protocol engine. This document defines what is measured, how it is measured, and what constitutes a pass/fail result.

## Objective

Validate that JSON-RPC over stdio meets latency requirements for the Attest SDK before committing to the protocol in Phase 1. If thresholds are breached, pivot to an alternative protocol (protobuf, streaming).

## Architecture

The benchmark harness contains a **minimal engine** — a message loop that accepts JSON-RPC requests over stdin, routes them to canned handlers, and writes responses to stdout. No actual trace processing occurs. This isolates protocol overhead from application logic.

```text
                    ┌─────────────────────────────┐
  stdin ──────────► │  bufio.Reader (1MB)         │
                    │  ReadBytes('\n')            │
                    │  json.Unmarshal             │
                    │  ┌───────────────────────┐  │
                    │  │ Route:                │  │
                    │  │  initialize → result  │  │
                    │  │  evaluate_batch → ok  │  │
                    │  │  shutdown → exit      │  │
                    │  │  trace.submit → ok    │  │
                    │  │  ping → pong          │  │
                    │  └───────────────────────┘  │
                    │  json.Marshal               │
                    │  bufio.Writer.Flush()       │
  stdout ◄──────── │                              │
                    └─────────────────────────────┘
```

### Message Framing

Newline-delimited JSON. Each line is one complete JSON-RPC 2.0 message. `encoding/json` escapes embedded newlines in string values automatically.

**Not** Content-Length framing (LSP style). That remains available as a pivot option if newline-delimited hits edge cases.

### Reader Implementation

`bufio.NewReaderSize(r, 1<<20)` with `ReadBytes('\n')`. **Not** `bufio.Scanner` — Scanner has a 64KB default token limit that silently truncates large messages.

## Synthetic Trace Sizes

Traces are generated deterministically using `math/rand` with a fixed seed (42).

| Size   | Steps | Tool Calls | Approx. Bytes | Represents                |
|--------|-------|------------|---------------|---------------------------|
| Small  | 10    | 1-2        | ~5 KB         | Simple query, single tool |
| Medium | 50    | 1-2        | ~25 KB        | Multi-step workflow       |
| Large  | 100   | 1-2        | ~60 KB        | Complex agent session     |
| XL     | 500   | 1-2        | ~250 KB       | Extended multi-agent run  |

## Benchmarks

### BenchmarkSerialization/{10step_5assert,50step_10assert,100step_10assert,500step_20assert}

**What it measures:** Pure JSON marshal/unmarshal cycle for a trace.submit request.

**How:** `UnmarshalRequest(data) → MarshalResponse(response)` in a tight loop. No IO, no pipes, no goroutines.

**Purpose:** Establish codec overhead baseline. If serialization alone exceeds thresholds, the protocol choice is the bottleneck regardless of transport.

### BenchmarkStdioRoundtrip/{10step_5assert,50step_10assert,100step_10assert,500step_20assert}

**What it measures:** Full protocol roundtrip through `io.Pipe` — write request, read response through the `Serve()` loop.

**How:** `io.Pipe` pair, `Serve()` in a goroutine, sequential write/read cycle per iteration.

**Purpose:** End-to-end in-process latency. This is the primary go/no-go metric.

### BenchmarkEngineStartup

**What it measures:** Cold start of the engine subprocess + first roundtrip.

**How:** `exec.Command("attest-engine", "serve")`, read `{"ready":true}` signal, send ping, read pong, kill process. Per iteration.

**Purpose:** Validate subprocess startup overhead for SDK integration patterns where the engine is spawned per-session.

### BenchmarkInitialize

**What it measures:** Cold protocol initialization — start Serve, send initialize, read response.

**How:** Per-iteration Serve start with io.Pipe, single initialize roundtrip, then shutdown.

**Purpose:** Baseline for connection establishment overhead.

### BenchmarkShutdown

**What it measures:** Graceful shutdown latency — initialize then shutdown.

**How:** Per-iteration Serve lifecycle: ready → initialize → shutdown → Serve returns.

**Purpose:** Verify clean session teardown does not add measurable overhead.

### BenchmarkSubprocessRoundtrip/{10step_5assert,100step_10assert}

**What it measures:** Full lifecycle through OS process — spawn, initialize, evaluate_batch, shutdown, wait.

**How:** `exec.Command("attest-engine", "serve")` with stdin/stdout pipes. Full protocol lifecycle per iteration.

**Purpose:** Real-world subprocess integration latency. Captures OS overhead missing from in-process benchmarks.

### BenchmarkConcurrentSessions

**What it measures:** Contention between two independent engine sessions.

**How:** Two in-process Serve instances on separate pipe pairs. Two goroutines send evaluate_batch requests concurrently (10 requests each).

**Purpose:** Verify no unexpected contention. Each Serve instance is independent — no shared state.

### BenchmarkSerializationScaling/{10,50,100,250,500,1000}_steps

**What it measures:** JSON marshal/unmarshal cost as trace size increases.

**How:** Generate trace with exact step count, marshal+unmarshal loop. Reports `json_kb` payload size.

**Purpose:** Characterize serialization scaling for capacity planning.

### BenchmarkLatency_StdioRoundtrip/{10step_5assert,50step_10assert,100step_10assert,500step_20assert}

**What it measures:** Percentile latency distribution for protocol roundtrips.

**How:** Same setup as BenchmarkStdioRoundtrip but records per-iteration `time.Duration`. Reports p50/p95/p99 via `b.ReportMetric`.

**Purpose:** Tail latency characterization. Mean ns/op hides outliers — percentiles reveal worst-case behavior.

## Go/No-Go Criteria

| Metric | Target | Hard Ceiling | Pivot Trigger |
|--------|--------|-------------|---------------|
| Small (10-step) evaluate_batch p50 | < 3ms | 5ms | > 5ms |
| Medium (50-step) evaluate_batch p50 | < 5ms | 10ms | > 10ms |
| Large (100-step) evaluate_batch p50 | < 5ms | 10ms | > 10ms |
| XL (500-step) evaluate_batch p50 | < 15ms | 30ms | > 30ms |
| Engine cold start to initialize response | < 500ms | 1000ms | > 1000ms |

**PASS:** All metrics below threshold. Proceed with JSON-RPC for Phase 1 SDK.

**PIVOT:** Any metric exceeds pivot trigger. Evaluate protobuf (Pivot 1) or chunked streaming (Pivot 2).

## Baseline Results

**Platform:** Apple M1 Pro, darwin/arm64, Go 1.25.0
**Date:** 2026-02-18
**Baseline file:** `results/baselines/2026-02-18-m1pro-jsonrpc-recal.txt`

### Protocol Roundtrip (median, 5 runs, 10s each)

| Benchmark | Steps | Assertions | Median | Target | Status |
|-----------|-------|------------|--------|--------|--------|
| StdioRoundtrip/10step | 10 | 5 | 0.07ms | <3ms | PASS |
| StdioRoundtrip/50step | 50 | 10 | 0.41ms | <5ms | PASS |
| StdioRoundtrip/100step | 100 | 10 | 1.19ms | <5ms | PASS |
| StdioRoundtrip/500step | 500 | 20 | 10.58ms | <15ms | PASS |
| EngineStartup | — | — | 3.19ms | <500ms | PASS |

### Percentile Latency (median of 5 runs)

| Benchmark | p50 | p95 | p99 |
|-----------|-----|-----|-----|
| 10step/5assert | 65us | 75us | 165us |
| 50step/10assert | 397us | 561us | 679us |
| 100step/10assert | 1134us | 1450us | 1570us |
| 500step/20assert | 10564us | 10851us | 11202us |

### Serialization Scaling (median ns/op)

| Steps | ns/op | MB/s |
|-------|-------|------|
| 10 | 54,160 | 95.31 |
| 50 | 336,040 | 114.35 |
| 100 | 896,470 | 129.19 |
| 250 | 2,562,124 | 128.15 |
| 500 | 7,213,754 | 153.31 |
| 1000 | 14,473,271 | 151.56 |

### Additional Benchmarks

| Benchmark | Median ns/op |
|-----------|-------------|
| Initialize | 41,478 |
| Shutdown | 41,573 |
| SubprocessRoundtrip/10step | 3,334,820 |
| SubprocessRoundtrip/100step | 4,603,868 |
| ConcurrentSessions (2x10 req) | 8,452,916 |

### Decision

**Go/No-Go: PASS** — All metrics below target. Proceed with JSON-RPC for Phase 1 SDK.

## Running Benchmarks

```bash
# Full suite (saves timestamped results)
make bench-all

# Individual benchmarks
make bench-serial      # Serialization only
make bench-protocol    # Stdio roundtrip only
make bench-startup     # Engine startup only

# Compare against baseline
make compare BASELINE=baselines/2026-02-18-m1pro-jsonrpc.txt CURRENT=bench-20260218-044308.txt

# Human-readable report with pass/fail
make report CURRENT=bench-20260218-044308.txt
```

## Pivot Protocol: Protobuf

Directory: `pivot/protobuf/`

If JSON-RPC breaches pivot triggers, implement length-prefixed protobuf as an alternative:

1. Define `messages.proto` mirroring the trace.submit request/response
2. Implement `codec.go` with proto marshal/unmarshal
3. Copy `benchmark_test.go` structure for apples-to-apples comparison
4. Run benchstat between JSON-RPC and protobuf results

Protobuf toolchain: `protoc` + `protoc-gen-go` (`google.golang.org/protobuf`). Deferred until pivot is triggered.

## Reproducibility

- All benchmarks use `-count=10 -cpu=1 -benchmem` for statistical stability
- Synthetic traces are seeded (seed=42) for deterministic generation
- Baseline files are committed to `results/baselines/`
- Regression detection via `benchstat` (p=0.05 threshold)
- Install benchstat: `go install golang.org/x/perf/cmd/benchstat@latest`
