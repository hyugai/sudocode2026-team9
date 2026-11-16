# Tổng quan dataset và schema kịch bản Sudo Code 2026

## Nguồn dữ liệu và cấu trúc thư mục

| Đường dẫn | Nguồn | Nội dung và mục đích |
|---|---|---|
| `organizer/` | Ban Tổ chức (BTC) | Catalog, CRM seed, chính sách, schema, simulator, kịch bản mẫu, ASR ground truth, dữ liệu RAG và công cụ chấm tham chiếu. |
| `main/` | Nhóm phát triển | 120 kịch bản kiểm thử gồm 250 cuộc gọi, bản prefilled, bản hoàn chỉnh và audio. Các kịch bản sử dụng định dạng và dữ liệu tham chiếu của BTC. |
| `text-to-speech/` | Nhóm phát triển | Notebook khảo sát dữ liệu giọng nói và sinh audio. |

Gói BTC có tên thư mục gốc là `BTC-Data-Vong1-TEAMS`, được đổi tên thành `organizer/` để phân biệt nguồn dữ liệu. Giữ nguyên cấu trúc bên trong và nội dung các tệp do BTC cung cấp. Xem [README của BTC](organizer/README.md) và [README kịch bản của nhóm](main/README.md) để biết chi tiết.

Các script seed, ingest và đánh giá sử dụng đường dẫn `dataset/organizer/`. Nếu chuẩn bị dữ liệu thủ công, đặt gói BTC vào thư mục này.

Tài liệu này mô tả yêu cầu dataset của đề Sudo Code 2026, các nguồn dữ liệu đầu vào và định dạng file scenario dùng để chạy agent và đánh giá tự động. Bản Markdown đã bổ sung kiểu dữ liệu, mức bắt buộc, ràng buộc giữa các trường và một scenario JSON hoàn chỉnh.

## Truy cập dataset audio dành cho BTC

Dataset audio được lưu trên Google Drive để Ban Tổ chức (BTC) truy cập và phục vụ việc kiểm tra, đánh giá.

**[Mở thư mục dataset audio trên Google Drive](https://drive.google.com/drive/folders/1_k-TuLra1Lca7YTOzMqlH-xNT54Ftrlk?usp=sharing)**

Cách truy cập: mở liên kết trên, chọn tệp audio cần kiểm tra để nghe trực tiếp hoặc tải về từ Google Drive.

## 1. Yêu cầu dataset

| Hạng mục | M1 cơ bản | M2 nâng cao |
|---|---|---|
| Persona transcript | Khách do dự cần hỏi người nhà; khách so giá; khách đã mua gọi lại đổi size hoặc khiếu nại | Bao gồm toàn bộ persona M1, cộng thêm khách hỏi nhiều không mua và khách gọi lần 3 đã hết kiên nhẫn |
| Số transcript hội thoại | Tối thiểu 120 | Tối thiểu 250 |
| Transcript có audio | Tối thiểu 40 cuộc, tổng thời lượng trên 1 giờ | Tối thiểu 100 cuộc, tổng thời lượng trên 3 giờ |
| Khách hàng đa phiên | Tối thiểu 30 khách có ít nhất 2 phiên | Tối thiểu 60 khách; có khách từ 3 phiên trở lên |
| Khách đa kênh | Tối thiểu 10 khách có cả gọi và chat | Tối thiểu 30 khách có cả gọi và chat |
| Ngành hàng | 1 ngành | 3 ngành |
| Giọng vùng miền | Bắc và Nam | Bắc, Trung và Nam |
| Audio nhiễu | Không bắt buộc | Tối thiểu 20%, gồm tiếng gió, đường phố hoặc sóng yếu |
| Catalog và chính sách | Tối thiểu 30 sản phẩm, có giá, khuyến mãi, đổi trả và vận chuyển | Tối thiểu 100 sản phẩm, có giá, khuyến mãi, đổi trả và vận chuyển |
