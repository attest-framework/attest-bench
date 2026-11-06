"""Approach (a): attest contracts and effect contracts, evaluated offline by the engine.

The contracts are the ones committed with the refund-desk fixtures (drafted by
`attest capture`, plus its relational contracts). Runs are judged from the recorded trace
and world snapshot: no agent runs and no model is called. A mutant is judged by
`attest-engine mutate`, which runs the same contracts on the mutated behavior.
"""

from __future__ import annotations

from corpus_bench import corpus
from corpus_bench.engine import Engine, EngineError
from corpus_bench.verdict import Verdict

DETERMINISTIC_STATUSES = {"pass", "hard_fail"}


def run(engine: Engine, items: list[corpus.Item]) -> dict[str, Verdict]:
    verdicts: dict[str, Verdict] = {}
    for item in items:
        if item.mutant is not None:
            verdicts[item.id] = Verdict(item.mutant.killed, item.mutant.mutate_id)
            continue
        assert item.trace is not None and item.world is not None
        assertions = corpus.assertions_for(corpus.contracts_for(item.scenario), item.world)
        rows = engine.evaluate(item.trace, assertions)
        odd = [r["assertion_id"] for r in rows if r["status"] not in DETERMINISTIC_STATUSES]
        if odd:
            raise EngineError(f"{item.id}: contracts {odd} were not decided pass or hard_fail")
        failed = [r["assertion_id"] for r in rows if r["status"] == "hard_fail"]
        verdicts[item.id] = Verdict(bool(failed), ",".join(failed))
    if engine.model_calls or engine.judge_calls or engine.cost_usd:
        raise EngineError("approach (a) must not call a model")
    return verdicts
