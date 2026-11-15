# Scenario Tests — 120 Paired Records

This package contains **120 scenarios across all 12 BTC personas**, with **250 calls**. The current sources are individual JSON files, paired by `scenario_id` from `SC-001` to `SC-120`. Each filename matches its ID.

## Files

| Path | Purpose | One file contains |
|---|---|---|
| `scenarios_prefilled/SC-xxx.json` | Input for completing or regenerating a scenario | A fixed scenario seed, missing-field list and supporting context |
| `scenarios_complete/SC-xxx.json` | Completed scenario tests, used directly by the evaluator | One BTC-format scenario with Vietnamese customer turns and grading conditions |

The superseded `01_scenarios_prefilled.jsonl` and `02_scenarios_complete.jsonl` files have been deleted. The existing JSON files are retained as the current versions. No JSONL conversion is needed.

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

These complete JSON files are ready for scenario loading. They contain **customer inputs and private grading expectations**. Actual agent responses and tool calls are produced later by running the system and saved as traces.

The complete scenarios already fill the generated fields; using an LLM again is optional. Review any seed/complete differences before regenerating content.

## Run with the evaluator

BTC's reference evaluator loads a folder containing one JSON file per scenario. Use `dataset/main/scenarios_complete/` directly; the prefilled folder contains generation wrappers and must not be passed to the evaluator.

From the repository root, run the team runner under `full` and `baseline_no_memory`, saving actual traces. Score those traces with BTC's reference evaluator:

```bash
python dataset/organizer/eval/reference_eval.py \
  --scenarios dataset/main/scenarios_complete \
  --trace outputs/eval/full.jsonl \
  --baseline outputs/eval/baseline.jsonl
```

The trace paths above are examples; supply the paths produced by your runs. Trace logs remain JSONL. `manifest.jsonl` is also retained as metadata, alongside the JSON and CSV manifests.

## Execution notes

- Reset runtime tool state **between scenarios**, while retaining it **between calls in the same scenario**.
- Exchange cases expect the first order created by the clean BTC mock to return `OD600001`. Read the case notes before adapting another order backend.
- Use each call's date for prices, promotions and stock. Never replace it with the computer's current date.
- When `input_mode` selects noisy input, feed `customer_turns_asr` to the system.
- Keep grading expectations private; do not place them in the tested agent's prompt. Scenarios with `memory_expectation` require memory-write logging.
- Addresses containing “đường Kiểm Thử” are synthetic customer inputs, not existing CRM addresses.

## Validation status

The original package used templates with 10 variations per persona. The quality revision changes only **SC-041–SC-120** and their paired prefilled records. **SC-001–SC-040, all 250 WAV files, and all three manifests remain unchanged.**

Current session distribution is **150 hotline (60%), 50 Fanpage (20%), and 50 Zalo OA (20%)**; 70 scenarios span multiple channels. Among the 80 revised scenarios, 24 retain their core difficulty, 42 add one hard case, and 14 add two. The first four persona groups remain unchanged because their scenarios have audio.

See `coverage.json` for per-scenario channels, core/additional hard cases, grading evidence, synthetic chat identities, source-hash audit, and 12 pilot IDs. Original provenance hashes are preserved: three recorded source hashes differ from the current organizer package and remain unresolved.

Offline checks verified 80 seed/complete pairs, 230 price/inventory snapshots against current BTC tools, 84 positive/negative grading probes, and audio/transcript/checksum consistency. These are fixture checks, not agent responses or performance results. **Actual-agent pilots have not run** because this environment lacks backend dependencies; semantic review and pilot runs remain necessary.

These are scenario tests. They do not by themselves satisfy BTC's separate requirements for complete customer-and-agent transcripts and audio conversations.
