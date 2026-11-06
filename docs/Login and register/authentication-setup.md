# Thiết lập đăng nhập, đăng ký và database ở giai đoạn tiếp theo

## 1. Trạng thái hiện tại

Hiện mới có **giao diện demo**, chưa có dịch vụ xác thực hoặc bảng lưu tài khoản.

| Thành phần | Vị trí / hành vi hiện tại |
| --- | --- |
| Trang đăng nhập | `/login` — `src/web/app/(auth)/login/page.tsx` |
| Trang đăng ký | `/register` — `src/web/app/(auth)/register/page.tsx` |
| Biểu mẫu dùng chung | `src/web/app/(auth)/auth-screen.tsx` |
| Header, footer và bố cục | `src/web/app/(auth)/layout.tsx`, `auth.css` |
| Điểm vào từ Tài khoản | `src/web/app/components/account-content.tsx` |

Biểu mẫu kiểm tra dữ liệu ngay trên trình duyệt, hỗ trợ hiện/ẩn mật khẩu, xác nhận mật khẩu và đồng ý điều khoản. Đăng ký demo yêu cầu mật khẩu mẫu từ 15 ký tự; đăng nhập chỉ kiểm tra email hợp lệ và mật khẩu không trống. Đây không phải kiểm tra thông tin đăng nhập thật.

Khi gửi hợp lệ, UI hiển thị thông báo demo và xóa hai ô mật khẩu. Không gọi API đăng nhập/đăng ký, không gửi email, không tạo cookie, không lưu thông tin biểu mẫu vào localStorage/sessionStorage và không đổi trạng thái khách. Các ô biểu mẫu cố ý không có thuộc tính `name`; fieldset bị vô hiệu hóa trước khi JavaScript khởi tạo, tránh native form submission mang thông tin đăng nhập khi chưa có handler demo.

Root `ConversationProvider` vẫn có thể gọi health check của dịch vụ tư vấn; đây không phải request xác thực. Dữ liệu hội thoại/giỏ hàng khách hiện có vẫn theo cơ chế riêng của ứng dụng. Mở trang đăng nhập/đăng ký không cấp quyền cho hồ sơ, đơn hàng hoặc hội thoại nào.

## 2. Chọn kiến trúc trước khi kết nối UI

Ưu tiên thư viện hoặc nhà cung cấp xác thực được duy trì, tương thích với backend hiện tại, thay vì tự xây các primitive bảo mật. Next.js cũng khuyến nghị dùng giải pháp xác thực có sẵn cho quản lý phiên và phân quyền. Nếu chọn tự quản lý tài khoản trong PostgreSQL, có thể dùng sơ đồ sau như một **đề xuất triển khai**, chưa phải tính năng hiện có. [Hướng dẫn xác thực Next.js](https://nextjs.org/docs/app/guides/authentication).

```text
Trình duyệt
  -> Next.js Route Handler /api/auth/* (cùng origin với web)
    -> FastAPI /api/auth/* (dịch vụ xác thực)
      -> application/auth + repository PostgreSQL
```

- Backend là nguồn xác thực duy nhất; frontend không tự quyết định người dùng đã đăng nhập.
- Next.js làm lớp trung gian cùng origin để tránh triển khai cookie xác thực giữa hai domain. Chỉ chuyển tiếp các header/cookie được phép và không cache phản hồi cá nhân.
- Phân tách module theo cấu trúc hiện tại: domain contract trong `src/telesale_agent/core/`, luồng xử lý trong `application/`, adapter database trong `adapters/`, HTTP router trong `entrypoints/api/`.
- Nếu dùng provider, dùng user ID đã được server xác minh làm khóa ánh xạ; không duy trì thêm một hệ thống mật khẩu song song ngoài nhu cầu thực tế.

## 3. Chuẩn bị PostgreSQL và migration

1. Chuẩn bị database phát triển và kết nối server theo [hướng dẫn PostgreSQL hiện có](../docs/deployment/postgresql_self_hosting.md). Dùng database thử nghiệm hoặc schema dành riêng cho auth.
2. Thêm công cụ migration có version nếu chưa có, ví dụ Alembic cho SQLAlchemy. Tạo migration bổ sung bảng auth; không dùng script nạp catalog để khởi tạo lại database đã có dữ liệu. Script `scripts/migrate_catalog.py` hiện từ chối database đã có bảng ứng dụng.
3. Dùng tên bảng có tiền tố `auth_` để phân biệt tài khoản đăng nhập với hồ sơ `customers` của CRM. Không dùng số điện thoại CRM như bằng chứng sở hữu tài khoản.
4. Cấu hình kết nối bằng biến môi trường **chỉ ở server**. Không đưa database URL, khóa ký hoặc service key vào biến `NEXT_PUBLIC_*` và không commit `.env`.
5. Chạy migration trên database thử nghiệm, kiểm tra rollback, unique email và khóa ngoại trước khi triển khai lên môi trường có dữ liệu.

Ví dụ biến môi trường dự kiến, **chưa được code hiện tại đọc**:

```dotenv
# Backend .env hoặc secret manager; thay placeholder khi triển khai thật.
AUTH_DATABASE_URL=postgresql+psycopg2://<user>:<password>@localhost:5432/<auth_database>
AUTH_WEB_ORIGIN=http://localhost:3000
AUTH_SESSION_TTL_SECONDS=86400
```

TTL một ngày chỉ là giá trị minh họa; chốt cả thời hạn tuyệt đối và thời gian không hoạt động theo nhu cầu vận hành. Production dùng HTTPS, kết nối database có TLS phù hợp với nhà cung cấp và tài khoản database đủ quyền cần thiết.

### Mô hình dữ liệu tối thiểu đề xuất

| Bảng | Trường chính | Ràng buộc cần có |
| --- | --- | --- |
| `auth_users` | `id` UUID, `email_normalized`, `display_name`, `password_hash`, `email_verified_at`, `status`, `created_at`, `updated_at` | PK UUID; email chuẩn hóa có unique index; mật khẩu chỉ lưu hash nếu tự quản lý mật khẩu |
| `auth_sessions` | `id`, `user_id`, `token_hash`, `created_at`, `expires_at`, `last_seen_at`, `revoked_at` | FK user; token hash unique; index user/expiry; kiểm tra hết hạn và thu hồi ở server |
| `auth_verification_tokens` | `id`, `user_id`, `purpose`, `token_hash`, `expires_at`, `used_at` | FK user; mục đích xác minh/reset; token một lần, có hạn dùng |

Sinh ID và token ngẫu nhiên bằng thư viện bảo mật phía server. Với token phiên có entropy cao, database chỉ lưu bản băm của token; giá trị gốc đi trong cookie. Đối với mật khẩu, dùng password hashing chuyên dụng như Argon2id với salt do thư viện quản lý; không dùng SHA-256 thuần hoặc mã hóa đảo ngược để lưu mật khẩu. Cấu hình tối thiểu và cách benchmark cần đối chiếu khi triển khai. [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

## 4. Hợp đồng API dự kiến

Các endpoint sau **chưa tồn tại**. Cần triển khai backend và lớp trung gian Next.js trước khi nối vào biểu mẫu.

| Endpoint | Request | Phản hồi / hành vi |
| --- | --- | --- |
| `POST /api/auth/register` | `display_name`, `email`, `password`, `terms_version` | Kiểm tra server, tạo tài khoản chờ xác minh và gửi hướng dẫn xác minh; chưa tự cấp quyền trước khi đủ điều kiện |
| `POST /api/auth/login` | `email`, `password` | Kiểm tra thông tin; xoay token phiên; thiết lập cookie; chỉ trả user công khai |
| `GET /api/auth/me` | Cookie phiên | User công khai nếu phiên hợp lệ; `401` nếu chưa xác thực |
| `POST /api/auth/logout` | Cookie phiên và bảo vệ CSRF | Thu hồi phiên tại database, xóa cookie; có thể gọi lại an toàn |
| `POST /api/auth/verify-email` | Token một lần | Xác minh email và đánh dấu token đã dùng |
| `POST /api/auth/forgot-password` | Email | Thông báo chung, không tiết lộ email có tài khoản hay không |
| `POST /api/auth/reset-password` | Token một lần và mật khẩu mới | Đổi password hash, tiêu thụ token, thu hồi các phiên cần thiết |

Quy ước phản hồi cần thống nhất:

- `422`: lỗi từng trường để UI gắn đúng input; `401`: lỗi xác thực chung; `429`: có thời gian chờ và `Retry-After`; `503`: dịch vụ chưa sẵn sàng.
- Không trả password hash, token phiên, cookie hoặc chi tiết truy vấn database trong JSON/debug log.
- Kiểm tra lại toàn bộ dữ liệu ở server, bao gồm email, độ dài mật khẩu, xác nhận điều khoản và giới hạn request. UI validation chỉ giúp trải nghiệm.
- Trả lỗi đăng nhập chung, hạn chế lộ trạng thái tồn tại của tài khoản; áp dụng rate limit cho đăng nhập, đăng ký và khôi phục mật khẩu. Cho phép passphrase dài, không trim/cắt mật khẩu âm thầm, kiểm tra mật khẩu phổ biến/bị lộ. Nếu chưa có MFA, dùng mốc tối thiểu 15 ký tự và hỗ trợ ít nhất 64 ký tự tối đa theo hướng dẫn hiện hành. [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).

## 5. Cookie, phiên và phân quyền

Đề xuất cookie production: `__Host-synee_session`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, không có thuộc tính `Domain`. Thiết lập TTL và cơ chế xoay/thu hồi rõ ràng; local HTTP cần cấu hình cookie phát triển riêng. `SameSite` là một lớp bảo vệ bổ sung: vẫn cần kiểm tra Origin và cơ chế CSRF phù hợp cho request thay đổi dữ liệu, kể cả login/logout. Không lưu bearer token hoặc mật khẩu trong Web Storage. [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

Mỗi API đọc/sửa dữ liệu cá nhân phải xác minh phiên và kiểm tra quyền sở hữu tại server. Chỉ ẩn nút hoặc chặn route ở frontend không đủ để phân quyền. Không dùng `customer_phone`, conversation ID do trình duyệt gửi, mã đơn hàng đoán được hoặc service API key dùng chung để xác định chủ sở hữu.

Đặc biệt với hệ thống hiện tại:

- Bổ sung quan hệ sở hữu đã xác minh cho hội thoại, đơn hàng và dữ liệu khách hàng; không trả dữ liệu người khác khi đổi ID/số điện thoại.
- Lập kế hoạch ánh xạ `auth_users.id` với hồ sơ CRM; chỉ liên kết số điện thoại sau khi xác minh quyền sử dụng, nếu tính năng đó được triển khai.
- Sau đăng nhập/đăng xuất hoặc đổi tài khoản, dừng Voice và xử lý dữ liệu khách trong `ConversationProvider`/`PurchaseProvider` để tránh trộn dữ liệu của hai người.
- Nếu cho phép nhập hội thoại/giỏ khách vào tài khoản, yêu cầu lựa chọn rõ ràng và kiểm tra dữ liệu lại tại server. Không tự nhập dữ liệu từ localStorage hoặc tin giá/receipt demo là đơn hàng thật.

## 6. Thay thế demo trong frontend

1. Thêm client API xác thực dùng cùng origin, ví dụ `src/web/utils/auth-api.ts`; thêm provider session chỉ giữ user công khai và trạng thái tải.
2. Trong `auth-screen.tsx`, thay đoạn thông báo demo trong `submit` bằng request thật. Chỉ bỏ badge demo sau khi backend và phân quyền đã hoàn chỉnh. Nếu chuyển sang native form/Server Action, thiết kế lại `name`, hành vi khi JavaScript chưa tải và bảo vệ CSRF tương ứng.
3. Có trạng thái đang gửi, khóa chống gửi lặp, lỗi từng trường, thông báo lỗi chung và thử lại thủ công. Không log credentials, không đưa chúng vào URL/analytics và không tự gửi lại mật khẩu sau lỗi.
4. Chỉ hiển thị đã đăng nhập sau khi server xác nhận phiên. Không suy ra đăng nhập từ việc form hợp lệ hay một cờ localStorage.
5. Bổ sung UI xác minh email, quên/đổi mật khẩu và đăng xuất thật. Chỉ bật các điểm vào khi endpoint tương ứng sẵn sàng.
6. Nếu thêm URL quay lại sau đăng nhập, chỉ chấp nhận đường dẫn nội bộ trong allowlist để tránh open redirect.
7. Cập nhật `AccountQuickLinks`, `AccountNavigation`, trang hồ sơ và chatbot theo phiên thật. Giữ luồng khách nếu sản phẩm vẫn cho phép tư vấn không đăng nhập.
8. Cập nhật trang Chính sách bảo mật/Điều khoản theo việc thu thập, lưu giữ dữ liệu và thông tin đơn vị vận hành thực tế.

## 7. Kiểm tra trước khi bật xác thực thật

- Đăng ký, email trùng, xác minh email, sai mật khẩu, hết hạn/thu hồi phiên, đăng xuất và reset token dùng lại.
- Hai tài khoản không thể đọc/sửa hội thoại, đơn hoặc hồ sơ của nhau dù thay ID hoặc số điện thoại; dữ liệu khách không tự trở thành dữ liệu tài khoản.
- Cookie đúng thuộc tính trên HTTPS, CSRF, rate limit, thông báo đăng nhập không tiết lộ tài khoản và không cache dữ liệu cá nhân.
- Database không có mật khẩu rõ; log/analytics/error response không chứa mật khẩu hoặc token.
- Bản nháp/audio được xử lý rõ ràng khi chuyển giữa phiên khách và tài khoản; Voice dừng đúng lúc; tải lại không tự gửi lại request.
- Kiểm tra mobile 320px, bàn phím, trình quản lý mật khẩu, lỗi mạng, khả năng thử lại; chạy `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build` cùng kiểm thử backend phù hợp.

Tài liệu này là lộ trình thiết lập tiếp theo, không phải xác nhận rằng xác thực hoặc database tài khoản đã được triển khai.
