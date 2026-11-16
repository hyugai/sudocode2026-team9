# Self Agent: post-session Knowledge Gap Loop

Thiết kế hiện hành và lịch sử trace: [knowledge-gap-loop-plan.md, mục 14](../../docs/implementation/knowledge-gap-loop-plan.md#14-thiết-kế-hiện-hành-english-lessons-routing-và-response-validation).
Lesson mới được sinh và kiểm tra bằng tiếng Anh, lưu `lessons/approved/*.md`.
Vòng 1 đóng băng lesson từ đúng vòng 0; mỗi câu hỏi chỉ nhận tối đa ba lesson
được router chọn theo ý nghĩa và ngữ cảnh gần nhất, không bắt khớp cụm trigger.
Validator có một lần sửa lời đáp, không chạy lại business tool;
lỗi kiểm tra dùng fallback. Xem `turns[].lesson_trace` để biết lesson nào thực
sự được đưa vào generate, đã pass/repaired/fallback hay chưa được gọi.
Validator nhận cả tool do harness chạy trước generate, knowledge của lượt hiện
tại và tool message mới. Claim nghiệp vụ phải cite evidence ID hợp lệ; lesson
và fallback không phải nguồn chính sách. Thiếu nguồn chỉ được nói chưa xác minh,
không suy ra dịch vụ không tồn tại hoặc hứa một quy trình thay thế. Runtime áp
dụng quy tắc fallback này cho cả lesson cũ. Xem `evidence_stages/origins`,
`tool_evidence_count`, `source_evidence_count`, `initial_grounding_valid` trong trace.
Citation vẫn cần model kiểm tra ý nghĩa; `passed` không bảo đảm tuyệt đối đúng.
Routing và validation là chi phí online riêng có thể tăng latency/token khi bật lesson;
benchmark gốc không cài layer này. Bản này cần chạy vòng 0/vòng 1 mới, không
tự nâng cấp artifact cũ chỉ có câu nhắc chung thành lesson được duyệt.

Hướng dẫn [nối API end session và test từng scenario](../../docs/implementation/self-learning-be-integration-and-testing.md): mô tả trạng thái hiện tại, các hook BE cần thêm và cách đọc artifact sau mỗi call. API backend chưa được nối tự động.

Package độc lập bọc base harness; benchmark `src/eval` không import package này.
`KNOWLEDGE_GAP_LOOP_ENABLED` mặc định `false`. Không có worker/model/artifact học
khi tắt. Không có hook vào core, web hay API.

## Chạy

Cài project và dependencies theo README gốc. Trong PowerShell:

```powershell
$env:KNOWLEDGE_GAP_LOOP_ENABLED='true'
python -m self_agent.runner 'Mua bằng voucher có đổi size được không?'
```

Runner gọi `end_session` rồi chủ động đợi worker, ngoài thời gian trả lời.
Đóng wrapper không tự sinh job, nhưng hủy công việc đang chạy và giữ job để retry.
Một process/worker ghi vào một root; không chạy nhiều runner cùng root.

Agent memory chỉ giữ lesson dùng cho lần sau:
`data/memory-root/agents/telesales_agent/knowledge_gap_loop/lessons/approved/*.md`.
Toàn bộ JSON trung gian (`gaps`, `patterns`, `knowledge`, `regression_cases`,
`releases`) cùng job/snapshot/report/token/thời gian nằm ở
`outputs/self-agent/learning-runtime/`. Pattern JSON phục vụ trace và chọn lesson
cho thí nghiệm; không phải một bản memory thứ hai.
Không có lesson hợp lệ thì agent memory có thể rỗng, dù job chạy thành công.
Queue chưa hoàn tất cũng ở runtime root; không xóa thư mục này nếu muốn retry.
Deployment cần lưu runtime root trên storage bền vững nếu yêu cầu phục hồi job.
`LearningConfig.runtime_root` có thể được inject riêng, không cần thêm env switch.
File JSON kiến thức giữ
nguyên cả đoạn nguồn được chọn, không tạo chính sách mới. LLM chọn đoạn rồi một
lượt kiểm tra khác xác minh; thiếu nguồn thì pending. Đây là biện pháp giảm sai,
không thay thế xác minh chính sách mới của người phụ trách.

Snapshot v2 có transcript, message ID và bằng chứng từng lượt từ `turn_results`:
phản hồi agent, tool name/args/result và knowledge sources. Hai runner đã truyền
kết quả từng lượt. Khi bên gọi không truyền hoặc thiếu lượt, report ghi coverage
thiếu; không tự coi nguồn cuối session là nguồn cho tất cả lượt.

Giữ giá, ngân sách, ngày và SKU phục vụ đối chiếu. Mask điện thoại/email, số tài
khoản/CCCD, mã đơn, địa chỉ và các trường PII đã biết trong identity/tool payload.
Masking dựa vào key, giá trị đã biết và regex, chưa phải bộ nhận diện PII tổng quát;
snapshot vẫn cần bảo vệ quyền truy cập. Artifact cũ không được tự viết lại.

Detector bắt cả unanswered question và unsupported/wrong answer, dùng message ID
để lấy câu gốc thay vì bắt LLM chép nguyên văn. Với lỗi suy luận, sai ngữ cảnh hoặc
tool, cần đối chiếu evidence qua một lượt kiểm tra. Thiếu bằng chứng thì giữ
pending; không coi câu trả lời tự tin là nguồn đúng. Sau kiểm tra, `patterns/`
chỉ lưu quy tắc chung theo loại lỗi, không chép câu khách, số tiền, SKU hay địa chỉ.
Các câu hỏi trong gap/FAQ/test dùng template chung; nội dung nguồn nghiệp vụ được
giữ để kiểm tra chính sách. Pattern đạt kiểm tra có status approved, nhưng gap
vẫn pending_remediation: ghi bài học không có nghĩa đã sửa hành vi model. Pattern
không tự đổi prompt của backend/benchmark hoặc publish Pinecone. Chế độ opt-in
`--round 1` áp dụng pattern chung đã duyệt vào bản instruction riêng của runner.

## Tái sử dụng DB/Pinecone hiện có

Runner giữ nguyên `KNOWLEDGE_BACKEND`, `PINECONE_INDEX_NAME`,
`PINECONE_NAMESPACE` và các cấu hình retrieval hiện tại. Worker tìm nguồn qua
`base.mcp_tools["search_policy"]`; không tạo Chroma, index mới hay đổi embedding.
Agent memory chỉ lưu lesson đã duyệt; FAQ ứng viên, test và báo cáo ở outputs.

`adapters.knowledge.publish_pinecone(chunks, index, namespace=...)` nhận instance
index đang có và ghi text records bằng `upsert_records`. Backend dùng model
embedding của index đó. Publication là thao tác tường minh, chưa tự gọi sau mỗi
job; runner hiện cập nhật artifact sau session, chưa tự đưa FAQ vào Pinecone.
Chỉ gọi publisher với nội dung đã kiểm tra và namespace đích đã chọn. Pinecone
có độ trễ nhất quán nên trạng thái submitted không có nghĩa đã tìm kiếm được ngay.

`build_release(..., build=publisher)` kiểm tra corpus/FAQ rồi ủy quyền cho backend
hiện có, không tự dựng database. Để benchmark giữ cùng knowledge, dùng namespace
học riêng trong cùng index, hoặc chỉ phát hành vào nguồn dùng chung giữa các vòng
đánh giá đã chốt. Tách code không tự ngăn thay đổi dữ liệu dùng chung.

## Minh chứng M1 và kiểm thử

### Hai vòng trên cùng bộ SC đã phát hiện lỗi

```powershell
.\scripts\run_self_learning_two_rounds.ps1 -Judge
```

Mặc định chạy lại SC-121 và SC-123 trong `dataset/main/m2_transcripts/scenarios_complete`.
Vòng 0 dùng instruction gốc, học sau session; vòng 1 dùng bản instruction chốt
các pattern approved có evidence refs. Cả hai vòng có user memory RAM ban đầu
trống, không seed từ file user cũ; memory giữa các call cùng SC vẫn được giữ.
Không được lấy run cũ trước bản sửa làm baseline vì đã thay chính sách seed.

Mỗi lần chạy script có kho học mới dưới `<output>/learning-memory/`.
Vòng 0 không đọc pattern/FAQ của bất kỳ lần chạy trước. Vòng 1 chỉ lấy pattern
approved trong `artifact_changes` của chính report vòng 0, kiểm tra job/evidence
provenance; không quét kho pattern toàn cục. `generation_context` trong từng report
ghi instruction hash/root, lesson_sources và applied_patterns để kiểm tra đầu vào
generate. Nếu vòng 0 không sinh bài học hợp lệ, vòng 1 giữ prompt gốc và báo
`lessons_loaded: false`; không dùng pattern cũ hoặc ép tạo lỗi để làm đẹp điểm.

`round_manifest.lessons_loaded` chỉ xác nhận có lesson. Xem `turns[].lesson_trace`:
`routing`, `selected_lessons`, `injected`, `validation`, `routing_ms/usage` và
`wrapper_total_ms`. Router lỗi thì giữ base flow và ghi `routing: failed`, không
giả làm không có lesson phù hợp. `injected: true` xác nhận context đã vào lời
gọi agent; `validation: not_invoked` cảnh báo base đã đi đường không qua decorator.
Router duyệt mọi lesson approved theo lô tối đa 24, rồi chọn tối đa ba; không có
lọc keyword trước bước chọn theo nghĩa. Model vẫn có thể chọn sai, cần đọc trace.

Khi bật `-Judge`, `comparison.json` có hai phép đo riêng: `quality` cho mục tiêu
session và `lesson_quality.quality` cho chính tiêu chí lesson đã đóng băng, chấm
cả hai vòng kể cả khi router bỏ sót. `learning_applied` trong comparison chỉ true
khi có lượt thật sự `injected`; `learning_runtime` báo số lượt chọn/đưa lesson vào
generate và lỗi routing. Không có cặp applicable ở cả hai vòng thì điểm lesson
là null. Đây là đánh giá lỗi mục tiêu học từ vòng 0, không phải điểm tổng quát
độc lập; judge vẫn cần được đối chiếu bằng chứng.

`outputs/self-agent/two-rounds/<timestamp>/` có round0, round1 và comparison.json
khi bật `-Judge`. Round manifest chặn thay bộ test, model/retrieval settings đã
ghi và instruction gốc; bản instruction áp dụng ghi rõ các pattern đã chọn.
Không cập nhật instruction giữa các call trong cùng vòng. Backend/benchmark gốc
không đọc instruction này; Pinecone và DB không bị chuyển backend.

`-Judge` gọi thêm LLM chấm theo cùng scenario spec/evidence ở cả hai vòng, tách
khỏi learner. Comparison báo tỷ lệ đạt, chênh lệch điểm phần trăm, sai→đúng,
đúng→sai, tỷ lệ sửa lỗi và detector failures. Đây là điểm judge bằng mô hình,
cần xem rationale, không tự xem là đáp án tuyệt đối. Chi phí/thời gian chấm và
học không cộng vào latency hội thoại. Giữ DB/catalog/chính sách tương đương khi
chạy hai vòng; manifest chưa tự snapshot toàn bộ dịch vụ ngoài.

LLM học có output budget riêng 4096 và retry JSON tối đa hai lần mỗi request;
nếu detector vẫn lỗi, job/report failed thay vì no_candidates. Open question
vẫn được ghi backlog, nhưng không dùng lỗi parser như minh chứng không có gap.

### Chạy 2 scenario song song

```powershell
.\scripts\run_self_learning_unseen.ps1 -Limit 5 -Workers 2
```

Chạy tối đa hai process SC, mỗi process có base harness, customer memory RAM,
MCP connections và kho learning riêng. Các call/lượt trong cùng SC vẫn tuần tự;
end call mới học. SC cùng số điện thoại được serialize để tránh thao tác đồng
thời trên cùng khách trong DB. DB/catalog/Pinecone vẫn dùng chung cấu hình,
không phải bản sao database riêng; quota/rate limit vẫn dùng chung.

Trong thư mục output có `summary.json` và `<SC-ID>/` chứa report từng call,
`console.log`, `runtime/` chứa toàn bộ JSON trung gian. Lesson nằm riêng tại
`<output>/learning-memory/<SC-ID>/lessons/approved/`;
đường dẫn được ghi trong summary. Không tự merge các pattern/knowledge về kho
chung vì cần kiểm tra trùng và xung đột trước. Một SC lỗi được ghi failed, các
SC khác tiếp tục; runner trả exit code 1 nếu có lỗi. Đường output phải chưa tồn tại.

Chỉ liệt kê lựa chọn, không gọi DB/LLM:

```powershell
.\scripts\run_self_learning_unseen.ps1 -Limit 5 -Workers 2 -List
```

### Replay dataset sau từng session

Runner riêng đọc `dataset/iterative-refinement/scenarios_complete dataset`;
mỗi `call_N` là một session. Hết call, gọi end, đợi học và ghi diff artifact.

```powershell
$env:PYTHONPATH='src'
$env:KNOWLEDGE_GAP_LOOP_ENABLED='true'
python -m self_agent.scenario_runner --scenario-id SC-001 --output outputs/self-agent/sc001
```

`SC-001-call_1.json` và `SC-001-call_2.json` trong thư mục output chứa transcript,
trạng thái job, report học và `artifact_changes`: đường dẫn, created/updated,
nội dung gap/knowledge/test sau session. Đây là report kiểm tra chức năng, không
phải trace benchmark. Report có transcript nên cần bảo vệ như dữ liệu hội thoại.

```powershell
# Chỉ xem danh sách, không gọi DB/LLM:
python -m self_agent.scenario_runner --limit 0 --list
# Chạy ba scenario đầu:
python -m self_agent.scenario_runner --limit 3
# Chạy tất cả 120 scenario:
python -m self_agent.scenario_runner --limit 0
```

Giữ customer memory trong RAM giữa các call của cùng scenario, reset giữa các
scenario; không ghi customer memory bền vững. Tool vẫn dùng DB/Pinecone đã cấu
hình, có thể tạo đơn test; runner thu thập ID và dọn các đơn tạo trong lượt chạy
bằng cơ chế hiện có. Không reset CRM/catalog hoặc mô phỏng thời gian tự động của
backend. Vì vậy đây không phải bản thay thế cho benchmark với fixture đầy đủ.
Không truyền facts/ground truth/expected outcomes làm feedback. Knowledge hiện
ghi artifact, chưa tự publish vào Pinecone; không phải session nào cũng có gap.

`self_agent.evaluation.run_gap_loop.evaluate` nhận các callback `run_round`,
`learn`, `judge`: chạy hai vòng cùng bộ test, chờ học ở giữa; judge không được
truyền đáp án chuẩn cho learner. Caller tạo lại harness/customer memory và chọn
release K1 giữa hai vòng. CLI so sánh hai file verdict `{test_id: boolean}`:

```powershell
python -m self_agent.evaluation.run_gap_loop round0.json round1.json
python -m unittest discover -s tests -p test_self_agent.py -v
```

Không chạy process learner song song khi đo hiệu năng benchmark cũ: worker vẫn
có thể tranh tài nguyên/quota dù không nằm trong trace. Token và thời gian học
chỉ ghi vào reports, không sửa `TurnResult.usage` hoặc latency của base harness.
