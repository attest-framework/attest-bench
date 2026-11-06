"""The labeled corpus: real refund-desk runs, derived clean runs, variants and mutants.

Every item is rebuilt from the committed sources by named transforms, so the corpus is
reproducible and `corpus/manifest.json` can pin each item by content hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corpus_bench import engine as eng

ROOT = eng.ROOT
SOURCES = ROOT / "corpus" / "sources"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
MUTATE_SEED = 0
MUTANTS_PER_BASE = 15
# o-2001-fixed is inc-1042-fixed with identities swapped: its mutants would repeat that base's.
MUTANT_BASES = ("inc-1042-fixed", "inc-1077-fixed")
REFUND_DESK_COMMIT = "bcc2ed7ec0276930df147173d85ac59294f5a4d1"


@dataclass(frozen=True)
class Scenario:
    """What a correct run looks like: the refunded amount and the contract set that applies."""

    amount_cents: int
    contracts_from: str


SCENARIOS = {
    "inc-1042": Scenario(8400, "inc-1042-fixed-py"),
    "inc-1077": Scenario(12600, "inc-1077-buggy-py"),
    "o-2001": Scenario(2650, "inc-1042-fixed-py"),
}


@dataclass(frozen=True)
class Mutant:
    """An `attest-engine mutate` mutant and the engine's verdict of the base's contracts."""

    mutate_id: str
    description: str
    killed: bool


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    group: str
    scenario: str
    source: str
    generator: str
    reply: str
    cassette: list[dict[str, Any]]
    trace: dict[str, Any] | None = None
    world: dict[str, Any] | None = None
    mutant: Mutant | None = None

    def digest(self) -> str:
        payload = {
            "trace": self.trace,
            "world": self.world,
            "cassette": self.cassette,
            "mutant": None
            if self.mutant is None
            else {"id": self.mutant.mutate_id, "description": self.mutant.description},
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def manifest_row(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "scenario": self.scenario,
            "source": self.source,
            "generator": self.generator,
            "sha256": self.digest(),
        }


def dollars(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def confirmation(cents: int) -> str:
    return f"Your refund of {dollars(cents)} has been processed."


def load_source(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((SOURCES / f"{name}.attest.json").read_text(encoding="utf-8"))
    return doc


def contracts_for(scenario: str) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = load_source(SCENARIOS[scenario].contracts_from)["contracts"]
    return contracts


def final_reply(fixture: dict[str, Any]) -> str:
    content = fixture["exchanges"][-1]["response"]["body"]["choices"][0]["message"]["content"]
    assert isinstance(content, str)
    return content


def final_cassette(fixture: dict[str, Any], reply: str) -> list[dict[str, Any]]:
    """The recorded final model exchange (request key and response) carrying `reply`."""
    last = copy.deepcopy(fixture["exchanges"][-1])
    last["response"]["body"]["choices"][0]["message"]["content"] = reply
    return [{"key": last["key"], "response": last["response"]}]


def _renumber(trace: dict[str, Any]) -> None:
    trace["turns"][0]["step_indices"] = list(range(len(trace["steps"])))


def _step_indices(trace: dict[str, Any], name: str) -> list[int]:
    return [
        i for i, s in enumerate(trace["steps"]) if s["type"] == "tool_call" and s["name"] == name
    ]


# --- derived clean bases -------------------------------------------------------------------


def derive_inc1077_fixed(buggy: dict[str, Any]) -> dict[str, Any]:
    """INC-1077 with the fix applied to the recording: one whole-order refund, the order's
    customer notified. Removes the extra shipping refund and corrects the recipient."""
    fixed = copy.deepcopy(buggy)
    trace = fixed["trace"]
    refunds = _step_indices(trace, "issue_refund")
    shipping = next(i for i in refunds if trace["steps"][i]["args"]["reason"] == "shipping refund")
    assert trace["steps"][shipping - 1]["type"] == "llm_call"
    del trace["steps"][shipping - 1 : shipping + 1]
    _renumber(trace)
    whole = trace["steps"][_step_indices(trace, "issue_refund")[0]]
    whole["result"]["refund_id"] = "R-0001"
    notify = trace["steps"][_step_indices(trace, "notify_customer")[0]]
    notify["args"]["customer_id"] = "C-0744"
    state = fixed["world"]["state"]
    state["refunds"] = [r for r in state["refunds"] if r["reason"] != "shipping refund"]
    state["refunds"][0]["refund_id"] = "R-0001"
    for note in state["notifications"]:
        note["customer_id"] = "C-0744"
    fixed["name"] = "inc-1077-fixed"
    return fixed


_SWAP = {
    "O-1042": "O-2001",
    "O-2001": "O-1042",
    "C-0311": "C-0520",
    "C-0520": "C-0311",
    "$84.00": "$26.50",
    "$26.50": "$84.00",
    "Ceramic pour-over set (synthetic)": "Linen apron (synthetic)",
    "Linen apron (synthetic)": "Ceramic pour-over set (synthetic)",
}
_SWAP_INT = {8400: 2650, 2650: 8400}


def _swap(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _swap(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_swap(v) for v in node]
    if isinstance(node, bool):
        return node
    if isinstance(node, int):
        return _SWAP_INT.get(node, node)
    if isinstance(node, str):
        if node in _SWAP:
            return _SWAP[node]
        # Replace every token in one pass so a swapped value is not swapped back.
        out, i = [], 0
        while i < len(node):
            token = next((t for t in _SWAP if node.startswith(t, i)), None)
            if token is None:
                out.append(node[i])
                i += 1
            else:
                out.append(_SWAP[token])
                i += len(token)
        return "".join(out)
    return node


def derive_o2001(fixed: dict[str, Any]) -> dict[str, Any]:
    """The same fixed run for the other seeded order (O-2001, $26.50, customer C-0520)."""
    derived: dict[str, Any] = _swap(fixed)
    derived["name"] = "o-2001-fixed"
    return derived


# --- benign (clean) variants ---------------------------------------------------------------


def benign_reason_wording(f: dict[str, Any], reply: str, cents: int) -> tuple[dict[str, Any], str]:
    out = copy.deepcopy(f)
    suffix = " (confirmed by customer)"
    for i in _step_indices(out["trace"], "issue_refund"):
        out["trace"]["steps"][i]["args"]["reason"] += suffix
    for record in out["world"]["state"]["refunds"]:
        record["reason"] += suffix
    return out, reply


def benign_usage_noise(f: dict[str, Any], reply: str, cents: int) -> tuple[dict[str, Any], str]:
    out = copy.deepcopy(f)
    trace = out["trace"]
    for step in trace["steps"]:
        step["metadata"]["duration_ms"] = 40
        if step["type"] == "llm_call":
            step["result"]["input_tokens"] += 13
    trace["metadata"]["latency_ms"] = 120
    return out, reply


def benign_reply_paraphrase(
    f: dict[str, Any], reply: str, cents: int
) -> tuple[dict[str, Any], str]:
    return f, f"We have processed your refund of {dollars(cents)}."


def benign_reply_reworded(f: dict[str, Any], reply: str, cents: int) -> tuple[dict[str, Any], str]:
    return f, f"{dollars(cents)} has been returned to your original payment method."


def benign_repeat_lookup(f: dict[str, Any], reply: str, cents: int) -> tuple[dict[str, Any], str]:
    """A read-only retry of the first order lookup: no effect on the world."""
    out = copy.deepcopy(f)
    trace = out["trace"]
    first = _step_indices(trace, "lookup_order")[0]
    top = max(int(s["span_id"], 16) for s in trace["steps"])
    extra = [copy.deepcopy(trace["steps"][first - 1]), copy.deepcopy(trace["steps"][first])]
    for offset, step in enumerate(extra, start=1):
        step["span_id"] = f"{top + offset:016x}"
    extra[1]["tool_call_id"] += "_retry"
    trace["steps"][first + 1 : first + 1] = extra
    _renumber(trace)
    return out, reply


BENIGN: dict[str, Callable[[dict[str, Any], str, int], tuple[dict[str, Any], str]]] = {
    "benign_reason_wording": benign_reason_wording,
    "benign_usage_noise": benign_usage_noise,
    "benign_reply_paraphrase": benign_reply_paraphrase,
    "benign_reply_reworded": benign_reply_reworded,
    "benign_repeat_lookup": benign_repeat_lookup,
}

# --- output-only faults: the reply is wrong, the tool calls and the world are right ---------


OUTPUT_FAULTS: dict[str, Callable[[int], str]] = {
    "reply_wrong_amount": lambda cents: confirmation(cents + 100),
    "reply_double_amount": lambda cents: confirmation(cents * 2),
    "reply_claims_failure": lambda cents: "Sorry, we could not process your refund.",
    "reply_empty": lambda cents: "",
    "reply_invented_credit": lambda cents: (
        f"{confirmation(cents)} We have also credited $20.00 to your account."
    ),
}

# --- assembly ---------------------------------------------------------------------------------


def _clean_bases() -> dict[str, dict[str, Any]]:
    fixed_1042 = load_source("inc-1042-fixed-py")
    return {
        "inc-1042-fixed": fixed_1042,
        "inc-1077-fixed": derive_inc1077_fixed(load_source("inc-1077-buggy-py")),
        "o-2001-fixed": derive_o2001(fixed_1042),
    }


def _scenario_of(base_id: str) -> str:
    return base_id.removesuffix("-fixed")


def _item(
    base: dict[str, Any],
    *,
    id: str,
    label: str,
    group: str,
    scenario: str,
    source: str,
    generator: str,
    reply: str | None = None,
    trace_world: dict[str, Any] | None = None,
) -> Item:
    fixture = trace_world if trace_world is not None else base
    text = final_reply(base) if reply is None else reply
    return Item(
        id=id,
        label=label,
        group=group,
        scenario=scenario,
        source=source,
        generator=generator,
        reply=text,
        cassette=final_cassette(base, text),
        trace=fixture["trace"],
        world=fixture["world"],
    )


def _verified(bases: dict[str, dict[str, Any]], engine: eng.Engine) -> None:
    """Derived bases must satisfy every contract of their scenario (they are labeled clean)."""
    for base_id, fixture in bases.items():
        contracts = contracts_for(_scenario_of(base_id))
        rows = engine.evaluate(fixture["trace"], assertions_for(contracts, fixture["world"]))
        failed = [r["assertion_id"] for r in rows if r["status"] != "pass"]
        if failed:
            raise eng.EngineError(f"clean base {base_id} violates contracts {failed}")
        fixture["contracts"] = contracts
        fixture["verification"] = {
            "expect_fail": False,
            "expected_failures": [],
            "results": [
                {"contract": r["assertion_id"], "explanation": r["explanation"], "status": "pass"}
                for r in rows
            ],
            "trace_check": fixture["verification"]["trace_check"],
            "verified": True,
        }


def assertions_for(contracts: list[dict[str, Any]], world: dict[str, Any]) -> list[dict[str, Any]]:
    """Engine assertions for drafted contracts; effect contracts carry the run's world."""
    rows = []
    for contract in contracts:
        spec = dict(contract["spec"])
        if contract["type"] == "effect":
            spec["world"] = world
        rows.append({"assertion_id": contract["id"], "type": contract["type"], "spec": spec})
    return rows


def build_items(engine_path: Path, engine: eng.Engine) -> list[Item]:
    """Materialize every item. Order is fixed so reruns are identical."""
    bases = _clean_bases()
    _verified(bases, engine)
    items: list[Item] = []
    prefix = load_source("inc-1042-prefix-py")
    buggy = load_source("inc-1077-buggy-py")
    for name, fixture, scenario, kind, path in (
        (
            "inc-1042-prefix",
            prefix,
            "inc-1042",
            "double_refund",
            "regression/pre-fix-fixtures/py/inc-1042.attest.json",
        ),
        (
            "inc-1077-buggy",
            buggy,
            "inc-1077",
            "over_refund_wrong_recipient",
            "py/tests/attest/fixtures/inc-1077.attest.json",
        ),
    ):
        items.append(
            _item(
                fixture,
                id=f"real/{name}",
                label=f"fault:{kind}",
                group="real-incident",
                scenario=scenario,
                source=f"refund-desk@{REFUND_DESK_COMMIT[:7]}:{path}",
                generator=f"cp {path} corpus/sources/{name}-py.attest.json",
            )
        )
    for base_id, base in bases.items():
        scenario = _scenario_of(base_id)
        cents = SCENARIOS[scenario].amount_cents
        origin = (
            f"refund-desk@{REFUND_DESK_COMMIT[:7]}:py/tests/attest/fixtures/inc-1042.attest.json"
            if base_id == "inc-1042-fixed"
            else f"derived from {base_id.replace('-fixed', '')} sources"
        )
        items.append(
            _item(
                base,
                id=f"clean/{base_id}",
                label="clean",
                group="clean-base",
                scenario=scenario,
                source=origin,
                generator=f"python -m corpus_bench show clean/{base_id}",
            )
        )
        for name, transform in BENIGN.items():
            variant, reply = transform(base, final_reply(base), cents)
            items.append(
                _item(
                    base,
                    id=f"clean/{base_id}+{name}",
                    label="clean",
                    group="clean-variant",
                    scenario=scenario,
                    source=f"clean/{base_id}",
                    generator=f"python -m corpus_bench show clean/{base_id}+{name}",
                    reply=reply,
                    trace_world=variant,
                )
            )
        for name, make_reply in OUTPUT_FAULTS.items():
            items.append(
                _item(
                    base,
                    id=f"output/{base_id}+{name}",
                    label=f"fault:{name}",
                    group="output-only",
                    scenario=scenario,
                    source=f"clean/{base_id}",
                    generator=f"python -m corpus_bench show output/{base_id}+{name}",
                    reply=make_reply(cents),
                )
            )
    items.extend(_mutant_items(engine_path, bases))
    return items


def _mutant_items(engine_path: Path, bases: dict[str, dict[str, Any]]) -> list[Item]:
    items: list[Item] = []
    with tempfile.TemporaryDirectory() as tmp:
        for base_id in MUTANT_BASES:
            base = bases[base_id]
            fixture = copy.deepcopy(base)
            fixture["name"] = base_id
            path = Path(tmp) / f"{base_id}.attest.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            report = eng.mutate(engine_path, path, seed=MUTATE_SEED, max_mutants=MUTANTS_PER_BASE)
            command = (
                f"attest-engine mutate {base_id}.attest.json --json --seed={MUTATE_SEED} "
                f"--max-mutants={MUTANTS_PER_BASE}"
            )
            for row in report["mutants"]:
                if row["status"] not in ("killed", "survived"):
                    raise eng.EngineError(f"mutant {row['id']} is {row['status']}: not scorable")
                items.append(
                    Item(
                        id=f"mutant/{row['id']}",
                        label=f"fault:{row['operator']}",
                        group="mutant",
                        scenario=_scenario_of(base_id),
                        source=f"clean/{base_id}",
                        generator=command,
                        reply=final_reply(base),
                        cassette=final_cassette(base, final_reply(base)),
                        mutant=Mutant(row["id"], row["description"], row["status"] == "killed"),
                    )
                )
    return items


# --- manifest ---------------------------------------------------------------------------------


def manifest_document(items: list[Item]) -> dict[str, Any]:
    return {
        "engine": eng.load_lock()["version"],
        "refund_desk_commit": REFUND_DESK_COMMIT,
        "mutate": {
            "seed": MUTATE_SEED,
            "max_mutants_per_base": MUTANTS_PER_BASE,
            "bases": list(MUTANT_BASES),
        },
        "items": [item.manifest_row() for item in items],
    }


def write_manifest(items: list[Item]) -> None:
    text = json.dumps(manifest_document(items), indent=2, sort_keys=True) + "\n"
    MANIFEST_PATH.write_text(text, encoding="utf-8")


def verify_manifest(items: list[Item]) -> None:
    """Fail when the rebuilt corpus differs from the committed manifest."""
    committed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rebuilt = manifest_document(items)
    if committed == rebuilt:
        return
    old = {row["id"]: row for row in committed["items"]}
    new = {row["id"]: row for row in rebuilt["items"]}
    changed = sorted(i for i in old.keys() & new.keys() if old[i] != new[i])
    raise eng.EngineError(
        "corpus differs from corpus/manifest.json "
        f"(added {sorted(new.keys() - old.keys())[:5]}, "
        f"removed {sorted(old.keys() - new.keys())[:5]}, "
        f"changed {changed[:5]}); review, then run `make corpus-manifest`"
    )
