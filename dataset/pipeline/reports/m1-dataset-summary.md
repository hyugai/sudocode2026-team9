# Tóm tắt bộ dữ liệu M1

## Cách sinh dữ liệu

1. **Lập kịch bản.** Từ 35 hồ sơ CRM của ban tổ chức (BTC) ở miền Trung và miền Nam, Stage 1 tạo 180 kịch bản hội thoại thời trang với 388 phiên dự kiến. Kịch bản sử dụng 12 kiểu khách hàng và 6 kiểu hội thoại, bao phủ 35 tổ hợp. Mục tiêu, dữ kiện và hành động kỳ vọng của từng phiên dựa trên danh mục, tồn kho và khuyến mãi của BTC. [Báo cáo Stage 1](m1-stage1-report.md)
2. **Sinh và kiểm tra lời thoại.** `Qwen3-30B-A3B Q4_K_M` sinh từ 2 đến 5 lượt lời tiếng Việt của khách trong mỗi phiên. Cả 180 hội thoại qua kiểm tra định dạng bằng Python ngay lần đầu. DeepEval dùng `Gemma 4 12B IT QAT Q4_0` để kiểm định lời thoại, chấp nhận 157 hội thoại (87,2%), loại 21 và đánh dấu 2 cần xem lại. [Báo cáo Stage 2](m1-stage2-report.md)
3. **Hoàn thiện bộ dữ liệu.** Stage 3 ghép lời thoại đã duyệt với kịch bản và hồ sơ khách hàng, rà soát thông tin cá nhân và so sánh độ tương đồng TF-IDF với ngưỡng 0,90. Cả 157 hội thoại được giữ lại, với 0 trường hợp bị loại do thông tin cá nhân hoặc trùng lặp. Mỗi hội thoại được xuất thành một tệp `SC-XXX.json` theo định dạng BTC. [Báo cáo Stage 3](m1-stage3-report.md) · [Dữ liệu M1 v1](../stage-3/output/m1-v1/)

## Phân bố bộ dữ liệu cuối cùng

| Chiều phân bố | Kết quả |
| --- | --- |
| Khách hàng theo vùng | 18 khách miền Trung với 78 hội thoại và 17 khách miền Nam với 79 hội thoại |
| Số phiên mỗi hội thoại | 133 hội thoại có 2 phiên và 24 hội thoại có 3 phiên, tổng cộng 338 phiên |
| Kênh tương tác | 293 phiên hotline, 28 phiên Zalo, 17 phiên Fanpage |
| Kiểu khách hàng | 12 kiểu. Ba nhóm phổ biến nhất là quay lại đổi hàng hoặc khiếu nại (38), hỏi ý kiến gia đình (26) và so sánh giá (21) |
| Kiểu hội thoại | Tiếp tục qua kênh khác (39), hỗ trợ sau mua (33), giá hoặc tồn kho thay đổi (29), cân nhắc rồi quyết định (28), xác minh danh tính hoặc lịch sử giao dịch (17), chuyển tiếp kèm ngữ cảnh (11) |

Phân bố theo vùng và kiểu hội thoại được đối chiếu giữa các tệp xuất Stage 3 và dữ liệu Stage 1. [Thống kê Stage 3](../stage-3/output/m1-v1/audit/dataset_stats.json) · [Kịch bản Stage 1](../stage-1/output/m1/blueprints.jsonl)

## Đối chiếu yêu cầu M1

| Hạng mục dataset | M1 | Bộ dữ liệu đã sinh |
| --- | --- | --- |
| Số cuộc hội thoại (dạng transcript) | ≥ 120 | 157 |
| Trong đó có audio (thu thật hoặc sinh bằng TTS) | ≥ 40 cuộc / ≥ 1 giờ | 0 cuộc / 0 giờ trong bản xuất văn bản |
| Khách hàng đa phiên (≥ 2 cuộc gọi cùng 1 khách) | ≥ 30 khách | 35 khách có ít nhất 2 cuộc gọi hotline trong cùng một hội thoại |
| Khách có cả cuộc gọi + chat (đa kênh) | ≥ 10 khách | 21 khách có hotline và chat trong cùng một hội thoại |
| Ngành hàng · giọng vùng miền | 1 ngành · 2 miền | 1 ngành thời trang · 2 nhãn vùng miền (Trung và Nam) |
| Audio có nhiễu (đường phố, sóng yếu) | — | Không áp dụng cho bản xuất văn bản |
| Catalog sản phẩm + chính sách (giá, KM, đổi trả, ship) | ≥ 30 SKU | 45 SKU biến thể thời trang từ 6 sản phẩm gốc, đối chiếu danh mục và quy tắc BTC |

Nhãn vùng miền lấy từ hồ sơ đầu vào. Yêu cầu về thời lượng và giọng vùng miền cần được kiểm tra trên audio. [Đề bài BTC, trang 3, mục C.1](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf#page=3>) · [Danh mục BTC](../stage-1/input/catalog/products.json)

## Hạn chế

- **Độ bao phủ.** Bộ dữ liệu xoay quanh 35 hồ sơ CRM thời trang, với 86,7% số phiên qua hotline. Kết quả phản ánh chủ yếu các tình huống thoại.
- **Phạm vi đánh giá.** Dữ liệu gồm các lượt lời khách ở dạng văn bản để phát lại. Đánh giá phản hồi thực tế của agent và chất lượng nhận dạng giọng nói cần lượt chạy và dữ liệu âm thanh riêng.
- **Kiểm định tự động.** Hai phản hồi của mô hình chấm có điểm ngoài thang 0–1 và được đánh dấu cần xem lại. TF-IDF đo độ giống nhau về từ vựng, nên có thể bỏ sót các hội thoại cùng nội dung được diễn đạt khác nhau. [Kết quả và phân loại lỗi Stage 2](m1-stage2-report.md#deepeval-validation) · [Điểm tương đồng Stage 3](m1-stage3-report.md#tf-idf-similarity)
