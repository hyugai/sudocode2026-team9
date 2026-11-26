# Stage 3 M1 finalization report

## Transcript results

| Received from Stage 2 | Passed and exported | Failed or dropped |
| ---: | ---: | ---: |
| 124 | 124 | 0 |

The exports cover 266 sessions in the BTC scenario format. The audits recorded zero privacy rejections and zero duplicate removals. [Dataset statistics](../stage-3/output/audit/dataset_stats.json) · [Privacy audit](../stage-3/output/audit/pii_audit_report.json) · [Duplicate log](../stage-3/output/audit/stage3_dropped_duplicates.jsonl)

## TF-IDF similarity

The summary uses the Stage 3 scoring method. It builds one TF-IDF vector from the customer turns across all sessions of each journey, then computes cosine similarity for all 7,626 unique pairs. [Scoring code](../stage-3/src/validate_and_split.py#L157)

| Measure | Cosine similarity |
| --- | ---: |
| Minimum | 0.0338 |
| Mean | 0.2371 |
| Median | 0.2193 |
| Maximum | 0.8221 |

`SC-133` and `SC-135` were the closest pair. No pair exceeded the 0.90 cutoff.
