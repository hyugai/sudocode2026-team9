# Bộ dữ liệu hội thoại bán hàng M1

Bộ dữ liệu dùng để đánh giá khả năng ghi nhớ và tiếp nối ngữ cảnh của trợ lý bán hàng qua nhiều phiên. Mỗi hội thoại gồm lời thoại tiếng Việt của khách hàng để phát lại và các điều kiện cần kiểm tra khi chạy trợ lý. [Dữ liệu M1](M1/stage-3/output/) · [Báo cáo chi tiết](M1/README.md)

## Phương pháp

### Stage 1 · Lập kịch bản

Từ 50 hồ sơ CRM của ban tổ chức (BTC), Stage 1 tạo 140 kịch bản. Mỗi kịch bản kết hợp một kiểu khách hàng với một kiểu hội thoại chính.

- **Kiểu khách hàng (persona)** mô tả hành vi và cách nói của khách, chẳng hạn như so sánh giá hoặc hỏi ý kiến gia đình. M1 dùng 12 kiểu khách hàng.
- **Kiểu hội thoại (journey pattern)** mô tả tình huống cần xử lý qua nhiều phiên, chẳng hạn như chuyển kênh, thay đổi giá hoặc tồn kho và hỗ trợ sau mua. M1 dùng 6 kiểu hội thoại.

140 kịch bản bao phủ **19 trong 72 tổ hợp**. Từng kịch bản xác định mục tiêu, dữ kiện và hành động kỳ vọng cho mỗi phiên dựa trên danh mục, tồn kho và khuyến mãi của BTC. [Bảng phân bố M1](M1/README.md#stage-1--lập-kịch-bản)

### Stage 2 · Sinh và kiểm định lời thoại

#### Sinh lời thoại

`Qwen3-30B-A3B Q4_K_M` sinh lời khách cho từng hội thoại. Bộ kiểm tra Python áp dụng ba điều kiện cho bản nháp.

- Các khóa phiên khớp chính xác với kịch bản.
- Mỗi phiên có 2–5 lượt lời. Mỗi lượt là một chuỗi không rỗng trên một dòng.
- Lượt lời không mở đầu bằng nhãn người nói và không chứa chỗ trống chưa điền.

#### Kiểm định lời thoại

DeepEval dùng `Gemma 4 12B IT QAT Q4_0` làm mô hình chấm. Mô hình đối chiếu lời khách với kịch bản theo các tiêu chí sau.

- Mục tiêu và dữ kiện bắt buộc của từng phiên.
- Tính liên tục và trình tự đưa dữ kiện qua các phiên.
- Tất cả các lượt lời đều thuộc về khách hàng.
- Độ phù hợp với kiểu khách hàng và độ tự nhiên của tiếng Việt.

Hội thoại được duyệt khi Gemma trả về `pass` và cả điểm phù hợp với kiểu khách lẫn điểm tự nhiên tiếng Việt đạt ít nhất 0,7. [Kết quả kiểm định M1](M1/README.md#stage-2--sinh-và-kiểm-định-lời-thoại)

### Stage 3 · Hoàn thiện bộ dữ liệu

#### Lắp ghép và rà soát thông tin cá nhân

Ghép lời thoại đã duyệt với kịch bản theo `scenario_id` và gắn hồ sơ theo `customer_id`. Sau đó rà soát thông tin cá nhân trong từng hội thoại đã ghép.

#### Lọc trùng lặp bằng TF-IDF

Tạo một vectơ TF-IDF từ toàn bộ lời khách của mỗi hội thoại. Loại một hội thoại nếu độ tương đồng cosine với một hội thoại đã giữ lớn hơn 0,90. M1 giữ cả 124 hội thoại đã duyệt và xuất mỗi hội thoại thành một tệp `SC-XXX.json` theo định dạng BTC. [Số liệu lắp ghép và lọc](M1/README.md#stage-3--lắp-ghép-và-xuất-dữ-liệu)

## Phân bố M1

| Đơn vị | Phân bố |
| --- | --- |
| Hội thoại | 124, gồm 106 hội thoại có 2 phiên và 18 hội thoại có 3 phiên |
| Phiên | 266, gồm 233 hotline, 19 Zalo và 14 Fanpage |
| Khách hàng | 50, gồm 15 miền Bắc, 18 miền Trung và 17 miền Nam |
| Bao phủ | 12 kiểu khách hàng, 6 kiểu hội thoại, 26 khách đa kênh và 52 tình huống khó |

Xem bảng phân bố kiểu khách × kiểu hội thoại, số lượt qua từng vòng và thống kê điểm theo nhóm trong báo cáo M1. [Báo cáo M1](M1/README.md)

## Hạn chế

- Hotline chiếm 87,6% số phiên. Bộ dữ liệu dùng 50 hồ sơ CRM của BTC và tập trung vào các tình huống thoại.
- Các lượt lời khách ở dạng văn bản phục vụ phát lại tĩnh. Chất lượng nhận dạng giọng nói và phản hồi của trợ lý cần được đo qua các lượt chạy riêng.
- Ba phán quyết loại viện dẫn quy tắc `must_not_ask` cho lời khách. BTC áp dụng quy tắc này cho câu hỏi của trợ lý. TF-IDF đo độ trùng từ vựng nên có thể bỏ sót các hội thoại tương đương về nghĩa. [Kết quả kiểm định M1](M1/README.md#stage-2--sinh-và-kiểm-định-lời-thoại)
