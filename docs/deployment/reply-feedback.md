# Kết nối feedback câu trả lời với API và database

## 1. Phạm vi đã hoàn thành: UI demo

Feedback hiện xuất hiện dưới từng tin nhắn **Synee AI** trong trang `/ai-chat` ở chế độ Chat, cạnh nút sao chép. Tin nhắn người dùng không có nút đánh giá. Câu trả lời từ file audio cũng dùng chung giao diện này.

| Nút | Hành vi demo |
| --- | --- |
| Thumbs up | Chọn đánh giá tích cực, thay thế đánh giá tiêu cực nếu có; bấm lại để bỏ chọn |
| Thumbs down | Chọn đánh giá tiêu cực, thay thế đánh giá tích cực nếu có; bấm lại để bỏ chọn |
| Icon văn bản | Mở biểu mẫu góp ý cho đúng câu trả lời; nhập và bấm **Gửi góp ý** |

Đánh giá và góp ý văn bản độc lập: một câu trả lời có thể có cả rating và comment. Mỗi lần gửi comment hợp lệ sẽ thay thế comment demo trước đó của câu trả lời đó. Text được trim, tối đa 1.000 ký tự theo giới hạn textarea, không chấp nhận toàn khoảng trắng.

UI có trạng thái chọn `aria-pressed`, thông báo xác nhận ghi rõ **demo**, label riêng cho mỗi nút, lỗi nhập liệu và focus bàn phím. Hủy hoặc Escape đóng biểu mẫu và đưa focus về icon văn bản; bản nháp vẫn còn để mở lại khi vùng Chat này còn được mount.

### Dữ liệu hiện được giữ ở đâu?

- Chỉ trong state React của `ReplyFeedbackProvider`, dùng Map gắn với object tin nhắn gốc. Lọc/tìm kiếm không làm feedback chuyển sang câu trả lời khác; bỏ lọc sẽ hiện lại lựa chọn/bản nháp.
- Bắt đầu hội thoại mới thành công hoặc đổi số điện thoại tư vấn sẽ tạo vùng feedback demo mới.
- Chuyển sang Voice, rời trang hoặc tải lại trang sẽ bỏ feedback tạm. Không có khôi phục feedback từ phiên khách.
- Không có API feedback, không ghi database/localStorage/sessionStorage, không sửa transcript và không đưa feedback vào prompt của Synee. Health check/chat hiện có là các luồng riêng.
- Thông báo “Đã ghi nhận … (demo)” chỉ xác nhận state giao diện, không có nghĩa phản hồi đã đến đội vận hành hoặc được lưu lâu dài.

### Vị trí code

- `src/web/app/ai-chat/reply-feedback.tsx`: state demo, nút rating, biểu mẫu comment và thông báo.
- `src/web/app/ai-chat/ai-chat-experience.tsx`: gắn feedback vào tin nhắn assistant và reset khi bắt đầu hội thoại mới.
- `src/web/app/ai-chat/icons.tsx`: SVG thumbs up/down và icon văn bản theo hệ icon hiện có.
- `src/web/app/ai-chat/ai-chat.css`: kiểu dáng nút chọn, form và trạng thái, dùng token dashboard.

## 2. Điều kiện cần trước khi lưu thật

Hiện API chat trả nội dung phản hồi, chưa trả một `message_id` ổn định cho mỗi câu trả lời. UI đang sử dụng object tin nhắn và vị trí trong mảng; **không dùng các giá trị này làm khóa database**. Hai câu trả lời có thể cùng nội dung, hoặc vị trí thay đổi khi tải lịch sử/lọc kết quả.

Trước khi nối feedback:

1. Lưu hội thoại và từng message tại server, hoặc dùng kho message đã có với khóa bất biến tương đương. Backend cấp UUID cho message và trả `assistant_message_id` sau lượt Chat/audio thành công.
2. Trả ID khi tải lại lịch sử. Truyền ID xuyên suốt contract backend, client API, `Message`, cơ chế lưu/khôi phục phiên và UI. Xác định riêng cách xử lý lời chào cục bộ chưa có ID server: chưa cho gửi thật hoặc tạo message server tương ứng.
3. Xác định danh tính tác giả feedback từ phiên đã được server xác minh. Nếu vẫn cho khách đánh giá, cấp guest session ở server; không coi số điện thoại tư vấn, conversation ID hay cờ localStorage là bằng chứng sở hữu.
4. Kiểm tra quyền đối với hội thoại/message ở mọi request. Service key dùng chung của hệ thống không thay thế xác thực và kiểm tra quyền của người dùng.

Giao diện đăng nhập/đăng ký hiện cũng là demo; xem [lộ trình xác thực](../../doc/authentication-setup.md) trước khi coi một feedback là của tài khoản đã đăng nhập.

## 3. Chuẩn bị PostgreSQL và migration

Làm theo [hướng dẫn PostgreSQL hiện có](postgresql_self_hosting.md) để chuẩn bị database phát triển. Dùng migration có version để bổ sung bảng; không chạy lại script nạp catalog trên database đã có dữ liệu. Không có migration feedback nào được thực thi trong phần UI demo này.

Mô hình tối thiểu đề xuất:

| Bảng / trường | Mục đích |
| --- | --- |
| `conversation_messages.id` | Khóa message ổn định do server cấp; liên kết hội thoại và tác giả |
| `message_feedback.id` | UUID feedback do server sinh |
| `message_feedback.message_id` | FK tới câu trả lời assistant; server kiểm tra role và quyền truy cập |
| `message_feedback.actor_id` | FK tới danh tính tài khoản/guest đã được server xác minh |
| `message_feedback.rating` | `positive`, `negative` hoặc `NULL` |
| `message_feedback.comment` | Text tối đa 1.000 ký tự theo quy ước đếm thống nhất giữa UI và API |
| `message_feedback.version` | Phiên bản bản ghi để xử lý sửa đồng thời |
| `message_feedback.created_at`, `updated_at` | Timestamp UTC do server quản lý |

Thêm unique constraint `(message_id, actor_id)` để mỗi người có một đánh giá hiện tại cho một câu trả lời; cập nhật rating/comment thay vì tạo thêm dòng mỗi lần click. Thêm ràng buộc giá trị rating, giới hạn comment và index FK/`updated_at` theo nhu cầu báo cáo. Nếu cần lịch sử thay đổi, thêm bảng event riêng thay vì đếm mỗi lần bấm là một người đánh giá mới.

Các khóa FK, model actor và quy tắc xóa/ẩn feedback cần được chốt cùng thiết kế lưu hội thoại và xác thực. Tài liệu này mô tả schema đề xuất, không giả định những bảng này đã tồn tại trong catalog/CRM hiện tại.

## 4. Hợp đồng API đề xuất

Các endpoint dưới đây **chưa được triển khai**:

| Endpoint | Hành vi |
| --- | --- |
| `GET /api/conversations/{conversation_id}/messages/{message_id}/feedback` | Lấy feedback hiện tại của actor đã xác minh; trả trạng thái rỗng nếu chưa có |
| `PUT /api/conversations/{conversation_id}/messages/{message_id}/feedback` | Ghi trạng thái rating/comment hiện tại theo unique constraint; request lặp không tạo đánh giá trùng |

Ví dụ body cho một lần lưu đầy đủ:

```json
{
  "rating": "positive",
  "comment": "Câu trả lời rõ ràng; mình muốn có thêm so sánh mức tiêu thụ điện.",
  "expected_version": 0
}
```

`expected_version: 0` nghĩa chưa có feedback; sau lần lưu thành công, client dùng version mới server trả về. Dùng `rating: null` để bỏ đánh giá, `comment: ""` để bỏ comment; thống nhất việc giữ bản ghi rỗng hay xóa bản ghi tại server. Body không chứa `actor_id` do client tự khai báo.

Phản hồi chỉ cần ID feedback/message, rating, comment, version và timestamp công khai. Không cần gửi toàn bộ transcript, thông tin CRM hoặc ghi âm kèm mỗi lần đánh giá.

Quy ước lỗi nên có:

- `401`: phiên chưa xác thực/hết hạn; `403` hoặc `404` theo chính sách chống lộ tài nguyên: không có quyền với câu trả lời.
- `422`: rating/comment không hợp lệ; `409`: phiên bản đã thay đổi, yêu cầu tải lại feedback trước khi cập nhật.
- `429`: kèm `Retry-After`; `503`: dịch vụ chưa sẵn sàng. Không trả lỗi database hoặc dữ liệu người khác trong thông báo.

## 5. Nối vào kiến trúc ứng dụng

1. Định nghĩa contract feedback trong `src/telesale_agent/core/`, service kiểm tra quyền/ghi feedback trong `application/`, repository PostgreSQL trong `adapters/`, router trong `entrypoints/api/`.
2. Thêm migration trên database thử nghiệm, kiểm tra unique constraint và transaction khi hai request đồng thời cập nhật cùng message/actor.
3. Thêm client riêng như `src/web/utils/reply-feedback-api.ts`. Chuyển Map từ object demo sang `message_id` ổn định. Giữ UI feedback tách khỏi cơ chế gửi tin nhắn/ASR/Voice.
4. Thay thông báo demo bằng pending/success/error thật. Chỉ báo đã gửi sau server xác nhận; khóa hoặc tuần tự hóa request đang chạy cho cùng câu trả lời, giữ bản nháp khi lỗi, cho thử lại thủ công và không tự phát lại khi tải trang.
5. Quy định cách hủy/đổi lựa chọn trong lúc chờ và cách giải quyết version conflict; không để phản hồi cũ ghi đè một lựa chọn mới hơn.
6. Khôi phục feedback theo API lịch sử sau đăng nhập/tải lại. Làm rỗng state khi đăng xuất, đổi tài khoản hoặc hội thoại. Không tự chuyển feedback guest sang tài khoản nếu chưa có quy tắc và sự lựa chọn phù hợp.
7. Bật badge/trạng thái lưu thật khi API và phân quyền đã hoàn chỉnh; xác định riêng việc feedback xuất hiện trong realtime Voice nếu muốn hỗ trợ tính năng này sau.

## 6. Dữ liệu và vận hành

- Validate lại rating, comment, độ dài và quyền sở hữu tại server. Chống gửi lặp, áp dụng rate limit; với xác thực cookie, bảo vệ request thay đổi dữ liệu bằng cơ chế CSRF phù hợp.
- Xem comment là dữ liệu không tin cậy. Render như text được escape, không chèn HTML; không đưa góp ý trực tiếp thành system prompt hoặc tự động thay đổi kiến thức/model.
- Chỉ thu thập dữ liệu cần thiết. Giới hạn người đọc dashboard feedback; thiết lập thời hạn lưu giữ và cách xử lý khi xóa hội thoại/tài khoản. Không log comment hoặc thông tin cá nhân không cần thiết.
- Giữ database URL/service key ở server, không dùng biến `NEXT_PUBLIC_*` cho secret. Nếu có trang thống kê, phân biệt đánh giá hiện tại, số người đánh giá và lịch sử thao tác.

## 7. Kiểm thử trước khi lưu thật

- Một actor không thể đánh giá hoặc đọc feedback ở message/hội thoại không thuộc quyền của mình, kể cả khi thay ID hoặc số điện thoại.
- Rating đổi chiều, bỏ chọn, comment độc lập với rating; sửa cùng lúc ở hai tab có kết quả xác định, không trùng dòng hoặc mất dữ liệu âm thầm.
- Nội dung rỗng/toàn khoảng trắng/quá dài, văn bản tiếng Việt dài, chuỗi giống HTML, lỗi mạng, `401`, `409`, `429`, `503` và thử lại thủ công.
- Lọc/tìm kiếm, thêm tin nhắn, tải lại, đổi hội thoại, đổi danh tính, Chat/Voice không làm gắn feedback nhầm câu trả lời.
- Label/focus/aria-pressed, Escape, thông báo lỗi qua live region và bố cục 320px không tràn ngang; kiểm tra cả câu trả lời từ text và file audio.
- Chạy `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build` từ `src/web/`, cùng kiểm thử backend và database khi đã triển khai API.
