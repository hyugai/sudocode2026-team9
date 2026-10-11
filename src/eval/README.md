# Chạy BTC evaluation

Chạy các lệnh bên dưới từ thư mục gốc của repository bằng PowerShell.

## 1. Smoke test

Smoke test một scenario trước khi chạy toàn bộ tập public:

```powershell
$env:PYTHONPATH = "src"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
.\.venv\Scripts\python.exe src\eval\generate_traces.py `
  --scenario-id SAMPLE-01 `
  --config full `
  --run-id smoke_public
```

Runner mặc định đọc input từ:

```text
dataset/BTC-Data-Vong1-TEAMS/test_set/public_sample
```

Trace mặc định được ghi vào:

```text
dataset/BTC-Data-Vong1-TEAMS/eval/runs/<run-id>.jsonl
```

Một smoke test chỉ được xem là thành công khi mọi dòng đều có `agent_text` và không có field `_error`.

## 2. Chạy toàn bộ public sample

```powershell
$env:PYTHONPATH = "src"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
.\.venv\Scripts\python.exe src\eval\generate_traces.py `
  --scenarios "dataset\BTC-Data-Vong1-TEAMS\test_set\public_sample" `
  --config full `
  --run-id full_public `
  --sleep 3 `
  --sleep-scenario 5
```

> **Mẹo tránh Rate Limit (TPM/RPM) trên Groq**:
> - Dùng cờ `--sleep <số_giây>` (mặc định 2s) để dãn khoảng cách giữa các turn.
> - Dùng cờ `--sleep-scenario <số_giây>` (mặc định 3s) để nghỉ giữa các kịch bản.
> - Hệ thống đã tích hợp **tự động bắt lỗi RateLimitError (429 / TPM limit) và retry backoff** (tự động ngủ đúng số giây Groq yêu cầu rồi tiếp tục lượt hội thoại mà không bị hủy).

## 3. Chấm trace

```powershell
.\.venv\Scripts\python.exe `
  dataset\BTC-Data-Vong1-TEAMS\eval\reference_eval.py `
  --scenarios "dataset\BTC-Data-Vong1-TEAMS\test_set\public_sample" `
  --trace "dataset\BTC-Data-Vong1-TEAMS\eval\runs\full_public.jsonl" `
  --out "dataset\BTC-Data-Vong1-TEAMS\eval\runs\full_public_report.json"
```

## 4. Kiểm tra nhanh trace lỗi

```powershell
$rows = Get-Content "dataset\BTC-Data-Vong1-TEAMS\eval\runs\full_public.jsonl" |
  ForEach-Object { $_ | ConvertFrom-Json }

$rows | Where-Object { $_._error } |
  Select-Object scenario_id, call, turn, _error
```

Không dùng report làm kết quả chính thức nếu trace còn `_error`.

## Trạng thái runner hiện tại

- Runner dùng `build_deepagent_harness_async()` và đọc đúng public test set.
- Windows stdout/stderr được đặt UTF-8 để `--help` và tiếng Việt không lỗi encoding.
- MCP order import đã được sửa sang package `mcp_servers.tools`.
- Model DeepAgent lấy từ `GROQ_MODEL`, sau đó `MODEL_NAME`, và mặc định là `openai/gpt-oss-20b`.
- Checkpoint mặc định có scope `turn`; các turn không replay toàn bộ raw history của DeepAgent.
- Cuối mỗi turn, fact mới được upsert vào evaluation memory. Đầu turn sau memory được reload và call brief được build lại từ trạng thái mới nhất.
- `tool_calls`, `questions`, `claims`, `facts_used` và `memory_writes` được ghi vào trace.
- `baseline_no_memory` dùng repository rỗng và không persist memory.
- Các call được tách `ConversationState`; carry-over giữa call chỉ đi qua customer memory.
- DeepAgent ẩn các built-in filesystem/execute/subagent tool không dùng để giảm tool-schema token.

Các giới hạn context có thể chỉnh qua `.env`: `GROQ_MAX_OUTPUT_TOKENS`,
`DEEPAGENT_RECENT_MESSAGE_COUNT`, `DEEPAGENT_RECENT_MESSAGE_CHARS` và
`DEEPAGENT_RECENT_CONTEXT_CHARS`. Không đổi `DEEPAGENT_CHECKPOINT_SCOPE` sang
`conversation` khi chạy BTC nếu tài khoản Groq có giới hạn TPM thấp.

