"""Aggregate verdicts into the results table (markdown and JSON)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from corpus_bench import corpus
from corpus_bench.verdict import Verdict

GROUP_ORDER = ["real-incident", "output-only", "mutant"]
GROUP_TITLES = {
    "real-incident": "real incident runs (INC-1042 before the fix, INC-1077)",
    "output-only": "output-only faults (wrong reply, correct behavior)",
    "mutant": "behavior mutants (`attest-engine mutate`)",
}
VARIANT_TITLES = {"clean-base": "clean runs", "clean-variant": "clean variants"}


def rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def pct(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.1f}%)" if den else "n/a"


def confusion(items: list[corpus.Item], verdicts: dict[str, Verdict]) -> dict[str, Any]:
    faults = [i for i in items if i.label != "clean"]
    clean = [i for i in items if i.label == "clean"]
    tp = sum(verdicts[i.id].flagged for i in faults)
    fp = sum(verdicts[i.id].flagged for i in clean)
    out: dict[str, Any] = {
        "tp": tp,
        "fn": len(faults) - tp,
        "fp": fp,
        "tn": len(clean) - fp,
        "tpr": rate(tp, len(faults)),
        "fpr": rate(fp, len(clean)),
        "by_group": {},
        "by_kind": {},
        "missed": sorted(i.id for i in faults if not verdicts[i.id].flagged),
        "false_positives": sorted(i.id for i in clean if verdicts[i.id].flagged),
    }
    out["by_group"] = _by(faults, lambda i: i.group, verdicts)
    out["by_kind"] = _by(faults, lambda i: i.label.removeprefix("fault:"), verdicts)
    out["clean_by_group"] = {
        g: _count([i for i in clean if i.group == g], verdicts)
        for g in sorted({i.group for i in clean})
    }
    out["false_positives_by_variant"] = {
        v: _count([i for i in clean if i.id.endswith(f"+{v}")], verdicts)
        for v in sorted({i.id.split("+", 1)[1] for i in clean if "+" in i.id})
    }
    return out


def _by(
    bucket: list[corpus.Item], select: Callable[[corpus.Item], str], verdicts: dict[str, Verdict]
) -> dict[str, dict[str, int]]:
    return {
        name: _count([i for i in bucket if select(i) == name], verdicts)
        for name in sorted({select(i) for i in bucket})
    }


def _count(items: list[corpus.Item], verdicts: dict[str, Verdict]) -> dict[str, int]:
    return {"flagged": sum(verdicts[i.id].flagged for i in items), "n": len(items)}


def build_results(
    items: list[corpus.Item],
    engine_version: str,
    approaches: dict[str, tuple[dict[str, Verdict], dict[str, Any]]],
) -> dict[str, Any]:
    """`approaches` maps a key to (verdicts, facts such as cost and model calls)."""
    combined = {
        i.id: Verdict(
            approaches["a"][0][i.id].flagged or approaches["b"][0][i.id].flagged, "a or b"
        )
        for i in items
    }
    rows: dict[str, Any] = {}
    for key, (verdicts, facts) in approaches.items():
        rows[key] = {"status": "run", **facts, **confusion(items, verdicts)}
    rows["a_or_b"] = {
        "status": "run",
        "cost_usd": 0.0,
        "model_calls": 0,
        **confusion(items, combined),
    }
    rows["c"] = {
        "status": "not_run",
        "reason": "judge-only needs a model key; it runs only through the opt-in "
        "corpus-bench-judge workflow_dispatch job",
    }
    return {
        "schema": 1,
        "engine": engine_version,
        "corpus": {
            "items": len(items),
            "clean": sum(i.label == "clean" for i in items),
            "faults": sum(i.label != "clean" for i in items),
            "groups": {
                g: sum(i.group == g for i in items) for g in sorted({i.group for i in items})
            },
        },
        "approaches": rows,
    }


NAMES = {
    "a": "(a) attest contracts + effects",
    "b": "(b) pytest + cassette, output assertions",
    "a_or_b": "(a) or (b) flags",
    "c": "(c) judge-only",
}


def render_markdown(results: dict[str, Any]) -> str:
    corpus_info = results["corpus"]
    approaches = results["approaches"]
    lines = [
        "# Fault-corpus results",
        "",
        f"Engine: attest-engine {results['engine']}. Corpus: {corpus_info['items']} labeled runs, "
        f"{corpus_info['faults']} faulty and {corpus_info['clean']} clean. "
        "All numbers below come from `make corpus-bench`.",
        "",
        "## Detection",
        "",
        "| Approach | True-positive rate | False-positive rate | Cost (USD) | Model calls |",
        "|---|---|---|---|---|",
    ]
    for key in ("a", "b", "a_or_b"):
        row = approaches[key]
        lines.append(
            f"| {NAMES[key]} | {pct(row['tp'], row['tp'] + row['fn'])} "
            f"| {pct(row['fp'], row['fp'] + row['tn'])} | ${row['cost_usd']:.2f} "
            f"| {row['model_calls']} |"
        )
    lines.append(f"| {NAMES['c']} | not run | not run | not run | not run |")
    lines += [
        "",
        "True-positive rate: faulty runs flagged / faulty runs. False-positive rate: clean runs "
        "flagged / clean runs. Wall time is in `timings.json` and varies by run.",
        "",
        "## True-positive rate by fault group",
        "",
        "| Fault group | Runs | (a) attest | (b) output assertions | (a) or (b) |",
        "|---|---|---|---|---|",
    ]
    for group in GROUP_ORDER:
        counts = [approaches[k]["by_group"].get(group) for k in ("a", "b", "a_or_b")]
        n = counts[0]["n"]
        lines.append(
            f"| {GROUP_TITLES[group]} | {n} | "
            + " | ".join(pct(c["flagged"], c["n"]) for c in counts)
            + " |"
        )
    lines += [
        "",
        "## True-positive rate by fault kind",
        "",
        "| Fault kind | Runs | (a) attest | (b) output assertions |",
        "|---|---|---|---|",
    ]
    for kind in sorted(approaches["a"]["by_kind"]):
        a, b = approaches["a"]["by_kind"][kind], approaches["b"]["by_kind"][kind]
        lines.append(
            f"| `{kind}` | {a['n']} | {pct(a['flagged'], a['n'])} | {pct(b['flagged'], b['n'])} |"
        )
    lines += [
        "",
        "## False positives by clean variant",
        "",
        "| Clean run | Runs | (a) attest flags | (b) output assertions flag |",
        "|---|---|---|---|",
    ]
    base_a, base_b = (
        approaches["a"]["clean_by_group"]["clean-base"],
        approaches["b"]["clean_by_group"]["clean-base"],
    )
    lines.append(
        f"| unmodified clean runs | {base_a['n']} | {pct(base_a['flagged'], base_a['n'])} "
        f"| {pct(base_b['flagged'], base_b['n'])} |"
    )
    for variant in sorted(approaches["a"]["false_positives_by_variant"]):
        a = approaches["a"]["false_positives_by_variant"][variant]
        b = approaches["b"]["false_positives_by_variant"][variant]
        lines.append(
            f"| `{variant}` | {a['n']} | {pct(a['flagged'], a['n'])} "
            f"| {pct(b['flagged'], b['n'])} |"
        )
    lines += ["", "## Runs each approach misses", ""]
    for key in ("a", "b"):
        missed = approaches[key]["missed"]
        lines.append(f"### {NAMES[key]}: {len(missed)} missed")
        lines.append("")
        lines += [f"- `{m}`" for m in missed]
        lines.append("")
    lines += ["## Clean runs each approach flags", ""]
    for key in ("a", "b"):
        flagged = approaches[key]["false_positives"]
        lines.append(f"### {NAMES[key]}: {len(flagged)} flagged")
        lines.append("")
        lines += [f"- `{m}`" for m in flagged] or ["- none"]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def dumps(results: dict[str, Any]) -> str:
    return json.dumps(results, indent=2, sort_keys=True) + "\n"
