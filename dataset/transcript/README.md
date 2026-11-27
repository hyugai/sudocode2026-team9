# Bộ dữ liệu hội thoại bán hàng M1 và M2

Bộ dữ liệu đánh giá khả năng ghi nhớ và tiếp nối ngữ cảnh của trợ lý bán hàng qua nhiều phiên. M1 có **157 hội thoại và 338 phiên**. Đợt M2 bổ sung **158 hội thoại và 344 phiên**. Mỗi tệp xuất chứa lời thoại tiếng Việt của khách và điều kiện đánh giá theo định dạng BTC. [Báo cáo M1](M1/README.md) · [Báo cáo M2](M2/README.md)

## Phương pháp

### Stage 1 · Lập kịch bản

Mỗi tier có 180 kịch bản, kết hợp 12 kiểu khách với 6 kiểu hội thoại. Kiểu khách mô tả hành vi và cách nói. Kiểu hội thoại mô tả tình huống qua nhiều phiên, như chuyển kênh, thay đổi giá hoặc tồn kho và hỗ trợ sau mua. M1 có 35/72 tổ hợp quan sát được và M2 có 19/72. Các bảng có đủ 72 ô, bao gồm các tổ hợp có số lượng 0. [Bảng M1](M1/README.md#stage-1--lập-kịch-bản) · [Bảng M2](M2/README.md#stage-1--lập-kịch-bản)

### Stage 2 · Sinh và kiểm định lời thoại

#### Sinh lời thoại

`Qwen3-30B-A3B Q4_K_M` sinh lời khách cho từng hội thoại. Bộ kiểm tra Python đối chiếu khóa phiên với kịch bản, yêu cầu 2–5 lượt lời không rỗng trên một dòng cho mỗi phiên và loại nhãn người nói hoặc chỗ trống chưa điền.

#### Kiểm định lời thoại

DeepEval dùng `Gemma 4 12B IT QAT Q4_0` để kiểm tra mục tiêu và dữ kiện bắt buộc, tính liên tục giữa các phiên, vai khách hàng, độ phù hợp với kiểu khách và độ tự nhiên của tiếng Việt. Hội thoại được duyệt khi mô hình trả về `pass` và cả điểm phù hợp với kiểu khách lẫn độ tự nhiên đạt ít nhất 0,7. [Kết quả M1](M1/README.md#stage-2--sinh-và-kiểm-định-lời-thoại) · [Kết quả M2](M2/README.md#stage-2--sinh-và-kiểm-định-lời-thoại)

### Stage 3 · Hoàn thiện bộ dữ liệu

#### Lắp ghép và rà soát thông tin cá nhân

Ghép lời thoại đã duyệt với kịch bản theo `scenario_id` và gắn hồ sơ theo `customer_id`. Sau đó rà soát thông tin cá nhân trong từng hội thoại đã ghép.

#### Lọc trùng lặp bằng TF-IDF

TF-IDF dùng toàn bộ lời khách của mỗi hội thoại. Một hội thoại bị loại nếu độ tương đồng cosine với một hội thoại đã giữ lớn hơn 0,90. M1 và M2 đều giữ toàn bộ hội thoại đã duyệt. Các tệp được đánh số liên tiếp từ `SC-001.json` đến `SC-315.json` qua M1 rồi M2, giữ nguyên `scenario_id` trong JSON. [Tệp M1](M1/stage-3/output/) · [Tệp M2](M2/stage-3/output/)

## Phân bố M1

| Hạng mục dataset | M1 | Bộ dữ liệu đã sinh |
| --- | --- | --- |
| Số cuộc hội thoại (dạng transcript) | ≥ 120 | 157 |
| Trong đó có audio (thu thật hoặc sinh bằng TTS) | ≥ 40 cuộc / ≥ 1 giờ | 100 hội thoại / 1 giờ 10 phút 59 giây |
| Khách hàng đa phiên (≥ 2 cuộc gọi cùng 1 khách) | ≥ 30 khách | 35 khách có ít nhất 2 cuộc gọi hotline trong cùng một hội thoại |
| Khách có cả cuộc gọi + chat (đa kênh) | ≥ 10 khách | 21 khách có hotline và chat trong cùng một hội thoại |
| Ngành hàng · giọng vùng miền | 1 ngành · 2 miền | 1 ngành thời trang · 2 nhãn vùng miền (Trung và Nam) |
| Audio có nhiễu (đường phố, sóng yếu) | — | 30 hội thoại có nhiễu nền (62 phiên hotline) |
| Catalog sản phẩm + chính sách (giá, KM, đổi trả, ship) | ≥ 30 SKU | 45 SKU biến thể thời trang từ 6 sản phẩm gốc, đối chiếu danh mục và quy tắc BTC |

Hai cột đầu theo trang 3, mục C.1 của *SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì*. Nhãn vùng miền lấy từ hồ sơ CRM. [Phân bố và điểm kiểm định chi tiết](M1/README.md)

## Phân bố M2

Bảng M2 tính trên cả hai đợt, gồm 157 hội thoại M1 và 158 hội thoại bổ sung M2, với tổng cộng 682 phiên. Mỗi khách được tính một lần theo mã CRM.

| Hạng mục dataset | M2 | Bộ dữ liệu đã sinh |
| --- | --- | --- |
| Số cuộc hội thoại (dạng transcript) | ≥ 250 | 315 |
| Trong đó có audio (thu thật hoặc sinh bằng TTS) | ≥ 100 / ≥ 3 giờ | 100 hội thoại / 1 giờ 10 phút 59 giây. Còn thiếu 1 giờ 49 phút 1 giây. |
| Khách hàng đa phiên (≥ 2 cuộc gọi cùng 1 khách) | ≥ 60 (có khách ≥ 3 phiên) | 50 khách có ít nhất 2 cuộc gọi hotline trong cùng một hội thoại, trong đó 37 khách có hội thoại 3 phiên |
| Khách có cả cuộc gọi + chat (đa kênh) | ≥ 30 khách | 33 khách có hotline và chat trong cùng một hội thoại |
| Ngành hàng · giọng vùng miền | 3 ngành · 3 miền | 3 ngành (thời trang, gia dụng, mẹ và bé) · 3 nhãn vùng miền (Bắc, Trung, Nam) |
| Audio có nhiễu (đường phố, sóng yếu) | ≥ 20% | 30/100 hội thoại có audio được trộn nhiễu nền (30%), tương ứng 62/211 phiên (29,4%) |
| Catalog sản phẩm + chính sách (giá, KM, đổi trả, ship) | ≥ 100 SKU | 136 SKU trong danh mục BTC, trong đó 89 SKU xuất hiện trong các tệp đánh giá |

Hai cột đầu theo trang 3, mục C.1 của *SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì*. Nhãn vùng miền lấy từ hồ sơ CRM. [Phân bố và điểm kiểm định đợt M2](M2/README.md)

## Hạn chế

- Giọng vùng miền thực tế của tệp WAV cần được kiểm tra riêng.
- Tập M1 dùng 35 hồ sơ BTC, với 293/338 phiên hotline. Tập M2 dùng 50 hồ sơ BTC, với 304/344 phiên hotline. Nhật ký xuất M2 ghi rõ mức **50/60 khách đa phiên**.
- Mỗi tier có hai phản hồi chấm vượt thang điểm và cần xem lại. TF-IDF đo độ giống nhau về từ vựng và có thể bỏ sót các cách diễn đạt tương đương về nghĩa. [Báo cáo M1](M1/README.md) · [Báo cáo M2](M2/README.md)

## Cách xử lý thông tin cá nhân khi trợ lý trả lời

Trước khi gửi phản hồi, bộ lọc dò các mẫu số điện thoại, CCCD/CMND và số tài khoản ngân hàng rồi thay giá trị khớp bằng nhãn che tương ứng, chẳng hạn như `[SĐT ĐÃ ẨN]`. Khi lọc bản tóm tắt cuộc gọi, hệ thống giữ nguyên các trường giá và ngân sách đã chuẩn hóa để tránh che nhầm số tiền. Phản hồi chứa nội dung bị cấm được thay bằng lời từ chối.
