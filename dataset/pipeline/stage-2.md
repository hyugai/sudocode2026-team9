# Stage 2 · Generate and validate transcripts

A Stage 1 blueprint becomes one transcript. Each session contains Vietnamese customer turns in `customer_turns`. Both notebooks use complete journeys as the unit of batching.

## Generate candidates

1. Upload [the generation input ZIP](./stage-2/phase-2/input/stage-2-input.zip) as a private Kaggle dataset. Attach it to [the generation notebook](./stage-2/phase-2/generate.ipynb). The ZIP contains the sanitized M1 blueprints, personas, prompts, and the generation helper. [Kaggle datasets](https://www.kaggle.com/docs/datasets)
2. Attach [Qwen 3 30B-A3B GGUF, version 1](https://www.kaggle.com/models/qwen-lm/qwen-3/Gguf/30b-a3b/1). The notebook selects `Qwen3-30B-A3B-Q4_K_M.gguf` from the attached model. Set `MODEL_PATH` to the exact file if multiple copies are attached.
3. Select **GPU T4 ×2**, enable Internet for the `llama.cpp` runtime, and choose **Save & Run All**. The model's layers are distributed across both GPUs. The default processes five journeys in batches of **2, 2, and 1**. Set `JOURNEYS = None` to generate all attached blueprints. [Kaggle notebook inputs](https://www.kaggle.com/docs/notebooks)
4. Download `output/candidates.jsonl`. It records every attempt and its Python format errors. A journey gets one retry after a format failure.

The Python check requires a JSON object with exactly the planned session keys and two to five nonempty, single-line strings per session. It rejects speaker-label prefixes and explicit unfilled placeholders. DeepEval evaluates address wording and factual accuracy.

## Validate candidates

1. Upload [the validation input ZIP](./stage-2/phase-3/input/stage-2-validation-input.zip) as a private Kaggle dataset and attach it to [the validation notebook](./stage-2/phase-3/validate.ipynb). It contains 140 M1 candidate journeys and their generation reference data. The notebook runs [src/validate.py](./stage-2/phase-3/src/validate.py).
2. Attach [Gemma 4 12B IT QAT Q4_0 GGUF, version 2](https://www.kaggle.com/models/google/gemma-4/gguf/gemma-4-12b-it-qat-q4_0-gguf/2). Select **GPU T4 ×2**, enable Internet, and choose **Save & Run All**. Configure installs DeepEval in a temporary Python environment and runs `pip check`. Validation reuses that environment and loads one Gemma instance per GPU from the attached model file. [Kaggle notebook inputs](https://www.kaggle.com/docs/notebooks)
3. Download `output/transcripts.jsonl` and `output/judge-report.jsonl`.

The validator checks the first attempt that passed Python formatting for each journey. DeepEval uses Gemma to check session goals, required facts, continuity, and customer-only turns. A journey passes when Gemma returns `pass` and the **persona fit** and **Vietnamese naturalness** scores each reach **0.7**. The report records the verdict, reason, and rubric scores. Journeys whose attempts all failed the format check receive `format_fail`. Only passing journeys appear in `transcripts.jsonl`. [DeepEval custom metrics](https://deepeval.com/docs/metrics-custom)

To validate a newer run from the same blueprint input, attach its generation notebook output and set `CANDIDATES_PATH` to the new `candidates.jsonl`. Set `JOURNEYS = None` to validate every candidate journey. For a different set of blueprints, use the reference files from that generation run.

## Full run checks

- Account for every requested journey in `judge-report.jsonl`, including failed and inconclusive checks.
- Retain only accepted transcripts with the original session keys and channels and two to five valid customer turns per session.
- Retain at least 120 sessions for M1 or 250 for M2 before handing the full run to downstream validation.
