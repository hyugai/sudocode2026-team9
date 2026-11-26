# Stage 2 writer comparison

The Kaggle pilot compared Qwen3.5-4B, Qwen3.5-9B, and Vistral-7B-Chat on six M1 blueprints. **Each writer produced 0 of 6 transcripts that passed first-pass validation.** Qwen3.5-9B received the highest persona and continuity scores. The Qwen models tied on Vietnamese naturalness. Vistral's results below come from the corrected retest. [Vistral retest](./stage_2_vistral_retest.md)

## Pilot setup

The writers received byte-identical requests covering 13 planned sessions from Stage 1 run `run_M1_20261120_1610`. The pilot used seed `2026`, temperature `0.7`, one Kaggle T4 per worker, and llama.cpp build `b11627`. Each request asked for customer turns only, with 2–5 turns per session and exact markers for protected facts such as price, payment, size, and delivery address. DeepEval used the same Gemma 4 12B judge and rubric for every writer. [Stage 1 manifest](../stage-1/runs/run_M1_20261120_1610/manifest.json) · [Stage 2 instructions](../stage-2.md)

| Scenario | Journey pattern | Sessions |
| --- | --- | --- |
| `SC-001` | Consults family before buying | Hotline → hotline |
| `SC-059` | Continues across channels and requests a size exchange | Zalo → hotline |
| `SC-062` | Returns after a promotion expires | Hotline → hotline |
| `SC-088` | Asks about a product, buys it, then requests an exchange | Hotline → hotline → hotline |
| `SC-125` | Two people share a phone number | Facebook → hotline |
| `SC-130` | Requests help outside the shop's scope and accepts a transfer | Hotline → hotline |

## Results

| Writer | Drafts returned | First-pass valid | Naturalness | Persona fit | Continuity | Worker time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3.5-4B Q4_K_M | 6/6 | 0/6 | 0.38 | 0.44 | 0.56 | 4m 22s |
| Qwen3.5-9B Q4_K_M | 5/6 | 0/6 | 0.38 | 0.70 | 0.60 | 5m 57s |
| Vistral-7B-Chat Q4_0, corrected template | 6/6 | 0/6 | 0.34 | 0.26 | 0.24 | 2m 49s |

The Gemma columns are mean scores on a 0–1 scale for the five scenarios all three writers completed. Qwen3.5-9B reached the 2,048-token output limit on `SC-062`. Worker time includes startup and generation. Time per accepted transcript is undefined because no draft passed validation.

- Both Qwen writers frequently wrote fact values directly where the importer expected markers. Vistral also omitted markers, and some drafts left the corresponding detail out of the dialogue.
- In a text review with writer names hidden, Codex preferred 4B's wording on four of the five paired Qwen drafts and 9B's wording on `SC-059`. This was a qualitative comparison of the two Qwen writers.
- The Gemma scores describe draft quality. The validator separately checks fact markers before a draft can be assembled into a Stage 2 transcript. This six-journey pilot leaves the production acceptance rate unmeasured.

**Keep 4B as the baseline for the next comparison.** Test whether putting the required facts into the output structure improves first-pass validation for both Qwen writers. Compare their naturalness and persona scores again under that shared format.

## Kaggle runs

| Job | Version |
| --- | ---: |
| [Qwen3.5-4B generation](https://www.kaggle.com/code/hyugai/s2-pilot-qwen35-4b-e8afd52f0c) | 1 |
| [Qwen3.5-9B generation](https://www.kaggle.com/code/hyugai/s2-pilot-qwen35-9b-a294d9bc93) | 1 |
| [Vistral generation with the corrected template](https://www.kaggle.com/code/hyugai/s2-vistral-retest-4d70fe3426) | 1 |
| [Original Gemma scoring batch 1](https://www.kaggle.com/code/hyugai/s2-pilot-writer-judge-1057f54cc0) | 1 |
| [Original Gemma scoring batch 2](https://www.kaggle.com/code/hyugai/s2-pilot-writer-judge-8cb8774a60) | 1 |
| [Vistral retest scoring](https://www.kaggle.com/code/hyugai/s2-vistral-retest-judge-1faed23e72) | 1 |
