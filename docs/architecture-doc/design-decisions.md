# Quyết định thiết kế và lý do

> Ghi nhận từ hiện trạng repository và đối chiếu trực tiếp với đề bài **SUDO CODE 2026 — Vòng 1**. Tài liệu tập trung vào **5 quyết định kiến trúc cốt lõi** định hình hệ thống Synee AI.

Liên quan: [hệ thống](system-architecture.md), [harness](agent-harness-loop.md), [bộ nhớ](memory-design.md), [tool](tool-catalog.md), [self-learning](self-learning.md).

---

## ADR-01 — Chọn DeepAgent cho model/tool loop, Application giữ quyền điều phối

**Bối cảnh:** Đề bài yêu cầu thiết kế Agent Harness theo vòng lặp `Perceive → Resolve Identity → Retrieve → Plan → Guardrail → Act → Observe → Persist`. Tư vấn tiếng Việt cần linh hoạt, nhưng nhận diện khách hàng, kiểm tra dữ liệu bắt buộc, chặn bịa giá và ghi nhận kết quả giao dịch phải được kiểm soát chặt chẽ.

**Lựa chọn:** Tách đôi trách nhiệm:
- **Application layer** sở hữu các bước tất định (deterministic): nhận diện khách hàng (`resolve/hydrate`), chuẩn hóa đầu vào (`perception`), truy hồi ngữ cảnh (`retrieval`), định tuyến intent (`routing`), đọc trước dữ liệu (`read prefetch`), thực thi mutation đã xác nhận và lưu trữ (`persistence`).
- **DeepAgent** đảm nhận vòng lặp reasoning và gọi tool trong phạm vi context và danh sách tool được phép ở lượt đó.

**Lý do:** Các bước đã có đủ dữ liệu được chạy theo quy tắc cố định, giúp giảm số lần LLM phải tự đoán arguments hoặc lặp lại chuỗi đọc thừa, giảm độ trễ và hạn chế sai sót nghiệp vụ. Bằng chứng từ Application vẫn đi chung trace với tool calls của DeepAgent.

**Đánh đổi:** Luồng xử lý đi qua nhiều lớp (executor, routing, response grounding), nên khi thêm intent hoặc tool mới cần cập nhật đồng bộ cả policy và routing để giữ tính nhất quán.

Căn cứ: [turn orchestration](../../src/telesale_agent/application/deepagent/turn.py), [tool policy](../../src/telesale_agent/application/conversation/tool_policy.py).

---

## ADR-02 — Kiến trúc Memory phân tầng (EverOS-style) bao phủ đủ 4 tầng theo đề bài

**Bối cảnh:** Đề bài xác định thiết kế lớp bộ nhớ là phần quan trọng nhất, yêu cầu bao phủ đủ 4 tầng (**Working**, **Episodic**, **Profile**, **Semantic / KB**), đồng thời phải xử lý được bài toán *ghi có chọn lọc*, *khách đổi ý* (vô hiệu hóa giá trị cũ) và *truy vết nguồn gốc ký ức*.

**Lựa chọn:** Tổ chức bộ nhớ theo hướng EverOS (lấy `customer_id` làm trung tâm, tách biệt nguồn sự thật) để ánh xạ trực tiếp 4 tầng của đề bài:
1. **Working Memory:** `ConversationState` trong RAM + `CallBrief` gọn nhẹ theo lượt (kết hợp `bounded context` và tin nhắn gần nhất).
2. **Episodic Memory:** `episodes/episode-YYYY-MM-DD.md` lưu tóm tắt từng cuộc gọi/tương tác (kèm `source_id` chống ghi trùng) và `foresights/` gợi ý hướng tiếp nối cho lần sau.
3. **Profile Memory:** `user.md`, `behaviors.md` và `facts.md` (upsert theo key-value JSON để không tồn tại hai giá trị mâu thuẫn khi khách đổi ý), đi kèm `atomic_facts/` ghi nhật ký thay đổi có nguồn lượt (`source`).

**Lý do:** Đảm bảo không trộn lẫn dữ kiện lịch sử cá nhân với giá/tồn kho biến động theo thời gian thực; tránh phình prompt khi hội thoại kéo dài nhiều phiên; đồng thời giữ quyền ghi bộ nhớ ở phía Application/Persister (không để agent tư vấn tự ý ghi đè dữ liệu giao dịch). Hỗ trợ cả lưu Markdown local lẫn snapshot trên Object Storage qua một contract thống nhất.

**Đánh đổi:** Cần duy trì cơ chế merge và ưu tiên nguồn cho từng trường dữ kiện; chế độ `LLMPersister` (tạo `episodes` và `foresights`) làm tăng thêm một phần độ trễ và token sau mỗi lượt so với chỉ ghi `facts` tất định.

Căn cứ: [fact persistence](../../src/telesale_agent/application/memory/persist.py), [LLM persister](../../src/telesale_agent/adapters/llm/llm_persist.py), [prompt/context](../../src/telesale_agent/application/deepagent/context/prompt.py).

---

## ADR-03 — Chọn MCP Tool thay vì Multi-Agent (A2A)

**Bối cảnh:** Mục C.3 của đề bài cho phép chọn **MCP (Model Context Protocol)** hoặc **A2A / Multi-Agent**, với yêu cầu chứng minh độ phù hợp kiến trúc và tránh tạo multi-agent chỉ mang tính hình thức (chuỗi prompt tuần tự).

**Lựa chọn:** Chọn kiến trúc **MCP** — đóng gói toàn bộ năng lực nghiệp vụ, tri thức và quy trình thành các MCP server tách biệt (**Business**, **Knowledge**, **Workflow**) giao tiếp qua `stdio`, kết hợp thu hẹp quyền tool theo từng lượt (intent routing) và theo kênh (Chat có quyền ghi khi xác nhận; Realtime Voice chỉ được cấp tool đọc).

**Lý do:**
- Bài toán telesale cốt lõi cần **trạng thái nhất quán và độ trễ thấp** (TTFT p95 ≤ 3s, Total Latency p95 ≤ 8s). Dùng một agent điều phối gọi MCP tool trực tiếp tránh được chi phí giao tiếp, truyền ngữ cảnh và độ trễ tích lũy giữa nhiều agent (Orchestrator → Memory Agent → Advisor → Compliance Agent).
- MCP giúp chuẩn hóa schema, tách biệt logic nghiệp vụ/DB khỏi LLM và dễ tái sử dụng chung một bộ tool cho cả Chat (DeepAgent) lẫn Voice (Gemini Live) mà không phải viết lại tích hợp.
- Kiểm soát guardrail và phân quyền ngay tại tầng backend/MCP thay vì trông chờ vào việc agent này kiểm tra agent kia qua prompt.

**Đánh đổi:** Phát sinh chi phí quản lý vòng đời process MCP (`stdin/stdout`) và yêu cầu đồng bộ chặt chẽ giữa tool registry, canonical name mapping và policy kiểm tra tham số ở backend.

Căn cứ: [MCP runtime](../../src/telesale_agent/adapters/mcp/runtime.py), [DeepAgent runtime](../../src/telesale_agent/application/deepagent/runtime.py).

---

## ADR-04 — Dùng Gemini API cho LLM & Voice Realtime, kết hợp Zipformer ASR chạy local

**Bối cảnh:** Đề bài quy định *ASR bắt buộc chạy được local*, còn *LLM được phép dùng API* để nhóm không bị chặn bởi phần cứng, ưu tiên thiết kế dữ liệu, bộ nhớ và đánh giá thay vì tự train hay chạy model nặng trên máy yếu.

**Lựa chọn:**
- **Chat & Reasoning / Learning:** Dùng **Gemini API** (`gemini-3.6-flash` qua `LLM_PROVIDER=gemini`) cho DeepAgent, tóm tắt `LLMPersister` và phân tích bài học.
- **Voice Realtime (tùy chọn nâng cao):** Dùng **Gemini Live API** (`gemini-3.8-live`) với controller riêng hỗ trợ audio hai chiều và ngắt lời (barge-in).
- **ASR (file ghi âm):** Chạy **Zipformer tiếng Việt** hoàn toàn local trên CPU để chuyển audio thành text trước khi đưa vào luồng Chat.

**Lý do:** Gemini API đáp ứng tốt tiếng Việt tự nhiên, hỗ trợ function calling ổn định cho chuỗi MCP tool và đạt ngưỡng độ trễ p95 của đề bài mà không đòi hỏi GPU cục bộ. Việc giữ Zipformer local vừa tuân thủ ràng buộc đề bài, vừa tách bạch khâu nhận dạng giọng nói (đo WER/CER) khỏi khâu suy luận.

**Đánh đổi:** Phụ thuộc kết nối mạng, hạn mức quota và chi phí API của Google Gemini cho phần suy luận/live voice; cần lớp che PII (`phone`, địa chỉ...) trước khi gửi transcript ra ngoài ở các luồng log/học.

Căn cứ: [Voice controller](../../src/telesale_agent/application/realtime/controller.py), [DeepAgent runtime](../../src/telesale_agent/application/deepagent/runtime.py).

---

## ADR-05 — Vòng lặp Self-Learning (Knowledge Gap Loop & Lesson Router) cải tiến không cần fine-tune

**Bối cảnh:** Đề bài (Mục C.5 & Tiêu chí đánh giá số 5 — 13%) đặt ràng buộc **không được huấn luyện lại / fine-tune mô hình**, mọi cải tiến theo thời gian phải đến từ dữ liệu, bộ nhớ, kịch bản/prompt và điều phối, có cơ chế kiểm chứng và kiểm soát an toàn.

**Lựa chọn:** Xây dựng **Self-Learning Service & Learning Worker** chạy bất đồng bộ sau khi kết thúc phiên (Chat và Voice):
1. Gom transcript (đã che PII), kết quả tool và feedback vào PostgreSQL dưới dạng job có cơ chế retry.
2. Worker chạy **Knowledge Gap Loop** để đối chiếu lỗi với bằng chứng tool thực tế, phát hiện khoảng trống tri thức (`search_policy`) và sinh các bài học có cấu trúc (`When / Do / Otherwise`) lưu trên Object Storage.
3. Ở các phiên Chat mới, **Chat Lesson Router** tự động chọn tối đa 3 bài học đã được duyệt (`approved`, giới hạn tổng 2.400 ký tự/lượt) để nạp vào ngữ cảnh trước khi trả lời.

**Lý do:** Đáp ứng trực tiếp yêu cầu *"tự cải tiến từ feedback mà không fine-tune"* của đề bài một cách có hệ thống và đo lường được. Việc chỉ lưu bài học sau khi đối chiếu bằng chứng và tách riêng kho `approved` giúp ngăn agent học nhầm (ví dụ: học thói quen hứa đại để chốt đơn) và giữ an toàn nếu kho lesson gặp sự cố (Chat vẫn hoạt động bình thường).

**Đánh đổi:** Cần cấu hình thêm PostgreSQL learning tables và Object Storage (S3-compatible) để lưu trữ bài học/artifacts; các thay đổi hiệu quả phụ thuộc vào chất lượng bước kiểm chứng trước khi đưa bài học vào trạng thái `approved`.

Căn cứ: [tài liệu Self-learning](self-learning.md), [tích hợp self_agent](../../src/self_agent/README.md).
