"""A detector's decision on one corpus item."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    flagged: bool
    detail: str
