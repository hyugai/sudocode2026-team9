# Synthetic Dataset Schema Overview

## Purpose

This document summarizes the schemas used to generate controlled synthetic customer-service cases and Vietnamese transcripts.

```text
Case Study
× Persona
× Optional Difficult Scenario
× Journey Pattern
× Customer
× Business Ground Truth
↓
Derived Properties
↓
Compatibility Rules
↓
Case Specification
↓
LLM generates Vietnamese transcript
```

> **Store primitive facts, derive summary properties in code, validate combinations, and let the LLM generate language rather than ground truth.**

---

## Schema Overview

| Schema | Role in the system | Current scope | Expandability |
|---|---|---|---|
| `case_studies.jsonl` | Defines the high-level system problem being tested | 4 project case studies | **Low / controlled** — expand only if the project adds a new system-level problem |
| `personas.jsonl` | Defines stable customer archetypes and typical behavior | 5 required personas in the current project design | **Medium** — additional personas can be added without changing the architecture |
| `difficult_scenarios.jsonl` | Defines optional complications added to a case | 4 core difficult-scenario types | **Medium** — new difficult situations can be added as long as their setup and expected behavior are defined |
| `journey_patterns.jsonl` | Defines the ordered session/channel/handler structure | Curated journey-pattern library | **High** — new channel orders, session counts, and handler sequences can be added freely |
| `derived_properties` | Calculates convenience values from primitive data | `session_count`, `cross_channel`, `handoff`, `requires_prior_state`, etc. | **High** — new derived values can be added whenever compatibility logic needs them |
| `compatibility_rules.jsonl` | Validates whether selected dimensions can form a logically valid case | Rule set grows with dimensions and constraints | **High** — add rules whenever a new constraint, persona, scenario, or business condition is introduced |
| `case_specs.jsonl` | Stores the fully instantiated case used for transcript generation and evaluation | Generated output, not a fixed library | **Very high** — the number of case specs scales with dataset size and valid dimension combinations |

---

## 1. `case_studies.jsonl`

### Responsibility

Defines **what system problem is being tested**: required context, trigger, baseline behavior, expected behavior, and system-level expected outcome.

---

## 2. `personas.jsonl`

### Responsibility

Defines **what kind of customer is participating in the case** through stable characteristics and typical behaviors. Journey-specific goals and states belong in the case specification.

---

## 3. `difficult_scenarios.jsonl`

### Responsibility

Defines an **optional complication** such as a changed decision, conflicting information, expired promotion, or question outside available documentation.

---

## 4. `journey_patterns.jsonl`

### Responsibility

Defines **how the customer journey is arranged**: ordered sessions, channel, platform, handler sequence, and relative timing. Summary properties such as `session_count`, `cross_channel`, and `handoff` are derived in code.

---

## 5. Derived Properties

### Responsibility

Derived properties are **not another source dimension**. They are calculated before compatibility validation.

| Derived property | Source |
|---|---|
| `session_count` | Number of journey sessions |
| `cross_channel` | Distinct channels/platforms in the journey |
| `handoff` | Handler transitions within or across sessions |
| `requires_prior_state` | Inferred from difficult-scenario setup |
| `customer_goal` | Assigned in the concrete case specification |
| `customer_state` | Assigned in the concrete case specification |

---

## 6. `compatibility_rules.jsonl`

### Responsibility

Defines **which combinations are valid** after dimensions are selected and derived properties are calculated.

---

## 7. `case_specs.jsonl`

### Responsibility

Defines the **fully instantiated case** before language generation, including customer/business context, session facts, events, expected actions, outcomes, and evaluation ground truth.

The case specification decides **what must happen**; the LLM decides only **how it is expressed in Vietnamese**.

---

## Expandability Summary

```text
Mostly fixed / bounded by the brief
-----------------------------------
case_studies          4
personas              5 required
difficult_scenarios   4 required


Curated but expandable
----------------------
journey_patterns
compatibility_rules


Generated / scalable
--------------------
customers
products
promotions
policies
case_specs
transcripts
```

A useful rule is:

> **Expand a schema only when the new information belongs to that schema's responsibility.**

For example:

```text
new system problem
→ Case Study

new customer archetype
→ Persona

new edge case
→ Difficult Scenario

new channel/session sequence
→ Journey Pattern

new combination constraint
→ Compatibility Rule

new concrete generated scenario
→ Case Specification
```

---

## Relationship Between Schemas

```text
case_studies.jsonl
        │
personas.jsonl
        │
difficult_scenarios.jsonl
        │
journey_patterns.jsonl
        │
customer + business ground truth
        │
        ▼
select dimensions
        │
        ▼
derive properties
        │
        ▼
compatibility_rules.jsonl
        │
        ▼
valid combination
        │
        ▼
case_specs.jsonl
        │
        ▼
LLM
        │
        ▼
Vietnamese transcript
```

This separation keeps the dataset generator controlled, reusable, and easier to evaluate while preventing the LLM from inventing important ground-truth decisions.
