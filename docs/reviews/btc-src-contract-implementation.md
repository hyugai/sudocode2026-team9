# Kết quả sửa contract BTC

Triển khai theo [audit F01–F12](btc-src-contract-audit.md) và `CLAUDE.md`. Nguồn đối chiếu là các schema cùng `eval/mock_tools.py` / `eval/reference_eval.py` hiện có trong `dataset/BTC-Data-Vong1-TEAMS`.

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
.\.venv-salesman\Scripts\python.exe scripts/migrate_order_lines.py
```

**Đã áp dụng vào database hiện cấu hình trong phiên làm việc**, sau khi test source: xác nhận cột tồn tại và số đơn trước/sau không thay đổi. Không reset, seed lại hoặc tạo đơn thử trên database này. Các đơn kiểm thử chỉ nằm trong SQLite tạm.

## Kết quả kiểm thử

- Bộ BTC mới: **64 test** tại [test_btc_contract.py](../../tests/test_btc_contract.py). Bao gồm so sánh trực tiếp với reference, validate schema chính thức và luồng agent → MCP wrapper → lưu/đọc đơn.
- Lần chạy hồi quy gộp: **342 pass, 3 fail từ trước, 30 skip**, thêm **35 subtest pass**.
- Kiểm tra cuối sau chỉnh matcher: `src/eval`, bộ BTC và `tests/test_team_eval.py`: **105 pass**, thêm **4 subtest pass**.
- `compileall` cho các package Python thay đổi và `git diff --check`: pass.

Lệnh kiểm tra contract/evaluator:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
.\.venv-salesman\Scripts\python.exe -m pytest src/eval tests/test_btc_contract.py tests/test_team_eval.py -q
```

Hồi quy gộp đã chạy các nhóm orchestration, pricing, order idempotency, basket, brief, latency, response grounding, memory, realtime voice, API và evaluator liên quan. Các test cũ bị ảnh hưởng được cập nhật expectation cho contract mới; không đổi test để chấp nhận đơn sai giá hoặc tính đơn lỗi là thành công.

### Ba lỗi có sẵn, giữ nguyên ngoài phạm vi

Đã chạy lại ba test này với các module thay đổi được nạp từ `git HEAD` trong một subprocess, không checkout/revert workspace. Cả ba cho cùng lỗi trước khi có bản sửa BTC:

1. `test_deepagent_runtime_refactor.py::test_runtime_loads_instructions_and_mcp_paths_from_project_root`: test monkeypatch `runtime.stdio_client`, nhưng module không còn thuộc tính này.
2. `test_deepagent_trace.py::test_harness_uses_turn_checkpoint_and_rebuilds_bounded_brief`: expectation runtime context chưa có `customer_id`.
3. `test_customer_context_service.py::test_refresh_memory_reloads_turn_updates_without_querying_crm`: fixture memory không có fact `budget_vnd` như test kỳ vọng.

Không sửa các lỗi này vì không thuộc F01–F12.

## Giới hạn còn lại

- 30 test skip do thiếu cấu hình PostgreSQL test riêng hoặc weights ASR. Persistence của contract đã được kiểm tra qua SQLAlchemy với SQLite trong bộ nhớ; chưa chạy bộ PostgreSQL API integration trong phiên này.
- Chưa chạy benchmark LLM/ASR thật hay xác nhận điểm thi. Test orchestration dùng tool nghiệp vụ thật và fixture BTC, không gọi dịch vụ trả phí.
- Claim extractor vẫn là heuristic cho các mẫu đã hỗ trợ; không thay thế LLM judge/đối chiếu thủ công toàn bộ lời thoại.
- Trace lỗi/không có phép đo dùng `measurement_mode="unavailable"`, `ttft_ms=0` để giữ kiểu bắt buộc của schema. Đây là giá trị đánh dấu thiếu phép đo, không phải TTFT đo được; bộ tổng hợp nội bộ không tính các lượt này vào measured latency.
- Không sửa artifact benchmark cũ. Cần sinh trace mới khi đánh giá bản code này.
