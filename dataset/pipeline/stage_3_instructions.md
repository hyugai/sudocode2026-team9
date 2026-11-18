# Stage 3: Validate, Deduplicate & Split

## 1. Objective
Read raw generated scenarios via the relative input symlink (`input_scenarios/raw_scenarios.jsonl`), enforce zero PII and schema/catalog validity, deduplicate utterances, partition into **Memory Seeding** and **Held-Out Golden Test Set** inside `runs/run_<tier>_YYYYMMDD_HHMM/` using `--tier M1 | M2` thresholds, and atomically promote `latest -> runs/run_<tier>_YYYYMMDD_HHMM/`.

## 2. Inputs

The organizer bundles are stored in [`btc_data/`](./btc_data/). The Stage 2 generation log identifies the exact Stage 1 customer registry used for that batch.
- `input_scenarios/raw_scenarios.jsonl` (symlinked to `../stage_2_transcripts/latest/raw_scenarios.jsonl`)
- [`btc_data/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md`](./btc_data/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) & [public samples SAMPLE-01 through SAMPLE-07](./btc_data/BTC-Data-Vong1-TEAMS/test_set/public_sample/)
- [`btc_data/BTC-Data-Vong1-TEAMS/catalog/`](./btc_data/BTC-Data-Vong1-TEAMS/catalog/) (`products.json`, `promotions.json`, `inventory_timeline.json`)
- [`btc_data/BTC-cap-nhat-11-2026/eval/reference_eval.py`](./btc_data/BTC-cap-nhat-11-2026/eval/reference_eval.py) and [`mock_tools.py`](./btc_data/BTC-cap-nhat-11-2026/eval/mock_tools.py)

## 3. Tier Quality Gates (`--tier M1` vs. `--tier M2`)

| Quality Gate Assertion | `--tier M1` Minimum | `--tier M2` Minimum |
| :--- | :--- | :--- |
| `total_transcripts` (one per retained journey) | $\ge 120$ | One per retained journey |
| `total_sessions` | $\ge 120$ | $\ge 250$ |
| `multi_session_customers` | $\ge 30$ | $\ge 60$ |
| `three_session_customers` | $\ge 3$ | $\ge 20$ |
| `omnichannel_customers` | $\ge 10$ | $\ge 30$ |
| `hard_edge_case_scenarios` | $\ge 5$ | $\ge 15$ |
| `golden_test_scenarios` (custom, excl. 7 BTC samples) | $\ge 20$ | $\ge 40$ |
| `simulator_profile` present on all scenarios | Optional | **Required (`100%`)** |
| `guardrail_violations` (PII leaks) | `0` | `0` |

## 4. Step-by-Step Implementation Instructions

### Step 4.1: PII Validation & Guardrail Audit (`pii_audit_report.json`)
1. Scan every synthetic customer turn and metadata field for actual-looking phone numbers, citizen IDs, bank accounts, street addresses, and legacy bracketed placeholders. Reject synthetic transcripts that fail the scan.
2. Mask detected PII in copies of the seven BTC public samples using sample-specific tokens.
3. Write `pii_audit_report.json` and assert `guardrail_violations == 0` across the retained synthetic transcripts and BTC sample copies.

### Step 4.2: Schema & Ground-Truth Validation
Validate every scenario programmatically before splitting:
1. **Schema Check:** Verify required keys (`scenario_id`, `persona`, `customer_phone`, `call_1`, `call_2`, `customer_turns`, `expected_outcome`, `success_if`) match `schemas/scenario_format.md`. For `--tier M2`, also assert `simulator_profile` (`persona_system_prompt`, `hidden_goal`) is non-empty.
2. **Slot Consistency Check:** Confirm every slot listed in `must_not_ask` and `must_carry_over` (on `call_2` and `call_3`) exists in prior sessions' `facts_established`.
3. **Multi-Entity Check:** Confirm every field in `entities_multi` holds a `list` value in `facts_established`.
4. **Catalog & Tool Check:** Verify `success_if.args_match.sku` exists in `products.json`, `price_vnd` matches catalog/promo pricing for the target call date, and `success_if.tool_called` is a valid tool in `mock_tools.py`.

### Step 4.3: Semantic Deduplication & Regeneration Loop
1. Compute TF-IDF cosine similarity across the concatenated customer turns of each validated journey.
2. **If similarity $> 0.90$:**
   - Quarantine the duplicate scenario into `stage3_dropped_duplicates.jsonl`.
   - If the retained dataset falls below a tier minimum, reuse the Stage 2 renderer with alternate seeds. Reject the original and matched opening phrases, then validate and compare each regenerated candidate with the retained set. Preserve the original duplicate in the quarantine log.

### Step 4.4: Customer-Level Stratified Split & Leakage Check
1. Group scenarios by `customer_id` (keeping each customer's complete multi-session history intact).
2. Stratify by persona, edge-case type, and session count. Hold out at least 20 custom M1 or 40 custom M2 scenarios and assign the remaining customers to `journeys_memory_seed.jsonl`.
   - **`journeys_memory_seed.jsonl`:** Pre-populates CRM/SQLite customer profiles and episodic history before evaluation.
   - **`team_golden_scenarios.json`.** Custom golden scenarios in the evaluator’s nested `calls` format, combined with scrubbed copies of the seven BTC public samples.
3. **Cross-Split Leakage Assertion:** Assert `set(seed_customer_ids).isdisjoint(set(golden_customer_ids))` and `set(seed_phones).isdisjoint(set(golden_phones))`.

### Step 4.5: Summary Statistics (`dataset_stats.json`) & Atomic Promotion
1. Compute and export `dataset_stats.json` containing `tier`, `total_journeys`, `total_transcripts`, `total_sessions`, `multi_session_customers`, `three_session_customers`, `omnichannel_customers`, `hard_edge_case_scenarios`, `golden_test_scenarios`, `persona_distribution`, `channel_distribution`, `outcome_distribution`, and `guardrail_violations` (`0`).
2. Atomically update `latest -> runs/run_<tier>_YYYYMMDD_HHMM/`.

## 5. Final Promoted Artifacts (`stage_3_validate_split/latest/`)
- `journeys_memory_seed.jsonl`
- `team_golden_scenarios.json`
- `dataset_stats.json`
- `pii_audit_report.json`
- `stage3_dropped_duplicates.jsonl`

## 6. Exit Criteria
- `guardrail_violations == 0` across all output files.
- Zero `customer_id` or `customer_phone` overlap between `journeys_memory_seed.jsonl` and `team_golden_scenarios.json`.
- `dataset_stats.json` satisfies all minimum thresholds for the active `--tier` (`M1` or `M2`).
- BTC’s reference evaluator loads all golden scenarios and completes an empty-trace smoke check. Stage 3 temporarily writes one evaluator-format JSON file per scenario for the directory-based loader.

## 7. Published Journey Exports

Run Stage 3 with `--publish` to update the tier’s pinned export after it passes validation. Each tier symlink in [`final_datasets/`](./final_datasets/) points to a pinned export under `stage_3_validate_split/journey_exports/`. Each directory contains only its memory-seed and custom golden journeys as individual `SC-XXX.json` files. M1 assigns consecutive filenames in ascending scenario ID order. M2 uses the numeric part of `TEAM-SC-XXX`, including numbering gaps. Each file retains its original scenario ID and record structure. The seven BTC samples are included in the aggregate golden bundle.

| Tier | Published transcripts | Retained sessions | Memory-seed journeys | Golden scenarios |
| :--- | ---: | ---: | ---: | ---: |
| M1 | 120 | 256 | 100 | 20 custom + 7 BTC |
| M2 | 124 | 268 | 84 | 40 custom + 7 BTC |
