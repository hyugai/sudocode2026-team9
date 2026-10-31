# `difficult_scenarios.jsonl` — Key Explanation

## Purpose

`difficult_scenarios.jsonl` defines **optional complications** that can be added to a synthetic case. These scenarios test whether the system handles changes, conflicts, expired information, or missing knowledge correctly.

Only primitive scenario requirements are stored. Summary properties such as `requires_prior_state` are intentionally not stored because they can be derived from `required_setup` during case generation.

## General format

```json
{
  "difficulty_id": "",
  "name": "",
  "source_label": "",
  "description": "",
  "required_setup": [],
  "event": "",
  "expected_behavior": [],
  "forbidden_behavior": [],
  "evaluation_focus": []
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `difficulty_id` | Lets generated cases and other files reference the difficult scenario reliably. |
| `name` | Provides a stable machine-readable name for sampling, filtering, and generation. |
| `source_label` | Preserves the original wording from the project brief for traceability. |
| `description` | Gives a concise explanation of the complication. |
| `required_setup` | Defines the state or conditions that must exist before the difficult event can happen logically. |
| `event` | Defines the concrete complication that should occur during the journey. |
| `expected_behavior` | Defines how the AI Agent Harness should correctly handle the complication. |
| `forbidden_behavior` | Defines behaviors that would make the handling incorrect or unsafe. |
| `evaluation_focus` | Identifies which capabilities or evaluation areas the scenario is intended to test. |

### Derived later

A property such as:

```text
requires_prior_state
```

should be derived from `required_setup`.

Example:

```text
required_setup contains previous_fact_exists
→ requires_prior_state = true
```
