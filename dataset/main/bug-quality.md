# Bug quality

## Trạng thái sau cải thiện

Đã sửa nội dung 80 scenario `SC-041`–`SC-120` và các bản prefilled tương ứng. Giữ nguyên cả complete/prefilled `SC-001`–`SC-040`, toàn bộ 250 file audio và ba manifest theo yêu cầu. Tổng vẫn là 120 scenario, 250 phiên; chưa chạy pilot bằng agent thực tế.

| Hạng mục | Trước | Sau | Trạng thái |
|---|---|---|---|
| Hotline | 230 phiên (92%) | 150 phiên (60%) | Đã cải thiện. |
| Fanpage | 20 phiên (8%) | 50 phiên (20%) | Đã cải thiện. |
| Zalo OA | 0 phiên | 50 phiên (20%) | Đã bổ sung. |
| Scenario đa kênh | 20/120 | 70/120 | Đã cải thiện. |
| Biến thể hard case | 11/12 persona có một nhãn cố định | 8 persona không có audio được thêm biến thể; 4 persona có audio được giữ nguyên | Cải thiện có giới hạn theo phạm vi bảo vệ audio. |
| Hash nguồn | Khác hash hiện hành ở ba file BTC | Đã ghi nhận hash cũ/mới trong `coverage.json`; chưa xác định được phiên bản nguồn cũ | Chưa giải quyết nguồn gốc. |

## Đa dạng kênh và danh tính

Đã thêm Fanpage → hotline, Zalo OA → hotline, hotline → Zalo OA và chuyển giữa hai kênh chat khi phù hợp. Các persona gọi lần ba và Fanpage → hotline giữ luồng kênh cốt lõi của mình. Chat dùng ID trong CRM nếu có; ID kênh còn thiếu được ghi rõ là dữ liệu tổng hợp, không tự thêm vào CRM. Lời khách cung cấp tên và số điện thoại để kiểm tra liên kết danh tính; các ca dùng chung số vẫn yêu cầu phân biệt đúng hồ sơ.

## Phân bổ hard case thực tế

`coverage.json` ghi riêng thử thách cốt lõi của persona, hard case bổ sung, kênh từng phiên và bằng chứng chấm. Trường BTC `hard_case` vẫn là chuỗi hoặc null; các biến thể chọn một hard case bổ sung làm nhãn chính.

| Nhóm | Trong 80 scenario được sửa | Toàn bộ 120 scenario |
|---|---:|---:|
| Không thêm hard case | 24 | 64 |
| Thêm một hard case | 42 | 42 |
| Thêm hai hard case tương thích | 14 | 14 |

Không thêm hard case không có nghĩa là scenario dễ: thử thách cốt lõi như dùng chung số, hỏi y tế hoặc gọi lần ba vẫn còn. Các ca có audio có thể đã chứa hard case từ trước.

### Danh sách 12 persona

1. Khách do dự, cần hỏi người nhà.
2. Khách so giá (`khach_so_gia`).
3. Khách đã mua, gọi đổi size.
4. Khách hỏi nhiều nhưng không mua.
5. Khách gọi lần ba, hết kiên nhẫn.
6. Khách chuyển từ Fanpage sang hotline.
7. Khách hỏi ngoài phạm vi và cần chuyển máy.
8. Khách hỏi thông tin không có trong tài liệu.
9. Khách nhận giá khác nhau giữa các kênh.
10. Hai người dùng chung số điện thoại.
11. Khách quay lại sau tám tháng.
12. Khách mua nhiều món và thay đổi giỏ hàng.

### Loại hard case và điều kiện áp dụng

- `het_hang_luc_tu_van_nhap_lai_truoc_khi_chot`: giữ các ca gốc có timeline phù hợp; không ép đổi SKU/ngày trong đợt này.
- `doi_khuyen_mai_het_han`: bổ sung yêu cầu áp mã thực sự đã hết hạn và phù hợp SKU; yêu cầu giải thích hết hạn, giữ giá hiện hành và cấm claim mã đang hiệu lực.
- `doi_size_sau_khi_nhan_hang`: giữ nhóm ca gốc có đơn đã nhận; không ghép vào sản phẩm không có size.
- `phien_ban_chinh_sach_cu`: hỏi bản tháng 6 ghi 14 ngày so với thời hạn thông thường 7 ngày của đơn mới từ tháng 10; có điều kiện chấm câu trả lời và cấm claim 14 ngày là thời hạn hiện hành.
- `asr_loi_va_teencode`: tạo đầu vào không dấu cho hotline, không dấu/teencode cho chat. Giữ nguyên chuỗi số và số lượt; các điều kiện giá, đơn và bộ nhớ áp dụng trên đầu vào lỗi. Đây là lỗi mô phỏng bằng văn bản, không phải audio mới hoặc đầu ra ASR đo thực tế.

Không ép tích Descartes `12 × 5`: đó là số tổ hợp, không phải số phiên. Nếu không có khuyến mãi hết hạn phù hợp giỏ hàng, dùng câu hỏi phiên bản chính sách; lý do được ghi trong coverage. Các câu hỏi bổ sung xuất hiện trước chỉ dẫn kết thúc/mua hàng, tránh thử thách mới sau khi khách đã yêu cầu hoàn tất.

## Kiểm chứng đã thực hiện

- 80 cặp seed/complete nhất quán sau khi bỏ đúng các trường cần sinh.
- 230 snapshot giá/tồn kho của các scenario được sửa khớp mock BTC hiện hành.
- 84 kiểm tra chấm dương/âm cho các yêu cầu chính sách và khuyến mãi qua evaluator BTC.
- 333 file được bảo vệ không đổi: 250 WAV, 80 JSON của 40 scenario có audio và 3 manifest.
- 250 WAV khớp transcript và checksum manifest; ID các cặp khớp.
- Có danh sách 12 pilot, mỗi persona một scenario, trong coverage. Đã kiểm tra cấu trúc/fixture; chưa chạy agent thực tế do môi trường thiếu dependency backend (`pytest`, `sqlalchemy`). Không coi kiểm tra offline là kết quả agent.

## Việc còn lại

- Chạy pilot 12 scenario qua agent, xem trace để kiểm tra liên kết danh tính, phục hồi đầu vào lỗi, bộ nhớ và điều kiện chấm; sửa lỗi phát hiện trước khi công bố benchmark.
- Rà soát ngữ nghĩa thủ công cho toàn bộ biến thể, nhất là ID chat tổng hợp và giới hạn của bộ chấm theo cụm từ/claim extractor.
- Xác minh bản nguồn đã dùng để sinh dataset: `schemas/tools.schema.json`, `eval/mock_tools.py`, `eval/reference_eval.py` có hash khác hiện hành; hash gốc được giữ nguyên, không thay bằng hash mới để che khác biệt. Không tìm thấy bản khớp hash trong Git history hiện có.
- Độ đa dạng của bốn persona đầu chưa thay đổi vì các scenario đó có audio cần giữ nguyên. Audio chỉ phủ 40/120 scenario; không mở rộng trong phạm vi này.
