"""CLI orchestrator: runs all 3 approaches × 50 scenarios × N trials and produces metrics."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Load .env files from benchmark dir and attest-bench root
for env_path in [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parents[1] / ".env",
]:
    if env_path.is_file():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

from assertions import APPROACH_BUILDERS
from scenarios import SCENARIOS, SCENARIOS_BY_ID, Scenario
from support_agent import build_trace

# ---------------------------------------------------------------------------
# Data structures for results
# ---------------------------------------------------------------------------


@dataclass
class ScenarioTrialResult:
    """Result of a single scenario evaluation in a single trial."""

    scenario_id: str
    approach: str
    trial: int
    assertion_count: int
    pass_count: int
    fail_count: int
    cost_usd: float
    duration_ms: int
    wall_clock_ms: float
    passed: bool
    assertion_ids: list[str] = field(default_factory=list)
    pass_fail_vector: list[str] = field(default_factory=list)


@dataclass
class ApproachSummary:
    """Aggregated results for one approach across all trials."""

    approach: str
    total_cost_usd: float
    total_wall_clock_ms: float
    total_assertions: int
    total_pass: int
    total_fail: int
    consistency_pct: float
    avg_cost_per_scenario: float
    avg_wall_clock_per_scenario_ms: float
    judge_call_count: int


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_single_evaluation(
    attest_fixture: Any,
    scenario: Scenario,
    approach_name: str,
    trial: int,
    budget: float | None = None,
) -> ScenarioTrialResult:
    """Run one scenario with one approach and collect metrics."""
    from attest.expect import ExpectChain

    # Build synthetic trace
    agent_result = build_trace(
        scenario_id=scenario.id,
        user_message=scenario.user_message,
        tool_sequence=scenario.tool_sequence,
        output_message=scenario.output_message,
        output_structured={"intent": scenario.category, "status": "resolved"},
        total_tokens=scenario.metadata.total_tokens,
        cost_usd=scenario.metadata.cost_usd,
        latency_ms=scenario.metadata.latency_ms,
        tool_args_overrides=scenario.tool_args_overrides,  # type: ignore[arg-type]
    )

    # Build assertion chain using selected approach
    builder_fn = APPROACH_BUILDERS[approach_name]
    chain: ExpectChain = builder_fn(scenario, agent_result)

    # Evaluate and measure wall-clock time
    t_start = time.perf_counter()
    eval_result = attest_fixture.evaluate(chain, budget=budget)
    t_end = time.perf_counter()
    wall_clock_ms = (t_end - t_start) * 1000

    pass_fail_vector = [r.status for r in eval_result.assertion_results]

    return ScenarioTrialResult(
        scenario_id=scenario.id,
        approach=approach_name,
        trial=trial,
        assertion_count=len(eval_result.assertion_results),
        pass_count=eval_result.pass_count,
        fail_count=eval_result.fail_count,
        cost_usd=eval_result.total_cost,
        duration_ms=eval_result.total_duration_ms,
        wall_clock_ms=wall_clock_ms,
        passed=eval_result.passed,
        assertion_ids=[r.assertion_id for r in eval_result.assertion_results],
        pass_fail_vector=pass_fail_vector,
    )


def compute_consistency(
    trial_results: list[list[ScenarioTrialResult]],
) -> float:
    """Compute consistency across trials as pct of assertions with identical results.

    trial_results is a list of trials, each containing results for all scenarios.
    """
    if not trial_results or not trial_results[0]:
        return 100.0

    total_assertions = 0
    identical_count = 0

    # Group by scenario_id
    scenario_ids = [r.scenario_id for r in trial_results[0]]
    for sid in scenario_ids:
        vectors = []
        for trial in trial_results:
            for r in trial:
                if r.scenario_id == sid:
                    vectors.append(r.pass_fail_vector)
                    break

        if len(vectors) < 2:
            continue

        # Compare assertion-by-assertion across trials
        num_assertions = len(vectors[0])
        total_assertions += num_assertions
        for i in range(num_assertions):
            statuses = {v[i] for v in vectors if i < len(v)}
            if len(statuses) == 1:
                identical_count += 1

    if total_assertions == 0:
        return 100.0
    return round((identical_count / total_assertions) * 100, 2)


def count_judge_calls(approach_name: str, scenarios: list[Scenario]) -> int:
    """Estimate judge call count for an approach."""
    if approach_name == "deterministic":
        return 0

    total = 0
    for s in scenarios:
        if approach_name == "all_judge":
            # 4 coarse judge calls per scenario:
            # 1. correctness, 2. tool usage, 3. response quality, 4. subjective
            total += 4
        elif approach_name == "graduated":
            # Only subjective criteria use judge
            total += len(s.judge_criteria)

    return total


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    approach_summaries: list[ApproachSummary],
    all_results: dict[str, list[list[ScenarioTrialResult]]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Generate the JSON report."""
    return {
        "metadata": metadata,
        "summary": {
            s.approach: {
                "total_cost_usd": round(s.total_cost_usd, 6),
                "total_wall_clock_ms": round(s.total_wall_clock_ms, 2),
                "total_assertions": s.total_assertions,
                "total_pass": s.total_pass,
                "total_fail": s.total_fail,
                "consistency_pct": s.consistency_pct,
                "avg_cost_per_scenario": round(s.avg_cost_per_scenario, 6),
                "avg_wall_clock_per_scenario_ms": round(s.avg_wall_clock_per_scenario_ms, 2),
                "judge_call_count": s.judge_call_count,
            }
            for s in approach_summaries
        },
        "scenarios": {
            approach: [
                [
                    {
                        "scenario_id": r.scenario_id,
                        "trial": r.trial,
                        "assertion_count": r.assertion_count,
                        "pass_count": r.pass_count,
                        "fail_count": r.fail_count,
                        "cost_usd": round(r.cost_usd, 6),
                        "wall_clock_ms": round(r.wall_clock_ms, 2),
                        "passed": r.passed,
                    }
                    for r in trial
                ]
                for trial in trials
            ]
            for approach, trials in all_results.items()
        },
    }


def print_markdown_table(summaries: list[ApproachSummary]) -> None:
    """Print a markdown table for direct use in publications."""
    print("\n## Approach Comparison Results\n")
    print("| Metric | All LLM Judge | Graduated | Pure Deterministic |")
    print("|--------|--------------|-----------|-------------------|")

    by_name = {s.approach: s for s in summaries}
    a = by_name.get("all_judge")
    b = by_name.get("graduated")
    c = by_name.get("deterministic")

    def _val(s: ApproachSummary | None, attr: str, fmt: str = ".4f") -> str:
        if s is None:
            return "N/A"
        return f"{getattr(s, attr):{fmt}}"

    def _wall_s(s: ApproachSummary | None) -> str:
        if s is None:
            return "N/A"
        return f"{s.total_wall_clock_ms / 1000:.1f}s"

    print(f"| Total Cost (USD) | ${_val(a, 'total_cost_usd', '.4f')} | ${_val(b, 'total_cost_usd', '.4f')} | ${_val(c, 'total_cost_usd', '.4f')} |")
    print(f"| Wall Clock (s) | {_wall_s(a)} | {_wall_s(b)} | {_wall_s(c)} |")
    print(f"| Consistency | {_val(a, 'consistency_pct', '.1f')}% | {_val(b, 'consistency_pct', '.1f')}% | {_val(c, 'consistency_pct', '.1f')}% |")
    print(f"| Judge Calls | {a.judge_call_count if a else 'N/A'} | {b.judge_call_count if b else 'N/A'} | {c.judge_call_count if c else 'N/A'} |")
    print(f"| Total Assertions | {a.total_assertions if a else 'N/A'} | {b.total_assertions if b else 'N/A'} | {c.total_assertions if c else 'N/A'} |")
    print(f"| Assertions passed (not a detection rate) | {a.total_pass}/{a.total_assertions if a else '?'} | {b.total_pass}/{b.total_assertions if b else '?'} | {c.total_pass}/{c.total_assertions if c else '?'} |")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _SimulationFixture:
    """Lightweight fixture that bypasses engine startup for dry-run mode.

    Evaluates all assertions as pass with zero cost using the SDK's
    built-in simulation path.
    """

    def evaluate(self, chain: Any, *, budget: float | None = None) -> Any:
        from attest._proto.types import AssertionResult
        from attest.result import AgentResult

        results = [
            AssertionResult(
                assertion_id=a.assertion_id,
                status="pass",
                score=1.0,
                explanation=f"[simulation] {a.type} assertion passed",
                cost=0.0,
                duration_ms=0,
            )
            for a in chain.assertions
        ]
        return AgentResult(
            trace=chain.trace,
            assertion_results=results,
            total_cost=0.0,
            total_duration_ms=0,
        )

    def stop(self) -> None:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the three-approach agent evaluation benchmark.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=3,
        help="Number of trials per approach (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulation mode — no engine, no API calls",
    )
    parser.add_argument(
        "--approach",
        choices=["all_judge", "graduated", "deterministic"],
        default=None,
        help="Run a single approach only",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=None,
        help="Comma-separated scenario IDs to run (e.g. SC-001,SC-010)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=15.0,
        help="Maximum USD budget for the run (default: 15.0)",
    )
    parser.add_argument(
        "--engine-path",
        type=str,
        default=None,
        help="Path to attest-engine binary",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for results (default: results/)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse engine judge/embedding cache across trials (faster iteration, not for final results)",
    )
    return parser.parse_args()


_APPROACH_LABELS: dict[str, str] = {
    "all_judge": "All LLM Judge",
    "graduated": "Graduated",
    "deterministic": "Pure Deterministic",
}

_APPROACH_COLORS: dict[str, str] = {
    "all_judge": "red",
    "graduated": "yellow",
    "deterministic": "green",
}


def _build_header_panel(
    selected_scenarios: list[Scenario],
    approaches: list[str],
    trials: int,
    dry_run: bool,
    *,
    use_cache: bool = False,
) -> Panel:
    """Build the benchmark header panel with cost estimates."""
    lines: list[str] = []
    lines.append(
        f"[bold]{len(selected_scenarios)}[/bold] scenarios x "
        f"[bold]{trials}[/bold] trials x "
        f"[bold]{len(approaches)}[/bold] approaches"
    )
    lines.append(f"Judge: [cyan]gpt-4.1[/cyan]  |  Embedding: [cyan]text-embedding-3-small[/cyan]")
    if dry_run:
        lines.append("[bold yellow]MODE: dry-run (simulation — no API calls)[/bold yellow]")
    if use_cache:
        lines.append("[bold magenta]CACHE: enabled (reusing cached evaluations)[/bold magenta]")
    lines.append("")

    for approach in approaches:
        judge_calls = count_judge_calls(approach, selected_scenarios)
        est_cost = judge_calls * 0.004 * trials
        color = _APPROACH_COLORS.get(approach, "white")
        label = _APPROACH_LABELS.get(approach, approach)
        lines.append(
            f"  [{color}]{label}[/{color}]: "
            f"~{judge_calls} judge calls/trial, "
            f"est. [bold]${est_cost:.2f}[/bold] for {trials} trials"
        )

    return Panel("\n".join(lines), title="[bold]Approach Comparison Benchmark[/bold]", border_style="blue")


def _build_results_table(
    completed_approaches: dict[str, list[list[ScenarioTrialResult]]],
    approaches: list[str],
    trials: int,
) -> Table:
    """Build a live-updating results table from completed trial data."""
    table = Table(title="Trial Results", show_lines=True, border_style="dim")
    table.add_column("Approach", style="bold", min_width=20)
    for t in range(trials):
        table.add_column(f"Trial {t + 1}", justify="center", min_width=28)

    for approach in approaches:
        if approach not in completed_approaches:
            continue
        color = _APPROACH_COLORS.get(approach, "white")
        label = _APPROACH_LABELS.get(approach, approach)
        row: list[str] = [f"[{color}]{label}[/{color}]"]

        for trial_results in completed_approaches[approach]:
            t_pass = sum(r.pass_count for r in trial_results)
            t_total = sum(r.assertion_count for r in trial_results)
            t_cost = sum(r.cost_usd for r in trial_results)
            t_wall_s = sum(r.wall_clock_ms for r in trial_results) / 1000

            pass_pct = (t_pass / t_total * 100) if t_total else 0
            pct_color = "green" if pass_pct >= 95 else "yellow" if pass_pct >= 80 else "red"
            row.append(
                f"[{pct_color}]{t_pass}/{t_total}[/{pct_color}] "
                f"({pass_pct:.0f}%)  ${t_cost:.4f}  {t_wall_s:.1f}s"
            )

        table.add_row(*row)
    return table


def main() -> None:
    args = parse_args()
    console = Console()

    # Select scenarios
    if args.scenarios:
        scenario_ids = [s.strip() for s in args.scenarios.split(",")]
        selected_scenarios = [SCENARIOS_BY_ID[sid] for sid in scenario_ids]
    else:
        selected_scenarios = SCENARIOS

    # Select approaches
    if args.approach:
        approaches = [args.approach]
    else:
        approaches = ["all_judge", "graduated", "deterministic"]

    # Enable simulation mode for dry-run
    if args.dry_run:
        os.environ["ATTEST_SIMULATION"] = "1"

    use_cache = getattr(args, "use_cache", False)

    from attest.plugin import AttestEngineFixture

    # Metadata
    metadata: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "judge_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-small",
        "trial_count": args.trials,
        "scenario_count": len(selected_scenarios),
        "approaches": approaches,
        "dry_run": args.dry_run,
        "cache_enabled": use_cache,
    }

    # Print header
    console.print()
    console.print(_build_header_panel(
        selected_scenarios, approaches, args.trials, args.dry_run,
        use_cache=use_cache,
    ))
    console.print()

    # ── Engine lifecycle helpers ──
    # When --no-cache: fresh engine + temp cache per trial for isolation.
    # Otherwise: single engine for the entire run.

    _temp_cache_dirs: list[str] = []

    def _start_fixture() -> AttestEngineFixture | _SimulationFixture:
        if args.dry_run:
            return _SimulationFixture()
        if not use_cache:
            td = tempfile.mkdtemp(prefix="attest-bench-cache-")
            _temp_cache_dirs.append(td)
            os.environ["ATTEST_CACHE_DIR"] = td
        fixture = AttestEngineFixture(engine_path=args.engine_path, log_level="warn")
        try:
            fixture.start()
        except FileNotFoundError:
            console.print("[bold red]ERROR:[/] attest-engine binary not found. Build with 'make engine' or use --dry-run.")
            sys.exit(1)
        return fixture

    def _stop_fixture(f: AttestEngineFixture | _SimulationFixture) -> None:
        f.stop()

    # In shared-engine mode (--use-cache), start once
    shared_fixture: AttestEngineFixture | _SimulationFixture | None = None
    if use_cache:
        with console.status("[bold blue]Starting attest engine...", spinner="dots"):
            shared_fixture = _start_fixture()

    # Run benchmark with progress
    all_results: dict[str, list[list[ScenarioTrialResult]]] = {}
    total_work = len(approaches) * args.trials * len(selected_scenarios)

    progress = Progress(
        SpinnerColumn("dots"),
        TextColumn("[bold]{task.fields[approach_label]}[/bold]"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("[dim]|[/dim]"),
        TimeElapsedColumn(),
        TextColumn("[dim]|[/dim]"),
        TextColumn("{task.fields[status]}"),
        console=console,
        expand=False,
    )

    overall_task = progress.add_task(
        "Overall",
        total=total_work,
        approach_label="[blue]Overall progress",
        status="starting...",
    )

    with progress:
        for approach in approaches:
            color = _APPROACH_COLORS.get(approach, "white")
            label = _APPROACH_LABELS.get(approach, approach)
            approach_total = args.trials * len(selected_scenarios)

            approach_task = progress.add_task(
                approach,
                total=approach_total,
                approach_label=f"[{color}]{label}",
                status="starting...",
            )

            approach_trials: list[list[ScenarioTrialResult]] = []

            for trial in range(args.trials):
                # Fresh engine per trial (default) for experimental isolation
                if not use_cache:
                    progress.update(approach_task, status=f"trial {trial + 1}/{args.trials}  starting engine...")
                    fixture = _start_fixture()
                else:
                    assert shared_fixture is not None
                    fixture = shared_fixture

                trial_results: list[ScenarioTrialResult] = []
                t_trial_start = time.perf_counter()

                for scenario in selected_scenarios:
                    progress.update(
                        approach_task,
                        status=f"trial {trial + 1}/{args.trials}  {scenario.id} ({scenario.name})",
                    )
                    progress.update(
                        overall_task,
                        status=f"{label} trial {trial + 1}  {scenario.id}",
                    )

                    result = run_single_evaluation(
                        attest_fixture=fixture,
                        scenario=scenario,
                        approach_name=approach,
                        trial=trial,
                        budget=args.budget,
                    )
                    trial_results.append(result)
                    progress.advance(approach_task)
                    progress.advance(overall_task)

                t_trial_end = time.perf_counter()
                trial_wall_s = t_trial_end - t_trial_start
                trial_pass = sum(r.pass_count for r in trial_results)
                trial_total = sum(r.assertion_count for r in trial_results)
                trial_cost = sum(r.cost_usd for r in trial_results)

                progress.update(
                    approach_task,
                    status=(
                        f"trial {trial + 1}/{args.trials} done: "
                        f"{trial_pass}/{trial_total} passed, "
                        f"${trial_cost:.4f}, {trial_wall_s:.1f}s"
                    ),
                )
                approach_trials.append(trial_results)

                # Stop per-trial engine
                if not use_cache:
                    _stop_fixture(fixture)

            all_results[approach] = approach_trials
            progress.update(approach_task, status="[bold green]complete")

        progress.update(overall_task, status="[bold green]all approaches complete")

    console.print()

    # Show results table
    console.print(_build_results_table(all_results, approaches, args.trials))
    console.print()

    # Aggregate summaries
    summaries: list[ApproachSummary] = []
    for approach in approaches:
        trials = all_results[approach]
        total_cost = sum(r.cost_usd for trial in trials for r in trial)
        total_wall = sum(r.wall_clock_ms for trial in trials for r in trial)
        total_assertions = sum(r.assertion_count for trial in trials for r in trial)
        total_pass = sum(r.pass_count for trial in trials for r in trial)
        total_fail = sum(r.fail_count for trial in trials for r in trial)
        consistency = compute_consistency(trials)
        num_evaluations = len(selected_scenarios) * args.trials

        summaries.append(ApproachSummary(
            approach=approach,
            total_cost_usd=total_cost,
            total_wall_clock_ms=total_wall,
            total_assertions=total_assertions,
            total_pass=total_pass,
            total_fail=total_fail,
            consistency_pct=consistency,
            avg_cost_per_scenario=total_cost / num_evaluations if num_evaluations else 0,
            avg_wall_clock_per_scenario_ms=total_wall / num_evaluations if num_evaluations else 0,
            judge_call_count=count_judge_calls(approach, selected_scenarios) * args.trials,
        ))

    # Print summary table
    summary_table = Table(title="[bold]Approach Comparison Summary[/bold]", show_lines=True, border_style="blue")
    summary_table.add_column("Metric", style="bold", min_width=22)
    for approach in approaches:
        color = _APPROACH_COLORS.get(approach, "white")
        label = _APPROACH_LABELS.get(approach, approach)
        summary_table.add_column(f"[{color}]{label}", justify="center", min_width=18)

    by_name = {s.approach: s for s in summaries}
    rows: list[tuple[str, ...]] = [
        ("Total Cost (USD)", *(f"${by_name[a].total_cost_usd:.4f}" for a in approaches)),
        ("Wall Clock (s)", *(_fmt_wall_clock(by_name[a].total_wall_clock_ms) for a in approaches)),
        ("Consistency", *(_fmt_consistency(by_name[a].consistency_pct) for a in approaches)),
        ("Judge Calls", *(str(by_name[a].judge_call_count) for a in approaches)),
        ("Total Assertions", *(str(by_name[a].total_assertions) for a in approaches)),
        ("Assertions passed (not a detection rate)", *(_fmt_pass_rate(by_name[a]) for a in approaches)),
    ]
    for row in rows:
        summary_table.add_row(*row)

    console.print(summary_table)
    console.print()

    # Also print markdown table for copy-paste
    print_markdown_table(summaries)

    # Write JSON report
    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_file = output_dir / f"benchmark-{timestamp}.json"

    report = generate_report(summaries, all_results, metadata)
    output_file.write_text(json.dumps(report, indent=2))
    console.print(f"Report written to: [bold]{output_file}[/bold]")

    # Cleanup
    if shared_fixture is not None:
        _stop_fixture(shared_fixture)
    for td in _temp_cache_dirs:
        shutil.rmtree(td, ignore_errors=True)


def _fmt_wall_clock(ms: float) -> str:
    """Format wall clock milliseconds as seconds."""
    return f"{ms / 1000:.1f}s"


def _fmt_consistency(pct: float) -> str:
    """Format consistency percentage with color."""
    if pct >= 99.0:
        return f"[bold green]{pct:.1f}%[/bold green]"
    if pct >= 90.0:
        return f"[yellow]{pct:.1f}%[/yellow]"
    return f"[red]{pct:.1f}%[/red]"


def _fmt_pass_rate(s: ApproachSummary) -> str:
    """Format the share of this approach's own assertions that passed.

    This is not a detection rate: the scenarios contain no labeled faults. Detection rates
    come from the fault corpus (`make corpus-bench`).
    """
    pct = (s.total_pass / s.total_assertions * 100) if s.total_assertions else 0
    return f"{s.total_pass}/{s.total_assertions} ({pct:.0f}%)"


if __name__ == "__main__":
    main()
