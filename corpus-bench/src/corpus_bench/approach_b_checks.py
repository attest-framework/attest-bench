"""The output assertions of approach (b); `approach_b.run` collects them and parametrizes `item`.

Every item gets the assertions a refund-desk test author writes from the customer message:
the reply states the refunded amount, does not say the refund failed and does not state
double the amount.
"""

from __future__ import annotations

from corpus_bench import corpus
from corpus_bench.cassette import Cassette


def test_reply_states_amount_and_no_failure(item: corpus.Item) -> None:
    cents = corpus.SCENARIOS[item.scenario].amount_cents
    reply = Cassette(item.cassette).replay(item.cassette[0]["key"])

    assert f"refund of {corpus.dollars(cents)}" in reply
    assert "could not" not in reply
    assert corpus.dollars(cents * 2) not in reply
