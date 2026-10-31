# `compatibility_rules.jsonl` — Key Explanation

## Purpose

`compatibility_rules.jsonl` defines the **validation rules** used to determine whether selected dimensions can be combined into a valid synthetic case.

It does not generate transcript content itself. Instead, it checks whether the chosen Case Study, Persona, Difficult Scenario, Journey Pattern, Customer, and Business Ground Truth satisfy the conditions required by the scenario.

The rules are applied **after derived properties are calculated** and **before the final `case_spec` is created**.

```text
dimension files
↓
derive properties
↓
compatibility rules
↓
case specification
↓
Vietnamese transcript generation
```

## General format

```json
{
  "rule_id": "",
  "name": "",
  "description": "",
  "when": {},
  "require": {},
  "forbid": {},
  "action_on_failure": ""
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `rule_id` | Gives each compatibility rule a unique identifier for debugging, validation, and reporting. |
| `name` | Provides a stable machine-readable name for the rule. |
| `description` | Explains what combination or constraint the rule is enforcing. |
| `when` | Defines when the rule should be activated, such as when a specific case study, persona, or difficult scenario is selected. |
| `require` | Defines conditions that must be true for the selected combination to be valid. |
| `forbid` | Defines conditions or combinations that must not occur. |
| `action_on_failure` | Defines what the generator should do when the rule fails, such as reject, resample, or regenerate the case. |

## Example

```json
{
  "rule_id": "R001",
  "name": "cross_channel_case_requires_multiple_channels",
  "description": "CASE_02 requires a journey containing more than one communication channel or platform.",
  "when": {
    "case_id": "CASE_02"
  },
  "require": {
    "cross_channel": true
  },
  "forbid": {},
  "action_on_failure": "resample_journey_pattern"
}
```

Another example:

```json
{
  "rule_id": "R002",
  "name": "expired_promotion_requires_prior_promotion",
  "description": "The expired-promotion difficult scenario requires a previous promotion that is no longer valid in the later session.",
  "when": {
    "difficulty_id": "D03"
  },
  "require": {
    "session_count_min": 2,
    "previous_promotion_exists": true,
    "current_session_after_promotion_expiry": true
  },
  "forbid": {},
  "action_on_failure": "resample_business_context"
}
```

## Design note

Compatibility rules should reference **derived properties** such as:

```text
session_count
cross_channel
handoff
requires_prior_state
```

rather than storing those summary values redundantly inside the source dimension files.
