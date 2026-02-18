# Protocol Benchmark Specification

Phase 0 performance validation for the Attest protocol engine. This document defines what is measured, how it is measured, and what constitutes a pass/fail result.

## Objective

Validate that JSON-RPC over stdio meets latency requirements for the Attest SDK before committing to the protocol in Phase 1. If thresholds are breached, pivot to an alternative protocol (protobuf, streaming).

## Architecture

The benchmark harness contains a **minimal engine** — a message loop that accepts JSON-RPC requests over stdin, routes them to canned handlers, and writes responses to stdout. No actual trace processing occurs. This isolates protocol overhead from application logic.

```text
                    ┌─────────────────────────┐
  stdin ──────────► │  bufio.Reader (1MB)     │
                    │  ReadBytes('\n')        │
                    │  json.Unmarshal         │
                    │  ┌───────────────────┐  │
                    │  │ Route:            │  │
                    │  │  trace.submit → ok│  │
                    │  │  ping → pong      │  │
                    │  └───────────────────┘  │
                    │  json.Marshal           │
                    │  bufio.Writer.Flush()   │
  stdout ◄──────── │                          │
                    └─────────────────────────┘
```

### Message Framing

Newline-delimited JSON. Each line is one complete JSON-RPC 2.0 message. `encoding/json` escapes embedded newlines in string values automatically.

**Not** Content-Length framing (LSP style). That remains available as a pivot option if newline-delimited hits edge cases.

### Reader Implementation

`bufio.NewReaderSize(r, 1<<20)` with `ReadBytes('\n')`. **Not** `bufio.Scanner` — Scanner has a 64KB default token limit that silently truncates large messages.

## Synthetic Trace Sizes

Traces are generated deterministically using `math/rand` with a fixed seed (42).

| Size   | Steps   | Tool Calls | Approx. Bytes | Represents                |
| ------ | ------- | ---------- | ------------- | ------------------------- |
| Small  | 3-5     | 1-2        | ~1 KB         | Simple query, single tool |
| Medium | 20-50   | 10-20      | ~50 KB        | Multi-step workflow       |
| Large  | 100-200 | 50-100     | ~500 KB       | Complex agent session     |

Sizes are estimates based on the Attest trace model (Step/ToolCall hierarchy). Calibrate against real traces once available.

## Benchmarks

### BenchmarkSerialization/{small,medium,large}

**What it measures:** Pure JSON marshal/unmarshal cycle for a trace.submit request.

**How:** `UnmarshalRequest(data) → MarshalResponse(response)` in a tight loop. No IO, no pipes, no goroutines.

**Purpose:** Establish codec overhead baseline. If serialization alone exceeds thresholds, the protocol choice is the bottleneck regardless of transport.

### BenchmarkStdioRoundtrip/{small,medium,large}

**What it measures:** Full protocol roundtrip through `io.Pipe` — write request, read response through the `Serve()` loop.

**How:** `io.Pipe` pair, `Serve()` in a goroutine, sequential write/read cycle per iteration.

**Purpose:** End-to-end in-process latency. This is the primary go/no-go metric.

### BenchmarkEngineStartup

**What it measures:** Cold start of the engine subprocess + first roundtrip.

**How:** `exec.Command("attest-engine", "serve")`, read `{"ready":true}` signal, send ping, read pong, kill process. Per iteration.

**Purpose:** Validate subprocess startup overhead for SDK integration patterns where the engine is spawned per-session.

## Go/No-Go Criteria

| Metric              | Threshold | Pivot Trigger |
| ------------------- | --------- | ------------- |
| Medium trace p50    | < 20ms    | > 30ms        |
| Large trace p50     | < 100ms   | > 150ms       |
| Serialization ratio | < 10%\*   | > 25%         |
| Engine startup      | < 10ms    | > 15ms        |

\*Serialization ratio = serialization time / stdio roundtrip time. Measures how much of the total latency is codec overhead vs transport overhead.

**PASS:** All metrics below threshold. Proceed with JSON-RPC for Phase 1 SDK.

**PIVOT:** Any metric exceeds pivot trigger. Evaluate protobuf (Pivot 1) or chunked streaming (Pivot 2).

## Baseline Results

### 2026-02-18 — M1 Pro (initial baseline)

```text
BenchmarkSerialization/small      ~21 µs/op    87 MB/s    4.2 KB/op   13 allocs
BenchmarkSerialization/medium    ~305 µs/op   108 MB/s   64.6 KB/op   14 allocs
BenchmarkSerialization/large    ~5.59 ms/op   116 MB/s    1.2 MB/op   16 allocs
BenchmarkStdioRoundtrip/small    ~32 µs/op    57 MB/s    9.4 KB/op   37 allocs
BenchmarkStdioRoundtrip/medium  ~453 µs/op    72 MB/s  130.0 KB/op   38 allocs
BenchmarkStdioRoundtrip/large   ~8.5 ms/op    76 MB/s    2.5 MB/op   41 allocs
BenchmarkEngineStartup          ~3.3 ms/op              16.2 KB/op   42 allocs
```

**Verdict: PASS.** All metrics well below thresholds. Medium roundtrip 0.45ms vs 20ms target (44x headroom). Large roundtrip 8.5ms vs 100ms target (12x headroom). Startup 3.3ms vs 10ms target (3x headroom).

Full raw data: `results/baselines/2026-02-18-m1pro-jsonrpc.txt`

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
