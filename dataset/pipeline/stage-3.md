# Stage 3 · Finalize the dataset

The notebook runs on CPU with standard Python 3.11+ libraries. Set `BATCH_SIZE` in Configure to control the number of whole journeys assembled in each batch.

## Run on Kaggle

1. Upload [stage3-m1-input.zip](./stage-3/stage3-m1-input.zip) as a private Kaggle dataset. The notebook can read the extracted dataset files or open the attached ZIP itself.
2. Import [finalize.ipynb](./stage-3/finalize.ipynb), attach the dataset with **Add Input**, and run all three code cells. Use CPU. The run works with Internet disabled.
3. Download `/kaggle/working/stage-3-output.zip`. The archive contains the final scenarios and audit files.

To run locally, open the same notebook from the pipeline root or `stage-3/`. It uses `stage3-m1-input.zip` when available and falls back to the regular files under `stage-3/input/`. The output is `stage-3/output/stage-3-output.zip`.

## Inputs

| Notebook input | Source |
| --- | --- |
| `stage-3/input/transcripts.jsonl` | [Stage 2 M1 accepted transcripts](./stage-2/phase-2/output/m1/transcripts.jsonl) |
| `stage-3/input/blueprints.jsonl` | [Stage 1 M1 blueprints](./stage-1/output/m1/blueprints.jsonl) |
| `stage-3/input/customers.json` | [Stage 1 M1 customer registry](./stage-1/output/m1/customers.json) |

The current M1 input ZIP bundles those files, the notebook and Python helpers, the [BTC CRM fixtures and reference evaluator](./btc/), and the [Stage 1 venue catalog](./stage-1/input/catalog/public-delivery-addresses.json). To package another run, use matching Stage 1 and Stage 2 files for the same tier and run.

## Processing

1. Join accepted transcripts to blueprints by `scenario_id` and attach the Stage 1 customer by `customer_id`. Keep the accepted customer turns and the blueprint's session dates and evaluation fields.
2. Assemble every journey in the [BTC scenario format](./btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md). Use `level` and nested `calls`, map chat channels to `chat_fanpage` or `zalo_oa`, and use `edge_case_type` as the label for a flagged hard case. M2 simulator settings stay in their Stage 1 blueprint.
3. Scan the assembled scenarios for unexpected contact and street-address values, citizen IDs, bank-account patterns, and legacy placeholders. The scan recognizes the organizer's CRM fixtures and the customer's assigned public venues. Keep the supplied values in the export and report rejected scenario IDs and finding types.
4. Compare the complete customer dialogue with TF-IDF cosine similarity. Keep the earlier journey in scenario ID order when a later journey scores above 0.90 against it.
5. Check the tier minimums and run the updated BTC evaluator with an empty trace to exercise scenario loading and field access.

## Outputs

| Path in `stage-3-output.zip` | Contents |
| --- | --- |
| `SC-XXX.json` | One BTC-format file per retained journey. M1 uses consecutive filenames in original scenario ID order. M2 uses the original scenario number. Each file keeps the original `scenario_id`. |
| `audit/renamed_scenarios.jsonl` | Original scenario ID and new filename for each renamed file |
| `audit/dataset_stats.json` | Journey and session counts and evaluator smoke-check result |
| `audit/pii_audit_report.json` | Privacy scan counts and any rejected journey IDs |
| `audit/stage3_dropped_duplicates.jsonl` | Dropped scenario IDs, matched IDs, and similarity scores |

A successful rerun replaces the output ZIP after validation and packaging complete.
