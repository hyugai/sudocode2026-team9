# Chuẩn hóa tin nhắn gõ tay trước LLM

Tin nhắn có `channel=chat` được chuẩn hóa bằng `normalize_chat_text()` trong `application/chat_normalization.py`, trước các bước identity, che PII, perception và main agent. Quy tắc và từ điển chạy hoàn toàn local, không tải thêm model và không phát sinh lượt gọi LLM. API text, giao diện web và Gradio dùng chung pipeline này.

## Các nhóm xử lý

| Nội dung người dùng nhập | Text sau chuẩn hóa |
| --- | --- |
| `sp nay co ship cod k a` | `Sản phẩm này có ship cod không anh` |
| `mik muon mua ao, shop co hang ko?` | `Mình muốn mua áo, shop có hàng không?` |
| `cho minh xem sp nay vs` | `Cho mình xem sản phẩm này với` |
| `minh muon order ao size xl, shop co freeship k?` | `Mình muốn order áo size XL, shop có miễn phí ship không?` |
| `sale nay con sz m k` | `Sale này còn size M không` |
| `ib minh gia sp nay` | `Inbox mình giá sản phẩm này` |
| `shop co chinh sach doi tra k` | `Shop có chính sách đổi trả không` |

- Mở rộng các viết tắt phổ biến như `sp`, `ko`, `k`, `đc`, `mik`, `sdt`, `ck`.
- Khôi phục dấu cho từ và cụm từ mua hàng đã có trong từ điển; một số từ đa nghĩa như `co`, `ban`, `con`, `a`, `vs` dùng ngữ cảnh lân cận.
- Chuẩn hóa từ Việt–Anh về các từ khóa quen thuộc `size`, `ship`, `sale`, `order`, `inbox`, `cod`; không dịch toàn bộ câu tiếng Anh. Ví dụ `sz` → `size`, `in box` → `inbox`, `freeship` → `miễn phí ship`. Các size chữ thông dụng được viết hoa.
- Chuẩn Unicode NFC và khoảng trắng, viết hoa đầu câu khi nhận diện được từ mở đầu.

## Dữ liệu cần giữ chính xác

Số điện thoại, ngày, tiền đã viết bằng chữ số, URL, email, mã có chữ số hoặc dấu phân cách được bảo vệ trước khi thay từ. Mã đứng sau `mã`/`sku`/`model`, tên sau các cụm giới thiệu tên và nội dung trong dấu nháy kép/backtick cũng được giữ nguyên. Ví dụ `249k`, `0984726714`, `17/10/2026`, `SP-249K`, `iPhone 16 Pro vs Galaxy S25` giữ nguyên nội dung. Không tự đoán lại giá, tên sản phẩm hoặc dấu của tên người.

Đây là bộ quy tắc cho hội thoại bán hàng, không phải model phục hồi dấu tổng quát. Từ lạ hoặc cụm thiếu ngữ cảnh có thể giữ nguyên; viết tắt đa nghĩa chỉ hỗ trợ các quy ước đã định nghĩa. Bổ sung dữ liệu thực tế vào `_ALIASES`, `_PHRASES` và các quy tắc ngữ cảnh kèm test để mở rộng độ phủ. Text từ ASR tiếp tục dùng bộ chuẩn hóa riêng cho chữ thường, tiền, ngày và số điện thoại; không áp các viết tắt gõ tay lên transcript voice.

## API và đối chiếu

`POST /api/chat` vẫn nhận `message` như trước, trả thêm `normalized_message` chứa câu đã chuẩn hóa. Web hiển thị câu này trong bong bóng khách hàng và log; lịch sử đưa vào LLM dùng câu đã chuẩn hóa. Frontend vẫn hỗ trợ backend cũ khi chưa có trường mới.

Text gốc được giữ trong `TurnInput.metadata.raw_user_text`. Khi `ENABLE_DEBUG_RESPONSE=true`, API trả `debug.raw_user_text` và `debug.normalized_input` để đối chiếu. Các trường gốc này chỉ thuộc metadata của lượt, không được tự ghép vào prompt LLM. Quy trình che PII hiện có vẫn áp dụng ở các bước tiếp theo.

## Kiểm thử

Từ thư mục gốc:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

Các test kiểm tra ví dụ chuẩn hóa, tính ổn định khi gọi lại, dữ liệu được bảo vệ, thứ tự chuẩn hóa trước identity/perception/main agent và hợp đồng API với debug bật/tắt. Các kiểm thử pipeline dùng model giả, không gọi LLM hoặc ghi CRM/memory.
