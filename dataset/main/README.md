# Scenario Tests — 120 Paired Records

This package contains **120 scenarios across all 12 BTC personas**, with **250 calls**. Each JSONL line is one JSON object. Records match between the two files by `scenario_id`, from `SC-G9-001` to `SC-G9-120`.

## Files

| File | Purpose | One line contains |
|---|---|---|
| `01_scenarios_prefilled.jsonl` | Input for completing or regenerating a scenario | A fixed scenario seed, missing-field list and supporting context |
| `02_scenarios_complete.jsonl` | Completed scenario tests | One BTC-format scenario with Vietnamese customer turns and grading conditions |

## 1. Prefilled file

Each record has four keys:

- `scenario_id`: matches the complete scenario.
- `scenario_seed`: populated identities, selected options, dates, planned facts and grading conditions. Preserve these values when generating text.
- `fields_to_generate`: missing fields to fill, such as `notes`, `customer_goal`, `customer_turns` and, where applicable, `customer_turns_asr`.
- `generation_context`: the objective, CRM record, persona, products, calculated business facts, source hashes and execution assumptions.

The seed includes both **copied/calculated values and team-selected test choices**. It is more than a list of finite-option fields. Missing fields are omitted and listed explicitly rather than represented by empty strings or placeholder `null` values.

To use it with an LLM, supply the record, ask it to fill only `fields_to_generate`, preserve the populated seed values, and return the completed scenario object without the request wrapper. Validate the result afterward.

## 2. Complete file

Each record contains the BTC scenario fields: identity, persona, notes and `calls`. Calls include customer dialogue, facts, memory requirements and success conditions as relevant.

This file is ready for scenario loading/export. It contains **customer inputs and private grading expectations**. Actual agent responses and tool calls are produced later by running the system and saved as traces.

The complete file already fills the missing fields from the prefilled file; using an LLM again is optional.

## Export for BTC's evaluator

BTC's reference evaluator loads a folder containing one JSON file per scenario. Run this Python code from the directory containing the complete JSONL file:

```python
import json
from pathlib import Path

output = Path("scenarios")
output.mkdir(exist_ok=True)

with Path("02_scenarios_complete.jsonl").open(encoding="utf-8") as source:
    for line in source:
        if not line.strip():
            continue
        scenario = json.loads(line)
        path = output / f"{scenario['scenario_id']}.json"
        path.write_text(
            json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
```

The team runner then executes these scenarios under `full` and `baseline_no_memory` and records actual traces for BTC scoring.

## Execution notes

- Reset runtime tool state **between scenarios**, while retaining it **between calls in the same scenario**.
- Exchange cases expect the first order created by the clean BTC mock to return `OD600001`. Read the case notes before adapting another order backend.
- Use each call's date for prices, promotions and stock. Never replace it with the computer's current date.
- When `input_mode` selects noisy input, feed `customer_turns_asr` to the system.
- Keep grading expectations private; do not place them in the tested agent's prompt. Scenarios with `memory_expectation` require memory-write logging.
- Addresses containing “đường Kiểm Thử” are synthetic customer inputs, not existing CRM addresses.

## Validation status

The package passed checks for record pairing, preserved seed values, structure, customer identity, dates, business facts and expected reference-tool behavior. It was generated from templates with 10 variations per persona and **has not been run against the actual agent**. Semantic review and system pilot runs remain necessary.

These are scenario tests. They do not by themselves satisfy BTC's separate requirements for complete customer-and-agent transcripts and audio conversations.
