# AGENTS.md — SUDO CODE 2026 Synthetic Dataset Generation Pipeline

## 0. User Approval Before Changes (MANDATORY)

Before making any workspace changes, summarize the proposed changes and affected files or outputs, then ask the user to confirm. Wait for explicit confirmation before editing files, changing symlinks, or running commands that write to the workspace. Read-only inspection may continue while approval is pending. If the proposed scope changes, request confirmation for the updated scope before applying it.

## 1. Project Context & Core Definitions
You are building a **3-stage, text-only synthetic dataset generation pipeline** supporting both **M1 (Baseline)** and **M2 (Advanced)** tiers (`--tier M1 | M2`) for the **SUDO CODE 2026** Stateful Multi-Session Telesale Call Center project.

### Key Domain Definitions
* **Customer / Journey (Blueprint):** One unique customer identity (`CUST-XXX`, linked across `phone`, `fb_id`, and `zalo_id`) and their connected end-to-end history across **2–3 consecutive sessions** (`call_1` $\rightarrow$ `call_2` [$\rightarrow$ `call_3`]).
* **Transcript (`Số cuộc hội thoại`):** The complete record of one customer journey. **One journey produces one transcript**, containing its 2–3 consecutive sessions.
* **Session:** One bounded call or chat interaction within a transcript, represented by `call_1`, `call_2`, or `call_3`. Each session contains its own customer turns and evaluation assertions.
* **Evaluation Format (`customer_turns` + M2 Simulator Fields):** Per [organizer scenario schema](./btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) and [seven public samples](./btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/), each session stores static replay utterances as `customer_turns: list[str]` (**do not** generate pre-written agent replies). For `--tier M2`, each scenario also includes `simulator_profile` (`persona_system_prompt`, `hidden_goal`, `patience_level`) so the evaluation harness can run a live LLM Customer Simulator.
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
| **Evaluation Mode** | Static `customer_turns` replay | Static `customer_turns` + **LLM Customer Simulator** |
| **Guardrail Violations (PII)** | `0` | `0` |

---

## 2. Directory Structure & Symlink Contract

Each stage has a dedicated root-level instruction file and immutable timestamped run folders. New Stage 1 and Stage 2 runs use `runs/run-<tier>-YYYYMMDD-HHMM/`. Readers also support the recorded names of older runs. Stage 1 uses regular directories for inputs and published output. Stages 2 and 3 use relative symlinks for their remaining run pointers. Organizer bundles are read-only.

```text
pipeline/
├── AGENTS.md                                          # Master orchestrator guide (this file)
├── stage-1.md
├── stage-2.md
├── stage-3.md
├── common.py
├── btc/                                          # Read-only organizer bundles
│   ├── BTC-Data-Vong1-TEAMS/
│   └── BTC-cap-nhat-11-2026/
├── final/
│   ├── M1/SC-XXX.json                                # Published copies of a validated M1 run
│   └── M2/SC-XXX.json                                # Published copies of a validated M2 run
│
├── stage-1/
│   ├── src/
│   │   └── generate.py
│   ├── input/                                        # Copies of the required organizer files
│   │   ├── catalog/
│   │   ├── eval/
│   │   └── simulator/
│   ├── runs/
│   │   └── run-<tier>-YYYYMMDD-HHMM/
│   │       ├── customers.json
│   │       └── blueprints.jsonl
│   └── output/                                       # Copy of the selected validated run
│
├── stage-2/
│   ├── run-kaggle.py
│   ├── prompts.json
│   ├── kaggle-input/
│   ├── kaggle-output/
│   ├── src/
│   │   ├── generate.py
│   │   ├── bundle.py
│   │   ├── jobs.py
│   │   ├── worker.py
│   │   └── quality.py
│   ├── runs/
│   │   └── run-<tier>-YYYYMMDD-HHMM/
│   │       ├── raw-scenarios.jsonl
│   │       ├── generation-log.json
│   │       ├── validation-report.jsonl
│   │       ├── ai-report.jsonl
│   │       ├── regeneration-list.json
│   │       ├── validation-manifest.json
│   │       ├── generation-manifest.json
│   │       ├── quality-report.jsonl
│   │       └── quality-report.manifest.json
│   └── latest -> runs/run-<tier>-YYYYMMDD-HHMM/
│
└── stage-3/
    ├── finalize.ipynb
    ├── stage-3-kaggle-input.zip
    ├── input/                                        # Copies of Stage 1 and Stage 2 outputs
    ├── output/
    │   ├── SC-XXX.json
    │   └── audit/
    ├── src/
    │   ├── finalize.py
    │   └── validate_and_split.py
    ├── runs/
    │   └── run_<tier>_YYYYMMDD_HHMM/
    │       ├── stage3_dropped_duplicates.jsonl
    │       ├── pii_audit_report.json
    │       └── dataset_stats.json
    ├── exports/
    │   └── run_<tier>_YYYYMMDD_HHMM/SC-XXX.json
    └── latest -> runs/run_<tier>_YYYYMMDD_HHMM/
```

---

## 3. Shared Execution & Symlink Rules (MANDATORY)

1. **CLI Tier Propagation:** Stage 1 accepts `--tier M1` or `--tier M2`, defaults to M1, and stores the tier in its blueprints. The manual Stage 2 workflow reads the tier from those blueprints. The Kaggle CLI infers the tier from its saved input bundle when `--tier` is omitted. Stage 3 defaults to M1. Use matching tiers across stages.
2. **Relative Symlinks:** Use relative targets for the Stage 2 and Stage 3 `latest` links. Stage 2 reads `stage-1/output/` directly. The Stage 3 notebook reads regular files in `stage-3/input/`.
3. **Run Publication:** Full runs write outputs into a new timestamped folder and run their tier exit assertions. Stage 1 updates its regular `output/` directory on `--publish` after validation. Stages 2 and 3 atomically update their `latest` symlinks after validation.
4. **Cross-Platform Helper:** Implement a shared utility `promote_latest(stage_dir, run_folder_name)` that atomically updates `latest` via `os.symlink` + `os.replace`, falling back to writing `latest_path.txt` if OS permissions restrict symlinks.

---

## 4. Stage Execution Index

Follow the root-level stage instructions and run the pipeline sequentially.

| Order | Stage | Instruction File | Script Target | Input | Published Output |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **World-State & Blueprints** | [`stage-1.md`](./stage-1.md) | `stage-1/src/generate.py` | `stage-1/input/` | `output/customers.json`, `output/blueprints.jsonl` |
| **2** | **Multi-Turn Transcripts** | [`stage-2.md`](./stage-2.md) | `stage-2/run-kaggle.py` | `stage-1/output/`, pinned Kaggle input bundle | `raw-scenarios.jsonl`, `generation-log.json`, `quality-report.jsonl` |
| **3** | **Validate & Export** | [`stage-3.md`](./stage-3.md) | `stage-3/finalize.ipynb` | `stage-3/input/` | `output/SC-XXX.json`, `output/audit/` |

Stage 2 uses two private Kaggle GPU notebooks, each started by its own command. `--generate OWNER/SLUG` saves every Qwen attempt and prints the exact generation version. `--validate OWNER/SLUG/VERSION` runs Python structure checks and uses Gemma and DeepEval to judge facts and goals in the customer dialogue before assembly. Validation writes regeneration feedback for clear draft failures and marks ambiguous or incomplete judgments for review. Use `--generate` with `--regenerate-from` to rerun the marked journeys. See the [Stage 2 instructions](./stage-2.md).

## 5. Published Journey Exports

[`final/M1`](./final/M1) and [`final/M2`](./final/M2) are regular directories containing copies of specific validated Stage 3 exports, so both can be opened directly on Windows. Each tier directory contains only individual synthetic journeys named `SC-XXX.json`. M1 assigns consecutive filenames in ascending scenario ID order. M2 uses the numeric part of each scenario ID as the filename number, including gaps left by deduplication. Every file retains its original `scenario_id`.

The Stage 3 notebook exports all retained journeys into one directory with one JSON file per journey and writes its validation artifacts under `audit/`. Stage 3 rejects detected PII in the generated journeys. The legacy CLI refreshes a published tier directory when invoked with `--publish`.
