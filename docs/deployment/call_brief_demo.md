# Demo Call Brief tự cập nhật từ dữ liệu backend

## Hành vi hiện tại

- `POST /api/chat` và `POST /api/chat/audio` trả `call_brief` ở cấp cao nhất của JSON, không cần bật debug.
- Call Brief lấy từ pipeline thật. Cuối lượt, hệ thống dựng lại bản tóm tắt cục bộ từ facts hiện tại sau bước lưu memory; không gọi thêm LLM/ASR hoặc chạy lại truy vấn tồn kho chỉ để cập nhật sidebar.
- Sidebar nhận brief cùng phản hồi của Synee và cập nhật ngay khi lượt thành công, không cần refresh hay nút cập nhật riêng.
- Bản tóm tắt ưu tiên facts đang được khách nói đến. Các mục nhu cầu, băn khoăn và vấn đề chưa giải quyết phản ánh dữ liệu đã được pipeline nhận dạng/lưu, không phải các câu mẫu cố định trên frontend.
- Với khách chưa nhập số điện thoại, facts được giữ trong brief của đúng phiên backend để cập nhật qua nhiều lượt text/audio. Không cần tạo hồ sơ khách hoặc ghi memory lâu dài cho phiên ẩn danh; phiên mới không kế thừa brief của khách trước.
- `call_brief` chỉ gồm `summary`, `needs`, `objections`, `unresolved_issues`. Các mẫu số điện thoại/CCCD/STK được xử lý qua bộ che PII hiện có; không đưa `customer_id`, tên khách hoặc toàn bộ CRM/memory object vào trường này. Dữ liệu debug vẫn theo cấu hình riêng.

Tên khóa fact như `budget_vnd`, `room_area_m2`, `has_children` có thể xuất hiện trong nhu cầu/tóm tắt vì đây là phép chiếu xác định từ dữ liệu pipeline, không phải một bản diễn giải mới bằng LLM. Mục Băn khoăn lấy từ `blocker`; mục Cần xử lý tiếp lấy từ `unresolved_question` khi có.

## 1. Chuẩn bị

Cần backend hoạt động với cấu hình model, MCP/database và memory hiện có. Riêng gửi file audio cần Zipformer ASR đã cài dependencies và tải trọng số. Xem [PostgreSQL](postgresql_self_hosting.md) và [voice input local](local_voice_input.md) nếu các phần này chưa sẵn sàng.

Nếu ứng dụng đã chạy từ trước khi cập nhật code, khởi động lại backend để nhận contract mới. Không chỉ tải lại trang web với một backend cũ.

### Terminal 1 — backend

Chạy từ thư mục gốc repository bằng PowerShell:

```powershell
$env:PYTHONUTF8 = "1"
$env:ENABLE_DEBUG_RESPONSE = "false"
.\.venv\Scripts\python.exe -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

Giữ cấu hình kết nối và model trong `.env` theo cách khởi chạy hiện tại của dự án. Việc tắt debug không tắt Call Brief.

### Terminal 2 — frontend

```powershell
cd src/web
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

Mở `http://localhost:3000/ai-chat?mode=text`. Nếu Next.js chọn cổng khác, dùng cổng được in trên terminal. Kiểm tra backend đã sẵn sàng trước khi gửi; lỗi 401/403 cần xử lý quyền truy cập API theo cấu hình triển khai hiện có, không đưa service key vào biến `NEXT_PUBLIC_*`.

## 2. Kịch bản demo bằng text

Để dễ quan sát dữ liệu của phiên mới, để trống số điện thoại tư vấn và chọn **Cuộc trò chuyện mới → Bắt đầu mới**. Nếu sử dụng cùng số điện thoại đã có memory, brief có thể chứa các nhu cầu đã ghi nhận từ các cuộc tư vấn trước.

### Lượt 1 — ghi nhận nhu cầu

Gửi:

> Mình cần máy lọc không khí cho phòng ngủ 25 m2, ngân sách tối đa 3 triệu, nhà có trẻ nhỏ.

Chờ Synee trả lời xong. Quan sát sidebar:

- Đang gửi: hiển thị **Đang cập nhật call brief…**.
- Sau phản hồi: hiển thị brief từ dịch vụ; kiểm tra nhu cầu về ngân sách, diện tích phòng và trẻ nhỏ nếu NLU đã nhận dạng được các facts này.
- Giá trị ngân sách tương ứng `budget_vnd: 3000000`; diện tích tương ứng `room_area_m2: 25`.

### Lượt 2 — sửa thông tin ngay trong hội thoại

Gửi tiếp:

> Mình đổi ngân sách tối đa lên 4 triệu. Diện tích phòng vẫn là 25 m2.

Sau phản hồi, kiểm tra mục nhu cầu/tóm tắt đã phản ánh ngân sách **4 triệu**, không phải chờ thêm một lượt chat nữa. Việc sửa ngân sách không cần tải lại web hoặc mở lại sidebar.

### Lượt 3 — thêm băn khoăn

Gửi:

> Mình đang lo chi phí thay màng lọc và tiếng ồn khi ngủ, chưa quyết định mua.

Nếu pipeline ghi nhận fact `blocker`, nội dung sẽ hiện trong **Băn khoăn**. **Cần xử lý tiếp** chỉ có nội dung khi pipeline ghi nhận câu hỏi chưa giải quyết (`unresolved_question`); mục này có thể trống và UI sẽ nói rõ, không tự tạo dữ liệu để lấp chỗ trống.

## 3. Kịch bản demo bằng file audio

1. Trong cùng hội thoại, bấm icon micro của ô nhập Chat để **chọn file ghi âm**, không chọn chế độ Voice.
2. Dùng WAV/MP3/M4A/FLAC/OGG/WebM, tối đa 25 MB và 120 giây. Có thể tự ghi câu:

   > Mình đổi ngân sách tối đa thành 5 triệu, phòng khoảng 30 mét vuông. Mình quan tâm chi phí thay màng lọc.

3. Nghe lại file trong phần preview rồi bấm **Gửi ghi âm**.
4. Sau khi ASR và lượt tư vấn thành công, kiểm tra bản chép lời trong hội thoại và Call Brief mới. Các facts được nhận dạng phải phản ánh **5 triệu / 30 m²** thay vì giá trị cũ.

Đây là luồng audio offline → ASR → pipeline chat. Chế độ realtime Voice giữ giao diện LiveKit toàn màn hình theo thiết kế hiện tại; hướng dẫn này không thêm sidebar Call Brief vào Voice.

## 4. Kiểm chứng dữ liệu thật, không bật debug

Mở DevTools → Network, gửi một câu text rồi chọn request `/api/chat`. Trong tab Response cần có cấu trúc:

```json
{
  "response": "... phản hồi của Synee ...",
  "call_brief": {
    "summary": "... dữ liệu do pipeline dựng ...",
    "needs": ["budget_vnd: 4000000", "room_area_m2: 25"],
    "objections": [],
    "unresolved_issues": []
  }
}
```

Nội dung ví dụ chỉ minh họa contract; dữ liệu thực tế phụ thuộc vào câu hỏi và facts mà pipeline nhận dạng. Với `ENABLE_DEBUG_RESPONSE=false`, không cần có trường `debug`. Với `/api/chat/audio`, JSON có thêm `transcript` và vẫn có `call_brief` cùng cấp với `response`.

Nếu pipeline không tạo được brief, trường `call_brief` là `null` và UI hiển thị trạng thái chưa có dữ liệu. Frontend không tự dựng brief từ các câu demo.

### Kiểm tra nhanh bằng PowerShell, không qua UI

Chỉ cần chạy khi muốn xem trực tiếp phản hồi API. Hai lệnh gửi dưới đây là hai lượt tư vấn thật của backend đang chạy, dùng cùng một ID hội thoại mới:

```powershell
$briefDemoConversation = [guid]::NewGuid().ToString()
$briefDemoMessages = @(
  "Mình cần máy lọc không khí cho phòng 25 m2, ngân sách 3 triệu.",
  "Mình đổi ngân sách tối đa lên 4 triệu."
)
foreach ($briefDemoMessage in $briefDemoMessages) {
  $briefDemoBody = @{
    conversation_id = $briefDemoConversation
    message = $briefDemoMessage
  } | ConvertTo-Json -Compress
  $briefDemoReply = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/chat" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($briefDemoBody))
  $briefDemoReply.call_brief | ConvertTo-Json -Depth 5
}
```

## 5. Những trạng thái cần thử

| Tình huống | Kết quả mong đợi |
| --- | --- |
| Gửi thành công | Brief được cập nhật cùng phản hồi, không cần thêm request hoặc refresh |
| Gửi lỗi/giới hạn tốc độ | Giữ brief từ lượt thành công trước; báo rõ chưa cập nhật được; nội dung nhập/audio vẫn cho thử lại thủ công |
| Backend cũ thiếu `call_brief` | Trạng thái chưa có dữ liệu; cần cập nhật/khởi động lại backend, không bật debug để chữa contract cũ |
| Chuyển Chat → Voice → Chat | Brief trong bộ nhớ của phiên web vẫn được giữ, không tự gửi lại tin nhắn |
| Bắt đầu hội thoại mới hoặc đổi số tư vấn | Xóa brief của phiên trước, tránh trộn dữ liệu |
| Tải lại toàn bộ trang | Hội thoại có thể được khôi phục nhưng brief chưa lưu ở trình duyệt; gửi lượt tiếp theo để nhận brief mới, không tự replay request |
| ASR chưa nhận đúng câu nói | Kiểm tra `transcript`, ghi lại rõ hơn hoặc nhập lại bằng text; không coi brief sai từ transcript sai là dữ liệu đúng |

## 6. Các kiểm tra kỹ thuật liên quan

- `tests/test_call_brief_preview.py`: brief có trong phản hồi text/audio khi debug tắt, chỉ có bốn trường gọn, che các mẫu PII và ưu tiên facts hiện tại.
- `tests/test_chat_latency.py`: brief được làm mới sau commit của lượt hiện tại; không đổi ranh giới đo thời gian trả lời đã có.
- `src/web/tests/call-brief.test.mjs`: client đọc brief cấp cao nhất mà không cần debug, xử lý dữ liệu thiếu/sai định dạng.
- Kiểm tra trình duyệt cần phân biệt mock/fixture dùng trong regression với demo thực tế qua backend/model/ASR đang hoạt động.

## 7. Kết quả chạy demo thực tế ngày 06/11/2026

Đã chạy production API với Gemini và các công cụ MCP/catalog đang cấu hình, ASR Zipformer local có trọng số thật, `ENABLE_DEBUG_RESPONSE=false`. Dùng câu hỏi mẫu và phiên không có số điện thoại, tách thư mục memory demo khỏi dữ liệu khách. Không dùng mock cho các lượt dưới đây. Thời gian là quan sát trên máy demo, có thể thay đổi theo model, mạng và độ dài audio.

| Lượt kiểm tra | Kết quả Call Brief | Thời gian toàn request quan sát |
| --- | --- | --- |
| Text: phòng 25 m², ngân sách 3 triệu, nhà có trẻ nhỏ | `room_area_m2: 25`, `budget_vnd: 3000000`, `has_children: True` | 10,51 giây |
| Text: đổi ngân sách lên 4 triệu | Ngân sách thành `4000000`, giữ diện tích và trẻ nhỏ | 3,91 giây |
| Audio có sẵn trong dataset: hỏi giá/tồn kho và ngân sách 5.190.000đ | ASR nhận đúng ngân sách; brief thành `5190000`, giữ các facts trước | 9,72 giây; riêng ASR 2,63 giây ở lần đầu |
| Audio: trích câu ngân sách từ cùng file | Phản hồi tư vấn bình thường, brief vẫn đúng `5190000 / 25 m² / có trẻ nhỏ` | 8,16 giây; riêng ASR 0,17 giây khi model ASR đã được nạp |

Đã kiểm tra upload audio bằng giao diện thật, sidebar desktop và drawer ở chiều rộng 320px: dữ liệu tự cập nhật, không có lỗi JavaScript hoặc tràn ngang. Không cần bật debug.

**Vấn đề phát hiện và đã sửa:** brief của khách ẩn danh bị mất facts sau bước persist do chưa có `customer_id`. Hiện facts được giữ trong brief của đúng phiên backend; đã có regression qua text → sửa ngân sách → audio và kiểm tra phiên mới không kế thừa dữ liệu cũ.

**Giới hạn còn lại:** ở lượt audio hỏi cả giá/tồn kho, agent trả `Model call limits exceeded: run limit (3/3)` trong trường `response`, dù API vẫn HTTP 200 và brief đã cập nhật đúng. Đây là giới hạn của chuỗi gọi model/tool (`DEEPAGENT_MAX_MODEL_CALLS` mặc định 3), không phải ASR hay sidebar. Vì vậy HTTP 200 không đủ để kết luận phần tư vấn đã thành công; cần đọc cả `response`. Lượt audio chỉ cập nhật nhu cầu sau đó trả lời bình thường. Lần kiểm tra này giữ nguyên giới hạn model hiện có.

Regression sau bản sửa: 19 bài backend về Call Brief/API/latency và 52 bài frontend đều qua. Các bài regression dùng mock để cô lập dịch vụ; chúng tách biệt với các lượt demo thật nêu trên.
