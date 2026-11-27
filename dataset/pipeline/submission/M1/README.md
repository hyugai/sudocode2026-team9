# Báo cáo bộ dữ liệu M1

Bộ M1 có **124 hội thoại, 266 phiên và 50 khách hàng**. Mỗi tệp `SC-XXX.json` chứa một hội thoại và giữ `scenario_id` gốc. [Tệp đánh giá](stage-3/output/) · [Thống kê cuối](stage-3/output/audit/dataset_stats.json)

| Bước | Hội thoại kiểm tra | Qua | Loại | Tỷ lệ qua |
| --- | ---: | ---: | ---: | ---: |
| Stage 1 · Lập và kiểm tra kịch bản | 140 | 140 | 0 | 100% |
| Stage 2 · Kiểm tra định dạng Python | 140 | 140 | 0 | 100% |
| Stage 2 · Kiểm định DeepEval | 140 | 124 | 16 | 88,6% |
| Stage 3 · Rà soát và xuất dữ liệu | 124 | 124 | 0 | 100% |

## Stage 1 – Lập kịch bản

Stage 1 lập 140 hội thoại cho 50 hồ sơ CRM của BTC, gồm 120 hội thoại có 2 phiên và 20 hội thoại có 3 phiên, tổng cộng 300 phiên dự kiến. Mỗi kịch bản được tính đúng một lần theo kiểu khách và kiểu hội thoại chính. [Kịch bản](stage-1/output/blueprints.jsonl) · [Hồ sơ khách](stage-1/output/customers.json)

| Kiểu khách | Cân nhắc và quyết định | Tiếp nối đa kênh | Thay đổi giá hoặc tồn kho | Hỗ trợ sau mua | Danh tính hoặc lịch sử | Chuyển tiếp | Tổng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hỏi ý kiến gia đình | 14 | 4 | 6 | 0 | 0 | 0 | 24 |
| So sánh giá | 14 | 5 | 11 | 0 | 0 | 0 | 30 |
| Quay lại đổi hàng hoặc khiếu nại | 0 | 3 | 3 | 24 | 2 | 0 | 32 |
| Hỏi nhiều, chưa mua | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| Mất kiên nhẫn ở cuộc gọi thứ ba | 0 | 0 | 0 | 6 | 0 | 0 | 6 |
| Chuyển giữa chat và hotline | 0 | 9 | 0 | 0 | 0 | 0 | 9 |
| Chấp nhận chuyển máy khi ngoài phạm vi | 0 | 0 | 0 | 0 | 0 | 11 | 11 |
| Hỏi ngoài tài liệu của cửa hàng | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| Chất vấn báo giá mâu thuẫn | 0 | 6 | 0 | 0 | 0 | 0 | 6 |
| Dùng chung số điện thoại | 0 | 0 | 0 | 0 | 4 | 0 | 4 |
| Quay lại sau tám tháng | 0 | 0 | 0 | 0 | 6 | 0 | 6 |
| Mua nhiều món | 0 | 0 | 6 | 0 | 0 | 0 | 6 |
| **Tổng** | **34** | **27** | **26** | **30** | **12** | **11** | **140** |

## Stage 2 – Sinh và kiểm định lời thoại

`Qwen3-30B-A3B Q4_K_M` tạo lời thoại khách hàng theo từng hội thoại. Cả 140 bản nháp qua kiểm tra Python ngay ở lần đầu. Bản nháp phải có đúng các phiên trong kịch bản và 2–5 lượt lời trên một dòng cho mỗi phiên. Bộ kiểm tra loại nhãn người nói và chỗ trống chưa điền. [Bản nháp và kết quả kiểm tra](stage-2/generation/output/candidates.jsonl)

DeepEval 4.3.4 dùng `Gemma 4 12B IT QAT Q4_0` để kiểm tra mục tiêu, dữ kiện bắt buộc, tính liên tục và vai khách hàng. Hội thoại được giữ khi Gemma trả về `pass` và cả `persona_fit` lẫn `vietnamese_naturalness` đạt ít nhất 0,7. Tổng cộng 124 hội thoại được giữ, phủ 266 phiên. [Luật chấm](stage-2/validation/src/judge_metric.py) · [Báo cáo chấm](stage-2/validation/output/judge-report.jsonl) · [Lời thoại đã duyệt](stage-2/validation/output/transcripts.jsonl)

### Thống kê điểm

Mỗi điểm ở thang 0–1 và thuộc một hội thoại. Tập toàn bộ gồm cả hai nhóm đã duyệt và bị loại. Thống kê được tính từ báo cáo chấm và làm tròn đến bốn chữ số thập phân. [Điểm gốc](stage-2/validation/output/judge-report.jsonl)

#### Toàn bộ (140 hội thoại được chấm)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 140 | 0,9621 | 1,0000 | 0,0000 | 1,0000 |
| `journey_continuity` | 140 | 0,9607 | 1,0000 | 0,0000 | 1,0000 |
| `persona_fit` | 140 | 0,9929 | 1,0000 | 0,7000 | 1,0000 |
| `vietnamese_naturalness` | 140 | 0,9757 | 1,0000 | 0,8000 | 1,0000 |

#### Đã duyệt (124 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 124 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `journey_continuity` | 124 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |
| `persona_fit` | 124 | 0,9992 | 1,0000 | 0,9000 | 1,0000 |
| `vietnamese_naturalness` | 124 | 0,9895 | 1,0000 | 0,8000 | 1,0000 |

#### Bị loại (16 hội thoại)

| Chỉ số | Số điểm | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_goal_coverage` | 16 | 0,6687 | 0,5000 | 0,0000 | 1,0000 |
| `journey_continuity` | 16 | 0,6562 | 0,5000 | 0,0000 | 1,0000 |
| `persona_fit` | 16 | 0,9437 | 1,0000 | 0,7000 | 1,0000 |
| `vietnamese_naturalness` | 16 | 0,8688 | 0,8500 | 0,8000 | 1,0000 |

### Hội thoại bị loại

Mỗi hội thoại được gán một nhóm lỗi chính theo lý do trong phán quyết đã lưu. Một phán quyết có thể nêu nhiều lỗi. [Lý do gốc](stage-2/validation/output/judge-report.jsonl)

| Nhóm lỗi chính | Số hội thoại | Mã kịch bản | Lý do được nêu |
| --- | ---: | --- | --- |
| Mục tiêu phiên hoặc kết quả kỳ vọng | 7 | SC-005, SC-016, SC-022, SC-035, SC-072, SC-073, SC-092 | Thiếu bước hẹn gọi lại, dừng trước khi đặt hàng hoặc diễn ra theo kết quả khác kịch bản. |
| Thiếu hoặc sai dữ kiện bắt buộc | 3 | SC-015, SC-023, SC-053 | Thiếu phương thức thanh toán hoặc địa chỉ giao hàng, hoặc địa chỉ sai kịch bản. |
| Tính liên tục hoặc trình tự | 2 | SC-012, SC-024 | Nhắc đến một tương tác hoặc đưa dữ kiện vào sai phiên. |
| Vai người nói hoặc luồng hội thoại | 1 | SC-045 | Một phần lời khách được diễn giải là lời của trợ lý. |
| Lặp câu hỏi hoặc đề cập chủ đề bị hạn chế | 3 | SC-104, SC-123, SC-129 | Judge viện dẫn `must_not_ask` khi khách lặp câu hỏi hoặc nhắc đến sản phẩm. |
| **Tổng** | **16** | | |

Ba phán quyết ở nhóm cuối cần được đọc cùng quy tắc chấm của BTC vì `must_not_ask` áp dụng cho câu hỏi của trợ lý. Bảng phản ánh phán quyết đã lưu. [Mã chấm của BTC](btc/BTC-cap-nhat-11-2026/eval/reference_eval.py)

## Stage 3 – Lắp ghép và xuất dữ liệu

Stage 3 ghép lời thoại đã duyệt với kịch bản theo `scenario_id` và gắn hồ sơ theo `customer_id`. Kết quả có 0 hội thoại bị loại do thông tin cá nhân và 0 hội thoại bị loại do trùng lặp. Trình chấm tham chiếu của BTC đọc được các tệp xuất trong lượt kiểm tra với vết tương tác rỗng. [Thống kê](stage-3/output/audit/dataset_stats.json) · [Rà soát thông tin cá nhân](stage-3/output/audit/pii_audit_report.json) · [Nhật ký trùng lặp](stage-3/output/audit/stage3_dropped_duplicates.jsonl)

TF-IDF dùng toàn bộ lời khách qua các phiên để tạo một vectơ cho mỗi hội thoại. Bảng tính cosine cho cả 7.626 cặp hội thoại khác nhau trong tập đã duyệt. Cặp gần nhất là SC-133 và SC-135, với điểm 0,8221, dưới ngưỡng loại 0,90. [Mã tính TF-IDF](stage-3/src/validate_and_split.py)

| Số cặp | Trung bình | Trung vị | Nhỏ nhất | Lớn nhất |
| ---: | ---: | ---: | ---: | ---: |
| 7.626 | 0,2371 | 0,2193 | 0,0338 | 0,8221 |

| Chiều phân bố cuối | Kết quả |
| --- | --- |
| Số phiên mỗi hội thoại | 106 hội thoại có 2 phiên, 18 hội thoại có 3 phiên |
| Kênh | Hotline 233, Zalo 19, Fanpage 14 |
| Kết quả kỳ vọng theo phiên | Chốt đơn 134, hẹn gọi lại 106, từ chối 15, chuyển máy 11 |
| Kiểu hội thoại | Hỗ trợ sau mua 28, cân nhắc và quyết định 27, tiếp nối đa kênh 24, thay đổi giá hoặc tồn kho 24, chuyển tiếp 11, danh tính hoặc lịch sử 10 |
| Kiểu khách phổ biến nhất | Quay lại đổi hàng hoặc khiếu nại 29, so sánh giá 23, hỏi ý kiến gia đình 21 |
| Khách theo vùng | Bắc 15, Trung 18, Nam 17 |

Phân bố kiểu hội thoại và vùng dùng các kịch bản và hồ sơ được liên kết với tệp xuất. [Kịch bản](stage-1/output/blueprints.jsonl) · [Hồ sơ khách](stage-1/output/customers.json) · [Tệp xuất](stage-3/output/)

## Chạy lại trên Kaggle

| Bước | Cách chạy |
| --- | --- |
| Stage 1 | Dùng CPU và đính kèm tệp đã giải nén với đường dẫn `stage-1/src/generate.py` cùng `stage-1/input/`. Giữ `TIER = "M1"`. Gói này dùng phiên bản bộ sinh đi kèm đầu vào của lần chạy M1. [Notebook](stage-1/generate.ipynb) |
| Stage 2 · Sinh lời thoại | Đính kèm thư mục `stage-2/generation/` và mô hình `Qwen3-30B-A3B-Q4_K_M.gguf`. Chọn GPU T4 ×2, bật Internet cho runtime và đặt `JOURNEYS = None` để chạy đủ 140 hội thoại. Bản sao notebook đọc dữ liệu từ `input/stage-2-input/`. [Notebook](stage-2/generation/generate.ipynb) |
| Stage 2 · Kiểm định | Đính kèm thư mục `stage-2/validation/` và mô hình `gemma-4-12b-it-qat-q4_0.gguf`. Chọn GPU T4 ×2, bật Internet để cài runtime và DeepEval, rồi đặt `JOURNEYS = None`. `CANDIDATES_PATH` cho phép chọn bản nháp mới từ cùng tập kịch bản. [Notebook](stage-2/validation/validate.ipynb) |
| Stage 3 | Dùng CPU và đính kèm thư mục `M1/` đã giải nén để giữ `stage-3/`, `stage-1/` và `btc/` cùng cấp. Notebook xuất tệp và báo cáo kiểm tra vào `/kaggle/working/output/`. [Notebook](stage-3/finalize.ipynb) |
