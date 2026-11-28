# Báo cáo bộ dữ liệu M2

Bản M2 có **158 hội thoại, 344 phiên và 50 khách hàng**. [Tệp đánh giá](./) · [Thống kê cuối](../../pipeline/submission/M2/stage-3/output/audit/dataset_stats.json)

| Bước | Hội thoại kiểm tra | Qua | Loại | Cần xem lại | Tỷ lệ qua |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stage 1 · Lập và kiểm tra kịch bản | 180 | 180 | 0 | 0 | 100% |
| Stage 2 · Kiểm tra định dạng Python | 180 | 180 | 0 | 0 | 100% |
| Stage 2 · Kiểm định DeepEval | 180 | 158 | 20 | 2 | 87,8% |
| Stage 3 · Rà soát và xuất dữ liệu | 158 | 158 | 0 | 0 | 100% |

## Stage 1 · Lập kịch bản

Stage 1 lập 180 hội thoại cho 50 hồ sơ CRM của BTC, gồm 150 hội thoại có 2 phiên và 30 hội thoại có 3 phiên, tổng cộng 390 phiên dự kiến. Tập kịch bản bao phủ **19/72 tổ hợp** từ 12 kiểu khách và 6 kiểu hội thoại. Mỗi kịch bản M2 có `simulator_profile` trong tệp Stage 1 để cấu hình tác nhân đóng vai khách. [Kịch bản](../../pipeline/submission/M2/stage-1/output/blueprints.jsonl) · [Hồ sơ khách](../../pipeline/submission/M2/stage-1/output/customers.json)

| Kiểu khách | Cân nhắc và quyết định | Tiếp nối đa kênh | Thay đổi giá hoặc tồn kho | Hỗ trợ sau mua | Danh tính hoặc lịch sử | Chuyển tiếp | Tổng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hỏi ý kiến gia đình | 14 | 8 | 7 | 0 | 0 | 0 | 29 |
| So sánh giá | 13 | 9 | 13 | 0 | 0 | 0 | 35 |
| Quay lại đổi hàng hoặc khiếu nại | 0 | 6 | 5 | 27 | 4 | 0 | 42 |
| Hỏi nhiều, chưa mua | 5 | 0 | 0 | 0 | 0 | 0 | 5 |
| Mất kiên nhẫn ở cuộc gọi thứ ba | 0 | 0 | 0 | 10 | 0 | 0 | 10 |
| Chuyển giữa chat và hotline | 0 | 12 | 0 | 0 | 0 | 0 | 12 |
| Chấp nhận chuyển máy khi ngoài phạm vi | 0 | 0 | 0 | 0 | 0 | 14 | 14 |
| Hỏi ngoài tài liệu của cửa hàng | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| Chất vấn báo giá mâu thuẫn | 0 | 10 | 0 | 0 | 0 | 0 | 10 |
| Dùng chung số điện thoại | 0 | 0 | 0 | 0 | 4 | 0 | 4 |
| Quay lại sau tám tháng | 0 | 0 | 0 | 0 | 9 | 0 | 9 |
| Mua nhiều món | 0 | 0 | 7 | 0 | 0 | 0 | 7 |
| **Tổng** | 35 | 45 | 32 | 37 | 17 | 14 | 180 |

## Stage 2 · Sinh và kiểm định lời thoại

### Sinh lời thoại

`Qwen3-30B-A3B Q4_K_M` tạo lời thoại khách theo kịch bản. Cả 180 hội thoại qua kiểm tra Python ngay lần đầu. Mã kiểm tra các khóa phiên, yêu cầu 2–5 lượt lời không rỗng trên một dòng cho mỗi phiên và loại nhãn người nói hoặc chỗ trống chưa điền. [Bản nháp và kết quả kiểm tra](../../pipeline/submission/M2/stage-2/generation/output/candidates.jsonl) · [Mã sinh lời thoại](../src/stage-2/generation/src/generation.py)

### Kiểm định lời thoại

DeepEval dùng `Gemma 4 12B IT QAT Q4_0` để kiểm tra mục tiêu, dữ kiện bắt buộc, tính liên tục và vai người nói. Hội thoại được duyệt khi mô hình trả về `pass` và cả `persona_fit` lẫn `vietnamese_naturalness` đạt ít nhất 0,7. Có 178 hội thoại với điểm hợp lệ. Hai hội thoại `SC-301`, `SC-339` cần xem lại vì phản hồi chấm chứa điểm vượt thang 0–1. [Luật chấm](../src/stage-2/validation/src/judge_metric.py) · [Báo cáo chấm](../../pipeline/submission/M2/stage-2/validation/output/judge-report.jsonl) · [Lời thoại đã duyệt](../../pipeline/submission/M2/stage-2/validation/output/transcripts.jsonl)

### Thống kê điểm

Mỗi điểm ở thang 0–1 và thuộc một hội thoại. Giá trị được làm tròn đến bốn chữ số thập phân.

#### Toàn bộ có điểm hợp lệ (178 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 178 | 0,9504 | 1,0000 | 0,0000 | 1,0000 |
| `journey_continuity` | 178 | 0,9539 | 1,0000 | 0,0000 | 1,0000 |
| `persona_fit` | 178 | 0,9904 | 1,0000 | 0,6000 | 1,0000 |
| `vietnamese_naturalness` | 178 | 0,9871 | 1,0000 | 0,8000 | 1,0000 |

#### Đã duyệt (158 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 158 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `journey_continuity` | 158 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `persona_fit` | 158 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `vietnamese_naturalness` | 158 | 0,9962 | 1,0000 | 0,8000 | 1,0000 |

#### Bị loại (20 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 20 | 0,5585 | 0,5000 | 0,0000 | 1,0000 |
| `journey_continuity` | 20 | 0,5900 | 0,5000 | 0,0000 | 1,0000 |
| `persona_fit` | 20 | 0,9150 | 1,0000 | 0,6000 | 1,0000 |
| `vietnamese_naturalness` | 20 | 0,9150 | 0,9000 | 0,8000 | 1,0000 |

### Hội thoại bị loại

Mỗi hội thoại bị loại được tính một lần theo lý do chính trong phán quyết đã lưu. [Lý do gốc](../../pipeline/submission/M2/stage-2/validation/output/judge-report.jsonl)

| Nhóm lỗi chính | Số hội thoại | Mã kịch bản gốc | Lý do được nêu |
| --- | ---: | --- | --- |
| Thiếu hoặc sai dữ kiện bắt buộc | 8 | `SC-195`, `SC-207`, `SC-227`, `SC-241`, `SC-245`, `SC-246`, `SC-249`, `SC-262` | Thiếu giờ hẹn, địa chỉ, cách thanh toán hay sản phẩm, hoặc đưa thông tin khác với kịch bản. |
| Mục tiêu hoặc kết quả phiên | 5 | `SC-219`, `SC-253`, `SC-275`, `SC-306`, `SC-330` | Chuyển sang đặt hàng quá sớm, tiếp tục do dự khi cần chốt, bỏ hẹn lại hoặc hỏi về đơn cũ thay vì đặt đơn mới. |
| Vai người nói hoặc cách xưng hô | 3 | `SC-186`, `SC-270`, `SC-352` | Đổi cách xưng hô giữa các phiên hoặc đưa câu báo giá của nhân viên vào lời khách. |
| Dữ kiện ngoài kịch bản hoặc sai phiên | 4 | `SC-184`, `SC-189`, `SC-217`, `SC-351` | Nhắc tương tác chưa xảy ra, báo hết hàng trái với kịch bản hoặc đưa chủ đề của phiên sau vào phiên trước. |
| **Tổng** | **20** |  |  |

## Stage 3 · Lắp ghép và xuất dữ liệu

Stage 3 ghép lời khách theo `scenario_id` và hồ sơ theo `customer_id`. Rà soát thông tin cá nhân và lọc trùng lặp giữ lại đủ 158 hội thoại đã duyệt. Trình chấm tham chiếu của BTC đọc được các tệp xuất khi chạy với vết tương tác rỗng. Tên tệp là `SC-158.json` đến `SC-315.json`, nối tiếp `SC-157.json` của M1. Mỗi tệp giữ `scenario_id` gốc. Thống kê xuất ghi 50/60 khách đa phiên theo tùy chọn đã duyệt cho đợt này. Hai thư mục chứa 315 tệp hội thoại văn bản, trong đó đợt M2 bổ sung 158 tệp. [Thống kê](../../pipeline/submission/M2/stage-3/output/audit/dataset_stats.json) · [Rà soát thông tin cá nhân](../../pipeline/submission/M2/stage-3/output/audit/pii_audit_report.json) · [Nhật ký trùng lặp](../../pipeline/submission/M2/stage-3/output/audit/stage3_dropped_duplicates.jsonl) · [Nhật ký đổi tên](../../pipeline/submission/M2/stage-3/output/audit/renamed_scenarios.jsonl)

### Độ tương đồng TF-IDF

Mỗi vectơ dùng toàn bộ lời khách qua các phiên. Ngưỡng loại theo độ tương đồng cosine là trên 0,90. [Mã tính TF-IDF](../src/stage-3/src/validate_and_split.py)

Cặp gần nhất có mã gốc `SC-257` và `SC-315`, với điểm 0,7872. [Tệp thứ nhất](SC-221.json) · [Tệp thứ hai](SC-274.json)

| Số cặp | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| ---: | ---: | ---: | ---: | ---: |
| 12.403 | 0,2394 | 0,2204 | 0,0387 | 0,7872 |

### Phân bố sau khi xuất

| Chiều phân bố cuối | Kết quả |
| --- | --- |
| Số phiên mỗi hội thoại | 130 hội thoại có 2 phiên và 28 hội thoại có 3 phiên |
| Kênh | Hotline 304, Zalo 24, Fanpage 16 |
| Kết quả kỳ vọng theo phiên | Chốt đơn 177, hẹn gọi lại 139, từ chối 16, chuyển máy 12 |
| Kiểu hội thoại | Tiếp nối đa kênh (37), Hỗ trợ sau mua (35), Cân nhắc và quyết định (30), Thay đổi giá hoặc tồn kho (29), Danh tính hoặc lịch sử (15), Chuyển tiếp (12) |
| Khách theo vùng | miền Bắc 15 khách (50 hội thoại), miền Trung 18 khách (54 hội thoại), miền Nam 17 khách (54 hội thoại) |
| Khách đa phiên | 50 |
| Khách có hội thoại 3 phiên | 28 |
| Khách có hotline và chat | 30 |
| Tình huống khó | 69 |
| SKU xuất hiện trong tệp đánh giá | 70 mã từ 35 sản phẩm gốc |

## Chạy lại trên Kaggle

Chuẩn bị một bản sao của [mã nguồn và đầu vào cố định](../src/) cho lần chạy. Đặt các tệp sinh ra trong lần chạy vào những đường dẫn mà notebook đọc trước khi đính kèm gói lên Kaggle. Ở Stage 2, `JOURNEYS = None` xử lý toàn bộ đầu vào.

| Bước | Cách chạy |
| --- | --- |
| Stage 1 | Dùng CPU và tắt Internet. Đặt `M1_BLUEPRINTS` trỏ tới `blueprints.jsonl` từ lần chạy Stage 1 của M1. [Notebook M2](../src/stage-1/generate-m2.ipynb) |
| Stage 2 · Sinh lời thoại | Đặt bản `blueprints.jsonl` đã chuẩn hóa cho Stage 2 vào `stage-2/generation/input/`. Đính kèm `Qwen3-30B-A3B-Q4_K_M.gguf`, dùng GPU T4 ×2 và bật Internet. [Notebook](../src/stage-2/generation/generate.ipynb) |
| Stage 2 · Kiểm định | Đặt cùng bản `blueprints.jsonl` và `candidates.jsonl` từ bước sinh vào `stage-2/validation/input/`. Đính kèm `gemma-4-12b-it-qat-q4_0.gguf`, dùng GPU T4 ×2 và bật Internet. [Notebook](../src/stage-2/validation/validate.ipynb) |
| Stage 3 | Dùng CPU. Đặt `blueprints.jsonl` và `customers.json` từ Stage 1 cùng `transcripts.jsonl` từ bước kiểm định vào `stage-3/input/`. Notebook áp dụng ngoại lệ ngưỡng khách đa phiên và xuất theo mã gốc. Bản công bố đánh số tiếp sau M1. Tải `/kaggle/working/stage-3-output.zip` sau khi chạy. [Notebook M2](../src/stage-3/finalize-m2.ipynb) |
