# Corpus provenance

Everything here is synthetic. The company, customers, orders and payments are invented by [refund-desk](https://github.com/attest-framework/refund-desk) (Apache-2.0); no real data and no paid model call is involved.

`sources/` holds three fixtures copied unchanged from refund-desk at commit `bcc2ed7ec0276930df147173d85ac59294f5a4d1`:

| File | Origin in refund-desk | Behavior |
|---|---|---|
| `inc-1042-fixed-py.attest.json` | `py/tests/attest/fixtures/inc-1042.attest.json` | INC-1042 request, fixed agent: one refund |
| `inc-1042-prefix-py.attest.json` | `regression/pre-fix-fixtures/py/inc-1042.attest.json` | INC-1042 before the fix: two refunds |
| `inc-1077-buggy-py.attest.json` | `py/tests/attest/fixtures/inc-1077.attest.json` | INC-1077: refunds above the order amount, notification to the wrong customer |

The TypeScript fixtures at the same commit differ from these only in `source.command`, so they are not copied.

Every other run is built from these by a named transform in `src/corpus_bench/corpus.py` or by `attest-engine mutate`. `manifest.json` lists each run with its label, source, generator command and the sha256 of its materialized trace, world and cassette; `make corpus-bench` fails when a rebuilt corpus differs from it. Print one run with `uv run python -m corpus_bench show <id>` from `corpus-bench/`.
