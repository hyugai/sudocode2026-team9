# Realtime voice với Gemini 3.8 Live

Giao diện có hai chế độ: **Chat / ghi âm** đi qua DeepAgent và Zipformer hiện tại;
**Realtime voice** đi qua voice controller và native audio Gemini Live. Hai chế độ
dùng chung identity, context preparation, tool policy, MCP connections và customer memory.

## Bật tính năng

Chạy từ repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[realtime]"
.\.venv\Scripts\python.exe scripts\migrate_voice.py
~~~

Migration chỉ tạo bảng voice_turn_journal trong PostgreSQL theo DATABASE_URL;
không thay đổi bảng catalog/order hoặc customer memory hiện tại.

Thêm vào .env của backend, sử dụng credential Gemini hiện có:

~~~dotenv
REALTIME_VOICE_ENABLED=true
GOOGLE_API_KEY=your_google_api_key_here
GEMINI_LIVE_MODEL=gemini-3.8-live
REALTIME_TOOLS_MODE=read_only
REALTIME_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
~~~

Sau đó khởi động lại backend. Frontend tiếp tục dùng NEXT_PUBLIC_API_BASE_URL như
chế độ chat; không đặt Google API key trong biến NEXT_PUBLIC_.
Nếu truy cập web bằng domain/port khác, thêm chính xác origin đó vào
REALTIME_ALLOWED_ORIGINS và cấu hình CORS_ORIGINS cho HTTP bootstrap.
Trang web cần HTTPS hoặc localhost và trình duyệt hỗ trợ AudioWorklet.

Nếu backend cấu hình API_KEY, giao diện voice sẽ yêu cầu **Mã truy cập**.
Đây là khóa truy cập backend của người vận hành, không phải Google API key.
Giá trị chỉ giữ trong bộ nhớ của component, không lưu localStorage và không đặt trong URL.
HTTP bootstrap kiểm tra khóa trước khi cấp owner token và ticket WebSocket dùng một lần.
Triển khai công khai cho nhiều người cần tích hợp auth người dùng thay cho khóa dùng chung.

Mở giao diện, chọn khách hàng, chuyển **Realtime voice** rồi bấm **Bắt đầu trò chuyện**.
Nói vào microphone; có thể tắt/bật mic hoặc kết thúc. Chuyển về chat hay sang trang
logs sẽ đóng microphone và kết nối voice; lịch sử chat/upload vẫn giữ nguyên.

## Phạm vi đã triển khai

- Cố định model gemini-3.8-live, SDK google-genai==2.30.1. Không kế thừa
  thinking config của model text, không tự chuyển sang model khác.
- Audio mono PCM16 16 kHz đầu vào, audio 24 kHz đầu ra được resample về thiết bị.
  Capture gửi frame 20 ms; playback có buffer giới hạn và generation để bỏ audio cũ.
  Playback tăng buffer theo lượng audio đang chờ, tối đa 60 giây; lượng audio sinh
  nhanh hơn tốc độ phát không bị xem là lỗi mạng chỉ vì vượt 5 giây. AudioContext
  được resume sau hộp thoại microphone hoặc khi trình duyệt tạm dừng audio.
- Transcript hai chiều; audio và transcript cùng provider event đều được xử lý.
- Tool chỉ đọc: context khách, catalog, inventory, pricing, knowledge/policy và memory
  archive khi registry hiện tại có hỗ trợ. Policy và identity được kiểm tra ở backend.
- Dùng cùng TurnMemoryPersister hoặc LLMPersister theo cấu hình hiện có.
  Voice turn có nguồn ghi riêng, journal bền vững và prepared memory batch để retry.
  Recovery chạy khi khởi tạo voice manager ở lần kết nối sau.
- Ngắt lời dừng playback, hủy read tool chưa còn cần; input chưa chốt được ghi incomplete.
- Provider reconnect có tối đa hai lần thử; ưu tiên resume, fallback mở phiên mới với
  CallBrief/memory đã commit khi resume không còn hợp lệ. Không replay thao tác nghiệp vụ.
- Khi trình duyệt mất WebSocket, microphone được giải phóng. Người dùng bấm bắt đầu
  lại để mở cuộc hội thoại mới và hydrate memory đã lưu; chưa tự nối lại browser transport.

## Giới hạn vận hành

**Chạy một backend worker.** Production PostgreSQL advisory lock từ chối voice manager
thứ hai; text/upload vẫn giữ cấu hình cũ. Giới hạn phiên, queue và timeout nằm trong
config/realtime.py và .env.example. Chưa có distributed session routing/CAS memory.

Tool ghi (tạo/sửa đơn, callback, handoff) bị khóa ở server và không đưa vào declarations.
REALTIME_TOOLS_MODE chỉ nhận off hoặc read_only; đặt read_write bị từ chối.
Khách có thể tư vấn bằng realtime rồi chuyển sang chat để thực hiện nghiệp vụ ghi.
Pha ledger/domain reconciliation cho mutation trong kế hoạch vẫn là công việc tiếp theo.

Raw audio không được lưu vào journal. Transcript, tool evidence và prepared memory jobs
có thể chứa dữ liệu khách hàng; áp dụng quyền truy cập và retention phù hợp cho database.
Journal và canonical memory không là một transaction xuyên hai kho. Prepared batches
giúp replay không lặp LLM learning và không nhân bản append; canonical facts mới hơn
không bị ghi đè khi replay một prepared batch cũ.

Native audio được phát trực tiếp. Text grounding/PII của chat không bảo đảm lọc mọi
lời nói trước khi khách nghe. Nếu cần bảo đảm đó, thiết kế text đã duyệt → TTS là
một chế độ output khác, chưa nằm trong nhánh native audio này.

## Kiểm tra

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_realtime.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_chat_latency.py -v
~~~

Trong src/web: npm test, npm run lint và npm run build.
Nếu Turbopack lỗi tiến trình CSS trên Windows, có thể kiểm tra bằng
npm run build -- --webpack; không cần thay dependency vì lỗi đó.

Tests dùng fake provider/tools, SQLite trong RAM và memory tách biệt, không gọi Gemini
hoặc sửa CRM thật. Chưa có phép đo TTFA/SLA tiếng Việt trên API thật; kiểm tra tài khoản
có quyền truy cập model trước khi rollout. Khi REALTIME_VOICE_ENABLED=false, mode vẫn
hiện nhưng nút bắt đầu bị vô hiệu hóa và chat/upload hoạt động như trước.

Kiểm tra ngày 25/10/2026: realtime tests, hồi quy chat/SSE và upload/ASR, frontend
tests, ESLint và production build với webpack đều qua. Đã kiểm tra chuyển chế độ
trên trình duyệt ở trạng thái chưa bật backend; chưa thử microphone hoặc Gemini thật.

## Rollback

Tắt REALTIME_VOICE_ENABLED và restart backend sau khi drain phiên đang hoạt động.
Giữ journal để recovery pending memory khi bật lại. Không xóa journal/memory để rollback,
không đóng MCP của nhánh text chỉ để tắt voice.

Tài liệu chính thức: [model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live),
[Live API](https://ai.google.dev/gemini-api/docs/live-api),
[session management](https://ai.google.dev/gemini-api/docs/live-api/session-management).
