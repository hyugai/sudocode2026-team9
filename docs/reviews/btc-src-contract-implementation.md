# Kết quả sửa contract BTC

Bản đồng bộ F01–F12 và sáu bản sửa sau review. Nguồn đối chiếu là các schema cùng `eval/mock_tools.py` / `eval/reference_eval.py` hiện có trong `dataset/BTC-Data-Vong1-TEAMS`.

## Phạm vi đã hoàn tất

| Mục | Thay đổi | Kiểm chứng |
| --- | --- | --- |
| F01 | Thêm `pricing.quote_order`, MCP `get_order_quote`, `order.create(lines, basket_skus)`; agent tạo một đơn cho giỏ | Hai SKU, hai/ba máy cùng SKU, lưu và đọc lại đủ dòng, E2E bằng tool thật với DB giả |
| F02 | Tính giá theo từng đơn vị; AIR-2ND-50 chỉ một máy rẻ nhất, xử lý bằng giá và trade-in | Differential tests so toàn bộ giá từng máy, chương trình áp dụng và tổng tiền với reference |
| F03 | Server tính lại giá trước khi ghi; kiểm tra COD theo tổng giỏ; giữ idempotency | Giá 1đ bị từ chối, giỏ vượt giới hạn không ghi DB, retry bank, retry cùng key không tạo thêm đơn |
| F04 | Handoff dùng `brief` đúng hợp đồng; enum tiếng Việt, câu hỏi dạng mảng; validate tại workflow | Brief hợp lệ được nhận; sai kiểu/enum/độ dài bị từ chối; brief do agent tạo vượt schema BTC |
| F05 | Bổ sung trường CallBrief và `to_btc()`; mapping phiên cũ, sản phẩm, blocker, slot đã biết; giữ cảnh báo và latency khi refresh | Khách mới/cũ, loại phiên hiện tại, ưu đãi hết hạn, timing voice, validate schema có FormatChecker |
| F06 | Latency xuất integer; generator validate từng trace và brief trước khi ghi | Trace thành công và lỗi đều đúng schema; số thực được làm tròn; lượt lỗi bị loại khỏi measured latency |
| F07 | Vùng xét theo địa chỉ; điều kiện và ngưỡng freeship theo reference | Đối chiếu Bắc/Trung/Nam, nhiều ngày, SKU và biến thể |
| F08 | Dùng chung lịch nghỉ và quy tắc callback/ETA của BTC | Thứ Bảy, Chủ nhật, ngoài giờ, 26/10, 01/01; giao vùng 2/4 ngày |
| F09 | Miễn phí lần đổi đầu; lần tiếp theo 60.000đ; thêm chênh giá, hoàn tiền/thu thêm và trạng thái | Đổi size/sản phẩm, đổi lần 2, trả hàng, cập nhật địa chỉ, action không hợp lệ |
| F10 | Truyền và áp dụng filter diện tích đã có trong schema; chặn hàng discontinued còn tồn; bổ sung identities/sessions/candidates CRM | Fixture BTC qua SQLite trong bộ nhớ, kiểm tra lọc 50 m² và hàng discontinued còn tồn 5 |
| F11 | Dùng matcher reference cho từng dòng hàng và alias order ID giữa các cuộc gọi | Cùng trace nhiều dòng/create→update đạt reference TSR, team TSR và TCA 100% |
| F12 | Trích thêm số ngày đổi trả, phí đổi, bảo hành; đọc giá/tổng từ quote_order; cập nhật expectation cũ | Phát hiện thông tin chính sách sai, bỏ câu phủ định và thông tin cũ được trích dẫn để đính chính |

Giữ preview CallBrief hiện có cho UI. DTO BTC được xuất riêng trong trace; không đưa toàn bộ CRM/memory nội bộ vào DTO. Không sửa giao diện hoặc bổ sung nghiệp vụ ngoài checklist.

## Database

Chỉ bổ sung một cột nullable `orders.lines JSONB`. Đơn cũ vẫn đọc được qua các trường đơn một SKU; đơn mới lưu các đơn vị cùng giá và các mã ưu đãi đã được server xác minh. Tổng tiền được tính từ dòng hàng, không thêm bảng hay quy trình thanh toán mới.

Migration: [scripts/migrate_order_lines.py](../../scripts/migrate_order_lines.py). SQL dùng `ADD COLUMN IF NOT EXISTS`, có thể chạy lại khi triển khai môi trường khác:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_order_lines.py
```

Migration đã được chạy trên PostgreSQL `telesale` và kiểm tra chạy lặp không thay đổi dữ liệu. Cột `lines` là JSONB nullable, không có default; hai đơn cũ vẫn giữ NULL và toàn bộ các cột cũ giữ nguyên. Không seed/reset dữ liệu. `migrate_catalog.py --orders-only` cũng đã nhận cột `lines`. Môi trường triển khai khác vẫn cần chạy migration với cấu hình DB riêng.

## Sáu lỗi sau review đã xử lý

1. Giỏ hàng giữ `basket_lines=[{sku, qty}]` từ báo giá đến tạo đơn và bộ nhớ. Đọc được dữ liệu cũ chỉ có `basket_skus`, SKU lặp và `quantity_each`. Ca 2 AirPure Pro + 1 AirPure Mini tại ngày tham chiếu 15/10/2026 tạo đúng 3 máy, tổng 16.475.000đ.
2. Tạo/cập nhật đơn làm mất hiệu lực cache giá, khuyến mãi và tra đơn, kể cả khi lần ghi cần thử lại. Sau khi dùng RUN-10, báo giá mới lấy lại từ DB.
3. Đổi một dòng hàng cập nhật `orders.sku` và `orders.lines` trong cùng transaction. Đơn cũ chưa có `lines` vẫn đọc qua các cột cũ. Yêu cầu đổi đơn nhiều dòng chưa chỉ định dòng trả `ambiguous_order_line` và giữ nguyên dữ liệu.
4. Backend cộng số lượng tất cả dòng trùng SKU trước khi kiểm tra tồn. Đây là kiểm tra chặt hơn vòng kiểm tra từng dòng trong BTC mock; các phép đối chiếu giá/khuyến mãi hợp lệ giữ nguyên.
5. Voice realtime công bố `get_order_quote`, kiểm tra cấu trúc/giới hạn dòng hàng và gắn danh tính, địa chỉ, ngày từ backend. Phiên voice vẫn chỉ có quyền đọc.
6. Đưa `scripts/migrate_order_lines.py` vào repo. PostgreSQL dùng `ADD COLUMN IF NOT EXISTS lines JSONB`; migration chỉ bổ sung cột nullable, không seed lại dữ liệu.

## Kết quả kiểm thử ngày 15/11/2026

- Bộ contract BTC tại [test_btc_contract.py](../../tests/test_btc_contract.py) kiểm tra các ca tái hiện sáu lỗi, giá từng máy trong câu trả lời và so sánh với reference. Fixture đặt ngày tham chiếu 15/10/2026; không phụ thuộc ngày thực chạy test.
- Hồi quy gộp `src/eval tests` với PostgreSQL test riêng: **370 pass, 0 skip**, thêm **5.203 subtest pass**, không có lỗi import hoặc test failure. Database tạm đã được dọn; DB nghiệp vụ không dùng làm nơi ghi/xóa của test integration.
- Frontend `npm test`: **64 pass**. Lần audit trước cũng đã qua lint, TypeScript và production build; phiên sửa runtime không đổi source frontend.
- Hai file test cũ đã được cập nhật sang `PricingCalculator` / `get_order_quote`; test lưu trữ/migration kiểm tra cấu trúc `orders.lines` hiện tại. Các test vẫn kiểm tra giá sai, đơn lỗi, COD, tách đơn, idempotency và đọc đơn cũ.
- Kiểm tra cú pháp các module nghiệp vụ thay đổi và `git diff --check`: pass.

Lệnh kiểm tra:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider src/eval tests -q
```

Các nhóm đã chạy gồm orchestration, pricing, order idempotency, basket, brief, latency, response grounding, memory, realtime voice, API, migration, readiness và evaluator. Unit/integration test mock dịch vụ LLM/MCP bên ngoài; E2E riêng bên dưới dùng HTTP, MCP, LLM cấu hình thật và PostgreSQL thật, với khách/đơn thử riêng đã dọn.

Để chạy các test PostgreSQL opt-in, cấu hình `APP_DATA_TEST_DATABASE_URL` đến database test tách biệt trước lệnh pytest. Không cần thay `DATABASE_URL` của môi trường đang vận hành. Các test tiếp tục tự tạo và dọn schema riêng trong database test.

## Sửa ngày nghiệp vụ, readiness và tracing

1. [business_time.py](../../src/telesale_agent/core/business_time.py) là nguồn ngày hiện tại theo UTC+7 cho catalog, giá, tồn kho, tạo đơn và voice. Context ghim ngày trước bước nạp khách/brief. Không lấy ngày tạo đơn cũ làm ngày hiện tại và không cập nhật lại giá/ngày/ETA đã lưu của đơn cũ khi replay idempotent.
2. `/api/chat` nhận `call_date` tùy chọn dạng `YYYY-MM-DD`; audio nhận trường form cùng tên. Thiếu ngày thì dùng ngày Việt Nam hiện tại; ngày sai trả 422. Harness/evaluator vẫn giữ `metadata.call_date` của kịch bản BTC. Catalog web hỗ trợ `?on=YYYY-MM-DD` để replay, mặc định dùng cùng đồng hồ. Luồng giỏ hàng demo trong trình duyệt vẫn là snapshot BTC 15/10 đã được ghi nhãn rõ, không tạo đơn thật.
3. `/health` và `/api/health` truy vấn `SELECT 1` bằng pool riêng và ping đủ ba session MCP db/knowledge/workflow. Probe có timeout 3 giây; thiếu session, lỗi DB/MCP hoặc agent chưa sẵn sàng trả 503. Kết quả chỉ chứa trạng thái; không trả URL DB hoặc exception. Đây là readiness, không phải cơ chế tự khởi động lại MCP.
4. LangSmith được preflight quyền đọc project trước khi dựng model/MCP. Key/project hiện cấu hình bị từ chối 403; runtime tạm ngừng tracing, ghi một cảnh báo và công bố `tracing={status: disabled, reason: authorization_failed}` trong health. `.env` và key không bị sửa/xóa. Thay key/quyền project/workspace rồi restart để kiểm tra lại; quyền tài khoản LangSmith chưa được khôi phục bởi bản sửa này. Tracing là phụ thuộc tùy chọn nên không chặn bán hàng/readiness DB/MCP.

E2E cùng giỏ **2 AirPure Pro + 1 AirPure Mini** đã qua cả hai chế độ:

| Ngày | Tổng tiền | Đơn giá | Kết quả |
| --- | --- | --- | --- |
| Mặc định hiện tại 15/11/2026 | 18.170.000đ | Pro 7.990.000đ × 2, Mini 2.190.000đ | COD bị chặn, bank tạo một đơn, retry không trùng |
| `call_date=2026-10-15` | 16.475.000đ | Pro 7.690.000đ × 2, Mini 1.095.000đ | Giữ đúng ưu đãi BTC cũ, COD/bank/retry đều đúng |

SKU-MB-STR1 hiện có tồn 0 ở cả web lẫn tool agent; replay 15/10 có tồn 2 ở cả hai. Đơn/khách/memory thử và session API đã dọn. Hash toàn bộ nội dung hai đơn cũ và 50 khách khớp trước/sau. API cùng ba MCP đã restart và tiếp tục chạy; log ingest LangSmith mới không còn 403 lặp lại sau tám lượt chat thật.

## Giới hạn còn lại

- PostgreSQL API/auth/persistence integration đã chạy, không còn 29 test skip của phiên trước. E2E thật chỉ kiểm tra luồng text báo giá/tạo đơn; chưa chạy audio ASR hoặc voice realtime thật trong phiên này.
- Chưa chạy benchmark đủ tối thiểu 100 lượt, bỏ 3 warm-up, để kết luận p95 đạt chuẩn BTC; chưa xác nhận điểm thi hoặc độ bền dưới tải dài hạn. Tám lượt E2E thật không thay thế benchmark.
- Claim extractor vẫn là heuristic cho các mẫu đã hỗ trợ; không thay thế LLM judge/đối chiếu thủ công toàn bộ lời thoại.
- Trace lỗi/không có phép đo dùng `measurement_mode="unavailable"`, `ttft_ms=0` để giữ kiểu bắt buộc của schema. Đây là giá trị đánh dấu thiếu phép đo, không phải TTFT đo được; bộ tổng hợp nội bộ không tính các lượt này vào measured latency.
- Không sửa artifact benchmark cũ. Cần sinh trace mới khi đánh giá bản code này.
