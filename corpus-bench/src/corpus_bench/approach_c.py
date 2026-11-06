"""Approach (c): one LLM judge per run, reading a transcript of the run.

Opt-in and paid: `make corpus-bench` never runs it. The `corpus-bench-judge` workflow
(workflow_dispatch, key-gated) and `make corpus-judge` do. The engine is given a spend
cap (`ATTEST_BUDGET_USD`) and a call cap (`ATTEST_MAX_JUDGE_CALLS`); the run refuses to start
without them. Mutants have no materialized trace, so only the other runs are judged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from corpus_bench import corpus
from corpus_bench.engine import Engine, EngineError
from corpus_bench.verdict import Verdict

CRITERIA = (
    "The transcript is one run of a customer-support refund agent. The run is correct only if "
    "every condition holds: the order is looked up before it is refunded; exactly one refund is "
    "issued for the order and its amount does not exceed the order amount; the customer is "
    "notified once, and the notification goes to the customer who owns the order; the final reply "
    "states the refunded amount accurately and says nothing false. Fail the run if any condition "
    "is broken."
)
SPEC = {
    "target": "output.message",
    "criteria": CRITERIA,
    "rubric": "default",
    "threshold": 0.8,
    "model": None,
    "soft": False,
}


def transcript(item: corpus.Item) -> str:
    assert item.trace is not None and item.world is not None
    lines = []
    for step in item.trace["steps"]:
        if step["type"] == "tool_call":
            lines.append(f"tool {step['name']} args={step['args']} -> {step['result']}")
    lines.append(f"world after the run: {item.world['state']}")
    lines.append(f"final reply: {item.reply}")
    return "\n".join(lines)


def _reason(row: dict[str, Any]) -> str:
    """Why the judge returned no verdict: the row's explanation, or its serialized form."""
    return str(row.get("explanation") or json.dumps(row))


def judged(items: list[corpus.Item]) -> list[corpus.Item]:
    return [i for i in items if i.mutant is None]


def require_caps() -> None:
    for name in ("ATTEST_BUDGET_USD", "ATTEST_MAX_JUDGE_CALLS", "ATTEST_JUDGE_PROVIDER"):
        if not os.environ.get(name):
            raise EngineError(f"approach (c) is paid: set {name} before running it")


def run(
    path: Path, items: list[corpus.Item], *, simulation: bool
) -> tuple[dict[str, Verdict], dict[str, Any]]:
    """Judge every non-mutant run. `simulation=True` checks the requests and calls no model.

    A spend or call cap, or a row with no verdict (provider unavailable, judge abstained or
    malformed), ends the run early; `stopped` in the facts names the run and the reason."""
    if not simulation:
        require_caps()
    verdicts: dict[str, Verdict] = {}
    stopped: str | None = None
    with Engine(path, simulation=simulation) as engine:
        for item in judged(items):
            assert item.trace is not None
            trace = {**item.trace, "output": {"message": transcript(item)}}
            row = engine.evaluate(
                trace, [{"assertion_id": "judge-run-correct", "type": "llm_judge", "spec": SPEC}]
            )[0]
            if simulation:
                if row["status"] != "not_evaluated":
                    raise EngineError(f"{item.id}: simulation judged a run: {row['status']}")
                verdicts[item.id] = Verdict(False, "not_evaluated(simulation)")
                continue
            if row["status"] == "not_evaluated" and "budget_exhausted" in json.dumps(row):
                stopped = f"{item.id}: budget_exhausted"
                break
            if row["status"] not in ("pass", "hard_fail"):
                stopped = f"{item.id}: {row['status']}: {_reason(row)}"
                break
            verdicts[item.id] = Verdict(row["status"] == "hard_fail", row["explanation"])
        facts = {
            "cost_usd": round(engine.cost_usd, 6),
            "model_calls": engine.model_calls + engine.judge_calls,
            "stopped": stopped,
        }
    return verdicts, facts
