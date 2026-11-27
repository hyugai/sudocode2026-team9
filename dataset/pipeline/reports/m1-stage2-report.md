# Stage 2 M1 transcript report

## Generation and Python format check

`Qwen3-30B-A3B Q4_K_M` generated one Vietnamese customer transcript per Stage 1 blueprint. The saved M1 generation run covers 388 sessions, and each conversation passed the Python format check on its first attempt. [Generation output](../stage-2/phase-1/output/m1/candidates.jsonl) · [Generation input ZIP](../stage-2/phase-1/stage2-m1-input.zip)

| Conversations checked | Passed | Failed | Pass rate |
| ---: | ---: | ---: | ---: |
| 180 | 180 | 0 | 100% |

The Python check verifies the planned session keys, two to five nonempty single-line customer turns per session, and the absence of speaker-label prefixes and unfilled placeholders. [Generation code](../stage-2/phase-1/src/generation.py)

## DeepEval validation

DeepEval uses `Gemma 4 12B IT QAT Q4_0` to check session goals, required facts, continuity, and the customer-only speaker role. A conversation passes when it receives a `pass` verdict and scores at least 0.7 on both persona fit and Vietnamese naturalness. [Judge code](../stage-2/phase-2/src/judge_metric.py) · [Validation input ZIP](../stage-2/phase-2/stage2-m1-validation-input.zip)

| Conversations checked | Passed | Failed | Review | Pass rate |
| ---: | ---: | ---: | ---: | ---: |
| 180 | 157 | 21 | 2 | 87.2% |

The accepted conversations cover 338 sessions. The two `review` records, `SC-041` and `SC-127`, came from judge responses with a score of 3.0 outside the required 0–1 range. Numeric score summaries cover the other 178 conversations. [Accepted transcripts](../stage-2/phase-2/output/m1/transcripts.jsonl) · [Judge report](../stage-2/phase-2/output/m1/judge-report.jsonl)

### Score distributions

#### All scored conversations

| Metric | Scores | Mean | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 178 | 0.9618 | 1.0000 | 0.0000 | 1.0000 |
| `journey_continuity` | 178 | 0.9579 | 1.0000 | 0.5000 | 1.0000 |
| `persona_fit` | 178 | 0.9865 | 1.0000 | 0.6000 | 1.0000 |
| `vietnamese_naturalness` | 178 | 0.9781 | 1.0000 | 0.8000 | 1.0000 |

#### Accepted conversations

| Metric | Scores | Mean | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 157 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `journey_continuity` | 157 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `persona_fit` | 157 | 0.9981 | 1.0000 | 0.8000 | 1.0000 |
| `vietnamese_naturalness` | 157 | 0.9885 | 1.0000 | 0.8000 | 1.0000 |

#### Rejected conversations with scores

| Metric | Scores | Mean | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 21 | 0.6762 | 0.8000 | 0.0000 | 1.0000 |
| `journey_continuity` | 21 | 0.6429 | 0.5000 | 0.5000 | 1.0000 |
| `persona_fit` | 21 | 0.9000 | 1.0000 | 0.6000 | 1.0000 |
| `vietnamese_naturalness` | 21 | 0.9000 | 0.9000 | 0.8000 | 1.0000 |

### Failure categories

Each failed conversation appears once under a primary category assigned from the saved judge reason. Some reasons cite more than one issue. [Judge report](../stage-2/phase-2/output/m1/judge-report.jsonl)

| Primary category | Conversations | Scenario IDs | What the judge cited |
| --- | ---: | --- | --- |
| Missing or incorrect required facts | 7 | `SC-011`, `SC-019`, `SC-037`, `SC-100`, `SC-132`, `SC-166`, `SC-175` | A callback time, address, or payment method was missing or incorrect, or the shop and competitor prices were swapped. |
| Session goal or expected outcome | 6 | `SC-023`, `SC-038`, `SC-107`, `SC-109`, `SC-129`, `SC-151` | The dialogue did not complete a planned purchase, deferral, order check, or identity confirmation. |
| Speaker role or perspective | 5 | `SC-086`, `SC-141`, `SC-143`, `SC-161`, `SC-171` | The judge read a turn as the agent presenting a quote or confirming the customer's details. |
| Unplanned facts or wrong session | 3 | `SC-145`, `SC-176`, `SC-178` | A customer added an unplanned item or size change, or raised a later session's question early. |
| **Total** | **21** | | |
