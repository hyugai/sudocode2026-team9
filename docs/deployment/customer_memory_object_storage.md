# Customer memory trên Neon Object Storage

Hai lớp memory có vai trò khác nhau:

```text
users/C031/
├── current.md                  # bản gọn để dựng call brief mỗi turn
├── user.md                     # archive hồ sơ
├── behaviors.md                # archive hành vi
├── facts.md                    # archive facts
├── atomic_facts/
│   └── fact-YYYY-MM-DD.md
├── episodes/
│   └── episode-YYYY-MM-DD.md
└── foresights/
    └── foresight-YYYY-MM-DD.md
```

`current.md` trên bucket giữ `user`, `behaviors`, `facts` và nội dung của **hai ngày có hoạt động gần nhất** trong ba nhóm theo ngày. Với `CUSTOMER_MEMORY_BACKEND=object_storage`, backend GET khi chưa có cache, rồi đọc/cập nhật snapshot trong RAM trong suốt phiên. Không PUT theo từng message và không cần Neon Function.

Backend đồng bộ khi kết thúc hội thoại (chat, audio hoặc realtime voice), khi khách không hoạt động 120 giây (kiểm tra mỗi 5 giây), và lúc graceful shutdown. Mỗi đợt ghi các file thay đổi trong `facts.md`, `atomic_facts/`, `episodes/`, `foresights/` cùng hồ sơ/hành vi nếu có thay đổi, rồi ghi `current.md` cuối cùng. Khách mới được tạo cây file ở lần đồng bộ đầu. Dữ liệu cũ phải được archive thành công trước khi bị loại khỏi snapshot trên bucket; snapshot RAM giữ nguyên dữ liệu chưa đồng bộ.

Mỗi đợt thử tối đa 3 lần, chờ 1 rồi 2 giây giữa các lần thử. Nếu vẫn lỗi, dữ liệu tiếp tục ở trạng thái chờ và worker thử lại sau 15 giây. Request kết thúc chờ tối đa 20 giây để upload; nếu chưa xong, trả lỗi và giữ phiên để người dùng thử lại. Job upload đang chạy được giữ lại, không tạo upload cạnh tranh khi request hết hạn. Cập nhật đến giữa lúc upload tiếp tục chờ cho đợt sau. Cache sạch được giải phóng khi không hoạt động.

Realtime voice giữ journal ở trạng thái `prepared` cho đến khi snapshot tương ứng được upload thành công. Vì vậy cơ chế recovery hiện có vẫn replay được các thao tác voice chưa đồng bộ sau khi mất RAM.

`render.yaml` đặt `maxShutdownDelaySeconds: 120` để dành thời gian kết thúc stream/voice và đồng bộ. Đây là bảo vệ khi shutdown bình thường, không bảo đảm khôi phục RAM nếu Render crash hoặc bị kill trước khi upload. Không dùng file local trên Render Free làm bản lưu bền vững.

## Nhận diện khách hàng

Khi bắt đầu tư vấn, số điện thoại được chuẩn hóa (`+84` và `0` nhận cùng khách); tài khoản đăng nhập có thể dùng email nếu không nhập số điện thoại. Contact đã tồn tại dùng lại mã CRM và memory của khách. Contact mới được cấp `CXXX` theo hậu tố số lớn nhất trong DB: nếu lớn nhất là `C050`, mã mới là `C051`. Cấp mã và kiểm tra contact chạy trong transaction có khóa bảng PostgreSQL để tránh trùng khi tạo đồng thời. Không tự chọn khách nếu số điện thoại dùng chung hoặc phone/email trỏ đến nhiều hồ sơ.

Email được lấy từ tài khoản đã xác thực phía backend; không tin metadata email do browser gửi. Số điện thoại nhập rõ ràng được ưu tiên để xác định khách của phiên; email là fallback khi không có số. Nếu email đã thuộc mã khác, không chuyển email hay trộn memory: phiên dùng mã của số điện thoại. Khi email chưa được gắn với khách nào, có thể gắn với mã KH của số đã nhận diện. Web nhận `customer_id` trong phản hồi chat và hiển thị tại hồ sơ cá nhân; đổi số hoặc kết thúc hội thoại sẽ xóa mã của phiên cũ trên web.

Node `resolve_identity` lấy cả tên và `honorific` từ CRM. Chat/voice đưa cách xưng hô này vào prompt; câu trả lời chat thay cách gọi chung `anh/chị` bằng cách xưng hô đã xác nhận. Khách mới có row `customers` ngay khi nhận diện; nếu chưa rõ cách gọi thì dùng trung tính và hỏi ngắn gọn. Khi khách nói rõ như “gọi tôi là chị”, node cập nhật `customers.honorific` theo mã KH. Không suy đoán từ tên/email hoặc từ câu đang nói về người thứ ba. Checkpoint cũ chưa xác định được mã khách được thử nhận diện lại ở lượt tiếp theo.

Khi khách hỏi về cuộc gọi/lịch sử cũ mà call brief không đủ, DeepAgent được phép gọi `search_customer_memory_archive`. Tool này lấy `customer_id` từ runtime, không cho model chọn ID khách khác. Nó chỉ đọc archive theo yêu cầu, không GET mọi file ở đầu turn. Kết quả archive là lịch sử, **không phải** nguồn xác minh giá, tồn kho, đơn hàng hay chính sách hiện hành.

## Cấu hình

Local cần cài `python -m pip install -e ".[object-storage]"`; image Render đã có boto3 trong `requirements-render.txt`.

```env
CUSTOMER_MEMORY_BACKEND=object_storage
CUSTOMER_MEMORY_BUCKET=your_private_bucket
CUSTOMER_MEMORY_PREFIX=users
AWS_ENDPOINT_URL_S3=https://your-neon-s3-endpoint
AWS_ACCESS_KEY_ID=your_storage_access_key
AWS_SECRET_ACCESS_KEY=your_storage_secret_key
AWS_REGION=your_neon_storage_region
MEMORY_PERSISTER_MODE=llm_learning
```

`DATABASE_URL` vẫn chỉ dùng cho CRM/catalog/đơn hàng PostgreSQL. Bucket memory nên là private. Render disk không phải bản lưu bền vững.

Khi benchmark ghi thật lên Neon, đặt `CUSTOMER_MEMORY_PREFIX=eval/<run_id>/users` để tách khỏi `users/<customer_id>/` production. Prefix là một phần của object key, không tạo bucket mới.

## Backfill C031 đã có `current.md` nhưng thiếu file archive

Chạy dry-run trước, rồi apply:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_memory_to_object_storage.py --customer-id C031
.\.venv\Scripts\python.exe scripts\migrate_memory_to_object_storage.py --customer-id C031 --apply
```

Script chỉ tạo những object archive còn thiếu từ local `data/memory-root/users/C031` và `current.md` hiện có; **không ghi đè `current.md` hoặc facts mới trên Neon**. Nếu local `foresights` rỗng, `.keep` giúp prefix `foresights/` hiện trên object storage. Muốn import toàn bộ khách thì bỏ `--customer-id`. Chỉ dùng `--overwrite` khi chủ ý thay `current.md` trên Neon bằng dữ liệu local.

## Smoke test ghi thật lên Neon

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_neon_memory.py
.\.venv\Scripts\python.exe scripts\smoke_test_neon_memory.py --apply
```

Lệnh đầu chỉ dry-run. Lệnh `--apply` tạo ID riêng `TEST_MEMORY_*`, ghi cây `.md` thật, chạy một lượt `TurnMemoryPersister`, rồi GET/list để xác nhận `current.md`, facts và archive. Nó **không gọi Gemini**, không sửa khách CRM và cố ý giữ dữ liệu thử trên bucket để có thể kiểm tra sau đó.

## Giới hạn

- Hai turn đồng thời cùng một khách trên nhiều instance vẫn có nguy cơ ghi đè `current.md`; cần serialize theo `customer_id` hoặc conditional write trước khi scale.
- Dữ liệu từ phiên bản cũ có source như `episode-0001.md` không có ngày sẽ được giữ trong `current.md`; không thể tự gán ngày archive một cách đáng tin cậy.
- Archive search chỉ đọc tối đa một số file gần đây để giới hạn latency; nếu cần truy tìm rất xa theo thời gian, nên cung cấp ngày cụ thể hoặc thêm chỉ mục.
