# benchmark_v3 — parallel benchmark

## Run status

- Status: `completed_with_errors`
- Started at: `2026-10-17T19:46:16+07:00`
- Finished at: `2026-10-17T20:32:49+07:00`
- Dataset: `D:\DOCUMENT\School\SUDO\sudo_code_2026-group_9\dataset\iterative-refinement\scenarios_complete dataset`
- Workers: `2`
- Trace rows: `770`
- Turn errors: `1`
- Worker/scenario process failures: `0`

## Partitioning

Scenarios are grouped by `customer_phone`, then balanced by total customer
turns. The same phone never runs in two workers. Every scenario uses an isolated
memory directory at `part_<N>/memory/<SCENARIO_ID>/`.

- Worker 1: 59 scenarios, 385 turns
- Worker 2: 61 scenarios, 385 turns

See `partitions.json` for the scenario assignment and each
`part_<N>/worker.log` for raw runner output.

## Parameters

- Config: `full`
- Provider/model: `gemini` / `gemini-3.6-flash`
- Request timeout: `30` seconds
- Max output tokens: `1524`
- Thinking level: `low`
- Memory persister: `llm_learning`
- Durable memory: `True`
- Cleanup eval orders: `True`
- Sleep between turns: `0.0` seconds
- Sleep between scenarios in one worker: `0.0` seconds
- Max retries per turn: `1`
- Max turns per scenario: `None`
- Python: `3.12.3`
- Git commit: `ca426d7`
- Dirty worktree at run time: `True`

## Reproduce

```powershell
.\.venv\Scripts\python.exe src\eval\run_parallel_benchmark.py --version benchmark_v3 --workers 2 --llm-provider gemini --llm-model gemini-3.6-flash --thinking-level low --max-output-tokens 1524 --memory-persister-mode llm_learning --persist-memory --cleanup-orders --max-retries 1
```

## Artifacts

- `trace.jsonl`: merged trace in dataset order.
- `report.json`: aggregate report for the selected scenarios.
- `partitions.json`: worker assignment without duplicating phone values.
- `part_<N>/trace.jsonl`: trace for one worker.
- `part_<N>/memory/<SCENARIO_ID>/`: isolated `.md` memory for audit.
- `part_<N>/worker.log`: stdout/stderr of worker process.
