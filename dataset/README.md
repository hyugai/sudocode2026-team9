# Tổng quan dataset và schema kịch bản Sudo Code 2026

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
