# Bug quality

## Độ đa dạng kênh còn thấp

- 92% cuộc gọi là hotline.
- 8% cuộc gọi đến từ Fanpage.
- Không có Zalo OA.
- Hiện chưa có scenario chat qua Zalo.

## Phân bổ hard case chưa đa dạng

Các kịch bản khó hiện không được phân bổ đều. Mỗi scenario đang có một hard case cố định, trong khi một scenario nên có nhiều hard case khác nhau.

Hướng đề xuất: trộn các `hard_case` vào các scenario với nhau.

### Danh sách các scenario

1. Khách do dự, cần hỏi người nhà.
2. Khách đã mua, gọi đổi size.
3. Khách hỏi nhiều nhưng không mua.
4. Khách gọi lần ba, hết kiên nhẫn.
5. Khách chuyển từ Fanpage sang hotline.
6. Khách hỏi ngoài phạm vi và cần chuyển máy.
7. Khách hỏi thông tin không có trong tài liệu.
8. Khách nhận giá khác nhau giữa các kênh.
9. Hai người dùng chung số điện thoại.
10. Khách quay lại sau tám tháng.
11. Khách mua nhiều món và thay đổi giỏ hàng.

### Danh sách các hard case đề xuất

1. `het_hang_luc_tu_van_nhap_lai_truoc_khi_chot`
2. `doi_khuyen_mai_het_han`
3. `doi_size_sau_khi_nhan_hang`
4. `phien_ban_chinh_sach_cu`
5. `asr_loi_va_teencode`

Nếu trộn scenario với hard case: `12 × 5 = 60` cuộc thoại.

Các scenario còn lại có thể không đến hard case.
