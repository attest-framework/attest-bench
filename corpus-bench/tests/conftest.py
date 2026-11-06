from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from corpus_bench import corpus
from corpus_bench import engine as eng


@pytest.fixture(scope="session")
def engine_path() -> Path:
    """The pinned engine; a missing one fails the test (`make corpus-engine` builds it)."""
    return eng.resolve_engine()


@pytest.fixture(scope="session")
def items(engine_path: Path) -> Iterator[list[corpus.Item]]:
    with eng.Engine(engine_path) as engine:
        yield corpus.build_items(engine_path, engine)
