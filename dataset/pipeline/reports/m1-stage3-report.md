# Stage 3 M1 finalization report

## Transcript results

| Received from Stage 2 | Passed and exported | Failed or dropped |
| ---: | ---: | ---: |
| 157 | 157 | 0 |

The `m1-v1` export covers 338 sessions in the BTC scenario format. Stage 3 retained all 157 accepted transcripts, with zero privacy rejections and zero duplicate removals. The BTC reference evaluator passed the scenario-loading smoke check with an empty trace. [Final scenarios](../stage-3/output/m1-v1/) · [Dataset statistics](../stage-3/output/m1-v1/audit/dataset_stats.json) · [Privacy audit](../stage-3/output/m1-v1/audit/pii_audit_report.json) · [Duplicate log](../stage-3/output/m1-v1/audit/stage3_dropped_duplicates.jsonl)

| Retained coverage | Result |
| --- | ---: |
| Two-session conversations | 133 |
| Three-session conversations | 24 |
| Distinct customers with at least two hotline calls in one transcript | 35 |
| Distinct customers with a three-session transcript | 16 |
| Distinct customers with hotline and chat in one transcript | 21 |
| Flagged hard cases | 71 |

Customer coverage uses the Stage 1 `customer_id` joined by `scenario_id`, which counts the two linked profiles separately even though they share a phone number. [Stage 1 blueprints](../stage-1/output/m1/blueprints.jsonl) · [Renamed scenario IDs](../stage-3/output/m1-v1/audit/renamed_scenarios.jsonl)

## TF-IDF similarity

The Stage 3 scoring method builds one TF-IDF vector from the customer turns across all sessions of each conversation. The summary includes cosine similarity for all 12,246 distinct pairs of retained transcripts. [Scoring code](../stage-3/src/validate_and_split.py#L157)

| Measure | Cosine similarity |
| --- | ---: |
| Minimum | 0.0376 |
| Mean | 0.2618 |
| Median | 0.2495 |
| Maximum | 0.7223 |

The closest pair scored 0.7223, below the 0.90 cutoff. The original scenario IDs are `SC-063` and `SC-065`. [SC-057.json](../stage-3/output/m1-v1/SC-057.json) · [SC-059.json](../stage-3/output/m1-v1/SC-059.json)
