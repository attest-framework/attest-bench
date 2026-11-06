"""A VCR-style cassette: recorded model responses replayed by request key."""

from __future__ import annotations

from typing import Any


class CassetteMissError(LookupError):
    """The request key has no recorded response: the cassette would need a live call."""


def _key(key: dict[str, Any]) -> str:
    return f"{key['model']}|{key['prompt_hash']}|{key['tool_schema_hash']}"


class Cassette:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._by_key = {_key(e["key"]): e["response"] for e in entries}

    def replay(self, key: dict[str, Any]) -> str:
        """The recorded assistant message for `key`; raises CassetteMissError when none matches."""
        response = self._by_key.get(_key(key))
        if response is None:
            raise CassetteMissError(f"no recorded response for {key}")
        content = response["body"]["choices"][0]["message"]["content"]
        assert isinstance(content, str)
        return content
