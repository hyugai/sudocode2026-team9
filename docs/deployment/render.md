# Deploy Telesale Agent lên Render

Tài liệu này deploy backend FastAPI + DeepAgent lên Render bằng Docker. Database
không được tạo trên Render; application kết nối tới PostgreSQL riêng qua
`DATABASE_URL`.

## 1. Kiến trúc khi deploy

**Render Free hiện dùng Neon Object Storage:** `render.yaml` đặt `CUSTOMER_MEMORY_BACKEND=object_storage`. Memory nằm trong RAM trong phiên và được upload khi kết thúc phiên, sau 120 giây không hoạt động, hoặc graceful shutdown. Không cần Persistent Disk hay Neon Functions. Cấu hình bucket/S3 credentials trước khi deploy; xem [Customer memory trên Neon Object Storage](customer_memory_object_storage.md). Phần Persistent Disk bên dưới chỉ áp dụng nếu chủ động chọn backend `file` trên service trả phí. RAM chưa upload vẫn có thể mất khi crash/restart đột ngột.

```text
Client / frontend
    -> HTTPS Render Web Service
       -> FastAPI /api/chat
       -> DeepAgent + MCP subprocesses
       -> Groq API
       -> PostgreSQL riêng qua DATABASE_URL
       -> ChromaDB read-only trong Docker image
       -> Customer memory trong RAM -> Neon Object Storage khi end/idle/shutdown
```

Các phần được đóng gói trong image:

- source tại `src/telesale_agent` và `src/mcp_servers`;
- DeepAgent instructions: `soul.md`, `agent.md`, `tools.md`;
- Chroma database dùng cho policy RAG;
- customer memory hiện có làm seed cho lần khởi tạo disk đầu tiên;
- Hugging Face embedding model `keepitreal/vietnamese-sbert`;
- Python dependencies đã khóa trong `requirements-render.txt`.

Docker cài bản PyTorch CPU-only, vì Render service này không dùng GPU. Embedding model
được tải lúc build và runtime bật `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`, nên quá trình
khởi động không phụ thuộc Hugging Face Hub. Image kiểm tra local có kích thước khoảng
1.53 GB; kích thước transfer/compressed mà Render hiển thị có thể khác.

Các phần không nằm trong image:

- `.env` và secret;
- PostgreSQL data;
- BTC datasets, tests, notebooks và frontend Next.js.

## 2. Vì sao cần Persistent Disk

Filesystem mặc định của Render là ephemeral. Customer memory `.md` sẽ mất khi
restart/redeploy nếu ghi bên trong image filesystem.

Blueprint mount disk tại:

```text
/var/data/customer-memory
```

và đặt:

```dotenv
CUSTOMER_MEMORY_ROOT=/var/data/customer-memory
```

`scripts/render_start.py` chỉ copy seed memory từ image khi disk chưa có file.
Khi disk đã có memory, startup không copy hoặc overwrite dữ liệu.

Persistent Disk chỉ dùng được với paid web service. Service có disk chỉ chạy
được một instance và deploy không zero-downtime. Điều này cũng phù hợp với
implementation file memory hiện tại vì repository chưa có distributed lock.

Nếu deploy Free không gắn disk, API có thể chạy nhưng memory ghi trong container
sẽ mất sau restart. Không dùng cấu hình này nếu cần self-learning memory.

## 3. Chuẩn bị PostgreSQL riêng

Database phải tồn tại và đã có schema/data trước khi deploy. Container không tự
tạo hoặc migrate database.

Connection string ví dụ:

```dotenv
DATABASE_URL=postgresql://user:password@db.example.com:5432/telesale?sslmode=require
```

Client chấp nhận cả `postgres://` và `postgresql://`, sau đó dùng psycopg2.
Connection pool bật `pool_pre_ping` và recycle connection sau 300 giây.

PostgreSQL phải cho phép network connection từ Render. Nếu DB dùng IP allowlist,
lấy outbound CIDR của service trong Render Dashboard, mục **Connect → Outbound**,
rồi thêm các range đó vào firewall/allowlist của PostgreSQL.

Không commit username/password database vào `.env.example`, `render.yaml` hoặc
source code.

## 4. Kiểm tra data trước khi commit

`.gitignore` chỉ mở lại ba runtime-data path:

```text
data/chroma_db/
data/memory-root/agents/
data/memory-root/users/
```

Trước khi commit, phải review customer files vì chúng có thể chứa dữ liệu cá
nhân hoặc lịch sử hội thoại:

```powershell
git status --short data
git diff --no-index NUL data\memory-root\users\C031\user.md
```

Nếu không muốn đưa customer memory hiện tại lên Git, không commit
`data/memory-root/users/`. Disk sẽ bắt đầu trống và tự tạo customer directory
khi agent ghi memory mới. Agent instructions và ChromaDB vẫn phải được commit.

## 5. Biến môi trường trên Render

Blueprint yêu cầu nhập bốn giá trị:

| Key | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `DATABASE_URL` | Có | PostgreSQL riêng của bạn |
| `GROQ_API_KEY` | Có | Perceiver, DeepAgent và durable episode summarizer |
| `API_KEY` | Khuyến nghị mạnh | Bảo vệ `/api/chat` và session endpoint |
| `CORS_ORIGINS` | Có nếu gọi từ browser | Danh sách frontend origin, phân cách bằng dấu phẩy |

Ví dụ `CORS_ORIGINS`:

```text
https://your-frontend.vercel.app,https://app.example.com
```

Không dùng `*` cho production nếu API được gọi trực tiếp từ browser.

Các path và token limits đã được khai báo sẵn trong `render.yaml`.

## 6. Deploy bằng Blueprint

1. Commit và push các file deploy lên GitHub/GitLab.
2. Mở Render Dashboard.
3. Chọn **New → Blueprint**.
4. Chọn repository này. Render tự đọc `render.yaml` ở root.
5. Nhập các secret được đánh dấu `sync: false`.
6. Xác nhận web service, compute plan và Persistent Disk.
7. Deploy và theo dõi build log.

Blueprint hiện chọn region `singapore`, compute `1c-2g` và disk 5 GB. Embedding
model/Chroma dùng khá nhiều RAM; nếu gặp out-of-memory, tăng compute plan.

Render inject biến `PORT`. `scripts/render_start.py` chạy Uvicorn trên
`0.0.0.0:$PORT` với đúng một worker.

## 7. Health check và gọi API

Health check:

```bash
curl https://YOUR-SERVICE.onrender.com/health
```

Kết quả:

```json
{"status":"ok"}
```

Gọi chat:

```bash
curl -X POST https://YOUR-SERVICE.onrender.com/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "conversation_id": "call-001",
    "message": "Chị cần máy lọc không khí cho phòng 25m2",
    "customer_phone": "0984726714"
  }'
```

Response production mặc định:

```json
{"response":"..."}
```

CRM profile và customer memory không được trả ra response trừ khi chủ động đặt:

```dotenv
ENABLE_DEBUG_RESPONSE=true
```

Không bật tùy chọn này trên public production API.

Kết thúc/reset active call state:

```bash
curl -X DELETE \
  -H "X-API-Key: YOUR_API_KEY" \
  https://YOUR-SERVICE.onrender.com/api/sessions/call-001
```

Việc reset session chỉ xóa `ConversationState` trong RAM. Customer memory `.md`
đã persist không bị xóa.

## 8. Chạy Docker local trước khi deploy

Build:

```powershell
docker build -t telesale-agent-render .
```

Tạo thư mục disk local:

```powershell
New-Item -ItemType Directory -Force .render-data\customer-memory
```

Run:

```powershell
docker run --rm -p 10000:10000 `
  --env-file .env `
  -e PORT=10000 `
  -e CUSTOMER_MEMORY_ROOT=/var/data/customer-memory `
  -e AGENT_INSTRUCTIONS_ROOT=/app/data/memory-root/agents/telesales_agent `
  -e CHROMA_DB_DIR=/app/data/chroma_db `
  -v "${PWD}/.render-data/customer-memory:/var/data/customer-memory" `
  telesale-agent-render
```

Sau đó kiểm tra `http://localhost:10000/health`.

## 9. Tắt Vector RAG để giảm tài nguyên

Nếu chỉ cần CRM/catalog/pricing/order và chưa cần policy semantic search:

```dotenv
ENABLE_VECTOR_RAG=false
```

Khi tắt, `VectorDBRetriever` không load embedding model/Chroma. Dockerfile hiện
vẫn chứa model để một image dùng được cho cả hai mode; muốn giảm mạnh image size
thì cần tạo một Dockerfile lite riêng và bỏ nhóm sentence-transformers/Chroma.

## 10. Session và scaling

Active `ConversationState` đang nằm trong RAM của FastAPI:

- restart service làm mất active session của cuộc gọi đang diễn ra;
- durable customer facts/episodes trên disk không mất;
- request cùng một `conversation_id` được serialize bằng `asyncio.Lock`;
- session phải được xóa bằng endpoint khi cuộc gọi kết thúc để tránh RAM tăng
  vô hạn.

Không tăng Uvicorn workers và không scale Render lên nhiều instance trong kiến
trúc hiện tại. Muốn scale ngang cần chuyển active sessions sang shared store và
customer memory sang storage hỗ trợ concurrent access.

## 11. Backup và cập nhật seed

Render tạo snapshot định kỳ cho Persistent Disk theo chính sách của platform.
Vẫn nên export customer memory riêng nếu dữ liệu quan trọng.

Thay đổi seed trong Git không cập nhật disk đã có dữ liệu. Đây là behavior cố ý
để deploy mới không ghi đè learned memory. Muốn import seed mới phải thực hiện
migration có kiểm soát hoặc tạo disk mới.

## 12. Checklist trước production

- [ ] PostgreSQL có SSL hoặc private tunnel phù hợp.
- [ ] Firewall DB cho phép outbound IP ranges của Render.
- [ ] `DATABASE_URL` và `GROQ_API_KEY` được lưu dưới dạng Render secrets.
- [ ] Đặt `API_KEY` dài và ngẫu nhiên.
- [ ] `CORS_ORIGINS` chỉ chứa frontend thật.
- [ ] Review toàn bộ `data/memory-root/users` trước khi commit.
- [ ] Health check `/health` trả 200.
- [ ] Test một cuộc gọi nhiều turn và xác nhận `facts.md` xuất hiện trên disk.
- [ ] Giữ một Render instance/Uvicorn worker.
- [ ] Không bật `ENABLE_DEBUG_RESPONSE` trên production.
