# AGENTS.md — SUDO CODE 2026 Synthetic Dataset Generation Pipeline

## 0. User Approval Before Changes (MANDATORY)

Before making any workspace changes, summarize the proposed changes and affected files or outputs, then ask the user to confirm. Wait for explicit confirmation before editing files, changing symlinks, or running commands that write to the workspace. Read-only inspection may continue while approval is pending. If the proposed scope changes, request confirmation for the updated scope before applying it.

## 1. Project Context & Core Definitions
You are building a **3-stage, text-only synthetic dataset generation pipeline** supporting both **M1 (Baseline)** and **M2 (Advanced)** tiers (`--tier M1 | M2`) for the **SUDO CODE 2026** Stateful Multi-Session Telesale Call Center project.

### Key Domain Definitions
* **Customer / Journey (Blueprint):** One unique customer identity (`CUST-XXX`, linked across `phone`, `fb_id`, and `zalo_id`) and their connected end-to-end history across **2–3 consecutive sessions** (`call_1` $\rightarrow$ `call_2` [$\rightarrow$ `call_3`]).
* **Transcript (`Số cuộc hội thoại`):** The complete record of one customer journey. **One journey produces one transcript**, containing its 2–3 consecutive sessions.
* **Session:** One bounded call or chat interaction within a transcript, represented by `call_1`, `call_2`, or `call_3`. Each session contains its own customer turns and evaluation assertions.
* **Evaluation Format (`customer_turns` + M2 Simulator Fields):** Per [organizer scenario schema](./btc_data/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) and [seven public samples](./btc_data/BTC-Data-Vong1-TEAMS/test_set/public_sample/), each session stores static replay utterances as `customer_turns: list[str]` (**do not** generate pre-written agent replies). For `--tier M2`, each scenario also includes `simulator_profile` (`persona_system_prompt`, `hidden_goal`, `patience_level`) so the evaluation harness can run a live LLM Customer Simulator.
* **Canonical Outcomes (`expected_outcome`):** `"chot_don"`, `"hen_goi_lai"`, `"tu_choi"`, or `"chuyen_may"` (paired with `success_if` tool assertions such as `order.create`, `order.update`, `schedule.callback`, or `handoff.transfer`).

### Tier Volume & Quality Thresholds (`--tier M1` vs. `--tier M2`)

| Metric / Requirement | `--tier M1` (Baseline) | `--tier M2` (Advanced) |
| :--- | :--- | :--- |
| **Target Blueprints Generated** | 140 journeys in a fresh batch | `~130` journeys |
| **Published Transcripts (Journeys)** | $\ge 120$ | One per retained journey |
| **Total Sessions** | $\ge 120$ | $\ge 250$ (`~280` generated) |
| **Multi-Session Customers** | $\ge 30$ ($\ge 2$ sessions; `~5` with 3 sessions) | $\ge 60$ ($\ge 2$ sessions; **$\ge 20$ with 3 sessions**) |
| **Omnichannel Customers** | $\ge 10$ (`12` call + chat journeys) | $\ge 30$ (`35` call + chat journeys) |
| **Hard Edge-Case Scenarios** | $\ge 5$ (`8` journeys) | $\ge 15$ (`18` journeys, incl. 3-call state mutations) |
| **Held-Out Golden Scenarios** | $\ge 20$ custom + `7` BTC public samples ($\ge 25$ total) | $\ge 40$ custom + `7` BTC public samples ($\ge 47$ total) |
| **Evaluation Mode** | Static `customer_turns` replay | Static `customer_turns` + **LLM Customer Simulator** |
| **Guardrail Violations (PII)** | `0` | `0` |

---

## 2. Directory Structure & Symlink Contract

Each stage has a dedicated root-level instruction file, an isolated stage directory with immutable timestamped run folders (`runs/run_<tier>_YYYYMMDD_HHMM/`), and **relative symlinks** (`latest` and `input_*`). Organizer bundles are read-only. Scripts use `btc_data/` when present, otherwise they read the bundles directly from the workspace root.

```text
synthetic_pipeline/
├── AGENTS.md                                          # Master orchestrator guide (this file)
├── stage_1_instructions.md
├── stage_2_instructions.md
├── stage_3_instructions.md
├── pipeline_common.py
├── btc_data/                                          # Read-only organizer bundles
│   ├── BTC-Data-Vong1-TEAMS/
│   └── BTC-cap-nhat-11-2026/
├── final_datasets/
│   ├── M1 -> ../stage_3_validate_split/journey_exports/run_M1_<timestamp>/
│   └── M2 -> ../stage_3_validate_split/journey_exports/run_M2_<timestamp>/
│
├── stage_1_blueprints/
│   ├── src/
│   │   └── generate_blueprints.py
│   ├── runs/
│   │   └── run_<tier>_YYYYMMDD_HHMM/
│   │       ├── stage1_customers.json
│   │       ├── stage1_blueprints.jsonl
│   │       └── manifest.json
│   └── latest -> runs/run_<tier>_YYYYMMDD_HHMM/
│
├── stage_2_transcripts/
│   ├── src/
│   │   └── generate_transcripts.py
│   ├── input_blueprints -> ../stage_1_blueprints/latest
│   ├── runs/
│   │   └── run_<tier>_YYYYMMDD_HHMM/
│   │       ├── raw_scenarios.jsonl
│   │       └── generation_log.json
│   └── latest -> runs/run_<tier>_YYYYMMDD_HHMM/
│
└── stage_3_validate_split/
    ├── src/
    │   └── validate_and_split.py
    ├── input_scenarios -> ../stage_2_transcripts/latest
    ├── runs/
    │   └── run_<tier>_YYYYMMDD_HHMM/
    │       ├── journeys_memory_seed.jsonl
    │       ├── team_golden_scenarios.json
    │       ├── stage3_dropped_duplicates.jsonl
    │       ├── pii_audit_report.json
    │       └── dataset_stats.json
    ├── journey_exports/
    │   └── run_<tier>_YYYYMMDD_HHMM/SC-XXX.json
    └── latest -> runs/run_<tier>_YYYYMMDD_HHMM/
```

---

## 3. Shared Execution & Symlink Rules (MANDATORY)

1. **CLI Tier Propagation:** Every stage script accepts `--tier M1` or `--tier M2` and records the tier in its run metadata. Stages 1 and 3 default to M1. Stage 2 infers the tier from its upstream manifest when the flag is omitted. Use matching upstream and downstream tiers.
2. **Always Use Relative Symlinks:** Create symlinks using relative paths (e.g., `runs/run_M2_20261118_1645` for `latest`; `../stage_1_blueprints/latest` for `input_blueprints`) so paths never break across machines or containers.
3. **Atomic Symlink Promotion:** Every full stage run must write outputs into a new timestamped folder `runs/run_<tier>_YYYYMMDD_HHMM/`, run its exit assertions for the active tier, and update its `latest` symlink **only after all checks succeed**.
4. **Cross-Platform Helper:** Implement a shared utility `promote_latest(stage_dir, run_folder_name)` that atomically updates `latest` via `os.symlink` + `os.replace`, falling back to writing `latest_path.txt` if OS permissions restrict symlinks.

---

## 4. Stage Execution Index

Follow the root-level stage instructions and run the pipeline sequentially.

| Order | Stage | Instruction File | Script Target | Input Symlink | Promoted Output (`latest/`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **World-State & Blueprints** | [`stage_1_instructions.md`](./stage_1_instructions.md) | `stage_1_blueprints/src/generate_blueprints.py` | Organizer bundles (read-only) | `stage1_customers.json`, `stage1_blueprints.jsonl`, `manifest.json` |
| **2** | **Multi-Turn Transcripts** | [`stage_2_instructions.md`](./stage_2_instructions.md) | `stage_2_transcripts/src/generate_transcripts.py` | `input_blueprints -> ../stage_1_blueprints/latest` | `raw_scenarios.jsonl`, `generation_log.json` |
| **3** | **Validate, Split & Publish** | [`stage_3_instructions.md`](./stage_3_instructions.md) | `stage_3_validate_split/src/validate_and_split.py` | `input_scenarios -> ../stage_2_transcripts/latest` | `journeys_memory_seed.jsonl`, `team_golden_scenarios.json`, `stage3_dropped_duplicates.jsonl`, `pii_audit_report.json`, `dataset_stats.json` |

## 5. Published Journey Exports

[`final_datasets/M1`](./final_datasets/M1) and [`final_datasets/M2`](./final_datasets/M2) are relative symlinks to exports of specific validated Stage 3 runs. Each tier directory contains only individual synthetic journeys named `SC-XXX.json`. M1 assigns consecutive filenames in ascending scenario ID order. M2 uses the numeric part of each scenario ID as the filename number, including gaps left by deduplication. Every file retains its original `scenario_id`.

Each export includes the memory-seed and custom golden journeys. Custom journeys use fictional contact values and delivery addresses generated for the dataset. Stage 3 rejects detected PII in these journeys. The seven scrubbed BTC samples and aggregate validation artifacts are available in the corresponding Stage 3 run. Changes to a stage's `latest` link do not move either tier export.
