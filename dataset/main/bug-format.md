# Bug format

## Kết quả kiểm tra hiện tại

| Hạng mục | Kết quả | Trạng thái |
|---|---|---|
| JSONL → JSON | Có 120 file trong `scenarios_complete/` và 120 file trong `scenarios_prefilled/`. Mỗi file chứa một scenario hoặc bản prefilled tương ứng. | Đã khắc phục. |
| `scenario_id` | JSON dùng `SC-001` đến `SC-120`, không trùng ID và khớp tên file. | Đã khắc phục. |
| Hướng dẫn export trong prefilled | Cả 120 bản hướng dẫn xuất `<scenario_id>.json`, giữ nguyên ID hiện có và bỏ wrapper; không còn yêu cầu tên `SC-G9-xxx.json`. | Đã khắc phục. |
| Nguồn dữ liệu cũ | Đã xóa `01_scenarios_prefilled.jsonl` và `02_scenarios_complete.jsonl`; giữ nguyên nội dung các file JSON hiện hành. | Đã khắc phục. |
| Tên thư mục | Đã bỏ dấu cách và từ `dataset` dư thừa trong tên hai thư mục scenario. | Đã khắc phục. |
| README và đường dẫn | README mô tả nguồn JSON; các mặc định chạy đánh giá trỏ đến `dataset/main/scenarios_complete/`. | Đã cập nhật. |

BTC dùng một file JSON cho mỗi scenario. `SC-xx.json` là cách mô tả tên file trong tài liệu BTC; bộ hiện tại dùng hậu tố ba chữ số cho 120 scenario.

## Nguồn dữ liệu hiện hành

- `scenarios_complete/*.json`: đầu vào chạy đánh giá.
- `scenarios_prefilled/*.json`: đầu vào hỗ trợ sinh kịch bản, có wrapper và không phải đầu vào trực tiếp cho evaluator BTC.
- JSONL cũ không còn là nguồn dữ liệu hoạt động. Lịch sử phiên bản vẫn có thể xem qua Git.

## Kiểm chứng và giới hạn

- Giữ nguyên nội dung của cả 240 file JSON khi đổi tên thư mục.
- Hai bộ có đủ 120 ID, ghép cặp theo ID và tên file khớp ID.
- Trước khi xóa, complete JSON khớp JSONL sau chuẩn hóa ID; prefilled có khác biệt ngoài ID. Theo quyết định giữ bản cập nhật nhất, giữ nguyên prefilled JSON hiện hành thay vì ghi đè bằng JSONL cũ.
- Manifest hiện không còn ID `SC-G9-xxx`; việc kiểm tra đầy đủ audio và tính nhất quán seed/complete là bước riêng, chưa được kết luận chỉ từ thay đổi cấu trúc thư mục.
- Các lỗi chất lượng trong `bug-quality.md` vẫn chưa được khắc phục.
