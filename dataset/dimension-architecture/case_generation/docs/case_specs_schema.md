# `case_specs.jsonl` — Key Explanation

## Purpose

`case_specs.jsonl` defines the **fully instantiated synthetic case** that is passed to the LLM for transcript generation.

A case specification combines the selected dimensions and resolves them into concrete session-by-session facts, events, expected actions, and evaluation ground truth.

The Case Specification should decide **what must happen**. The LLM should only decide **how it is naturally expressed in Vietnamese**.

```text
Case Study
× Persona
× Optional Difficult Scenario
× Journey Pattern
× Customer
× Business Ground Truth
× Expected Outcome
↓
Compatibility Rules
↓
Case Specification
↓
LLM generates Vietnamese transcript
```

## General format

```json
{
  "case_spec_id": "",
  "case_id": "",
  "persona_id": "",
  "difficulty_id": null,
  "journey_pattern_id": "",
  "customer_id": "",

  "business_context": {
    "product_ids": [],
    "promotion_ids": [],
    "policy_ids": []
  },

  "initial_state": {
    "known_facts": {},
    "unknown_facts": [],
    "customer_goal": "",
    "customer_state": ""
  },

  "sessions": [
    {
      "session_number": 0,
      "channel": "",
      "platform": "",
      "handler_sequence": [],
      "goal": "",
      "facts_to_establish": {},
      "facts_to_carry": [],
      "facts_to_confirm": [],
      "facts_to_change": {},
      "facts_to_invalidate": [],
      "must_not_ask": [],
      "event": null,
      "expected_actions": [],
      "expected_outcome": ""
    }
  ],

  "final_expected_state": {
    "customer_state": "",
    "purchase_state": "",
    "resolved_items": [],
    "unresolved_items": []
  },

  "evaluation_ground_truth": {
    "must_carry_over": [],
    "must_not_ask": [],
    "must_confirm": [],
    "must_not_claim": [],
    "required_actions": [],
    "forbidden_actions": [],
    "success_conditions": []
  }
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `case_spec_id` | Gives each generated case a unique identifier for generation, evaluation, and reproducibility. |
| `case_id` | References the system problem being tested from `case_studies.jsonl`. |
| `persona_id` | References the customer archetype from `personas.jsonl`. |
| `difficulty_id` | References an optional difficult scenario. `null` is allowed when the case has no extra complication. |
| `journey_pattern_id` | References the interaction structure selected from `journey_patterns.jsonl`. |
| `customer_id` | References the controlled synthetic customer identity used across sessions and channels. |
| `business_context` | Links the case to authoritative product, promotion, and policy ground truth. |
| `business_context.product_ids` | Defines which products are relevant to the case. |
| `business_context.promotion_ids` | Defines which promotions may affect the case. |
| `business_context.policy_ids` | Defines which business policies are relevant to the case. |
| `initial_state` | Defines the concrete state that exists before the first generated session. |
| `initial_state.known_facts` | Stores facts already known by the system before the journey begins. |
| `initial_state.unknown_facts` | Stores information that has not yet been learned and may need to be collected later. |
| `initial_state.customer_goal` | Defines the customer's goal for this specific case rather than treating it as a permanent persona property. |
| `initial_state.customer_state` | Defines the customer's starting state for this specific journey. |
| `sessions` | Defines exactly what must happen in each interaction session. |
| `sessions[].session_number` | Preserves the ordered sequence of interactions. |
| `sessions[].channel` | Defines the interaction mode for that session. |
| `sessions[].platform` | Defines the specific platform used in that session. |
| `sessions[].handler_sequence` | Defines who handles the session and any intra-session handler transition. |
| `sessions[].goal` | Defines the concrete purpose of that session. |
| `sessions[].facts_to_establish` | Defines new facts that should become known during the session. |
| `sessions[].facts_to_carry` | Defines prior facts that must remain available and usable in the session. |
| `sessions[].facts_to_confirm` | Defines facts that should be confirmed because they may be uncertain, outdated, or conflicting. |
| `sessions[].facts_to_change` | Defines facts whose current value should change during the session. |
| `sessions[].facts_to_invalidate` | Defines prior facts that should no longer be treated as valid after the session event. |
| `sessions[].must_not_ask` | Defines information the agent must not ask again because it is already known and valid. |
| `sessions[].event` | Defines the concrete event or difficult-scenario trigger that happens in the session. |
| `sessions[].expected_actions` | Defines the actions the correct system should perform during the session. |
| `sessions[].expected_outcome` | Defines the expected result of that individual session. |
| `final_expected_state` | Defines what the customer and business state should look like after the entire journey. |
| `final_expected_state.customer_state` | Defines the customer's expected final state. |
| `final_expected_state.purchase_state` | Defines the final purchase status, such as purchased, not_purchased, or pending. |
| `final_expected_state.resolved_items` | Lists issues or tasks that should be resolved by the end of the journey. |
| `final_expected_state.unresolved_items` | Lists issues that are intentionally still open at the end. |
| `evaluation_ground_truth` | Stores deterministic assertions used to evaluate the generated transcript and agent behavior. |
| `evaluation_ground_truth.must_carry_over` | Defines facts that must be preserved across sessions for context-carryover evaluation. |
| `evaluation_ground_truth.must_not_ask` | Defines questions that must not be repeated because the information is already known. |
| `evaluation_ground_truth.must_confirm` | Defines facts that must be confirmed before being trusted or changed. |
| `evaluation_ground_truth.must_not_claim` | Defines statements the agent must not make because they would be unsupported or incorrect. |
| `evaluation_ground_truth.required_actions` | Defines actions that must occur for the case to be considered successful. |
| `evaluation_ground_truth.forbidden_actions` | Defines actions that should cause the case to fail evaluation. |
| `evaluation_ground_truth.success_conditions` | Defines the final assertions used to determine whether the case succeeded. |

## Design note

`case_specs.jsonl` should contain the concrete ground truth needed for generation and evaluation.

The LLM should **not invent**:

```text
customer identity
product facts
promotion validity
policy rules
known prior facts
required carry-over facts
expected actions
success conditions
```

The LLM should only generate natural Vietnamese dialogue that realizes the already-defined case specification.
