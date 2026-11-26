# Tóm tắt bộ dữ liệu M1

## Cách sinh dữ liệu

1. **Lập kịch bản.** Từ 50 hồ sơ CRM do ban tổ chức (BTC) cung cấp, Stage 1 tạo 140 kịch bản hành trình với 300 phiên dự kiến. Mỗi kịch bản xác định mục tiêu từng phiên, dữ kiện cần ghi nhớ và hành động kỳ vọng dựa trên danh mục, tồn kho và khuyến mãi của BTC. [Báo cáo Stage 1](m1-stage1-report.md)
2. **Sinh và kiểm tra lời thoại.** Qwen sinh từ 2 đến 5 lượt lời tiếng Việt của khách trong mỗi phiên. Cả 140 hành trình qua kiểm tra định dạng bằng Python. DeepEval dùng Gemma để kiểm tra mục tiêu, dữ kiện và tính liên tục giữa các phiên, chấp nhận 124 hành trình (88,6%). [Báo cáo Stage 2](m1-stage2-report.md)
3. **Hoàn thiện bộ dữ liệu.** Stage 3 ghép lời thoại đã duyệt với kịch bản và hồ sơ khách hàng. Bước này rà soát thông tin cá nhân và dùng TF-IDF để phát hiện các cặp hành trình có độ tương đồng trên 0,90. Kết quả ghi nhận 0 hành trình bị loại. Cả 124 hành trình được xuất chung vào một thư mục, mỗi hành trình là một tệp `SC-XXX.json` theo định dạng BTC. [Báo cáo Stage 3](m1-stage3-report.md) · [Dữ liệu M1 đã xuất](../stage-3/output/)

## Phân bố bộ dữ liệu cuối cùng

| Chiều phân bố | Kết quả |
| --- | --- |
| Khách hàng theo vùng | 50 khách, gồm 15 miền Bắc, 18 miền Trung và 17 miền Nam |
| Số phiên mỗi hành trình | 106 hành trình có 2 phiên và 18 hành trình có 3 phiên, tổng cộng 266 phiên |
| Kênh tương tác | 233 phiên hotline, 19 phiên Zalo, 14 phiên Fanpage |
| Kiểu khách hàng | 12 kiểu. Ba nhóm phổ biến nhất là quay lại đổi hàng hoặc khiếu nại (29), so sánh giá (23) và hỏi ý kiến gia đình (21) |
| Kiểu hành trình | Hỗ trợ sau mua (28), cân nhắc rồi quyết định (27), tiếp tục qua kênh khác (24), giá hoặc tồn kho thay đổi (24), chuyển tiếp kèm ngữ cảnh (11), xác minh danh tính hoặc lịch sử giao dịch (10) |

Phân bố theo vùng và kiểu hành trình được đối chiếu giữa các tệp xuất Stage 3 và dữ liệu Stage 1. [Thống kê Stage 3](../stage-3/output/audit/dataset_stats.json) · [Kịch bản Stage 1](../stage-1/output/blueprints.jsonl)

## Hạn chế

- **Độ bao phủ.** Bộ dữ liệu xoay quanh 50 hồ sơ CRM, với 87,6% số phiên qua hotline. Kết quả phản ánh chủ yếu các tình huống thoại.
- **Phạm vi đánh giá.** Dữ liệu gồm các lượt lời khách ở dạng văn bản để phát lại. Đánh giá phản hồi thực tế của agent và chất lượng nhận dạng giọng nói cần lượt chạy và dữ liệu âm thanh riêng.
- **Kiểm định tự động.** Ba trong số 16 phán quyết loại của DeepEval viện dẫn `must_not_ask` cho lời khách. BTC dùng quy tắc này để chấm câu hỏi của agent, nên ba trường hợp đó cần xem lại. TF-IDF đo độ giống nhau về từ vựng, nên có thể bỏ sót các hành trình cùng nội dung được diễn đạt khác nhau. [Phân loại lỗi Stage 2](m1-stage2-report.md#failure-categories) · [Điểm tương đồng Stage 3](m1-stage3-report.md#tf-idf-similarity)
