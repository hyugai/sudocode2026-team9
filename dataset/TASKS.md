# Công việc chuẩn bị và mô tả dataset

## Yêu cầu bàn giao

> Dataset: Bộ dữ liệu kèm mô tả ngắn về cách sinh dữ liệu, phân bố, hạn chế và cách xử lý thông tin cá nhân.

Đầu ra gồm bộ transcript, bộ audio hiện có và tài liệu mô tả ngắn bằng tiếng Việt tại `dataset/DATASET_CARD.md` (khoảng 1–2 trang). Manifest cần chỉ rõ các bản ghi transcript và audio tương ứng; ghi nhận cả những bản ghi chưa có dữ liệu đối ứng.

## Trạng thái rà soát ngày 16/11/2026

Kết quả: [DATASET_CARD.md](DATASET_CARD.md), gồm bản mô tả ngắn và phụ lục bằng chứng. Dấu `[x]` bên dưới nghĩa là đã hoàn tất công việc kiểm kê/rà soát/mô tả bằng chứng local và ghi rõ phần chưa xác minh; không chứng nhận mọi điều kiện của bộ dữ liệu đã đạt.

Đã chạy validator M2 và 9 regression test; kiểm tra đường dẫn, checksum và header của 250 WAV. Các khoảng trống còn tồn tại: audio hai người nói M2, 40 tệp giọng tham chiếu không có local, ba hash nguồn chưa khớp, rà soát nghe/ngữ nghĩa, xác nhận quyền dùng giọng và bản xuất che thông tin toàn bộ. Chưa xác minh tính không trùng người thật của định danh được mô tả là tổng hợp.

## 1. Xác nhận bộ dữ liệu bàn giao

- [x] Xác định thư mục và manifest chính thức của transcript và audio; phân biệt dữ liệu BTC cung cấp với dữ liệu nhóm tạo.
- [x] Phân biệt kịch bản kiểm thử, hội thoại đầy đủ, phiên, lượt nói và clip audio khi thống kê.
- [x] Kiểm tra liên kết transcript–audio; chỉ rõ audio chứa lời khách, lời agent hay cả hai người nói.
- [x] Tránh đếm trùng dữ liệu được mở rộng từ cùng kịch bản nguồn; kiểm tra đường dẫn và khả năng truy cập các tệp bàn giao.

## 2. Mô tả cách sinh dữ liệu

- [x] Ghi nguồn dữ liệu và cách soạn hoặc sinh transcript; phân biệt lời agent mẫu với phản hồi của hệ thống khi chạy thực tế.
- [x] Ghi cách thu âm hoặc sinh audio bằng TTS, công cụ/model và cấu hình có bằng chứng trong repo.
- [x] Tóm tắt bước kiểm tra đã thực hiện: định dạng, dữ kiện nghiệp vụ và độ khớp transcript–audio; ghi rõ các bước chưa thực hiện.
- [x] Đánh dấu thông tin về nguồn hoặc quy trình chưa xác minh, không suy đoán để điền đủ tài liệu.

## 3. Thống kê phân bố

- [x] Đếm transcript theo số hội thoại, khách hàng, phiên, persona, kênh và ngành hàng; nêu cách đếm khách đa phiên/đa kênh.
- [x] Đếm audio theo số clip, số hội thoại được bao phủ và tổng thời lượng đo thực tế.
- [x] Thống kê vùng miền, người nói và audio nhiễu theo metadata có thể xác minh; ghi nhận trường hợp thiếu metadata.
- [x] Nêu tỷ lệ hoặc số lượng transcript có audio tương ứng. Tách số liệu hiện có khỏi kế hoạch tạo thêm dữ liệu.

## 4. Mô tả hạn chế

- [x] Nêu tính tổng hợp, mức lặp template và giới hạn đại diện cho hội thoại thực tế.
- [x] Nêu phần thiếu hoặc không khớp giữa transcript và audio; không quy đổi clip một lượt nói thành hội thoại đầy đủ.
- [x] Nêu giới hạn của lời agent mẫu và kiểm tra fixture; không trình bày chúng như kết quả đánh giá agent thực tế.
- [x] Ghi nhận vấn đề nguồn gốc chưa giải quyết và nguy cơ rò rỉ nếu chia các bản ghi cùng khách hoặc cùng kịch bản nguồn vào nhiều tập.

## 5. Mô tả xử lý thông tin cá nhân

- [x] Rà soát tên, số điện thoại, địa chỉ, metadata người nói và audio tham chiếu trong phạm vi bàn giao.
- [x] Xác minh bằng chứng về danh tính tổng hợp; không khẳng định dữ liệu đã ẩn danh chỉ vì dùng cho kiểm thử.
- [x] Mô tả biện pháp thay thế/che định danh đã áp dụng và cách giữ liên kết nhất quán giữa các phiên; tách rõ việc còn cần làm trước khi chia sẻ.
- [x] Ghi nguồn và bằng chứng về quyền sử dụng hoặc sự đồng ý đối với giọng thu/giọng tham chiếu; đánh dấu trường hợp chưa xác minh.
- [x] Kiểm tra phần mô tả bao phủ cả nội dung transcript, metadata và thông tin được đọc trong audio.

## 6. Hoàn thiện tài liệu ngắn

- [x] Viết `dataset/DATASET_CARD.md` với bốn mục chính: **Cách sinh dữ liệu**, **Phân bố dữ liệu**, **Hạn chế**, **Xử lý thông tin cá nhân**.
- [x] Thêm đường dẫn tới dữ liệu và manifest, định nghĩa đơn vị đếm, và nguồn đối chiếu cho số liệu quan trọng.
- [x] Kiểm tra số liệu, liên kết và tính nhất quán giữa tài liệu với các tệp thực tế.

## Tiêu chí hoàn thành

- [x] Có thể tìm và đọc bộ transcript, audio và manifest được bàn giao.
- [x] Bốn nội dung bắt buộc được mô tả ngắn gọn, có căn cứ và dùng số liệu thực tế.
- [x] Phần chưa có, chưa kiểm tra hoặc chưa xác minh được ghi rõ.

Sinh thêm audio, viết lại transcript hoặc thay đổi nội dung dataset là công việc riêng, chỉ thực hiện sau khi được phê duyệt. Nếu có yêu cầu số lượng/độ bao phủ tối thiểu ở tài liệu khác, cần đối chiếu riêng; việc hoàn thành mô tả không thay thế việc bổ sung dữ liệu còn thiếu.
