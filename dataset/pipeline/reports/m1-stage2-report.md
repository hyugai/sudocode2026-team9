# Stage 2 M1 transcript report

## Generation and Python format check

Stage 2 generated one Vietnamese customer transcript per Stage 1 blueprint. The saved M1 generation run covers 300 sessions, and each journey passed on its first attempt. [Generation output](../stage-2/phase-2/output/candidates.jsonl)

| Journeys checked | Passed | Failed | Pass rate |
| ---: | ---: | ---: | ---: |
| 140 | 140 | 0 | 100% |

The Python check verifies the planned session keys, two to five nonempty single-line customer turns per session, and the absence of speaker-label prefixes and unfilled placeholders. [Generation workflow](../stage-2.md#generate-candidates)

## DeepEval validation

DeepEval uses Gemma to check session goals, required facts, continuity, and the customer-only speaker role. A journey passes when it receives a `pass` verdict and scores at least 0.7 on both persona fit and Vietnamese naturalness. [Validation workflow](../stage-2.md#validate-candidates)

| Journeys checked | Passed | Failed | Pass rate |
| ---: | ---: | ---: | ---: |
| 140 | 124 | 16 | 88.6% |

The accepted journeys cover 266 sessions. [Accepted transcripts](../stage-2/phase-3/output/transcripts.jsonl)

### Failure categories

Each failed journey appears once under a primary category assigned from the saved judge reason. Some reasons cite more than one issue. [Judge report](../stage-2/phase-3/output/judge-report.jsonl)

| Primary category | Journeys | Scenario IDs | What the judge cited |
| --- | ---: | --- | --- |
| Session goal or expected outcome | 7 | `SC-005`, `SC-016`, `SC-022`, `SC-035`, `SC-072`, `SC-073`, `SC-092` | A turn missed the planned callback, stopped short of placing the order, or assumed a different outcome. |
| Missing or incorrect required facts | 3 | `SC-015`, `SC-023`, `SC-053` | A required payment method or delivery address was absent, or the address differed from the blueprint. |
| Continuity or sequence | 2 | `SC-012`, `SC-024` | A turn referred to a prior interaction or introduced a fact out of sequence. |
| Speaker role or dialogue flow | 1 | `SC-045` | The judge interpreted part of the customer's dialogue as the agent's response. |
| Repeated or restricted topic | 3 | `SC-104`, `SC-123`, `SC-129` | The judge cited `must_not_ask` when a customer repeated a question or mentioned the product. |
| **Total** | **16** | | |

The BTC evaluator uses `must_not_ask` to score the agent's questions. In the last category, the judge cited it for customer turns. These three verdicts warrant review of the cited rule and any separate issues in the rationale. The counts above reflect the saved verdicts. [BTC scoring rule](../btc/BTC-cap-nhat-11-2026/eval/reference_eval.py#L85)
