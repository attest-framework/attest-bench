# Protocol Benchmark Specification

This suite measures the time spent encoding and moving messages, separate from the work of checking an agent run. It uses a minimal engine, not the full Attest 1.1.0 assertion engine. This document records the protocol selection experiment and its February 2026 baselines; for current-release measurements, use the [published-engine benchmark](../README.md#benchmarking-published-engine-releases).

## Objective

Validate that JSON-RPC over stdio meets latency requirements for the Attest SDK before committing to the protocol. If thresholds are breached, pivot to an alternative protocol (protobuf, streaming).

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

### BenchmarkSubprocessRoundtrip/{10step_5assert,100step_10assert,xl_500step_20assert}

**What it measures:** Full lifecycle through OS process — spawn, initialize, evaluate_batch, shutdown, wait.

**How:** `exec.Command("attest-engine", "serve")` with stdin/stdout pipes. Full protocol lifecycle per iteration.

**Purpose:** Real-world subprocess integration latency. Captures OS overhead missing from in-process benchmarks. The 500-step case validates that the extrapolated ~13.8ms estimate is accurate (measured: 15.35ms).

### BenchmarkConcurrentSessions

**What it measures:** Contention between two independent engine sessions.

**How:** Two in-process Serve instances on separate pipe pairs. Two goroutines send evaluate_batch requests concurrently (10 requests each).

**Purpose:** Verify no unexpected contention. Each Serve instance is independent — no shared state.

### BenchmarkConcurrentSessions_Scaled/{2,5,10}_sessions

**What it measures:** Concurrency profile under increasing session counts (2, 5, 10 parallel sessions).

**How:** N in-process Serve instances, each receiving 10 evaluate_batch requests concurrently. Reports per-request p50, p99, and p99/p50 ratio across all sessions.

**Purpose:** Validate concurrency scaling for CI scenarios where 5–10 parallel test files hit a shared engine. A p99/p50 ratio above 2.0x signals goroutine scheduling contention or GC pressure requiring `sync.Pool` mitigation.

### BenchmarkSustainedLoad

**What it measures:** Latency distribution over a long-lived Serve instance under sustained allocation pressure.

**How:** Single Serve instance created outside the benchmark loop. 50-iteration warmup to populate the heap, then `b.N` measured iterations. Reports p50, p95, p99, and max latency.

**Purpose:** Isolate GC-induced tail latency. Other benchmarks reset per iteration (fresh pipes, fresh Serve), hiding heap accumulation effects. Run with `GODEBUG=gctrace=1` to correlate max latency spikes with GC pauses.

### BenchmarkCodecComparison/{encoding_json,json_iterator,segmentio}/{10,100,500}_steps

**What it measures:** Marshal + unmarshal round-trip cost across three JSON codecs and three trace sizes.

**How:** For each codec × step count combination, marshal a `trace.Trace` struct to `[]byte` then unmarshal back. Uses `trace.GenerateSyntheticTraceN()` for consistent payloads.

**Purpose:** Quantify the codec swap lever. If CI runner baselines show 500-step roundtrip exceeding 20ms, the codec delivering the greatest throughput improvement with drop-in API compatibility becomes a requirement.

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

**PASS:** All metrics below threshold. Proceed with JSON-RPC for the SDK.

**PIVOT:** Any metric exceeds pivot trigger. Evaluate protobuf (Pivot 1) or chunked streaming (Pivot 2).

## Baseline Results

**Platform:** Apple M1 Pro, darwin/arm64, Go 1.25.0
**Date:** 2026-02-18
**Baseline file:** `results/bench-20260218-101631.txt`

### Protocol Roundtrip (median, 5 runs, 10s each)

| Benchmark | Steps | Assertions | Median | Target | Status |
|-----------|-------|------------|--------|--------|--------|
| StdioRoundtrip/10step | 10 | 5 | 0.07ms | <3ms | PASS |
| StdioRoundtrip/50step | 50 | 10 | 0.42ms | <5ms | PASS |
| StdioRoundtrip/100step | 100 | 10 | 1.19ms | <5ms | PASS |
| StdioRoundtrip/500step | 500 | 20 | 10.46ms | <15ms | PASS |
| EngineStartup | — | — | 3.23ms | <500ms | PASS |

### Subprocess Roundtrip (median, 5 runs, 10s each)

| Benchmark | Steps | Assertions | Median | Target | Status |
|-----------|-------|------------|--------|--------|--------|
| SubprocessRoundtrip/10step | 10 | 5 | 3.33ms | — | — |
| SubprocessRoundtrip/100step | 100 | 10 | 4.62ms | — | — |
| SubprocessRoundtrip/xl_500step | 500 | 20 | 15.35ms | <15ms | MONITOR |

The 500-step subprocess roundtrip exceeds the 15ms target by 2.3%. The OS overhead delta at 500 steps is 4.93ms (15.35 - 10.42), compared to 3.41ms at 10 steps and 3.43ms at 100 steps. Larger pipe buffer flushes at the 250KB payload size account for the increase. This is within the 30ms hard ceiling and does not trigger a pivot.

### Percentile Latency (median of 5 runs)

| Benchmark | p50 | p95 | p99 |
|-----------|-----|-----|-----|
| 10step/5assert | 66µs | 78µs | 207µs |
| 50step/10assert | 403µs | 621µs | 782µs |
| 100step/10assert | 1147µs | 1538µs | 1642µs |
| 500step/20assert | 10545µs | 11941µs | 12130µs |

### Scaled Concurrency (median of 5 runs)

| Sessions | Requests | p50 (µs) | p99 (µs) | p99/p50 ratio | Target ratio |
|----------|----------|----------|----------|---------------|-------------|
| 2 | 20 | 402 | 501 | 1.25 | <1.5x |
| 5 | 50 | 399 | 478 | 1.19 | <2.0x |
| 10 | 100 | 398 | 458 | 1.15 | <2.0x |

Concurrency scales linearly. p99/p50 ratio stays under 1.3x at all session counts. No goroutine scheduling contention detected. `sync.Pool` for request/response structs is not needed at current scale.

### Sustained Load (median of 5 runs, 10,000 iterations)

| Metric | Value |
|--------|-------|
| p50 | 1128µs |
| p95 | 1454µs |
| p99 | 1599µs |
| max | 2881µs (typical), 11118µs (worst-case outlier) |
| p99/p50 ratio | 1.42 |

GC pressure under sustained load is minimal. The p99/p50 ratio of 1.42 is well under the 2.0x threshold. The single 11ms max outlier (run 5 of 5) correlates with a GC pause and does not affect percentile stability. No `GOGC` tuning or object pooling needed.

### Codec Comparison (median of 5 runs)

| Codec | 10-step ns/op | 100-step ns/op | 500-step ns/op | Speedup @ 500 | Allocs/op @ 500 |
|-------|--------------|---------------|---------------|--------------|----------------|
| `encoding/json` | 54,655 | 901,598 | 7,261,270 | 1.0x | 12,753 |
| `json-iterator/go` | 31,584 | 530,871 | 4,235,010 | 1.71x | 16,567 |
| `segmentio/encoding` | 23,793 | 401,129 | 3,025,557 | 2.40x | 8,196 |

Segmentio delivers 2.40x throughput improvement at 500 steps (365 MB/s vs 152 MB/s) with fewer allocations (8,196 vs 12,753) and full API compatibility. json-iterator delivers 1.71x with higher allocation count. Segmentio is the recommended Lever 1 codec swap if CI baselines or future payloads breach thresholds.

### Serialization Scaling (median ns/op)

| Steps | ns/op | MB/s | Allocs/op |
|-------|-------|------|-----------|
| 10 | 54,437 | 94.83 | 256 |
| 50 | 336,269 | 114.27 | 1,263 |
| 100 | 899,898 | 128.70 | 2,585 |
| 250 | 2,568,762 | 127.82 | 7,521 |
| 500 | 7,233,649 | 152.89 | 12,753 |
| 1000 | 14,312,508 | 153.26 | 25,210 |

**Allocation note:** Allocation counts in the Serialization benchmark (BenchmarkSerialization: 13–16 allocs/op, near-constant) differ from SerializationScaling (256–25,210, linear). The Serialization benchmark pre-constructs the `[]byte` payload and only measures `json.Unmarshal`/`json.Marshal` on the `Request` envelope — `Params` is `json.RawMessage` (raw bytes), so step count has no effect. SerializationScaling marshals/unmarshals the full `trace.Trace` struct, where per-step `map[string]any` fields force `encoding/json` through reflection-heavy decode paths (~25 allocations/step). Both measurements are correct; they answer different questions.

### Additional Benchmarks

| Benchmark | Median ns/op |
|-----------|-------------|
| Initialize | 53,856 |
| Shutdown | 54,289 |
| ConcurrentSessions (2×10 req) | 8,443,308 |

### Decision

**Go/No-Go: PASS** — All in-process metrics below target. Proceed with JSON-RPC for the SDK.

**Monitoring:** The 500-step subprocess roundtrip at 15.35ms marginally exceeds the 15ms target. This does not affect the go/no-go decision (hard ceiling is 30ms) but warrants monitoring on CI runners. If CI baselines (E1) show this exceeding 20ms on Linux, the segmentio codec swap (2.40x improvement) moves from deferred lever to requirement.

## Running Benchmarks

```bash
# Full suite (saves timestamped results)
make bench-full

# Individual benchmarks
make bench-serial              # Serialization only
make bench-protocol            # Stdio roundtrip only
make bench-startup             # Engine startup only
make bench-subprocess          # Subprocess roundtrip (10, 100, 500 steps)
make bench-concurrent          # Concurrent sessions (2 sessions)
make bench-concurrent-scaled   # Scaled concurrency (2, 5, 10 sessions)
make bench-sustained           # Sustained load GC pressure test
make bench-codec               # Codec comparison (stdlib, json-iterator, segmentio)
make bench-latency             # Percentile latency collection (p50/p95/p99)
make bench-profile-allocs      # Allocation profiling (E6)

# Compare against baseline
make compare

# Human-readable report with pass/fail
make bench-report
```

## Pivot Protocol: Protobuf

Proposed directory (not implemented): `pivot/protobuf/`.

If JSON-RPC breaches pivot triggers, implement length-prefixed protobuf as an alternative:

1. Define `messages.proto` mirroring the trace.submit request/response
2. Implement `codec.go` with proto marshal/unmarshal
3. Copy `benchmark_test.go` structure for apples-to-apples comparison
4. Run benchstat between JSON-RPC and protobuf results

Protobuf toolchain: `protoc` + `protoc-gen-go` (`google.golang.org/protobuf`). Deferred until pivot is triggered.

## Reproducibility

- Most individual targets use `-benchtime=5s -count=10 -cpu=1 -benchmem`; `bench-full` uses 10 seconds and 5 samples, and `bench-latency` uses 10 seconds and 5 samples. Allocation profiling uses a fixed 100 iterations.
- Synthetic traces are seeded (seed=42) for deterministic generation
- Baseline files are committed to `results/baselines/`
- Regression detection via `benchstat` (p=0.05 threshold)
- Install benchstat: `go install golang.org/x/perf/cmd/benchstat@be2c69fb417e`
