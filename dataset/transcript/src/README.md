# Đầu vào của pipeline transcript

## Stage 1 · Lập kịch bản

| Trạng thái | Đầu vào | Cách dùng |
| --- | --- | --- |
| Cố định, có sẵn | Danh mục sản phẩm, lịch tồn kho, khuyến mãi, CRM mẫu, địa chỉ tham chiếu, `personas.json` và công cụ giả lập BTC | Tạo khách, phiên và dữ kiện nghiệp vụ cho kịch bản. [Thư mục đầu vào](stage-1/input/) |
| Cần cung cấp cho M2 | `blueprints.jsonl` từ Stage 1 của M1 | Trỏ `M1_BLUEPRINTS` tới tệp này để đối chiếu trùng lặp và đánh tiếp mã kịch bản. |
| Cần cung cấp khi tái lập M1 đã công bố | Các blueprint đối chiếu lịch sử | Đặt trong `stage-1/input/duplicate-references/` để dùng lại bộ đối chiếu của lần chạy đã công bố. |

## Stage 2 · Sinh và kiểm định lời thoại

| Trạng thái | Đầu vào | Cách dùng |
| --- | --- | --- |
| Cố định, có sẵn | `personas.json` và `prompts.json` | Mô tả hành vi, cách nói, hướng dẫn sinh lời thoại và tiêu chí chấm DeepEval. [Đầu vào bước sinh](stage-2/generation/input/) · [Đầu vào bước kiểm định](stage-2/validation/input/) |
| Cần cung cấp cho cả hai bước | `blueprints.jsonl` từ Stage 1, đã chuẩn hóa theo định dạng Stage 2 | Đặt cùng bản vào `stage-2/generation/input/` và `stage-2/validation/input/`. |
| Cần cung cấp cho bước kiểm định | `candidates.jsonl` từ bước sinh lời thoại | Đặt trong `stage-2/validation/input/` để chấm các lời thoại đã sinh. |
| Cần đính kèm trên Kaggle | `Qwen3-30B-A3B-Q4_K_M.gguf` và `gemma-4-12b-it-qat-q4_0.gguf` | Qwen sinh lời thoại. Gemma chấm lời thoại qua DeepEval. |

## Stage 3 · Hoàn thiện bộ dữ liệu

| Trạng thái | Đầu vào | Cách dùng |
| --- | --- | --- |
| Cố định, có sẵn | CRM mẫu, danh sách địa chỉ và trình chấm tham chiếu BTC | Đối chiếu thông tin nhận dạng, địa chỉ và kiểm tra tệp kịch bản đã xuất. [Hồ sơ CRM](btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json) · [Địa chỉ](stage-1/input/catalog/public-delivery-addresses.json) · [Trình chấm BTC](btc/BTC-cap-nhat-11-2026/eval/reference_eval.py) |
| Cần cung cấp từ Stage 1 | `blueprints.jsonl` và `customers.json` | Đặt trong `stage-3/input/` để ghép kịch bản và hồ sơ khách. |
| Cần cung cấp từ Stage 2 | `transcripts.jsonl` đã qua kiểm định | Đặt trong `stage-3/input/` để ghép lời thoại đã duyệt vào kịch bản. |

Xem cách chuẩn bị và chạy notebook cho từng tier. [M1](../M1/README.md#chạy-lại-trên-kaggle) · [M2](../M2/README.md#chạy-lại-trên-kaggle)
