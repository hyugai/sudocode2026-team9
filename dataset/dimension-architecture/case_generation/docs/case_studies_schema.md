# `case_studies.jsonl`

## Purpose

`case_studies.jsonl` defines the **high-level system problem** each synthetic case should test. It is not a transcript. It describes the failure, when it appears, what context must exist, and how baseline vs. AI Agent Harness behavior should differ.

required_context
    ↓
trigger occurs
    ↓
problem becomes observable
    ↓
baseline_behavior shows the failure
    ↓
expected_behavior defines correct harness behavior
    ↓
expected_outcome defines system-level success

## General format

```json
{
  "case_id": "",
  "name": "",
  "title": "",
  "description": "",
  "problem": "",
  "trigger": "",
  "required_context": [],
  "baseline_behavior": [],
  "expected_behavior": [],
  "expected_outcome": ""
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `case_id` | Lets other files and generated cases reference the case study reliably. |
| `name` | Provides a stable machine-readable name for code, filtering, generation, and evaluation. |
| `title` | Gives the team a concise human-readable label for documentation and debugging. |
| `description` | Gives a short explanation of the situation represented by the case study. |
| `problem` | Defines the core system or business failure that the case is intended to test. |
| `trigger` | Defines the event or condition that activates or exposes the case during a customer journey. |
| `required_context` | Defines the information or state that must exist for the case to be logically meaningful. |
| `baseline_behavior` | Defines the expected failure behavior of the system without the AI Agent Harness for comparison. |
| `expected_behavior` | Defines the correct behavior that the AI Agent Harness should demonstrate. |
| `expected_outcome` | Defines the high-level system result that indicates the case was handled successfully. |
