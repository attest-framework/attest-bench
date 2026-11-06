"""Approach (b): pytest with a VCR-style cassette and output assertions.

The cassette holds the recorded final model exchange of a run. A test replays it by request
key and asserts on the reply text, as the refund-desk output-only tests do. It re-runs no
agent, so it sees the reply and nothing else. A cassette miss fails loudly.
"""

from __future__ import annotations

import pytest

from corpus_bench import approach_b_checks, corpus
from corpus_bench.verdict import Verdict


class _Collector:
    """Maps each test to its corpus item and records pass or fail."""

    def __init__(self, items: list[corpus.Item]) -> None:
        self.items = items
        self.ids: dict[str, str] = {}
        self.failed: dict[str, str] = {}
        self.passed: set[str] = set()

    def pytest_generate_tests(self, metafunc: pytest.Metafunc) -> None:
        if "item" in metafunc.fixturenames:
            metafunc.parametrize("item", self.items, ids=[i.id for i in self.items])

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for test in items:
            callspec = getattr(test, "callspec", None)
            if callspec is not None:
                self.ids[test.nodeid] = callspec.params["item"].id

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call":
            item_id = self.ids[report.nodeid]
            if report.failed:
                self.failed[item_id] = str(report.longrepr).strip().splitlines()[-1]
            else:
                self.passed.add(item_id)
        elif report.failed:
            raise RuntimeError(f"{report.nodeid} errored in {report.when}: {report.longrepr}")


def run(items: list[corpus.Item]) -> dict[str, Verdict]:
    collector = _Collector(items)
    code = pytest.main(
        [
            str(approach_b_checks.__file__),
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-header",
            "--disable-warnings",
            "-o",
            "python_files=approach_b_checks.py",
        ],
        plugins=[collector],
    )
    if code not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
        raise RuntimeError(f"pytest exited {code}")
    verdicts = {i: Verdict(True, d) for i, d in collector.failed.items()}
    verdicts.update({i: Verdict(False, "") for i in collector.passed})
    missing = {item.id for item in items} - verdicts.keys()
    if missing:
        raise RuntimeError(f"no test ran for {sorted(missing)[:5]}")
    return verdicts
