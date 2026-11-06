# Fault-corpus results

Engine: attest-engine 1.1.0-rc.3. Corpus: 65 labeled runs, 47 faulty and 18 clean. All numbers below come from `make corpus-bench`.

## Detection

| Approach | True-positive rate | False-positive rate | Cost (USD) | Model calls |
|---|---|---|---|---|
| (a) attest contracts + effects | 11/47 (23.4%) | 3/18 (16.7%) | $0.00 | 0 |
| (b) pytest + cassette, output assertions | 12/47 (25.5%) | 3/18 (16.7%) | $0.00 | 0 |
| (a) or (b) flags | 23/47 (48.9%) | 6/18 (33.3%) | $0.00 | 0 |
| (c) judge-only | not run | not run | not run | not run |

True-positive rate: faulty runs flagged / faulty runs. False-positive rate: clean runs flagged / clean runs. Wall time is in `timings.json` and varies by run.

## True-positive rate by fault group

| Fault group | Runs | (a) attest | (b) output assertions | (a) or (b) |
|---|---|---|---|---|
| real incident runs (INC-1042 before the fix, INC-1077) | 2 | 2/2 (100.0%) | 0/2 (0.0%) | 2/2 (100.0%) |
| output-only faults (wrong reply, correct behavior) | 15 | 0/15 (0.0%) | 12/15 (80.0%) | 12/15 (80.0%) |
| behavior mutants (`attest-engine mutate`) | 30 | 9/30 (30.0%) | 0/30 (0.0%) | 9/30 (30.0%) |

## True-positive rate by fault kind

| Fault kind | Runs | (a) attest | (b) output assertions |
|---|---|---|---|
| `alter_world_effect` | 13 | 0/13 (0.0%) | 0/13 (0.0%) |
| `double_refund` | 1 | 1/1 (100.0%) | 0/1 (0.0%) |
| `drop_tool_call` | 3 | 2/3 (66.7%) | 0/3 (0.0%) |
| `duplicate_tool_call` | 5 | 5/5 (100.0%) | 0/5 (0.0%) |
| `inject_tool_error` | 3 | 0/3 (0.0%) | 0/3 (0.0%) |
| `over_refund_wrong_recipient` | 1 | 1/1 (100.0%) | 0/1 (0.0%) |
| `perturb_argument` | 4 | 0/4 (0.0%) | 0/4 (0.0%) |
| `reorder_tool_calls` | 2 | 2/2 (100.0%) | 0/2 (0.0%) |
| `reply_claims_failure` | 3 | 0/3 (0.0%) | 3/3 (100.0%) |
| `reply_double_amount` | 3 | 0/3 (0.0%) | 3/3 (100.0%) |
| `reply_empty` | 3 | 0/3 (0.0%) | 3/3 (100.0%) |
| `reply_invented_credit` | 3 | 0/3 (0.0%) | 0/3 (0.0%) |
| `reply_wrong_amount` | 3 | 0/3 (0.0%) | 3/3 (100.0%) |

## False positives by clean variant

| Clean run | Runs | (a) attest flags | (b) output assertions flag |
|---|---|---|---|
| unmodified clean runs | 3 | 0/3 (0.0%) | 0/3 (0.0%) |
| `benign_reason_wording` | 3 | 0/3 (0.0%) | 0/3 (0.0%) |
| `benign_repeat_lookup` | 3 | 3/3 (100.0%) | 0/3 (0.0%) |
| `benign_reply_paraphrase` | 3 | 0/3 (0.0%) | 0/3 (0.0%) |
| `benign_reply_reworded` | 3 | 0/3 (0.0%) | 3/3 (100.0%) |
| `benign_usage_noise` | 3 | 0/3 (0.0%) | 0/3 (0.0%) |

## Runs each approach misses

### (a) attest contracts + effects: 36 missed

- `mutant/inc-1042-fixed:alter_world_effect:notifications.0.drop`
- `mutant/inc-1042-fixed:alter_world_effect:notifications.0.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:orders.0.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:orders.1.change.amount_cents`
- `mutant/inc-1042-fixed:alter_world_effect:orders.1.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:refunds.0.change.amount_cents`
- `mutant/inc-1042-fixed:alter_world_effect:refunds.0.drop`
- `mutant/inc-1042-fixed:inject_tool_error:3`
- `mutant/inc-1042-fixed:perturb_argument:3.reason`
- `mutant/inc-1042-fixed:perturb_argument:5.order_id`
- `mutant/inc-1077-fixed:alter_world_effect:orders.0.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:orders.1.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:orders.2.drop`
- `mutant/inc-1077-fixed:alter_world_effect:orders.2.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:refunds.0.drop`
- `mutant/inc-1077-fixed:alter_world_effect:refunds.0.duplicate`
- `mutant/inc-1077-fixed:drop_tool_call:1`
- `mutant/inc-1077-fixed:inject_tool_error:1`
- `mutant/inc-1077-fixed:inject_tool_error:5`
- `mutant/inc-1077-fixed:perturb_argument:5.order_id`
- `mutant/inc-1077-fixed:perturb_argument:5.reason`
- `output/inc-1042-fixed+reply_claims_failure`
- `output/inc-1042-fixed+reply_double_amount`
- `output/inc-1042-fixed+reply_empty`
- `output/inc-1042-fixed+reply_invented_credit`
- `output/inc-1042-fixed+reply_wrong_amount`
- `output/inc-1077-fixed+reply_claims_failure`
- `output/inc-1077-fixed+reply_double_amount`
- `output/inc-1077-fixed+reply_empty`
- `output/inc-1077-fixed+reply_invented_credit`
- `output/inc-1077-fixed+reply_wrong_amount`
- `output/o-2001-fixed+reply_claims_failure`
- `output/o-2001-fixed+reply_double_amount`
- `output/o-2001-fixed+reply_empty`
- `output/o-2001-fixed+reply_invented_credit`
- `output/o-2001-fixed+reply_wrong_amount`

### (b) pytest + cassette, output assertions: 35 missed

- `mutant/inc-1042-fixed:alter_world_effect:notifications.0.drop`
- `mutant/inc-1042-fixed:alter_world_effect:notifications.0.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:orders.0.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:orders.1.change.amount_cents`
- `mutant/inc-1042-fixed:alter_world_effect:orders.1.duplicate`
- `mutant/inc-1042-fixed:alter_world_effect:refunds.0.change.amount_cents`
- `mutant/inc-1042-fixed:alter_world_effect:refunds.0.drop`
- `mutant/inc-1042-fixed:drop_tool_call:3`
- `mutant/inc-1042-fixed:drop_tool_call:5`
- `mutant/inc-1042-fixed:duplicate_tool_call:1`
- `mutant/inc-1042-fixed:duplicate_tool_call:3`
- `mutant/inc-1042-fixed:inject_tool_error:3`
- `mutant/inc-1042-fixed:perturb_argument:3.reason`
- `mutant/inc-1042-fixed:perturb_argument:5.order_id`
- `mutant/inc-1042-fixed:reorder_tool_calls:1-3`
- `mutant/inc-1077-fixed:alter_world_effect:orders.0.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:orders.1.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:orders.2.drop`
- `mutant/inc-1077-fixed:alter_world_effect:orders.2.duplicate`
- `mutant/inc-1077-fixed:alter_world_effect:refunds.0.drop`
- `mutant/inc-1077-fixed:alter_world_effect:refunds.0.duplicate`
- `mutant/inc-1077-fixed:drop_tool_call:1`
- `mutant/inc-1077-fixed:duplicate_tool_call:1`
- `mutant/inc-1077-fixed:duplicate_tool_call:5`
- `mutant/inc-1077-fixed:duplicate_tool_call:7`
- `mutant/inc-1077-fixed:inject_tool_error:1`
- `mutant/inc-1077-fixed:inject_tool_error:5`
- `mutant/inc-1077-fixed:perturb_argument:5.order_id`
- `mutant/inc-1077-fixed:perturb_argument:5.reason`
- `mutant/inc-1077-fixed:reorder_tool_calls:5-7`
- `output/inc-1042-fixed+reply_invented_credit`
- `output/inc-1077-fixed+reply_invented_credit`
- `output/o-2001-fixed+reply_invented_credit`
- `real/inc-1042-prefix`
- `real/inc-1077-buggy`

## Clean runs each approach flags

### (a) attest contracts + effects: 3 flagged

- `clean/inc-1042-fixed+benign_repeat_lookup`
- `clean/inc-1077-fixed+benign_repeat_lookup`
- `clean/o-2001-fixed+benign_repeat_lookup`

### (b) pytest + cassette, output assertions: 3 flagged

- `clean/inc-1042-fixed+benign_reply_reworded`
- `clean/inc-1077-fixed+benign_reply_reworded`
- `clean/o-2001-fixed+benign_reply_reworded`
