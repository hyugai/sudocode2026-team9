# Quyết định thiết kế và lý do

> Ghi nhận ngày 18/11/2026 từ hiện trạng repository. Các lựa chọn bên dưới **đã thể hiện trong code**; phần lý do/đánh đổi là diễn giải kỹ thuật từ implementation và tài liệu hiện có, không phải biên bản phê duyệt hay lịch sử quyết định của nhóm.

Liên quan: [hệ thống](system-architecture.md), [harness](agent-harness-loop.md), [bộ nhớ](memory-design.md), [tool](tool-catalog.md).

## ADR-01 — Application điều phối, DeepAgent xử lý model/tool loop

**Bối cảnh:** tư vấn ngôn ngữ tự nhiên cần linh hoạt, còn identity, xác nhận mua hàng, dữ liệu bắt buộc và ghi kết quả cần được kiểm soát rõ.

**Lựa chọn:** application sở hữu resolve/hydrate, perception, retrieval, routing, read prefetch, mutation đã xác nhận và persistence. DeepAgent nhận context/tool còn được phép để tiếp tục reasoning và tạo câu trả lời.

**Lý do:** những bước đã có đủ dữ liệu được thực hiện theo quy tắc, giảm việc model phải tự lập lại chuỗi đọc hoặc đoán arguments. Evidence từ application vẫn đi chung trace với model tool calls.

**Đánh đổi:** logic nghiệp vụ trải qua executor, routing và response grounding; cần duy trì nhất quán khi thêm intent/tool mới. Giới hạn graph không phải tổng budget của toàn bộ lượt.

Căn cứ: [turn orchestration](../../src/telesale_agent/application/deepagent/turn.py), [tool policy](../../src/telesale_agent/application/conversation/tool_policy.py).

## ADR-02 — Chat/file audio và Voice realtime có hai vòng điều phối

**Bối cảnh:** file ghi âm là input theo lượt; microphone realtime cần vừa nhận, phát audio vừa xử lý transcript và ngắt lời.

**Lựa chọn:** Chat/file audio dùng DeepAgent; file chạy Zipformer local. Voice dùng Gemini Live và controller riêng, tái sử dụng shared services, memory và registry thay vì chạy lại Chat harness cho từng audio chunk.

**Lý do:** giữ đường audio liên tục và giảm phụ thuộc vào việc hoàn tất NLU/persistence trước mỗi phần âm thanh; vẫn dùng chung identity và dữ liệu đã học.

**Đánh đổi:** hai state/protocol khác nhau, chuyển chế độ không mang nguyên history sang. Guard final text của Chat không duyệt trước từng audio chunk Live; phải kiểm thử riêng interruption, playback và transcript completion.

Căn cứ: [Voice controller](../../src/telesale_agent/application/realtime/controller.py), [shared services](../../src/telesale_agent/application/conversation/services.py).

## ADR-03 — Bounded context và checkpoint mặc định theo turn

**Bối cảnh:** replay transcript và tool outputs qua mọi lượt làm prompt tăng, tốn token và khó giữ dữ kiện hiện tại nổi bật.

**Lựa chọn:** graph thread riêng cho từng turn; application đưa compact CallBrief, facts theo ưu tiên và recent messages có giới hạn vào lượt mới. CallBrief projection chạy cục bộ.

**Lý do:** continuity dựa vào dữ kiện đã chọn thay vì phụ thuộc toàn bộ raw graph history; dựng brief không thêm một model request mỗi lượt.

**Đánh đổi:** projection có thể bỏ sót chi tiết; khi cần có archive lookup. Giới hạn prompt không dọn toàn bộ RAM checkpoint và không bảo đảm tool output trong lượt luôn nhỏ. Có thể đổi scope `conversation`, nhưng phải chấp nhận history tăng.

Căn cứ: [prompt/context](../../src/telesale_agent/application/deepagent/context/prompt.py), [fact selector](../../src/telesale_agent/application/deepagent/context/facts.py).

## ADR-04 — Customer memory do application ghi, tách khỏi nghiệp vụ và instructions

**Bối cảnh:** sở thích khách, giá hiện tại và quy tắc agent có nguồn sự thật cũng như vòng đời khác nhau.

**Lựa chọn:** CRM/order/catalog ở PostgreSQL; learned memory theo `customer_id`; instructions nạp từ file lúc startup. Facts thay đổi dùng upsert. Persister lấy customer evidence và verified tool results, không xem lời agent là chứng cứ giao dịch.

**Lý do:** tránh lẫn ghi nhớ lịch sử với giá/tồn kho mới, tránh canonical facts chứa nhiều giá trị hiện tại cho cùng key và giữ quyền ghi ngoài agent tư vấn.

**Đánh đổi:** phải định nghĩa nguồn/merge cho từng field. Merge hiện cho customer candidates ưu tiên khi trùng sau lọc, không có quy tắc toàn cục tool luôn thắng. Metadata provenance/timestamp chưa được chuẩn hóa đầy đủ trên từng canonical value.

Căn cứ: [fact persistence](../../src/telesale_agent/application/memory/persist.py), [runtime instructions](../../src/telesale_agent/application/deepagent/runtime.py).

## ADR-05 — Tool nghiệp vụ qua MCP, quyền được thu hẹp theo lượt và kênh

**Bối cảnh:** model không cần toàn bộ tool schema trong mọi câu hỏi; Voice chưa có cơ chế đối soát write khi interruption/reconnect.

**Lựa chọn:** ba MCP process chia Business, Knowledge, Workflow; chuẩn hóa tên trong trace. Chat có intent routing và call limits; shell/filesystem tool bị ẩn, general-purpose subagent bị tắt. Voice chỉ công bố tool đọc và kiểm tra lại arguments/policy tại backend.

**Lý do:** giảm schema/context không cần thiết, giữ nghiệp vụ sau interface rõ và không để quyền tool phụ thuộc chỉ vào lời nhắc model. Identity/ngày của Voice do backend bind.

**Đánh đổi:** thêm vòng đời process/stdin-stdout và yêu cầu đồng bộ registry, canonical mapping, schema, policy. Mutation Voice cần operation ledger/idempotency/reconciliation trước khi mở quyền. Callback/handoff hiện chưa có hàng đợi bền vững.

Căn cứ: [MCP runtime](../../src/telesale_agent/adapters/mcp/runtime.py), [DeepAgent runtime](../../src/telesale_agent/application/deepagent/runtime.py), [Voice dispatcher](../../src/telesale_agent/application/realtime/tool_dispatch.py).

## ADR-06 — Một memory contract, nhiều backend và persister

**Bối cảnh:** phát triển local, triển khai cloud và evaluation cần cùng semantics nhưng khác yêu cầu lưu trữ/tái lập.

**Lựa chọn:** file Markdown mặc định; object-storage snapshot khi cấu hình; in-memory repository cho evaluation/disabled. Durable mode mặc định dùng LLM learning; có deterministic persister chỉ ghi facts.

**Lý do:** Markdown dễ kiểm tra/migrate; snapshot gom cập nhật remote; repository/persister tách rời giúp evaluation giữ upsert semantics mà không sửa seed thật. LLM learning bổ sung episode/foresight bên cạnh canonical facts.

**Đánh đổi:** LLM learning tăng latency, token và độ biến thiên; deterministic mode không tự học episode/foresight. File không có transaction toàn lượt; snapshot remote chưa có distributed CAS. Cấu hình mode phải được ghi rõ khi so sánh benchmark.

Căn cứ: [bootstrap](../../src/telesale_agent/bootstrap.py), [write session](../../src/telesale_agent/adapters/memory/write_session.py), [LLM persister](../../src/telesale_agent/adapters/llm/llm_persist.py).

## ADR-07 — Buffer memory remote trong RAM và vận hành một backend writer

**Bối cảnh:** ghi nhiều file/object trong mỗi turn làm đường phản hồi phụ thuộc I/O remote; nhiều session của cùng khách phải nhìn thấy cập nhật mới.

**Lựa chọn:** object backend được bọc bằng `BufferedCustomerMemoryStore`; publish snapshot RAM, flush khi idle/shutdown, retry upload và theo dõi version. Chat/Voice dùng customer writer trong process; Voice giữ lease PostgreSQL cho một worker.

**Lý do:** giảm remote I/O trên đường xử lý từng lượt, chia sẻ snapshot mới giữa các session cùng process và tuần tự hóa ghi trong phạm vi hiện tại.

**Đánh đổi:** snapshot RAM chưa flush không crash-durable. Chat chưa có durable memory journal tương đương Voice; lease/khóa nội bộ chưa đủ cho scale nhiều process. Nếu mở rộng nhiều worker cần cơ chế điều phối session và writer phân tán.

Căn cứ: [RAM buffer](../../src/telesale_agent/adapters/memory/buffered.py), [coordinator](../../src/telesale_agent/application/memory/coordinator.py), [Voice lease](../../src/telesale_agent/application/realtime/session.py).

## ADR-08 — Journal và prepared batch cho memory Voice

**Bối cảnh:** lượt Voice có thể kết thúc bởi completion, interruption hoặc disconnect; retry không nên học lại episode hay append lặp.

**Lựa chọn:** chỉ chốt memory từ input đã hoàn chỉnh; lưu journal pending/prepared, ghi operations bằng RecordingRepository rồi replay. Append dùng source marker, upsert kiểm tra previous/current value; remote buffer trì hoãn journal committed tới sau upload.

**Lý do:** tách việc chuẩn bị memory khỏi apply; batch đã chuẩn bị có thể được phát lại mà không gọi lại LLM learning và hạn chế ghi đè fact mới.

**Đánh đổi:** PostgreSQL và memory store không có transaction chung; recovery chỉ cứu job đã ghi journal. Quét recovery chạy khi manager initialize, chưa có worker định kỳ xử lý mọi pending job. Cơ chế này chưa phải ledger cho mutation nghiệp vụ.

Căn cứ: [memory coordinator](../../src/telesale_agent/application/memory/coordinator.py), [Voice journal store](../../src/telesale_agent/adapters/db/voice_store.py).

## ADR-09 — SSE tách bản nháp khỏi kết quả cuối

**Bối cảnh:** người dùng cần phản hồi sớm, nhưng grounding, ghi memory và lưu hội thoại có thể còn đang chạy sau khi model bắt đầu sinh text.

**Lựa chọn:** Chat hỗ trợ JSON hoặc SSE. SSE phát bản nháp `text` và trạng thái; `done` mang final response sau kiểm tra/lưu. Task đang chạy tiếp tục hoàn tất khi client ngắt kết nối, không tự replay lượt.

**Lý do:** hiển thị tiến độ sớm mà vẫn có mốc kết quả cuối và giảm nguy cơ gửi lại mutation chỉ vì stream đứt.

**Đánh đổi:** bản nháp có thể khác final response và chưa qua final guard. DB, memory và business mutation không có transaction chung; nếu kết quả lưu chưa rõ, client phải kiểm tra lịch sử trước khi retry. `done` cũng không đồng nghĩa remote memory buffer đã flush.

Căn cứ: [Chat API/SSE](../../src/telesale_agent/entrypoints/api/chat.py), [agent streaming và final guard](../../src/telesale_agent/application/deepagent/turn.py).

## Những quyết định còn mở

Các mục sau là hướng cần thiết kế tiếp, **chưa được ghi nhận là đã triển khai**: distributed memory writer/CAS; durable journal cho memory Chat; mutation ledger cho Voice; schema/TTL/retention cho memory; hàng đợi callback/handoff thực tế; ranh giới duyệt nội dung audio trước phát. Phần này không giả định nhóm đã chọn giải pháp cụ thể.
