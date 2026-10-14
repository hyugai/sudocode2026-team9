# benchmark_v4

## Run status

- Status: `completed`
- Started at: `2026-10-14T00:13:15+07:00`
- Finished at: `2026-10-14T00:24:00+07:00`
- Dataset: `sudo_code_2026-group_9\dataset\iterative-refinement\scenarios_complete dataset`
- Scenario selector: `first 3`
- Trace: `trace.jsonl`
- Report: `report.json`
- Turn errors: `0`

## Parameters

- Config: `full`
- LLM provider: `gemini`
- LLM model: `gemini-3-flash-preview`
- LLM request timeout: `60.0` seconds
- LLM provider-internal retries: `0`
- LLM max output tokens: `768`
- Memory mode: `durable files`
- Durable memory writes: `True`
- Memory persister: `llm_learning`
- Memory root: `memory/`
- PostgreSQL eval-order cleanup: `True`
- Sleep between turns: `20.0` seconds
- Sleep between scenarios: `3.0` seconds
- Max retries per turn: `1`
- Max turns per scenario: `None`
- Team evaluator: `team_eval_v1`
- Memory Write Quality judge enabled: `False`
- Judge provider/model: `gemini` / `gemini-3-flash-preview`
- Input price / 1M tokens: `None` USD
- Output price / 1M tokens: `None` USD
- Tool call price: `None` USD
- Memory write price: `None` USD
- Memory storage price / MB: `None` USD
- Fixed infrastructure price / call: `None` USD
- Python: `3.12.3`
- Git commit: `5c4afd3`
- Dirty worktree at run time: `True`

## Reproduce

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe src\eval\run_benchmark.py --version benchmark_v4 --limit 3 --llm-provider gemini --llm-model gemini-3-flash-preview --request-timeout 60.0 --memory-persister-mode llm_learning --persist-memory --cleanup-orders --sleep 20.0 --sleep-scenario 3.0 --max-retries 1
```

Notes:

- API keys and `DATABASE_URL` are read from `.env` and are never copied here.
- By default, each benchmark version writes its own customer `.md` files under `memory/`; later calls read those files.
- Use `--no-persist-memory` only for a disposable in-memory smoke test.
- Orders created during evaluation are deleted by exact `order_id` after the scenario unless `--no-cleanup-orders` is used.
- MWQ uses an extra post-run LLM request per scenario only when `--judge-memory` is enabled.
- Calls-to-Close currently replays scripted `customer_turns`; it is not a dynamic customer-agent simulation.
- A one-scenario smoke test is useful for regression checking, but its aggregate metrics are not statistically representative.
