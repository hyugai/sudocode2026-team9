# Stage 3 · Finalize the dataset

The notebook runs on CPU with standard Python 3.11+ libraries. Set `BATCH_SIZE` in Configure to control the number of whole journeys assembled in each batch.

## Run on Kaggle

1. Upload [stage-3-kaggle-input.zip](./stage-3/stage-3-kaggle-input.zip) as a private Kaggle dataset. The notebook can read the extracted dataset files or open the attached ZIP itself.
2. Import [finalize.ipynb](./stage-3/finalize.ipynb), attach the dataset with **Add Input**, and run all three code cells. Use CPU. The run works with Internet disabled.
3. Download the final scenarios, splits, and audits from `/kaggle/working/output/`.

To run locally, open the same notebook from the pipeline root or `stage-3/`. Local runs write to `stage-3/output/`.

## Inputs

| Notebook input | Source |
| --- | --- |
| `stage-3/input/transcripts.jsonl` | [Stage 2 accepted transcripts](./stage-2/phase-3/output/transcripts.jsonl) |
| `stage-3/input/blueprints.jsonl` | [Stage 1 blueprints](./stage-1/output/blueprints.jsonl) |
| `stage-3/input/customers.json` | [Stage 1 customer registry](./stage-1/output/customers.json) |

The local inputs are regular copies of the M1 files. The ZIP bundles those copies, the notebook and Python helpers, the [BTC CRM fixtures, public samples, and reference evaluator](./btc/), and the [Stage 1 venue catalog](./stage-1/input/catalog/public-delivery-addresses.json). To package another run, use matching Stage 1 and Stage 2 files for the same tier and run.

## Processing

1. Join accepted transcripts to blueprints by `scenario_id` and attach the Stage 1 customer by `customer_id`. Keep the accepted customer turns and the blueprint's session dates and evaluation fields.
2. Assemble every journey in the [BTC scenario format](./btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md). Use `level` and nested `calls`, map chat channels to `chat_fanpage` or `zalo_oa`, and use `edge_case_type` as the label for a flagged hard case. M2 simulator settings stay in their Stage 1 blueprint.
3. Scan the assembled scenarios for unexpected contact and street-address values, citizen IDs, bank-account patterns, and legacy placeholders. The scan recognizes the organizer's CRM fixtures and the customer's assigned public venues. Keep the supplied values in the export and report rejected scenario IDs and finding types.
4. Compare the complete customer dialogue with TF-IDF cosine similarity. Keep the earlier journey in scenario ID order when a later journey scores above 0.90 against it.
5. Split by phone group so customers sharing a phone stay together. Keep groups used by the public samples in the golden split. Select at least 20 custom golden journeys for M1 or 40 for M2, balancing persona, edge case, and session count.
6. Check the tier minimums and run the updated BTC evaluator with an empty trace to exercise scenario loading and field access.

## Outputs

| Path under `output/` | Contents |
| --- | --- |
| `SC-XXX.json` | One BTC-format file per retained journey, named by its scenario ID |
| `splits/journeys_memory_seed.jsonl` | One BTC scenario per line for memory seeding |
| `splits/team_golden_scenarios.json` | Custom golden scenarios plus the seven unchanged BTC public samples |
| `audit/dataset_stats.json` | Journey, session, and split counts and evaluator smoke-check result |
| `audit/pii_audit_report.json` | Privacy scan counts and any rejected journey IDs |
| `audit/stage3_dropped_duplicates.jsonl` | Dropped scenario IDs, matched IDs, and similarity scores |

Use the golden bundle when selecting held-out journeys for evaluation. The output root contains the complete export across both splits. A successful rerun replaces the notebook output with the newly generated files.
