from __future__ import annotations

from pathlib import Path

import pytest

from corpus_bench import approach_a, approach_b, approach_c, corpus, report
from corpus_bench import engine as eng
from corpus_bench.cassette import Cassette, CassetteMissError
from corpus_bench.verdict import Verdict


def make_item(item_id: str, label: str, group: str) -> corpus.Item:
    return corpus.Item(
        id=item_id,
        label=label,
        group=group,
        scenario="inc-1042",
        source="test",
        generator="test",
        reply="",
        cassette=[],
    )


def test_cassette_replay_unknown_key_raises_miss() -> None:
    fixture = corpus.load_source("inc-1042-fixed-py")
    cassette = Cassette(corpus.final_cassette(fixture, "recorded"))

    assert cassette.replay(fixture["exchanges"][-1]["key"]) == "recorded"
    with pytest.raises(CassetteMissError):
        cassette.replay({"model": "other", "prompt_hash": "x", "tool_schema_hash": "y"})


def test_derive_o2001_swaps_order_customer_and_amount() -> None:
    derived = corpus.derive_o2001(corpus.load_source("inc-1042-fixed-py"))

    refund = derived["trace"]["steps"][3]
    assert refund["args"]["order_id"] == "O-2001"
    assert refund["args"]["amount_cents"] == 2650
    assert corpus.final_reply(derived) == "Your refund of $26.50 has been processed."


def test_derive_inc1077_fixed_leaves_one_refund_for_the_order_customer() -> None:
    fixed = corpus.derive_inc1077_fixed(corpus.load_source("inc-1077-buggy-py"))

    refunds = [s for s in fixed["trace"]["steps"] if s["name"] == "issue_refund"]
    assert [r["args"]["amount_cents"] for r in refunds] == [12600]
    assert fixed["world"]["state"]["notifications"][0]["customer_id"] == "C-0744"
    assert fixed["trace"]["turns"][0]["step_indices"] == list(range(len(fixed["trace"]["steps"])))


def test_benign_repeat_lookup_adds_one_lookup_pair() -> None:
    base = corpus.load_source("inc-1042-fixed-py")

    variant, _ = corpus.benign_repeat_lookup(base, "reply", 8400)

    names = [s["name"] for s in variant["trace"]["steps"] if s["type"] == "tool_call"]
    assert names == ["lookup_order", "lookup_order", "issue_refund", "notify_customer"]
    span_ids = [s["span_id"] for s in variant["trace"]["steps"]]
    assert len(set(span_ids)) == len(span_ids)


def test_confusion_counts_rates_over_faulty_and_clean_runs() -> None:
    items = [
        make_item("f1", "fault:x", "mutant"),
        make_item("f2", "fault:x", "mutant"),
        make_item("c1", "clean", "clean-base"),
        make_item("c2", "clean", "clean-base"),
    ]
    verdicts = {
        "f1": Verdict(True, ""),
        "f2": Verdict(False, ""),
        "c1": Verdict(True, ""),
        "c2": Verdict(False, ""),
    }

    counts = report.confusion(items, verdicts)

    assert (counts["tp"], counts["fn"], counts["fp"], counts["tn"]) == (1, 1, 1, 1)
    assert counts["tpr"] == 0.5 and counts["fpr"] == 0.5
    assert counts["missed"] == ["f2"]


def test_corpus_rebuild_matches_committed_manifest(items: list[corpus.Item]) -> None:
    corpus.verify_manifest(items)


def test_corpus_labels_every_item_clean_or_fault_kind(items: list[corpus.Item]) -> None:
    assert all(i.label == "clean" or i.label.startswith("fault:") for i in items)
    assert len({i.id for i in items}) == len(items)
    assert any(i.label == "clean" for i in items) and any(i.group == "output-only" for i in items)


def test_approach_a_flags_inc_1077_and_passes_its_fixed_run(
    engine_path: Path, items: list[corpus.Item]
) -> None:
    with eng.Engine(engine_path) as engine:
        verdicts = approach_a.run(engine, items)

    assert verdicts["real/inc-1077-buggy"].flagged
    assert not verdicts["clean/inc-1077-fixed"].flagged
    assert engine.cost_usd == 0.0


def test_approach_b_misses_inc_1042_double_refund_but_flags_a_wrong_amount(
    items: list[corpus.Item],
) -> None:
    verdicts = approach_b.run(items)

    assert not verdicts["real/inc-1042-prefix"].flagged
    assert verdicts["output/inc-1042-fixed+reply_wrong_amount"].flagged


def test_results_are_identical_across_reruns(engine_path: Path, items: list[corpus.Item]) -> None:
    def table() -> str:
        with eng.Engine(engine_path) as engine:
            a = approach_a.run(engine, items)
        b = approach_b.run(items)
        facts = {"cost_usd": 0.0, "model_calls": 0}
        results = report.build_results(items, "1.1.0-rc.3", {"a": (a, facts), "b": (b, facts)})
        return report.render_markdown(results) + report.dumps(results)

    assert table() == table()


def test_approach_c_dry_run_sends_valid_judge_requests_without_a_model(
    engine_path: Path, items: list[corpus.Item]
) -> None:
    verdicts, facts = approach_c.run(engine_path, items, simulation=True)

    assert len(verdicts) == len(approach_c.judged(items))
    assert facts["cost_usd"] == 0.0 and facts["model_calls"] == 0


def test_approach_c_paid_run_refuses_to_start_without_spend_caps(
    engine_path: Path, items: list[corpus.Item], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATTEST_BUDGET_USD", raising=False)

    with pytest.raises(eng.EngineError, match="ATTEST_BUDGET_USD"):
        approach_c.run(engine_path, items, simulation=False)


class ScriptedJudgeEngine:
    """Stands in for the engine process: answers each judge request from a fixed status list."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.cost_usd = 0.0
        self.model_calls = 0
        self.judge_calls = 0

    def __enter__(self) -> ScriptedJudgeEngine:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def evaluate(
        self, _trace: dict[str, object], _assertions: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        status = self.statuses.pop(0)
        return [{"status": status, "explanation": f"scripted {status}"}]


@pytest.mark.parametrize("status", ["provider_unavailable", "judge_abstained", "judge_malformed"])
def test_approach_c_row_without_verdict_stops_with_partial_results(
    status: str,
    engine_path: Path,
    items: list[corpus.Item],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in (
        ("ATTEST_BUDGET_USD", "1"),
        ("ATTEST_MAX_JUDGE_CALLS", "10"),
        ("ATTEST_JUDGE_PROVIDER", "openai"),
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        approach_c, "Engine", lambda *_a, **_k: ScriptedJudgeEngine(["pass", status])
    )
    judged = approach_c.judged(items)

    verdicts, facts = approach_c.run(engine_path, items, simulation=False)

    assert list(verdicts) == [judged[0].id]
    assert facts["stopped"] == f"{judged[1].id}: {status}: scripted {status}"


def test_resolve_engine_wrong_commit_raises(
    engine_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = {**eng.load_lock(), "commit": "0" * 40}
    monkeypatch.setattr(eng, "load_lock", lambda: lock)
    monkeypatch.setenv("ATTEST_ENGINE_PATH", str(engine_path))

    with pytest.raises(eng.EngineError, match="was built from"):
        eng.resolve_engine()


def test_mutants_kill_world_edits_through_embedded_effect_contracts(
    items: list[corpus.Item],
) -> None:
    by_id = {i.id: i for i in items if i.mutant is not None}

    killed = by_id["mutant/inc-1077-fixed:alter_world_effect:refunds.0.duplicate"].mutant
    assert killed is not None and killed.killed
