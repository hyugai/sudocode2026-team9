# Evaluation và benchmark

Thư mục `src/eval/` chứa pipeline chạy scenario, ghi trace, chấm metric và đóng gói kết quả benchmark theo version cho telesale agent.

Chạy tất cả lệnh trong tài liệu này từ thư mục gốc repository bằng PowerShell.

## 1. Kiến trúc eval hiện tại

```text
scenario JSON
    │
    ▼
run_benchmark.py
    │
    ├── generate_traces.py
    │      ├── chạy DeepAgent thật
    │      ├── gọi CRM/PostgreSQL/MCP tools
    │      ├── persist self-learning memory
    │      └── ghi trace.jsonl
    │
    ├── memory_judge.py                 [tùy chọn]
    │      └── LLM-as-a-judge cho Memory Write Quality
    │
    ├── team_eval.py
    │      ├── gọi công thức từ reference_eval.py
    │      ├── tính metric mở rộng của team
    │      └── ghi report.json
    │
    └── ghi README.md cho benchmark version
```

Mỗi benchmark được cô lập trong:

```text
outputs/benchmark/benchmark_vN/
├── README.md              # cấu hình, model, thời gian và lệnh reproduce
├── trace.jsonl            # một JSON object cho mỗi turn
├── report.json            # metric tổng hợp
├── memory_judge.json      # chỉ có khi bật --judge-memory
└── memory/
    └── <customer_id>/
        ├── facts.md
        ├── episodes/
        ├── atomic_facts/
        └── foresights/
```

`run_benchmark.py` không ghi đè một version đã có dữ liệu. Muốn chạy lại phải dùng tên mới, ví dụ `benchmark_v5`, hoặc chủ động quản lý version cũ.

## 2. Vai trò của từng file

| File | Vai trò |
|---|---|
| `run_benchmark.py` | Entry point được khuyến nghị. Tạo thư mục version, cấu hình provider/model/memory, gọi trace generator, optional MWQ judge, team evaluator và tạo README tái lập run. |
| `generate_traces.py` | Đọc scenario JSON, chạy DeepAgent qua từng call/turn, thu agent response, tool calls, memory writes, usage và latency rồi ghi JSONL. Có thể cleanup chính xác các order được tạo trong eval. |
| `trace_extractors.py` | Chuyển response/tool evidence thành `questions`, `claims` và `facts_used` để reference evaluator chấm RQR, HR và CCR. Đây là heuristic/regex, không phải ground truth tuyệt đối. |
| `team_eval.py` | Bộ chấm chính của team. Import công thức BTC từ `reference_eval.py`, sau đó bổ sung Tool-Call Accuracy, cost estimate, MWQ report và RAG metrics. Hỗ trợ `--scenario-id` và `--limit`. |
| `memory_judge.py` | LLM-as-a-judge tùy chọn để chấm chất lượng memory write theo provenance, relevance, atomicity, non-redundancy, supersession, privacy và actionability. |
| `prepare_scenarios.py` | Tiện ích chuyển dataset JSONL đóng gói thành các file scenario JSON riêng. Không cần chạy nếu thư mục scenario đã có file `SC-xxx.json`. |
| `__init__.py` | Đánh dấu `eval` là Python package. |

Nguồn công thức tham chiếu:

```text
dataset/BTC-Data-Vong1-TEAMS/eval/reference_eval.py
```

`team_eval.py` tải trực tiếp file này để tránh viết lại các metric BTC theo một công thức khác.

## 3. Dữ liệu trong trace

Mỗi dòng `trace.jsonl` tương ứng một customer turn và có các field chính:

| Field | Nội dung |
|---|---|
| `scenario_id`, `call`, `turn` | Vị trí của turn trong dataset. |
| `customer_text` | Câu nói của khách ở turn hiện tại. |
| `agent_text` | Câu trả lời cuối cùng gửi cho khách. |
| `questions` | Câu hỏi và slot được `trace_extractors.py` nhận diện. |
| `facts_used` | Memory facts có bằng chứng được dùng trong response hoặc tool args. |
| `claims` | Các claim có cấu trúc lấy từ tool results để đối chiếu ground truth. |
| `tool_calls` | Tên tool, args chuẩn hóa và result của từng tool call. |
| `memory_writes` | Các fact update được persist sau turn. |
| `usage` | Số LLM request, failed request, input/output/total tokens. |
| `latency` | `ttft_ms`, `ttfa_ms` và `total_ms` nếu runtime cung cấp. |
| `_error` | Lỗi turn nếu runner không hoàn thành được turn đó. |

Không dùng một report làm kết quả chính thức nếu trace còn `_error` hoặc thiếu turn so với scenario đã chọn.

## 4. Các metric đang có

### 4.1 Repeat-Question Rate — RQR

```text
RQR = số câu hỏi thừa / tổng số câu hỏi agent đặt ra × 100%
```

- Càng thấp càng tốt.
- Chỉ chấm các call có `must_not_ask`.
- Một câu hỏi mở về slot bị cấm hỏi lại được tính là thừa.
- Câu xác nhận cùng slot từ lần thứ hai trong một call cũng bị tính là thừa.
- Nguồn dữ liệu: `questions` do regex extractor tạo ra.

### 4.2 Context Carryover Rate — CCR

```text
CCR = số fact bắt buộc được sử dụng đúng / tổng fact bắt buộc mang sang × 100%
```

- Càng cao càng tốt.
- Ground truth lấy từ `must_carry_over` trong scenario.
- Fact được xem là đã dùng khi xuất hiện trong `facts_used` hoặc tool arguments.
- CCR đo việc **sử dụng memory ở call sau**, không đo chất lượng lúc ghi memory.

### 4.3 Task Success Rate — TSR

```text
TSR = số scenario đạt toàn bộ success condition / tổng scenario được chấm × 100%
```

- Càng cao càng tốt.
- Một scenario chỉ pass khi tất cả call có `success_if` đều pass.
- Điều kiện hiện tại gồm tool name, required args, forbidden tools/claims, cụm từ bắt buộc và giới hạn số câu hỏi.
- Có báo riêng TSR cho hard cases.

### 4.4 Hallucination Rate — HR

```text
HR = số claim sai / tổng claim kiểm chứng được × 100%
```

- Càng thấp càng tốt.
- Chỉ claim có field tồn tại trong `ground_truth_facts` mới được tính.
- Report có HR tổng và HR riêng cho price/promotion.
- Claim không trích xuất được hoặc không có ground truth sẽ không vào mẫu số.

### 4.5 Tool-Call Accuracy

Đo agent có gọi đúng business tool và truyền đúng required arguments hay không.

```text
numerator   = số expected tool call khớp tên và required args
denominator = expected calls + forbidden calls + unexpected mutation calls
```

Report còn có:

- `expected_call_recall`;
- `tool_name_accuracy`;
- số missing tool;
- số wrong-argument call;
- forbidden và unexpected mutation calls.

Retrieval/read tools chỉ được chấm khi scenario yêu cầu rõ. Các mutation tool được theo dõi gồm `order.create`, `order.update`, `schedule.callback` và `handoff.transfer`.

### 4.6 Calls-to-Close

- Là số call trung bình đến lúc trace có `order.create`.
- Càng thấp càng tốt trong nhóm scenario có chốt đơn.
- Customer hiện được replay từ `customer_turns`; chưa phải customer simulator động.

### 4.7 Latency p50/p95

Report latency cho:

- `ttft`: time to first token;
- `ttfa`: time to first action nếu runtime ghi nhận được;
- `total`: tổng thời gian xử lý turn;
- `call_brief`: thời gian build call brief.

p50 phản ánh trải nghiệm điển hình. p95 phản ánh nhóm request chậm ở đuôi. Report cảnh báo khi có dưới 100 turn vì p95 lúc đó chưa ổn định.

### 4.8 Estimated Cost per Call

Tính từ:

- input/output tokens;
- tool calls;
- memory writes;
- số byte memory quan sát trong trace;
- fixed infrastructure cost nếu được cung cấp.

Giá không được hard-code. Nếu không truyền pricing flags hoặc biến môi trường `EVAL_*`, report vẫn ghi usage nhưng cost là `null`.

### 4.9 Memory Write Quality — MWQ

MWQ là LLM-as-a-judge, chấm thang 1–5 theo:

- provenance;
- relevance;
- atomicity;
- non-redundancy;
- supersession;
- privacy;
- actionability.

Điểm tổng được quy đổi sang phần trăm. MWQ đo chất lượng **ghi memory**, còn CCR đo khả năng **dùng lại memory**. MWQ mặc định không chạy vì tốn thêm một model request cho mỗi scenario.

### 4.10 Guardrail và memory checks

- `guardrail_violations`: PII không được phép, chuyển máy thừa, tự nhận là người thật và forbidden patterns.
- `memory_checks`: heuristic kiểm tra giá trị kỳ vọng có xuất hiện trong `memory_writes`; kết quả `likely_ok/review` vẫn cần review thủ công.
- `avg_turns_per_call`: số turn trung bình trên mỗi call.

### 4.11 ASR metrics — tùy chọn

Khi truyền `--asr`, evaluator có thể tính:

- WER;
- CER;
- Entity Accuracy;
- diarization turn accuracy nếu có segment/speaker ground truth;
- WER riêng cho clean/noisy dialogue.

Metric này chỉ có ý nghĩa khi đã chuẩn bị `ground_truth.json` và `hypotheses.json` đúng schema.

### 4.12 RAG metrics — tùy chọn

Khi truyền `--rag`, `team_eval.py` tính:

- recall@3, recall@5 theo tổng relevant documents;
- macro recall@k;
- hit rate@k;
- multi-hop full recall@k;
- abstention rate cho unanswerable/restricted;
- false abstention rate.

RAG metric không tự chạy trong benchmark telesale nếu chưa có RAG result và labeled QA tương ứng.

Tool tra cứu chính sách của team là MCP `search_policy`, ghi trong trace dưới tên
`policy.search`. Đây là tool mở rộng, không thay thế các tên bắt buộc của BTC:
giá/khuyến mãi dùng `pricing.get_quote`; chính sách đổi trả, bảo hành, giao hàng
dùng `policy.search`. Mỗi kết quả policy có `chunk_id` dạng `DT-03` để đối chiếu
với `rag/qa_labeled.json`. Trace benchmark telesale không tự biến thành RAG
result: muốn tính recall@k vẫn phải tạo artifact kết quả cho bộ QA và truyền
`--rag`. Các scenario có `success_if.tool_called = null` vẫn cho TCA là N/A,
không phải lỗi của tên `policy.search`.

## 5. Cách chạy khuyến nghị

### 5.1 Smoke test SC-001–003 bằng Gemini

```powershell
.\.venv\Scripts\python.exe src\eval\run_benchmark.py `
  --version benchmark_v5 `
  --limit 3 `
  --llm-provider gemini `
  --llm-model gemini-3-flash-preview `
  --request-timeout 60 `
  --memory-persister-mode llm_learning `
  --persist-memory `
  --cleanup-orders `
  --sleep 20 `
  --sleep-scenario 3 `
  --max-retries 1
```

Các API key và `DATABASE_URL` được đọc từ `.env`; không được copy vào thư mục output.

### 5.2 Chạy đúng một scenario

```powershell
.\.venv\Scripts\python.exe src\eval\run_benchmark.py `
  --version benchmark_v6 `
  --scenario-id SC-003 `
  --llm-provider gemini `
  --llm-model gemini-3-flash-preview `
  --memory-persister-mode llm_learning `
  --persist-memory `
  --cleanup-orders
```

### 5.3 Chạy full benchmark

```powershell
.\.venv\Scripts\python.exe src\eval\run_benchmark.py `
  --version benchmark_v7 `
  --scenarios "dataset\iterative-refinement\scenarios_complete dataset" `
  --llm-provider gemini `
  --llm-model gemini-3-flash-preview `
  --memory-persister-mode llm_learning `
  --persist-memory `
  --cleanup-orders `
  --sleep 20 `
  --sleep-scenario 3 `
  --max-retries 1
```

Không bật `--judge-memory` ngay trong full run nếu quota chưa được kiểm tra. Có thể judge một subset sau khi trace hoàn tất.

### 5.4 Chấm lại trace mà không gọi agent

Ví dụ trace chỉ chứa ba scenario đầu:

```powershell
.\.venv\Scripts\python.exe src\eval\team_eval.py `
  --scenarios "dataset\iterative-refinement\scenarios_complete dataset" `
  --limit 3 `
  --trace "outputs\benchmark\benchmark_v5\trace.jsonl" `
  --out "outputs\benchmark\benchmark_v5\report.json"
```

Phải truyền lại cùng `--scenario-id` hoặc `--limit` đã dùng khi generate. Nếu không, report sẽ lấy các scenario không tồn tại trong trace làm failure và mẫu số bị sai.

### 5.5 Chạy MWQ cho một subset

```powershell
.\.venv\Scripts\python.exe src\eval\memory_judge.py `
  --scenarios "dataset\iterative-refinement\scenarios_complete dataset" `
  --limit 3 `
  --trace "outputs\benchmark\benchmark_v5\trace.jsonl" `
  --provider gemini `
  --model gemini-3-flash-preview `
  --out "outputs\benchmark\benchmark_v5\memory_judge.json"
```

Sau đó chấm lại và gắn report MWQ:

```powershell
.\.venv\Scripts\python.exe src\eval\team_eval.py `
  --scenarios "dataset\iterative-refinement\scenarios_complete dataset" `
  --limit 3 `
  --trace "outputs\benchmark\benchmark_v5\trace.jsonl" `
  --memory-judge-report "outputs\benchmark\benchmark_v5\memory_judge.json" `
  --out "outputs\benchmark\benchmark_v5\report.json"
```

### 5.6 So sánh với baseline không memory

Chạy một version riêng với:

```powershell
--config baseline_no_memory --no-persist-memory
```

Sau đó truyền trace baseline vào `team_eval.py` bằng `--baseline`.

## 6. Memory mode khi eval

`run_benchmark.py` hỗ trợ:

| Mode | Mục đích |
|---|---|
| `turn` | Persist fact bằng `TurnMemoryPersister`, không gọi thêm LLM. |
| `deterministic` | Hiện là alias của `turn`; cũng dùng `TurnMemoryPersister`. |
| `llm_episode` | Persist fact deterministic, atomic-fact audit; gọi thêm LLM để tạo episode và foresight. |
| `llm_learning` | Hiện dùng cùng `LLMPersister` với `llm_episode`; đây là tên mode mặc định cho benchmark self-learning. |

Với `--persist-memory`, mỗi benchmark dùng memory root riêng trong thư mục version. Điều này ngăn memory của benchmark cũ làm nhiễu run mới. `--no-persist-memory` chỉ phù hợp smoke test dùng memory tạm.

`--cleanup-orders` xóa các order eval bằng đúng `order_id` sau mỗi scenario. File memory snapshot vẫn được giữ để audit việc agent đã học gì.

## 7. Lỗi và giới hạn eval còn tồn tại

### P0 — Có thể làm metric tốt hơn thực tế

1. **TSR chưa kiểm tra tool result.** Reference evaluator chỉ kiểm tra tool đã được gọi với args khớp. Trong `benchmark_v4`, SC-003 gọi đúng `order.create` nhưng result là `out_of_stock`; evaluator vẫn tính scenario pass. Cần thêm Tool Execution Success và dùng result khi quyết định task success.

2. **Calls-to-Close cũng chỉ nhìn thấy `order.create`.** Một order call thất bại vẫn có thể bị tính là đã close.

3. **Tool-Call Accuracy không phải Tool Execution Accuracy.** Metric hiện tại không phạt tool trả business error nếu tên và required args đúng.

### P1 — Extraction còn heuristic

4. **RQR có false positive.** Regex có thể gán câu “có muốn em lên đơn không?” thành hỏi lại product/price vì trong cùng câu có từ khóa liên quan. Cần cải thiện question/slot extractor hoặc bổ sung judge cho các case mơ hồ.

5. **HR chưa phủ toàn bộ free text.** HR chỉ chấm claim được extract và có field trong `ground_truth_facts`. Những câu như “địa chỉ cũ” hoặc “nhu cầu an toàn cho bé như anh đã chia sẻ” có thể sai nhưng không bị HR hiện tại bắt.

6. **CCR không chứng minh memory được ghi đúng.** CCR chỉ biết fact xuất hiện trong output/tool args. Dùng MWQ và memory checks để đánh giá write quality, provenance và supersession.

7. **Memory checks chỉ là heuristic substring.** `likely_ok` không thay thế review nội dung thật của `facts.md`, episode và atomic facts.

### P1 — Độ bền runner

8. **Chưa có resume/checkpoint chính thức.** `generate_traces.py` mở trace ở mode ghi mới. Nếu full benchmark dừng giữa chừng, chưa có cờ `--resume` an toàn để tiếp tục từ turn cuối.

9. **Rate limit đang sleep theo turn/scenario, không theo từng LLM request nội bộ.** Một turn `llm_learning` có thể tạo nhiều request liên tiếp. Với `benchmark_v4`, 18 turn đã tạo 71 request.

10. **Retry có thể replay toàn bộ turn.** Mutation cần idempotency đầy đủ để retry/resume không tạo order hoặc callback trùng.

11. **Trace chưa ghi đầy đủ model finish reason.** Vì vậy response bị cắt do max tokens/timeout chưa được phân loại chắc chắn, và chưa có truncation-rate metric.

12. **MWQ mặc định chưa chạy.** Nếu không có `memory_judge.json`, report trả `status=not_run`; không được diễn giải là memory quality bằng 0 hay đạt yêu cầu.

13. **Cost chỉ là estimate có cấu hình.** Nếu chưa truyền giá, cost là `null`. Database, hosting, network và các chi phí không có rate sẽ không tự xuất hiện.

14. **p95 cần đủ mẫu.** Với dưới 100 turn, p95 chỉ dùng để quan sát smoke test, không nên đưa thành kết luận hiệu năng chính thức.

15. **ASR và RAG không tự động thuộc pipeline telesale hiện tại.** Chúng chỉ được tính khi cung cấp đúng artifacts đầu vào.

16. **Các tên memory mode chưa hoàn toàn tách biệt về implementation.** `turn` và `deterministic` đang đi cùng một code path; `llm_episode` và `llm_learning` cũng đi cùng một code path. Không nên so sánh bốn mode như bốn thuật toán độc lập ở thời điểm hiện tại.

### Lỗi runtime được benchmark phát hiện, không phải lỗi công thức eval

- SC-003 có lệch ngày nghiệp vụ: inventory được kiểm tra tại `call_date`, nhưng `order.create` trong trace không nhận `on`, dẫn tới tool kiểm tra ngày mặc định và trả `out_of_stock`.
- Có turn chạm tool-call limit và agent trả chuỗi lỗi kỹ thuật trực tiếp cho khách.
- Có response Gemini bị cắt giữa câu; trace hiện chưa có đủ `finish_reason` để kết luận chính xác nguyên nhân.

Các lỗi này phải được sửa trong orchestration/tool runtime. Đồng thời evaluator vẫn cần được nâng cấp để các lỗi business-result như trên làm TSR fail đúng cách.

## 8. Checklist trước khi công bố benchmark

- [ ] Dùng version output mới và không thay code trong lúc run.
- [ ] Scenario selector của generate và score giống nhau.
- [ ] Trace không có `_error` và đủ số turn mong đợi.
- [ ] Review tool `result`, không chỉ nhìn TSR/Tool-Call Accuracy.
- [ ] Review một số `facts.md`, episode, atomic facts và foresights.
- [ ] Xác nhận order/callback không bị tạo trùng và cleanup đúng scope.
- [ ] Ghi đúng provider, model, memory mode, commit và dirty-worktree status.
- [ ] Với full run, kiểm tra quota trước khi bật MWQ judge.
- [ ] Ghi rõ các limitation trên khi báo cáo kết quả cho leader.
