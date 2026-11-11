# attest-bench

Benchmarks for [attest](https://github.com/attest-framework/attest): how much time its message transport takes, how evaluation styles compare in cost and consistency, and which faults checks catch in recorded agent runs. These are separate experiments, not a general ranking of agent-testing tools.

## Purpose

The current Attest release is [1.1.0 "Hardened"](https://github.com/attest-framework/attest/releases/tag/v1.1.0). Published measurements below are historical: the protocol baselines date from February 2026, and the corpus results use a pre-1.1.0 source build. They are not measurements of the final 1.1.0 release.

| Suite | What it measures | Run from the repository root | Paid API key? |
|---|---|---|---|
| Protocol and codec | Serialization, message round-trips, startup and concurrency in the local minimal Go engine, not full assertion evaluation | `make bench-all` or individual `make bench-*` targets below | No |
| Published engine | Startup and assertion round-trips in downloaded release binaries | `scripts/published-bench.sh --tag v1.1.0 --platform darwin-arm64 --out /tmp/published-bench` | No |
| Approach comparison | Cost, time and consistency of three assertion styles on support scenarios | `make setup-approaches`, then `make bench-approaches-dry` or `make bench-approaches` | Optional; full runs need a configured judge key |
| Fault corpus | Faults and clean runs flagged by contracts versus output assertions | `make corpus-setup corpus-engine`, then `make corpus-bench` | No; optional `make corpus-judge` calls a paid judge |

For the main Attest framework, see [github.com/attest-framework/attest](https://github.com/attest-framework/attest).

## Quick Start

```bash
make bench-all
```

Requires Go (see [`go.mod`](go.mod)) and Make. This runs the local minimal-engine benchmarks with synthetic traces and saves output to `results/bench-<timestamp>.txt`; it does not run the Python or paid suites.

## Fault-corpus benchmark

`corpus-bench/` measures, on a small labeled corpus of synthetic [Refund Desk](https://github.com/attest-framework/refund-desk) runs, how many faulty runs each approach flags (true-positive rate) and how many clean runs it flags (false-positive rate). `make corpus-bench` reproduces the table below offline, at $0, for approaches (a) and (b).

**Approaches**

- **(a) attest contracts and effects.** The contracts committed with the Refund Desk fixtures (tool order and per-order call cardinality, plus the effect contract "refunds sum to at most the order amount"; only the INC-1077 contract set also has "the notification goes to the order's customer"), evaluated by `attest-engine` on each run's recorded trace and world snapshot. No agent is re-run and no model is called.
- **(b) pytest with a cassette and output assertions.** Each run's recorded final model response sits in a VCR-style cassette that a pytest test replays by request key. The test asserts that the reply states the refunded amount, does not say "could not" and does not state double the amount. It sees the reply and nothing else. It is a hand-written harness, not the `vcrpy` library.
- **(c) judge-only.** Not run. It needs a model key and runs only through the opt-in `corpus-bench-judge` workflow (`workflow_dispatch`, spend-capped). No (c) number is published.

**Corpus** (65 runs, each with an id, a label, a source and a generator command in [`corpus-bench/corpus/manifest.json`](corpus-bench/corpus/manifest.json))

| Group | Runs | Label | Source |
|---|---|---|---|
| Real incident runs | 2 | fault | Refund Desk recordings: INC-1042 before the fix (double refund), INC-1077 (refunds total above the order amount, wrong recipient) |
| Output-only faults | 15 | fault | A clean run with only the reply changed: wrong amount, doubled amount, claims failure, empty, invented credit |
| Behavior mutants | 30 | fault | `attest-engine mutate --seed=0 --max-mutants=15` on two clean runs |
| Clean runs | 3 | clean | INC-1042 fixed (recording); INC-1077 with the fix applied and the O-2001 run, both derived by editing a recording |
| Clean variants | 15 | clean | Five harmless changes to each clean run |

**Results** (historical pre-1.1.0 source build from attest commit [`2e59fd612e6804c97f88f04b3f6397ded4a6d0f3`](https://github.com/attest-framework/attest/commit/2e59fd612e6804c97f88f04b3f6397ded4a6d0f3), labeled `1.1.0-rc.3` in [`engine.lock.json`](corpus-bench/engine.lock.json) and the generated [results](corpus-bench/published/results.md)). That label is not the released `v1.1.0-rc.3` binary, and these numbers have not been rerun against final 1.1.0.

| Approach | Faulty runs flagged | Clean runs flagged | Cost (USD) | Model calls |
|---|---|---|---|---|
| (a) attest contracts + effects | 19/47 (40.4%) | 3/18 (16.7%) | $0.00 | 0 |
| (b) pytest + cassette, output assertions | 12/47 (25.5%) | 3/18 (16.7%) | $0.00 | 0 |
| (a) or (b) flags | 31/47 (66.0%) | 6/18 (33.3%) | $0.00 | 0 |
| (c) judge-only | not run | not run | not run | not run |

| Fault group | Runs | (a) | (b) |
|---|---|---|---|
| Real incident runs | 2 | 2/2 | 0/2 |
| Output-only faults | 15 | 0/15 | 12/15 |
| Behavior mutants | 30 | 17/30 | 0/30 |
| of which: agent-behavior mutants | 23 | 11/23 | 0/23 |
| of which: edits to seeded `orders` rows | 7 | 6/7 | 0/7 |

Wall time is in `corpus-bench/published/timings.json` (median of three runs on the author's machine, under a second for each approach); it varies by machine and run. Everything else is byte-for-byte reproducible: the same engine commit, the same seed, the same table.

**Limits. Read these before quoting a number.**

- The aggregate rates are not detection rates for agents in general. They depend on how many runs of each kind the corpus holds, and the corpus holds 47 faulty and 18 clean runs chosen by the benchmark's authors. The per-group rows are the informative ones.
- The corpus is synthetic and small. Every run comes from one scripted-model agent, Refund Desk. Its Python and TypeScript recordings differ only in the command that produced them, so one copy is used.
- The contracts in (a) were drafted after INC-1042 and INC-1077 were known. Catching both incidents shows the contracts encode them, not that attest would have caught an incident nobody had seen.
- (a) flags none of the 15 output-only faults, by design: its contracts check tool calls and the world, not the reply. (b) flags none of the 2 real incidents: the reply was the same whether the customer was refunded once or twice. The reply-versus-behavior split is the result; attest also has reply assertions, which (a) does not use here.
- (a) misses 13 of the 30 mutants: 4 of 6 `alter_world_effect`, 1 of 7 `alter_world_effect_seeded_orders`, all 4 `perturb_argument`, all 3 `inject_tool_error` and 1 of 3 `drop_tool_call`. The effect contracts are measured: each is given the fixture's world, and the refund-sum contract alone kills the duplicated and altered refund rows (INC-1077 `refunds.0.duplicate`, INC-1042 `refunds.0.change.amount_cents`); the notification-recipient contract reads only `notifications` and `orders`. They have no check for dropped or duplicated notifications, dropped refunds, a changed tool argument or a tool error. `attest-engine mutate` suggests contracts that would kill the survivors; none are applied here.
- The 7 `alter_world_effect_seeded_orders` mutants edit `orders` rows that the agent never writes, so they change input data and not agent behavior. Five of the six kills are duplicated `orders` rows: the engine reports "orders has more than one record with order_id …, so order_id is not a unique key", because the relational contracts join on `order_id`. Those kills are ambiguous-join failures, not detected agent behavior. They are counted in the 30 and reported as their own subcategory; the 23 agent-behavior mutants are the cleaner measure of (a) on behavior (11/23).
- Mutants are labeled faulty by operator, not by a judgment of harm, so some may be harmless (changing a refund's free-text reason, for example). An unchanged cassette stands in for each mutant's reply, so (b)'s 0/30 follows from the construction. It does not measure how strong output assertions are.
- The false-positive rate is a property of the 5 variants written here, not of real traffic. One variant, a read-only retry of the order lookup, breaks (a)'s drafted "lookup_order at most once per order" contract. Another, a reply that states the amount without the words "refund of", breaks (b)'s phrase match. Each approach flags 3 of 18 clean runs because there are 3 of each variant.
- Both approaches are scoped to what they were given. Neither is a competitor tool, and no other tool was run.
- The released `v1.1.0-rc.3` engine binary rejects the relational contracts in these fixtures, so reproduction still builds the pinned source commit in [`corpus-bench/engine.lock.json`](corpus-bench/engine.lock.json). Relational contracts shipped in 1.1.0; changing this historical pin requires a separate benchmark run, not relabeling the existing results.

**Run it**

```bash
make corpus-setup corpus-engine   # once: uv sync, then build the pinned engine (needs git, Go, network)
make corpus-bench                 # offline: writes corpus-bench/published/{results.md,results.json,timings.json}
make corpus-check                 # ruff, mypy, pytest for the harness
make corpus-manifest              # rewrite corpus/manifest.json after an intended corpus change
```

`make corpus-bench` rebuilds the corpus and fails if it differs from `corpus/manifest.json`. `make corpus-judge-dry` checks that approach (c)'s requests are valid without calling a model.

## Go/No-Go Criteria

Measured on an M1 Pro on 2026-02-18; the committed baselines are in `results/baselines/`.

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
gh workflow run benchmark-regression.yml -f tag=v1.1.0
gh workflow run benchmark-regression.yml -f tag=v1.1.0 -f base_tag=v1.0.1
```

`tag` and `base_tag` must match `vX.Y.Z` or `vX.Y.Z-rc.N`. `base_tag` defaults to the previous published `v*` release by semver order (rc tags count). Without `tag`, the workflow keeps its source-built mode against `results/baselines/ci-linux-amd64.txt`.

For each tag the job downloads `attest-engine-linux-amd64` and `checksums-sha256.txt` with the read-only workflow token in a fetch step, verifies the sha256, and fails closed on a missing asset, a missing or duplicate entry or a mismatch. A second step, whose environment has no token, re-verifies each binary against the hashes passed from the fetch step before every run. These checks detect corruption and mismatched uploads, not a compromised release: the checksum and binary come from the same release. Attest 1.1.0 release binaries also carry GitHub build-provenance attestations, but this benchmark workflow does not verify them. To verify a downloaded 1.1.0 Linux binary separately:

```bash
gh attestation verify attest-engine-linux-amd64 \
  --repo attest-framework/attest \
  --signer-workflow attest-framework/attest/.github/workflows/release.yml \
  --source-ref refs/tags/v1.1.0
```

This verifies the build's workflow and tag identity, not that the code is safe. See the [configuration guide](https://github.com/attest-framework/attest/blob/v1.1.0/docs/guides/configuration.md). The benchmark engine runs with an allowlisted environment in an empty working directory, which guards against accidental leaks and is not a sandbox (the runner user has sudo). The job does not use the Go cache because it executes release binaries.

It then runs `BenchmarkPublishedEngine*` (process start plus `initialize`, and `evaluate_batch` round-trips; every assertion in the first response must pass) against each binary, alternating base and tag samples (10 samples of 200 iterations, at least 6 so benchstat can compute intervals), and compares them with benchstat. The delta is written to the job summary and uploaded as the `published-engine-benchmarks` artifact.

Gate: the job fails only when a `sec/op` row shows a significant regression above 15% of `tag` against `base_tag`. `B/op` and `allocs/op` measure the Go client rather than the engine and are reported, not gated. Improvements and non-significant deltas pass. The comparison is always reported first, so a failing run still carries the full delta.

To run it locally (needs `gh`, `benchstat` and Go; `scripts/test-published-bench.sh` holds the fixture tests for the gate and tag ordering and runs in the `Benchmark` workflow):

```bash
scripts/published-bench.sh --tag v1.1.0 --platform darwin-arm64 --out /tmp/published-bench
```

## Project Structure

- `engine/` — Minimal engine implementation for benchmarking
  - `cmd/attest-engine/` — CLI entry point (`serve` subcommand)
  - `internal/protocol/` — JSON-RPC codec, stdio message loop, benchmarks
  - `internal/trace/` — Trace types and synthetic data generation
- `approach-comparison/` — Cost, time and consistency of three assertion styles on 50 support scenarios (Python, needs a model key)
- `corpus-bench/` — Fault-corpus benchmark: labeled runs, approaches (a)/(b)/(c), published table
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

A Python benchmark comparing 3 assertion styles across 50 customer support scenarios on cost, wall time and run-to-run consistency:

- **All LLM Judge** — broad judge calls for every evaluation dimension
- **Graduated** — deterministic layers (schema, constraints, trace, content) + judge for subjective criteria only
- **Pure Deterministic** — deterministic assertions only, zero judge calls, zero API cost

The scenarios contain no labeled faults, so this benchmark reports no detection rates; the share of assertions that passed says nothing about whether faults would be caught. Detection is measured in the [fault-corpus benchmark](#fault-corpus-benchmark). A full run calls a paid model, so no results from it are published here.

```bash
make setup-approaches                        # install dependencies (uv sync)
make bench-approaches-dry                    # dry-run: no engine, no API calls
make bench-approaches                        # full run (fresh engine per trial)
make bench-approaches-single SCENARIO=SC-001 # run a single scenario ID
```

Each trial starts a fresh engine with an isolated cache directory for experimental reproducibility. For development, run `uv run python run_benchmark.py --use-cache` from `approach-comparison/` to share the engine and cached evaluations across trials.

Requirements: Python 3.12+, `uv`, and a full Attest engine (not this repository's minimal protocol engine) for non-dry runs. `make setup-approaches` runs `uv sync`; the project's dependency floor is still `attest-ai>=1.0.1`. To select the current SDK without changing that manifest, run `uv sync --upgrade-package attest-ai` from `approach-comparison/` and check the resolved version before recording results. Full judge runs require `OPENAI_API_KEY` (or `ATTEST_JUDGE_API_KEY`); they are optional and incur provider charges. Dry runs need neither a key nor an engine and do not measure real assertion outcomes.

Results are written to `approach-comparison/results/benchmark-<timestamp>.json`.

## Specification

See [docs/protocol-benchmark-spec.md](docs/protocol-benchmark-spec.md) for the full benchmark specification, architecture, go/no-go criteria, and baseline results.
