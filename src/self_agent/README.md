# Self Agent: post-session Knowledge Gap Loop

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

Kết quả cải tiến ở `data/memory-root/agents/telesales_agent/knowledge_gap_loop/`:
`gaps/`, `knowledge/`, `patterns/`, `regression_cases/` và `releases/`.
Job/snapshot để retry và report/token/thời gian ở
`outputs/self-agent/learning-runtime/jobs/` và `outputs/self-agent/learning-runtime/reports/`.
Không có gap/pattern thì agent memory có thể rỗng, dù job chạy thành công.
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
chưa tự được đưa vào prompt hoặc publish Pinecone trong bản hiện tại.

## Tái sử dụng DB/Pinecone hiện có

Runner giữ nguyên `KNOWLEDGE_BACKEND`, `PINECONE_INDEX_NAME`,
`PINECONE_NAMESPACE` và các cấu hình retrieval hiện tại. Worker tìm nguồn qua
`base.mcp_tools["search_policy"]`; không tạo Chroma, index mới hay đổi embedding.
Agent memory chỉ lưu gap, FAQ ứng viên, test và báo cáo, không thay DB nghiệp vụ.

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
