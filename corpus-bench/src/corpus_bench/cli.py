"""`python -m corpus_bench`: build, verify and run the fault-corpus benchmark."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from corpus_bench import approach_a, approach_b, approach_c, corpus, report
from corpus_bench import engine as eng
from corpus_bench.verdict import Verdict

PUBLISHED = eng.ROOT / "published"


def _build() -> tuple[Path, list[corpus.Item], float]:
    path = eng.resolve_engine()
    start = time.perf_counter()
    with eng.Engine(path) as engine:
        items = corpus.build_items(path, engine)
    return path, items, time.perf_counter() - start


def _run_a(
    path: Path, items: list[corpus.Item]
) -> tuple[dict[str, Verdict], dict[str, Any], float]:
    start = time.perf_counter()
    with eng.Engine(path) as engine:
        verdicts = approach_a.run(engine, items)
        facts = {
            "cost_usd": round(engine.cost_usd, 6),
            "model_calls": engine.model_calls + engine.judge_calls,
        }
    return verdicts, facts, time.perf_counter() - start


def _run_b(items: list[corpus.Item]) -> tuple[dict[str, Verdict], dict[str, Any], float]:
    start = time.perf_counter()
    verdicts = approach_b.run(items)
    return verdicts, {"cost_usd": 0.0, "model_calls": 0}, time.perf_counter() - start


def cmd_run(args: argparse.Namespace) -> int:
    path, items, build_s = _build()
    corpus.verify_manifest(items)
    version = eng.engine_version(path)
    first: tuple[dict[str, Verdict], dict[str, Verdict]] | None = None
    facts_a: dict[str, Any] = {}
    facts_b: dict[str, Any] = {}
    times: dict[str, list[float]] = {"a": [], "b": []}
    for _ in range(args.timing_runs):
        verdicts_a, facts_a, seconds_a = _run_a(path, items)
        verdicts_b, facts_b, seconds_b = _run_b(items)
        times["a"].append(seconds_a)
        times["b"].append(seconds_b)
        if first is None:
            first = (verdicts_a, verdicts_b)
        elif first != (verdicts_a, verdicts_b):
            raise RuntimeError("verdicts differ between repeated runs: the benchmark is not stable")
    assert first is not None
    results = report.build_results(
        items, version, {"a": (first[0], facts_a), "b": (first[1], facts_b)}
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(report.dumps(results), encoding="utf-8")
    (out / "results.md").write_text(report.render_markdown(results), encoding="utf-8")
    timings = {
        "note": "wall seconds on the machine that ran `make corpus-bench`; not reproducible",
        "runs": args.timing_runs,
        "corpus_build_s": round(build_s, 3),
        **{
            f"approach_{k}_s": {
                "median": round(statistics.median(v), 3),
                "min": round(min(v), 3),
                "max": round(max(v), 3),
            }
            for k, v in times.items()
        },
    }
    (out / "timings.json").write_text(json.dumps(timings, indent=2) + "\n", encoding="utf-8")
    print((out / "results.md").read_text(encoding="utf-8"))
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    """Approach (c). Paid unless --dry-run; never called by `run`."""
    path, items, _seconds = _build()
    corpus.verify_manifest(items)
    verdicts, facts = approach_c.run(path, items, simulation=args.dry_run)
    if args.dry_run:
        print(f"dry run: {len(verdicts)} judge requests accepted by the engine, no model called")
        return 0
    scored = [i for i in approach_c.judged(items) if i.id in verdicts]
    result = {
        "engine": eng.engine_version(path),
        "provider": os.environ["ATTEST_JUDGE_PROVIDER"],
        "model": os.environ.get("ATTEST_JUDGE_MODEL", ""),
        "judged_items": len(scored),
        "judgeable_items": len(approach_c.judged(items)),
        **facts,
        **report.confusion(scored, verdicts),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "judge-results.json").write_text(report.dumps(result), encoding="utf-8")
    print(report.dumps(result))
    if facts["stopped"]:
        print(f"judge run stopped early, partial results written: {facts['stopped']}")
        return 1
    return 0


def cmd_manifest(_args: argparse.Namespace) -> int:
    _path, items, _seconds = _build()
    corpus.write_manifest(items)
    print(f"wrote {corpus.MANIFEST_PATH} ({len(items)} items)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _path, items, _seconds = _build()
    match = [i for i in items if i.id == args.id]
    if not match:
        raise SystemExit(f"no corpus item {args.id!r}")
    item = match[0]
    print(
        json.dumps(
            {
                **item.manifest_row(),
                "reply": item.reply,
                "trace": item.trace,
                "world": item.world,
                "mutant": item.mutant and vars(item.mutant),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_fetch(_args: argparse.Namespace) -> int:
    print(eng.fetch_engine())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corpus_bench")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run approaches (a) and (b) offline and write the table")
    run.add_argument("--out", default=str(PUBLISHED))
    run.add_argument("--timing-runs", type=int, default=3)
    run.set_defaults(func=cmd_run)
    judge = sub.add_parser("judge", help="approach (c): paid, opt-in; --dry-run calls no model")
    judge.add_argument("--out", default=str(PUBLISHED))
    judge.add_argument("--dry-run", action="store_true")
    judge.set_defaults(func=cmd_judge)
    sub.add_parser("manifest", help="rewrite corpus/manifest.json").set_defaults(func=cmd_manifest)
    show = sub.add_parser("show", help="print one corpus item")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)
    fetch = sub.add_parser("fetch-engine", help="build attest-engine from the pinned attest commit")
    fetch.set_defaults(func=cmd_fetch)
    args = parser.parse_args(argv)
    try:
        code: int = args.func(args)
    except eng.EngineError as exc:
        print(f"corpus-bench: {exc}", file=sys.stderr)
        return 1
    return code
