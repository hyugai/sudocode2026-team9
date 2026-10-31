# `personas.jsonl` — Key Explanation

## Purpose

`personas.jsonl` defines the **customer archetypes** used in synthetic case generation. A persona contains only relatively stable customer characteristics and common behaviors.

Journey-specific values such as the customer's current goal or state are intentionally **not stored here** because they depend on the concrete case. They should be assigned later when building `case_specs.jsonl`.

## General format

```json
{
  "persona_id": "",
  "level": "",
  "name": "",
  "source_label": "",
  "description": "",
  "characteristics": [],
  "typical_behaviors": []
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `persona_id` | Lets generated cases and other files reference the persona reliably. |
| `level` | Indicates whether the persona is required at M1 or added at M2. |
| `name` | Provides a stable machine-readable name for sampling, filtering, and generation. |
| `source_label` | Preserves the original wording from the project brief for traceability. |
| `description` | Gives a concise explanation of the customer archetype. |
| `characteristics` | Defines relatively stable traits that shape the customer's behavior. |
| `typical_behaviors` | Defines common observable actions that the transcript generator can realize naturally. |

### Derived later

The following values should be determined in the concrete case specification instead of stored in the persona:

```text
customer_goal
customer_state
purchase_state
expected_outcome
```
