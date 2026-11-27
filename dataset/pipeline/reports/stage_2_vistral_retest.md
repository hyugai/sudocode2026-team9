# Stage 2 Vistral retest

The corrected Vistral setup generated Vietnamese dialogue for **all six M1 journeys**. Its prompt grew from **4 tokens on each request** to **818–1,176 tokens**. All six drafts still failed first-pass validation because required fact markers were missing. [Writer comparison](./stage_2_writer_comparison.md)

## Template diagnosis and fix

The original notebook loaded Vistral-7B-Chat and returned six structurally valid JSON drafts. The turns contained placeholders such as `llama1` and `llama2`. The worker log recorded four input tokens on each request, consistent with rendering the bare `llama2` override as template text.

The worker now supplies Vistral's published chat format. It checks the server's rendered prompt before generation and raises an error if either the system instructions or the complete scenario request is missing. The retest confirmed a 3,393-character rendered prompt for the first request. Both Vistral runs used the same checkpoint, six request payloads, seed `2026`, and temperature `0.7`. Gemma scored the retest with the original rubric. [Vistral prompt format](https://huggingface.co/uonlp/Vistral-7B-Chat-gguf#prompt-template-vistral-7b-chat) · [Stage 2 worker](../stage-2/src/worker.py)

## Retest scores

| Scenario | First-pass validation | Naturalness | Persona fit | Continuity |
| --- | --- | ---: | ---: | ---: |
| `SC-001` | Rejected | 0.20 | 0.20 | 0.20 |
| `SC-059` | Rejected | 0.50 | 0.40 | 0.40 |
| `SC-062` | Rejected | 0.40 | 0.40 | 0.30 |
| `SC-088` | Rejected | 0.20 | 0.00 | 0.00 |
| `SC-125` | Rejected | 0.40 | 0.30 | 0.30 |
| `SC-130` | Rejected | 0.40 | 0.40 | 0.30 |
| **Mean across all six** | **0/6 passed** | **0.35** | **0.28** | **0.25** |

- `SC-059` captured why the customer wanted an exchange, but asked for “size lớn hơn.” The blueprint required **size 40**.
- `SC-088` switched into the agent's role with “đây là hotline của shop.” Stage 2 expects customer turns only.
- Across the five scenarios available for all three writers, Vistral averaged **0.34 naturalness**, **0.26 persona fit**, and **0.24 continuity**. Both Qwen writers scored higher on all three metrics for this pilot.

## Kaggle runs

| Job | Version | Result |
| --- | ---: | --- |
| [Original Vistral generation](https://www.kaggle.com/code/hyugai/s2-pilot-vistral-7b-9c1d6ac7fa) | 1 | Six placeholder drafts |
| [Vistral generation with the corrected template](https://www.kaggle.com/code/hyugai/s2-vistral-retest-4d70fe3426) | 1 | Six dialogue drafts in 2m 49s including startup |
| [Gemma scoring of the corrected drafts](https://www.kaggle.com/code/hyugai/s2-vistral-retest-judge-1faed23e72) | 1 | All six drafts scored |
