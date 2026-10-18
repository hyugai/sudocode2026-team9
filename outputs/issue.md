# Vấn đề còn lại sau benchmark_v3

Nguồn kiểm tra: [README](benchmark/benchmark_v3/README.md), [report](benchmark/benchmark_v3/report.json), [trace](benchmark/benchmark_v3/trace.jsonl), memory `.md` và worker log trong hai `part_*`. Chỉ ghi vấn đề quan sát được ở **v3**; các mô tả lỗi cũ của benchmark trước đã được bỏ khỏi file này.

## Tóm tắt

| Chỉ số | Kết quả v3 | Cách đọc |
|---|---:|---|
| Kịch bản | 120; 770 turn | 2 worker, hoàn thành trong 46 phút 33 giây |
| TSR | 118/120 = 98,3% | Một fail kỹ thuật SC-048; một fail cách chấm SC-086 |
| Tool-call accuracy | 99,4%; thiếu 1 expected call | Expected `order.create` của SC-048 không có trong trace |
| Lỗi turn | 1 | `504 DEADLINE_EXCEEDED` tại SC-048/call_3/turn1 |
| Gemini usage | 2.372 request; 2.393.400 input + 397.938 output token | 1.130 tool call; chưa cấu hình đơn giá nên cost USD = `null` |
| RQR / CCR / HR | 31,5% / 67,7% / 0% | Chưa nên dùng ba số này làm kết luận độc lập; xem mục Evaluator |

Các nhóm lỗi cũ về policy SC-031–040, câu hỏi chưa được xác minh SC-071–080, promotion variant SC-081–090 và SKU giỏ SC-111–120 **không còn scenario fail theo report v3**. Điều đó không chứng minh mọi turn đều hoàn hảo: các vấn đề dưới đây vẫn tồn tại dù TSR cao.

## P0 — SC-048: lỗi 504 đúng lúc chốt đơn, trạng thái đơn không đối soát được

- `call_3/turn1`: khách nói “Chốt một chiếc như đã trao đổi nhé.” Provider trả `504 DEADLINE_EXCEEDED`; trace ghi response rỗng, 0 tool call, 0 memory write. [Worker log](benchmark/benchmark_v3/part_1/worker.log) có lỗi tại SC-048/call_3/turn1.
- `call_3/turn2`: agent khẳng định đã tạo đơn `ORD-7DF97225`, nhưng turn này cũng **không có `order.create`/`order.status`**; [facts.md](benchmark/benchmark_v3/part_1/memory/SC-048/C024/facts.md) không có `order_id`. Vì turn trước đã lỗi sau khi bắt đầu chạy, không thể kết luận từ trace rằng đơn thật chưa tồn tại hay ID là bịa. Vấn đề chắc chắn là **mất khả năng đối soát side effect** sau timeout.
- Runner vẫn in `SC-048: ✓ 7 turns` dù README ghi `completed_with_errors` và report tính SC này fail. Dòng tiến độ gây hiểu nhầm.

**Cần làm:** trước khi trả lời “đã tạo đơn” sau một turn timeout, truy vấn `order.status` bằng idempotency key/phone hoặc kiểm tra trực tiếp trạng thái đã lưu. Ghi mutation thành công vào trace/audit bền vững trước bước gọi model tiếp theo; khi retry phải dùng lại idempotency key. Tách nhãn `turn_error` khỏi trạng thái “scenario đã chạy hết turn” trong runner. Test lại SC-048 với timeout giả lập ở thời điểm sau `order.create`.

## P1 — SC-114: nhắc tổng tiền mà không lấy báo giá hiện hành

- `call_2/turn1` khách yêu cầu nhắc hai món và **tổng tiền**. Agent gọi `catalog.search` 3 lần, **không gọi `pricing.get_quote`**, nhưng vẫn nói tổng `6.580.000đ` lấy từ thông tin đã có. Con số tình cờ trùng giá được xác minh ở turn sau; logic này sẽ sai nếu promotion đổi giữa hai call.
- Nhiều SC cùng mẫu có 2 `pricing.get_quote` đúng ở turn nhắc giỏ. SC-114 khác vì câu có “tiếp tục phần **tư vấn** lần trước”; hàm [is_basket_recap_request](../src/telesale_agent/core/basket.py) hiện loại mọi câu chứa `tu van`, có khả năng làm mất nhánh recap/pricing. Đây là **nguyên nhân suy ra từ code và trace**, cần regression test để xác nhận.

**Cần làm:** nhận diện yêu cầu “nhắc giỏ + tổng tiền” độc lập với cụm dẫn chuyện “tư vấn lần trước”; báo tổng chỉ khi có quote ngày hiện tại cho **mọi SKU**. Nếu không đủ quote, nói rõ chưa xác minh giá thay vì dùng giá lịch sử. Thêm test bằng nguyên văn SC-114/call_2/turn1.

## P1 — Giỏ nhiều món: chốt đơn trễ dù đã đủ thông tin

Trong 10 SC giỏ hàng, **SC-111, SC-116, SC-117, SC-118** nhận địa chỉ rồi nhận phương thức thanh toán ở `call_2/turn3`, nhưng agent chỉ hỏi khách xác nhận chốt thêm lần nữa. `order.create` đến `turn4` khi khách nhắc “lên đơn đúng giỏ”. Sáu SC còn lại tạo ngay ở turn3. Report vẫn cho cả 10 pass vì chấm ở cấp call, không đo turn hoàn tất.

**Cần làm:** khi giỏ/SKU, số lượng, địa chỉ, phương thức thanh toán và ý định đặt hàng đã được xác nhận trong luồng đang chốt, orchestration phải quyết định tạo đơn nhất quán; vẫn không tạo khi khách nói rõ “chưa đặt”. Thêm kiểm tra `time-to-create`/số turn thừa để evaluator không bỏ lọt việc chốt trễ.

## P2 — Read tool dư thừa, tăng latency/credit

- Cả **10/10** SC-111–120 đều gọi `order.status` ở `call_1/turn4` chỉ để xác nhận giỏ **chưa đặt**; đây không phải câu hỏi trạng thái đơn.
- SC-114/call_2/turn1 gọi 3 `catalog.search` nhưng bỏ qua pricing cần thiết. Các tool dư không bị TCA phạt.
- Tổng run dùng 2.372 Gemini request, 2.791.338 token và 1.130 tool call. Đây là số đo vận hành, không phải lỗi provider; ưu tiên sửa routing trên các mẫu cụ thể thay vì giảm tool bừa bãi.

**Cần làm:** phân biệt “xác nhận giỏ” với “kiểm tra đơn”; chỉ expose `order.status` khi hỏi đơn thực tế. Với basket đã lưu tên SKU từ catalog, tránh tìm lại từng món nếu không có lý do cập nhật catalog.

## Evaluator — các chỉ số cần sửa trước khi làm KPI

1. **SC-086 là false fail của TSR.** `call_2/turn1` agent nói RUN2-SALE “đã **hết thời hạn áp dụng**”, đúng ý hết hiệu lực, đồng thời báo giá mới `1.521.000đ`; turn2 còn xin lỗi và giải thích lại. Evaluator chỉ chấp nhận cụm `hết hạn | kết thúc | không còn hiệu lực`, nên chấm thiếu `must_say_any`. Mở rộng phrase/semantic match; không đánh dấu lỗi agent ở SC này.
2. **SC-048 cần technical-validity gate và audit mutation.** Turn 504 có response rỗng; không nên quy toàn bộ thành lỗi chọn tool. TCA thiếu `order.create` là đúng **trên trace quan sát được**, nhưng side effect có thể đã xảy ra trước timeout. Runner/evaluator cần trạng thái `incomplete/unknown` cho turn lỗi và đối soát order trước khi kết luận.
3. **RQR 31,5% (84/267) có false positive.** Ví dụ SC-002/call_2/turn2 agent hỏi địa chỉ và thanh toán, nhưng question extractor gắn slot `product_advised` chỉ vì phần dẫn có “sản phẩm này”. CTA “có muốn lên đơn không?” cũng dễ bị tính là hỏi lại fact. Chấm từng câu hỏi thực sự, không quét từ khóa trên cả câu ghép.
4. **CCR 67,7% (264/390) thấp hơn mức dùng memory quan sát được.** `facts_used` bỏ sót việc dùng `basket_skus`, tên sản phẩm hoặc fact biểu diễn khác tên canonical. Không suy ra tỷ lệ quên memory thực từ 67,7%.
5. **16 `memory_checks: review` là false flag trong v3 theo kiểm tra final file.** Sáu SC-092–100 còn `product_advised`; mười SC-111–120 còn `basket_item_1` đúng trong `facts.md`. Heuristic hiện chỉ tìm fact trong `memory_writes` của call được chấm, không đọc trạng thái cuối; không nên coi `review` là memory fail.
6. **HR 0/472 chưa bao phủ lời khẳng định tự do.** Ví dụ SC-048/call_3/turn2 tuyên bố một mã đơn khi trace hiện hành không có tool/memory chứng thực; `claims[]` không đưa claim này vào mẫu số. Cần trích claim trong `agent_text` và đối soát bằng tool/DB; không diễn giải HR 0% là không hallucination.
7. **Khoảng trống đo lường:** `memory_write_quality` chưa chạy; giá USD/call = `null` vì chưa nhập rate; Calls-to-Close 1,99 dựa trên customer script cố định, không phải mô phỏng khách động.

## Thứ tự xử lý trước lần full tiếp theo

1. P0: đối soát đơn sau 504/retry và sửa status runner, chạy lại SC-048.
2. P1: sửa route recap/pricing SC-114, regression test giá thay đổi giữa hai call.
3. P1: bỏ turn xác nhận thừa ở SC-111/116/117/118 mà vẫn giữ guard “chưa đặt”.
4. P2: loại `order.status` trên turn chỉ xác nhận giỏ.
5. Sửa evaluator SC-086, memory checks, RQR/CCR/HR trước khi dùng số tổng làm KPI báo cáo.
