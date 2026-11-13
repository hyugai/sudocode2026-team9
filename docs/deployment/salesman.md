# Salesman — kết nối backend cho demo

Cập nhật 14/11/2026: `/salesman` đọc dữ liệu backend, yêu cầu đăng nhập role `salesman`. Dữ liệu fixture trong `salesman-demo.ts` chỉ phục vụ test.

## Chức năng

- Register chọn `user` hoặc `salesman`; thiếu role mặc định `user`.
- Login Salesman chuyển vào `/salesman`; các route tư vấn chuyển về trang này và không mount chat/cart/microphone providers.
- Salesman xem danh sách Chat account và Realtime Voice đã có journal: tìm theo tên/email/SĐT/mã phiên/mã khách, lọc nguồn, phân trang và làm mới.
- Chi tiết có transcript, Call brief compact và memory cuối lượt đã lưu; trang chỉ xem.
- User thường giữ API lịch sử/feedback của mình. Salesman bị chặn thao tác chat, upload, tạo/end conversation, feedback và bootstrap Voice ở backend.
- Header hiển thị tài khoản và nút đăng xuất; hết phiên xóa nội dung đang xem.

Đây là demo với chính sách tự chọn role khi đăng ký. Dùng dữ liệu minh họa theo phạm vi demo đã chốt.

## Migration và chạy

Từ repository root, với Python environment có dependency dự án:

```powershell
python scripts/migrate_app_data.py
python scripts/migrate_voice.py
python -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --reload
```

Migration app thêm `users.role` trước bước validate schema, default `user`, check `user|salesman`. Account cũ, mật khẩu, session và lịch sử giữ nguyên. Chạy lại được; không reset hoặc ingest lại CRM/catalog. Voice migration chỉ cần khi dùng Realtime Voice, không bổ sung bảng history mới.

**Phải migrate trước khi dùng code auth mới với DB cũ.** Nếu thiếu `users.role`, login/register có thể trả 503. Database demo đang chạy đã được migrate trong lần triển khai này.

Frontend `.env.local`:

```dotenv
API_BACKEND_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Backend đặt `WEB_ORIGIN=http://localhost:3000`; CORS và `REALTIME_ALLOWED_ORIGINS` phải chứa origin dùng để mở web. Restart sau khi đổi env. Từ `src/web`, chạy `npm run dev`, mở `http://localhost:3000`.

`next.config.ts` cho phép dev assets từ `127.0.0.1` qua `allowedDevOrigins`. Cấu hình này không thay thế Origin check của API: nếu mở web bằng host/port khác, cần cấu hình backend tương ứng.

Tạo tài khoản Salesman ở `/register`, sau đó đăng nhập. Giữ một backend worker theo giới hạn Voice/memory hiện có.

## API

| Endpoint | Nội dung |
| --- | --- |
| `POST /api/auth/register` | `{name,email,password,role?}` |
| `POST /api/auth/login`, `GET /api/auth/me` | Public user `{id,name,email,role}` |
| `GET /api/salesman/conversations?q=&source=all&limit=20&offset=0` | `{items,total,has_more}`; source `all|chat|voice` |
| `GET /api/salesman/conversations/{source}/{id}?limit=50&offset=0` | Transcript phân trang + brief/memory/snapshot time; `has_more`, `next_offset` |

Limit 1–100, offset không âm. 401 chưa đăng nhập/hết phiên, 403 sai role, 404 không có phiên, 422 input sai, 503 DB unavailable. Salesman responses dùng `Cache-Control: no-store`; frontend gọi cùng origin qua rewrite và cookie hiện có.

Chat gồm cả text và upload audio. ID Chat là UUID; ID Voice dùng conversation ID hiện có, thường `live-...`.

## Nguồn dữ liệu và giới hạn

### Chat

Đọc `conversations`, `messages`, `users`. Transcript xếp theo lượt, user trước agent. Brief lấy bản compact đã lưu. Memory đọc các nhóm được phép trong checkpoint: customer memory, working memory, deltas, profile, past history và retrieved data; bỏ trường credential/token/debug và không trả toàn checkpoint.

Nhãn “Bản lưu cuối lượt” chỉ bản lưu mới nhất của phiên, không phải mọi input lịch sử hoặc canonical memory hiện tại. Checkpoint thiếu/sai phiên bản thì memory null, vẫn đọc transcript. GET không chạy agent/LLM, đọc lại bucket memory hoặc ghi memory.

Chat guest chỉ ở RAM/browser như trước, không tự xuất hiện trong trang quản lý.

### Realtime Voice

Tận dụng `voice_turn_journal`, thêm vào JSON payload: owner `user_id` từ session server, `turn_number`, `created_at`; sau lượt hoàn tất thêm compact brief, memory projection và `snapshot_at`. Account bootstrap đi qua proxy cùng origin; guest giữ access code hiện có. WebSocket vẫn dùng owner token/ticket một lần.

API gom theo `payload.conversation_id`, xếp thứ tự bằng số lượt khi đủ metadata, chọn snapshot mới nhất đã lưu của lượt hoàn tất. Lượt bị ngắt có nhãn riêng, không thay snapshot trước bằng dữ liệu rỗng.

Không đổi `pending/prepared/committed` hoặc recovery memory. Nếu memory đã commit nhưng snapshot ghi lỗi, có thể chỉ xem transcript; không commit lại memory để dựng dữ liệu hiển thị. Không thêm recovery snapshot hoặc backfill owner theo SĐT.

Journal cũ thiếu owner/sequence/snapshot vẫn xem được phần có sẵn. Phiên chưa ghi journal chưa xuất hiện; không thể dùng status một job để khẳng định toàn cuộc gọi đã kết thúc. Không lưu audio gốc. Chưa quản trị thu hồi Voice đang mở/đổi role nóng.

### UI và commerce

Request cũ bị hủy khi đổi tìm kiếm/phiên; lỗi không fallback fixture. Không lưu transcript/memory Salesman vào Web Storage. Offset pagination phù hợp quy mô demo, có refresh, chưa đảm bảo tập dữ liệu đứng yên khi phiên đang cập nhật.

Giỏ hàng, đơn hàng và thanh toán vẫn giữ demo local; không nằm trong đợt triển khai Salesman.

## Kiểm tra

Backend regression chính:

```powershell
# PYTHONPATH cần gồm src và tests khi gọi module như dưới.
python -m unittest discover -s tests -p test_salesman_api.py -v
python -m unittest discover -s tests -p test_realtime.py -v
```

DB tests dùng `APP_DATA_TEST_DATABASE_URL` trỏ rõ tới DB test/demo được chọn; mỗi suite tạo schema riêng và chỉ xóa schema do test tạo. `test_salesman_api.py` cũng có API/DB SQLite synthetic để kiểm tra nhanh không cần PostgreSQL.

Frontend từ `src/web`, Node 24:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Browser: chạy Chrome test có CDP, đặt `BASE_URL`, `CDP_URL`, `BROWSER_ARTIFACT_DIR`, rồi chạy `node tests/salesman-browser.mjs`. Test dùng fixture API synthetic có auth; không thay dữ liệu backend demo. Chạy thêm `ai-chat-browser.mjs`, `voice-browser.mjs` cho các luồng liên quan.

Trên Windows, có thể dùng `npm.cmd`/`npx.cmd` nếu PowerShell chặn script; đặt `PYTHON` về Python environment hợp lệ cho Node contract probes. Với Python ghi log tiếng Việt, đặt `PYTHONIOENCODING=utf-8`.

Xem [kết quả kiểm tra](../implementation/salesman-verification.md) và [plan/checklist](../implementation/web-backend-integration-plan.md).
