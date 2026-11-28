# Báo cáo bộ dữ liệu M1

Bản M1 có **157 hội thoại, 338 phiên và 35 khách hàng**. [Tệp đánh giá](./) · [Thống kê cuối](../../pipeline/submission/M1/stage-3/output/audit/dataset_stats.json)

| Bước | Hội thoại kiểm tra | Qua | Loại | Cần xem lại | Tỷ lệ qua |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stage 1 · Lập và kiểm tra kịch bản | 180 | 180 | 0 | 0 | 100% |
| Stage 2 · Kiểm tra định dạng Python | 180 | 180 | 0 | 0 | 100% |
| Stage 2 · Kiểm định DeepEval | 180 | 157 | 21 | 2 | 87,2% |
| Stage 3 · Rà soát và xuất dữ liệu | 157 | 157 | 0 | 0 | 100% |

## Stage 1 · Lập kịch bản

Stage 1 lập 180 hội thoại cho 35 hồ sơ CRM của BTC, gồm 152 hội thoại có 2 phiên và 28 hội thoại có 3 phiên, tổng cộng 388 phiên dự kiến. Tập kịch bản bao phủ **35/72 tổ hợp** từ 12 kiểu khách và 6 kiểu hội thoại. [Kịch bản](../../pipeline/submission/M1/stage-1/output/blueprints.jsonl) · [Hồ sơ khách](../../pipeline/submission/M1/stage-1/output/customers.json)

| Kiểu khách | Cân nhắc và quyết định | Tiếp nối đa kênh | Thay đổi giá hoặc tồn kho | Hỗ trợ sau mua | Danh tính hoặc lịch sử | Chuyển tiếp | Tổng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hỏi ý kiến gia đình | 13 | 5 | 7 | 3 | 0 | 0 | 28 |
| So sánh giá | 10 | 5 | 9 | 2 | 0 | 3 | 29 |
| Quay lại đổi hàng hoặc khiếu nại | 3 | 5 | 5 | 19 | 5 | 2 | 39 |
| Hỏi nhiều, chưa mua | 3 | 4 | 2 | 2 | 0 | 0 | 11 |
| Mất kiên nhẫn ở cuộc gọi thứ ba | 0 | 0 | 2 | 10 | 2 | 2 | 16 |
| Chuyển giữa chat và hotline | 0 | 12 | 0 | 0 | 0 | 0 | 12 |
| Chấp nhận chuyển máy khi ngoài phạm vi | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| Hỏi ngoài tài liệu của cửa hàng | 2 | 5 | 0 | 0 | 0 | 2 | 9 |
| Chất vấn báo giá mâu thuẫn | 0 | 6 | 0 | 0 | 0 | 0 | 6 |
| Dùng chung số điện thoại | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| Quay lại sau tám tháng | 0 | 0 | 2 | 3 | 10 | 0 | 15 |
| Mua nhiều món | 0 | 0 | 4 | 2 | 0 | 0 | 6 |
| **Tổng** | 31 | 42 | 31 | 41 | 19 | 16 | 180 |

## Stage 2 · Sinh và kiểm định lời thoại

### Sinh lời thoại

`Qwen3-30B-A3B Q4_K_M` tạo lời thoại khách theo kịch bản. Cả 180 hội thoại qua kiểm tra Python ngay lần đầu. Mã kiểm tra các khóa phiên, yêu cầu 2–5 lượt lời không rỗng trên một dòng cho mỗi phiên và loại nhãn người nói hoặc chỗ trống chưa điền. [Bản nháp và kết quả kiểm tra](../../pipeline/submission/M1/stage-2/generation/output/candidates.jsonl) · [Mã sinh lời thoại](../src/stage-2/generation/src/generation.py)

### Kiểm định lời thoại

DeepEval dùng `Gemma 4 12B IT QAT Q4_0` để kiểm tra mục tiêu, dữ kiện bắt buộc, tính liên tục và vai người nói. Hội thoại được duyệt khi mô hình trả về `pass` và cả `persona_fit` lẫn `vietnamese_naturalness` đạt ít nhất 0,7. Có 178 hội thoại với điểm hợp lệ. Hai hội thoại `SC-041`, `SC-127` cần xem lại vì phản hồi chấm chứa điểm vượt thang 0–1. [Luật chấm](../src/stage-2/validation/src/judge_metric.py) · [Báo cáo chấm](../../pipeline/submission/M1/stage-2/validation/output/judge-report.jsonl) · [Lời thoại đã duyệt](../../pipeline/submission/M1/stage-2/validation/output/transcripts.jsonl)

### Thống kê điểm

Mỗi điểm ở thang 0–1 và thuộc một hội thoại. Giá trị được làm tròn đến bốn chữ số thập phân.

#### Toàn bộ có điểm hợp lệ (178 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 178 | 0,9618 | 1,0000 | 0,0000 | 1,0000 |
| `journey_continuity` | 178 | 0,9579 | 1,0000 | 0,5000 | 1,0000 |
| `persona_fit` | 178 | 0,9865 | 1,0000 | 0,6000 | 1,0000 |
| `vietnamese_naturalness` | 178 | 0,9781 | 1,0000 | 0,8000 | 1,0000 |

#### Đã duyệt (157 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 157 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `journey_continuity` | 157 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `persona_fit` | 157 | 0,9981 | 1,0000 | 0,8000 | 1,0000 |
| `vietnamese_naturalness` | 157 | 0,9885 | 1,0000 | 0,8000 | 1,0000 |

#### Bị loại (21 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 21 | 0,6762 | 0,8000 | 0,0000 | 1,0000 |
| `journey_continuity` | 21 | 0,6429 | 0,5000 | 0,5000 | 1,0000 |
| `persona_fit` | 21 | 0,9000 | 1,0000 | 0,6000 | 1,0000 |
| `vietnamese_naturalness` | 21 | 0,9000 | 0,9000 | 0,8000 | 1,0000 |

### Hội thoại bị loại

Mỗi hội thoại bị loại được tính một lần theo lý do chính trong phán quyết đã lưu. [Lý do gốc](../../pipeline/submission/M1/stage-2/validation/output/judge-report.jsonl)

| Nhóm lỗi chính | Số hội thoại | Mã kịch bản gốc | Lý do được nêu |
| --- | ---: | --- | --- |
| Thiếu hoặc sai dữ kiện bắt buộc | 7 | `SC-011`, `SC-019`, `SC-037`, `SC-100`, `SC-132`, `SC-166`, `SC-175` | Thiếu hoặc sai giờ hẹn, địa chỉ hay cách thanh toán. Một số lượt nhầm giá của cửa hàng với giá bên khác. |
| Mục tiêu hoặc kết quả phiên | 6 | `SC-023`, `SC-038`, `SC-107`, `SC-109`, `SC-129`, `SC-151` | Thiếu bước chốt đơn, hẹn lại, kiểm tra đơn hoặc xác minh người gọi theo kịch bản. |
| Vai người nói hoặc góc nhìn | 5 | `SC-086`, `SC-141`, `SC-143`, `SC-161`, `SC-171` | Mô hình chấm đọc một lượt báo giá hoặc xác nhận thông tin khách như lời nhân viên. |
| Dữ kiện ngoài kịch bản hoặc sai phiên | 3 | `SC-145`, `SC-176`, `SC-178` | Thêm món hoặc yêu cầu đổi kích cỡ ngoài kịch bản, hoặc hỏi trước nội dung của phiên sau. |
| **Tổng** | **21** |  |  |

## Stage 3 · Lắp ghép và xuất dữ liệu

Stage 3 ghép lời khách theo `scenario_id` và hồ sơ theo `customer_id`. Rà soát thông tin cá nhân và lọc trùng lặp giữ lại đủ 157 hội thoại đã duyệt. Trình chấm tham chiếu của BTC đọc được các tệp xuất khi chạy với vết tương tác rỗng. Tên tệp là `SC-001.json` đến `SC-157.json`, đánh số theo thứ tự mã kịch bản. Mỗi tệp giữ `scenario_id` gốc. [Thống kê](../../pipeline/submission/M1/stage-3/output/audit/dataset_stats.json) · [Rà soát thông tin cá nhân](../../pipeline/submission/M1/stage-3/output/audit/pii_audit_report.json) · [Nhật ký trùng lặp](../../pipeline/submission/M1/stage-3/output/audit/stage3_dropped_duplicates.jsonl) · [Nhật ký đổi tên](../../pipeline/submission/M1/stage-3/output/audit/renamed_scenarios.jsonl)

### Độ tương đồng TF-IDF

Mỗi vectơ dùng toàn bộ lời khách qua các phiên. Ngưỡng loại theo độ tương đồng cosine là trên 0,90. [Mã tính TF-IDF](../src/stage-3/src/validate_and_split.py)

Cặp gần nhất có mã gốc `SC-063` và `SC-065`, với điểm 0,7223. [Tệp thứ nhất](SC-057.json) · [Tệp thứ hai](SC-059.json)

| Số cặp | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| ---: | ---: | ---: | ---: | ---: |
| 12.246 | 0,2618 | 0,2495 | 0,0376 | 0,7223 |

### Phân bố sau khi xuất

| Chiều phân bố cuối | Kết quả |
| --- | --- |
| Số phiên mỗi hội thoại | 133 hội thoại có 2 phiên và 24 hội thoại có 3 phiên |
| Kênh | Hotline 293, Zalo 28, Fanpage 17 |
| Kết quả kỳ vọng theo phiên | Chốt đơn 184, hẹn gọi lại 120, từ chối 23, chuyển máy 11 |
| Kiểu hội thoại | Tiếp nối đa kênh (39), Hỗ trợ sau mua (33), Thay đổi giá hoặc tồn kho (29), Cân nhắc và quyết định (28), Danh tính hoặc lịch sử (17), Chuyển tiếp (11) |
| Khách theo vùng | miền Trung 18 khách (78 hội thoại), miền Nam 17 khách (79 hội thoại) |
| Khách đa phiên | 35 |
| Khách có hội thoại 3 phiên | 16 |
| Khách có hotline và chat | 21 |
| Tình huống khó | 71 |
| SKU xuất hiện trong tệp đánh giá | 45 mã từ 6 sản phẩm gốc |

## Chạy lại trên Kaggle

Chuẩn bị một bản sao của [mã nguồn và đầu vào cố định](../src/) cho lần chạy. Đặt các tệp sinh ra trong lần chạy vào những đường dẫn mà notebook đọc trước khi đính kèm gói lên Kaggle. Ở Stage 2, `JOURNEYS = None` xử lý toàn bộ đầu vào.

| Bước | Cách chạy |
| --- | --- |
| Stage 1 | Dùng CPU và tắt Internet. Để tái lập lần sinh đã công bố, bổ sung các blueprint đối chiếu lịch sử vào `stage-1/input/duplicate-references/`. [Notebook M1](../src/stage-1/generate-m1.ipynb) |
| Stage 2 · Sinh lời thoại | Đặt bản `blueprints.jsonl` đã chuẩn hóa cho Stage 2 vào `stage-2/generation/input/`. Đính kèm `Qwen3-30B-A3B-Q4_K_M.gguf`, dùng GPU T4 ×2 và bật Internet. [Notebook](../src/stage-2/generation/generate.ipynb) |
| Stage 2 · Kiểm định | Đặt cùng bản `blueprints.jsonl` và `candidates.jsonl` từ bước sinh vào `stage-2/validation/input/`. Đính kèm `gemma-4-12b-it-qat-q4_0.gguf`, dùng GPU T4 ×2 và bật Internet. [Notebook](../src/stage-2/validation/validate.ipynb) |
| Stage 3 | Dùng CPU. Đặt `blueprints.jsonl` và `customers.json` từ Stage 1 cùng `transcripts.jsonl` từ bước kiểm định vào `stage-3/input/`. Tải `/kaggle/working/stage-3-output.zip` sau khi chạy. [Notebook M1](../src/stage-3/finalize-m1.ipynb) |
