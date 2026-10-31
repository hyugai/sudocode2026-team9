# Synthetic Scenario → Agent → Evaluation Flow

```text
                SYNTHETIC SCENARIO
               "What should be true"
                        │
                        │
                        │  Defines:
                        │  - known facts from previous sessions
                        │  - must_carry_over
                        │  - must_not_ask
                        │  - valid business ground truth
                        │  - expected tool calls
                        │  - expected outcome
                        │
                        ▼
                   AI AGENT RUN
               "What actually happened"
                        │
                        │
                        │  Produces:
                        │  - responses
                        │  - questions
                        │  - memory retrieval
                        │  - Call Brief
                        │  - tool calls
                        │  - memory updates
                        │  - final task result
                        │
                        ▼
                    EVALUATOR
          "Compare actual vs expected behavior"
                        │
        ┌───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼
       RQR             CCR             TSR              HR
Repeat-Question   Context Carryover  Task Success   Hallucination
     Rate              Rate             Rate             Rate
        │               │               │               │
        │               │               │               │
        ▼               ▼               ▼               ▼
Did the agent     Did the agent     Did the agent     Did the agent
ask for facts     correctly reuse   complete the      make false
that were         relevant facts    required task?    verifiable
already known?    from earlier                        claims?
                  sessions?
        │               │               │               │
        ▼               ▼               ▼               ▼
 Lower is better   Higher is better Higher is better  Lower is better

        └───────────────┬───────────────┴───────────────┘
                        ▼
              PERFORMANCE MEASUREMENT
                        │
                        │
                        │  Compare:
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
      BASELINE SYSTEM        FULL SYSTEM
       no memory             memory + harness
              │                   │
              └─────────┬─────────┘
                        ▼
             QUANTITATIVE IMPROVEMENT
```

## Key idea

```text
Synthetic scenario
= reference expectations

Agent run
= actual behavior

Evaluator
= checks how well actual behavior satisfies those expectations

Baseline vs Full System
= proves whether memory/harness actually improves performance
```

## Metric directions

```text
RQR ↓
CCR ↑
TSR ↑
HR  ↓
```

- **RQR — Repeat-Question Rate:** lower is better.
- **CCR — Context Carryover Rate:** higher is better.
- **TSR — Task Success Rate:** higher is better.
- **HR — Hallucination Rate:** lower is better.
