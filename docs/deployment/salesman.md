# Salesman — demo UI và kế hoạch database

## Trạng thái hiện tại

**Hiện chỉ triển khai giao diện demo, chưa triển khai phân quyền Salesman hay kết nối database.**

- Mở trực tiếp `/salesman`, không cần đăng nhập. Trang đăng nhập/đăng ký cũng có liên kết **Xem demo Salesman**.
- Có 8 hội thoại giả lập, gồm Chat và Realtime Voice; tìm kiếm không dấu theo tên, email, SĐT hoặc mã phiên; lọc nguồn và phân trang.
- Chọn một hội thoại để xem transcript, Call brief và Memory agent. Có ví dụ Voice bị ngắt, thiếu snapshot và hội thoại chưa có tin nhắn.
- Chỉ xem; không có composer, tạo hội thoại, micro hoặc khởi tạo LiveKit.
- Dữ liệu ở `src/web/utils/salesman-demo.ts`, kiểu dữ liệu ở `salesman-types.ts`. Toàn bộ khách hàng, email, số điện thoại, giá và nội dung đều là minh họa; không lấy từ dữ liệu thật.
- Trang demo không gọi API xác thực, giỏ hàng hoặc hội thoại; không đọc/ghi localStorage, sessionStorage hay database. Nút làm mới chỉ đọc lại fixture.
- Luồng đăng ký/đăng nhập hiện tại giữ nguyên. **Chưa có lựa chọn role thực, cột `users.role`, API `/api/salesman/*` hoặc migration Salesman.** Các phần bên dưới là kế hoạch triển khai sau, không phải tính năng đã hoạt động.

## Cách mở demo

Từ thư mục repository:

```powershell
cd src/web
npm install
npm run dev -- --hostname 127.0.0.1 --port 3100
```

Truy cập <http://localhost:3100/salesman>. Không cần chạy Python, PostgreSQL, ASR, LiveKit hoặc cấu hình `.env` để xem demo. Khi đưa frontend lên host đang dùng, đường dẫn tương ứng là `https://<frontend-host>/salesman`.

## Yêu cầu cho phiên bản có database (chưa triển khai)

1. Đăng ký cho chọn `user` hoặc `salesman`.
2. Chỉ tài khoản có role `salesman` được vào trang quản lý dữ liệu thật.
3. Salesman xem được toàn bộ lịch sử có trong database, gồm mọi tài khoản và trạng thái đang hoạt động/đã kết thúc; không chỉ lịch sử của chính Salesman.
4. Mỗi phiên hiển thị transcript, Call brief hiện tại và snapshot memory/ngữ cảnh mà harness agent đã sử dụng.
5. Salesman không tạo hội thoại, gửi chat, upload âm thanh, dùng realtime voice hoặc sửa/xóa lịch sử và memory.
6. Khi thay fixture bằng dữ liệu thật, bắt buộc thay đường dẫn công khai hiện tại bằng trang có kiểm tra quyền; không giữ dữ liệu thật trong bản demo công khai.

## Database hiện có cần tận dụng

| Bảng | Nội dung liên quan | Công việc cần làm sau |
| --- | --- | --- |
| `users` | Tài khoản, tên, email, password hash | Thêm role; không trả password hash ra UI |
| `auth_sessions` | Phiên đăng nhập và hạn phiên | Giữ cơ chế cookie hiện có; tra role từ DB |
| `conversations` | Chủ tài khoản, customer ID, trạng thái, turn number, `call_brief`, `checkpoint`, thời gian | Đọc xuyên tài khoản ở API dành riêng cho Salesman |
| `messages` | Transcript theo conversation, lượt và role | Phân trang ổn định theo lượt, user trước agent trong cùng lượt |
| `customers` và dữ liệu CRM/memory | Hồ sơ và memory canonical | Chỉ dùng thông tin cần hiển thị; không sửa CRM khi Salesman mở trang |
| `voice_turn_journal` | `source_id`, `customer_id`, `payload`, `prepared`, `status`, `updated_at` | Chuẩn hóa nhóm phiên, chủ sở hữu và bổ sung snapshot để xem Voice |

Chat của khách chưa đăng nhập hiện chỉ có trong trình duyệt không tự xuất hiện trong database. Nếu muốn quản lý cả các phiên đó, cần thiết kế lưu server riêng; không âm thầm nhập lịch sử trình duyệt vào tài khoản khác.

## Kế hoạch migration role PostgreSQL

Triển khai trong migration idempotent riêng hoặc mở rộng `src/telesale_agent/adapters/db/app_schema.py`; đồng thời cập nhật model `User` và repository. Chỉ chạy sau khi phần backend tương ứng đã được viết và kiểm thử. Không cần chạy SQL này để xem demo.

SQL dự kiến:

```sql
BEGIN;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16);
UPDATE users SET role = 'user' WHERE role IS NULL;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user';
ALTER TABLE users ALTER COLUMN role SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_users_role' AND conrelid = 'users'::regclass
  ) THEN
    ALTER TABLE users ADD CONSTRAINT ck_users_role
      CHECK (role IN ('user', 'salesman'));
  END IF;
END $$;
COMMIT;
```

- Tất cả tài khoản cũ trở thành `user`; không đổi UUID, mật khẩu hoặc cookie session.
- Cột `users.role` là vai trò nghiệp vụ, không phải tạo PostgreSQL login/DB superuser cho mỗi Salesman.
- Validate role ở API đăng ký, chỉ nhận hai giá trị trên; thiếu role mặc định `user` để tương thích client cũ.
- Theo yêu cầu sản phẩm hiện tại, người đăng ký tự chọn Salesman. Khi triển khai cần xác nhận lại chính sách này vì role được xem hội thoại của mọi khách hàng.
- Dùng đúng connection/schema của ứng dụng qua cấu hình môi trường hiện có; không ghi credentials vào tài liệu hay mã nguồn. Không drop/reset DB hoặc catalog/CRM.
- Trước triển khai thật: backup DB, chạy thử trên staging, kiểm tra constraint và số tài khoản theo role. Chưa có kế hoạch rollback phá hủy dữ liệu; có thể tắt luồng Salesman bằng rollback ứng dụng và giữ cột bổ sung.

Script `python scripts/migrate_app_data.py` hiện chỉ xử lý schema ứng dụng đang có. **Nó chưa thêm role Salesman.** Sau khi bổ sung migration và test thành công mới cập nhật hướng dẫn deploy/Docker startup và chạy script với phiên bản mới.

## Call brief và memory của Chat

- Đọc `conversations.call_brief` đã lưu, gồm `summary`, `needs`, `objections`, `unresolved_issues`.
- Lấy các trường cho phép từ checkpoint mới nhất của **chính phiên được chọn**: `customer_memory`, `working_memory`, `memory_deltas`, `customer_profile`, `past_history`, `retrieved_data`.
- Hiển thị thời điểm snapshot; làm mới lấy bản đã lưu mới nhất. Không chạy lại agent, tạo tóm tắt mới, commit memory hoặc thay dữ liệu canonical khi xem.
- Không thay memory tại thời điểm phiên bằng memory hiện tại của khách rồi gắn nhãn là snapshot cũ. Nếu cần hiển thị cả memory canonical hiện tại, phải tách rõ nguồn và thời gian.
- Checkpoint thiếu/null thì hiển thị “Chưa lưu snapshot memory”. Chỉ serialize danh sách trường cho phép; không trả toàn bộ checkpoint, tool credentials, debug trace, password hash hoặc session token.

## Lưu lịch sử và snapshot Realtime Voice

`voice_turn_journal` hiện thiên về journal từng lượt, không phải schema lịch sử có quan hệ tài khoản như `conversations`. Cần hoàn thiện trước khi dùng cho màn hình quản lý:

1. Xác định `conversation_id`/room ID ổn định giữa các lượt, `user_id` từ session server và `customer_id` nếu có. Không đoán chủ tài khoản từ số điện thoại; không nhận `user_id` tùy ý từ client.
2. Với journal cũ thiếu chủ sở hữu, hiển thị rõ khách chưa xác định; không backfill chủ tài khoản bằng suy đoán. Cân nhắc tạo bảng phiên Voice riêng hoặc thêm cột có index/FK phù hợp thay vì chỉ tìm trong JSON.
3. Sau lượt hoàn tất, lưu `call_brief`, các trường memory cho phép, `turn_number` và `snapshot_at` cùng phiên. Payload JSON có thể chứa snapshot có phiên bản, hoặc dùng bảng snapshot riêng.
4. Giữ nguyên logic `pending`/`prepared`/`committed` của journal và retry jobs; việc ghi snapshot không được đổi trạng thái commit, mất prepared batch hoặc gây double commit memory.
5. Lượt bị ngắt vẫn có thể hiển thị transcript với nhãn “Chưa hoàn tất / bị ngắt”. Nếu có snapshot hoàn tất trước đó thì hiển thị snapshot đó kèm thời gian; không gắn nhãn snapshot mới khi chưa có.
6. Nhật ký cũ không có snapshot thì trả `null`, không chạy lại job/LLM để bịa dữ liệu lịch sử.

Migration Voice hiện có là `python scripts/migrate_voice.py`; chỉ dùng khi triển khai backend Voice theo hướng dẫn hiện có. Bản demo không cần chạy lệnh này và chưa bổ sung snapshot mới.

## API và phân quyền dự kiến

| Endpoint | Hành vi cần triển khai |
| --- | --- |
| `POST /api/auth/register` | Nhận thêm role hợp lệ và lưu DB |
| `POST /api/auth/login`, `GET /api/auth/me` | Trả public user có role; không có dữ liệu bí mật |
| `GET /api/salesman/conversations?q=&source=all&limit=20&offset=0` | Tìm theo tên/email/SĐT/mã phiên/mã khách, lọc `all\|chat\|voice`, phân trang toàn bộ DB |
| `GET /api/salesman/conversations/{source}/{id}?limit=50&offset=0` | Transcript phân trang + brief + memory + timestamp cho phiên được chọn |

- Chưa đăng nhập: 401; tài khoản `user`: 403; phiên không tồn tại: 404. Quyền được kiểm tra ở backend trên từng request dựa trên session và role trong DB, không tin role gửi từ browser.
- Response chứa dữ liệu khách hàng dùng `Cache-Control: no-store`; không static export, CDN cache, hoặc lưu lâu trong browser. Hủy request cũ khi đổi khách/tìm kiếm để tránh lẫn nội dung phiên.
- Chỉ có API đọc cho Salesman, dùng query tham số hóa, giới hạn `limit`, kiểm tra source/ID, sắp xếp ổn định (thời gian + ID). Với dữ liệu lớn cân nhắc cursor và index theo `updated_at`, `conversation_id`, cùng index tìm kiếm phù hợp.
- Chặn Salesman tại các API tạo/kết thúc hội thoại, gửi chat, feedback, upload ASR và mở Voice/LiveKit token/WebSocket. Không chỉ ẩn nút trên UI. Endpoint tài khoản/đăng xuất cần tiếp tục hoạt động.
- Sau đăng nhập Salesman chuyển tới `/salesman`; route khách Chat/Voice/Dashboard chuyển về đó. Khi vào Salesman không mount provider hội thoại, giỏ hàng hoặc microphone. Khi đổi tài khoản, xóa state nhạy cảm của phiên trước.

## Tích hợp frontend sau này

Thay adapter local `salesmanDemo` bằng client đọc API có session, timeout và hủy request; giữ kiểu `HistoryItem`, `HistoryDetail`, `HistoryPage` làm hợp đồng khởi đầu. Không tự động fallback về fixture khi API thật lỗi. Tách hẳn fixture khỏi bản quản lý dữ liệu thật và bổ sung loading, 401/403, retry, pagination, snapshot mới/thiếu.

## Kiểm tra

Cho bản demo hiện tại, từ `src/web`:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Browser smoke test: chạy frontend trên port 3100 và Chromium có CDP port 9222 (profile test riêng), đặt `BASE_URL`/`CDP_URL`/`BROWSER_ARTIFACT_DIR` rồi chạy `node tests/salesman-browser.mjs`. Test truy cập thẳng không đăng nhập, chặn toàn bộ `/api/*`, kiểm tra tìm/lọc/phân trang, các tab, dữ liệu thiếu, keyboard và chiều rộng 320–1440px. Ảnh chụp ghi vào thư mục artifact.

Trước khi triển khai database thật, bổ sung test backend cho role, migration chạy lại, tài khoản cũ, đọc xuyên tài khoản, 401/403, chặn mọi thao tác ghi/chat/voice, không gọi LLM khi xem, snapshot Voice và pagination; test migration PostgreSQL trên schema/database test riêng, không dùng dữ liệu khách thật. Các test đó **chưa có trong bản demo này**.
