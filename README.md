# Synee AI — Vietnamese Telesales Agent

> **SUDO CODE 2026 Project** · Hệ thống tư vấn bán hàng bằng tiếng Việt tích hợp Text Chat, nhận dạng giọng nói cục bộ (ASR), Voice realtime và Self-learning.

Agent sử dụng dữ liệu sản phẩm, CRM, tồn kho và chính sách từ PostgreSQL & Vector Store để tư vấn khách hàng, thực hiện nghiệp vụ qua MCP và lưu trữ ngữ cảnh cho các lần chăm sóc tiếp theo.

## Tài liệu 

Tài liệu mô tả kiến trúc hệ thống và kết quả đánh giá hiệu năng (benchmark) được tổng hợp tại: [Link](https://drive.google.com/drive/folders/1XrpHdxwW4ANGoQY0pMw_DpifY_E0WPoH?usp=drive_link)

## Mục lục

- [1. Tính năng chính](#1-tính-năng-chính)
- [2. Cấu trúc dự án](#2-cấu-trúc-dự-án)
- [3. Khởi chạy nhanh với Docker (Khuyên dùng)](#3-khởi-chạy-nhanh-với-docker-khuyên-dùng)
- [4. Cài đặt & Chạy thủ công (Windows PowerShell)](#4-cài-đặt--chạy-thủ-công-windows-powershell)
  - [4.1. Cài đặt môi trường & Biến cấu hình](#41-cài-đặt-môi-trường--biến-cấu-hình)
  - [4.2. Khởi tạo Database & Dữ liệu](#42-khởi-tạo-database--dữ-liệu)
  - [4.3. Khởi động từng thành phần](#43-khởi-động-từng-thành-phần)
- [5. Tính năng mở rộng](#5-tính-năng-mở-rộng)
  - [5.1. Self-learning](#51-self-learning)
  - [5.2. Real-time Voice (Gemini Live)](#52-real-time-voice-gemini-live)
- [6. Benchmark & Đánh giá](#6-benchmark--đánh-giá)
  - [6.1. Chuẩn bị chấm chéo BTC M1](#61-chuẩn-bị-chấm-chéo-btc-m1)
  - [6.2. Chạy hai cấu hình và chấm điểm](#62-chạy-hai-cấu-hình-và-chấm-điểm)
  - [6.3. Chấm cùng ASR theo quy trình BTC](#63-chấm-cùng-asr-theo-quy-trình-btc)

---

## 1. Tính năng chính

| Chức năng | Mô tả |
| :--- | :--- |
| **Chat tư vấn** | Nhắn tin và tra cứu danh sách, giá, biến thể, tồn kho sản phẩm từ PostgreSQL. Agent dùng MCP để tra CRM, khuyến mãi, chính sách và xử lý nghiệp vụ (tạo đơn, hẹn gọi lại) theo quyền được cấp. |
| **Tải file ghi âm** | Chạy Zipformer trên CPU để chuyển file audio thành văn bản; transcript và phản hồi xuất hiện trong cùng cuộc chat. |
| **Voice realtime** | Trò chuyện qua microphone bằng Gemini Live, hiển thị transcript và hỗ trợ ngắt lời *(công cụ agent ở chế độ chỉ đọc)*. |
| **Bộ nhớ khách hàng** | Lưu thông tin đã biết từ các lần tư vấn trước và tạo **Call Brief** để tiếp tục cuộc gọi. |
| **Tài khoản & Lịch sử** | Đăng ký, đăng nhập, xem lại hội thoại và gửi phản hồi. Tài khoản **Salesman** có trang xem lịch sử riêng. |
| **Self-learning** | Rút ra bài học từ hội thoại sau khi kết thúc phiên; các bài học đã duyệt được áp dụng cho những phiên chat mới. |
| **Benchmark** | Chạy kịch bản text/audio, so sánh chế độ có/không có bộ nhớ, đo chất lượng tư vấn, độ trễ và lỗi nhận dạng (WER/CER). |

> [!NOTE]
> Giỏ hàng, checkout và thanh toán trên storefront là luồng demo. Nghiệp vụ đơn hàng do agent thực hiện qua MCP với dữ liệu từ PostgreSQL.

---

## 2. Cấu trúc dự án

```text
.
├── src/
│   ├── telesale_agent/   # FastAPI, DeepAgent, ASR, hội thoại, bộ nhớ và voice
│   ├── mcp_servers/      # Công cụ MCP tra dữ liệu, policy và nghiệp vụ
│   ├── web/              # Frontend Next.js / React
│   ├── self_agent/       # Luồng self-learning và công cụ đánh giá bài học
│   └── eval/             # Script chạy benchmark và chấm điểm kết quả
├── scripts/              # Lệnh khởi động, migration, ingest policy, tải ASR
├── dataset/
│   ├── organizer/        # Policy, dữ liệu RAG, schema và bộ chấm tham chiếu BTC
│   ├── transcript/       # Kịch bản M1/M2, bộ chọn Coverage30 và pipeline sinh lời thoại
│   │   └── src/stage-1/input/catalog/ # Dữ liệu catalog/CRM dùng để seed database
│   ├── text-to-speech/   # Pipeline sinh audio M1 bằng TTS và trộn nhiễu nền
│   ├── audio/            # Notebook thử nghiệm TTS và phân tích dữ liệu giọng nói
│   └── test_data_btc/    # Audio mẫu D01–D04, transcript, alignment và manifest
├── data/memory-root/     # Hướng dẫn agent và file bộ nhớ khách hàng
├── tests/                # Kiểm thử backend
└── docs/                 # Tài liệu kiến trúc và triển khai
```

---

## 3. Khởi chạy nhanh với Docker (Khuyên dùng)

Chỉ cần **Git** và **Docker Desktop** (chế độ **Linux containers**) — không cần cài đặt Python, Node.js hay PostgreSQL trên máy.

> [!TIP]
> Nếu dùng Docker, bạn có thể **bỏ qua toàn bộ Mục 4**.

### Bước 1: Tạo file `.env`

Mở PowerShell tại thư mục gốc repository và chạy:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Mở `.env`, thay `GOOGLE_API_KEY` bằng key Gemini thật, kiểm tra quyền gọi `LLM_MODEL`, và giữ `API_KEY` của backend trống cho web local.

### Bước 2: Khởi động hệ thống

```powershell
docker compose up --build -d
```

Compose sẽ tự động:
1. Chạy PostgreSQL 16 và chờ DB sẵn sàng.
2. Tạo schema, seed catalog/CRM và nạp policy vào Chroma.
3. Khởi động Backend (kèm MCP) và Frontend (chỉ bật sau khi Backend qua health check).

### Bước 3: Truy cập & Kiểm tra

| Dịch vụ | Đường dẫn | Ghi chú |
| :--- | :--- | :--- |
| **Trang Chat** | http://localhost:3000/ai-chat | Giao diện tư vấn chính |
| **Frontend** | http://localhost:3000 | Storefront & tài khoản |
| **Backend API** | http://localhost:8000 | REST API |
| **Health Check** | http://localhost:8000/health | Kiểm tra trạng thái server |
| **Swagger UI** | http://localhost:8000/docs | Tài liệu API tương tác |


Kiểm tra Next.js tải đủ catalog và dữ liệu trang chi tiết từ backend (không chỉ kiểm tra HTTP 200):

```powershell
docker compose exec -T web node --test tests/docker-catalog.mjs
```

### Lệnh quản lý Docker thường dùng

```powershell
# Kiểm tra trạng thái các container (init kết thúc với mã 0 là bình thường)
docker compose ps -a

# Xem tiến trình nạp dữ liệu hoặc lỗi khởi động (Ctrl+C để thoát)
docker compose logs -f init backend web

# Tắt toàn bộ hệ thống nhưng vẫn giữ dữ liệu trong volumes
docker compose down
```

<details>
<summary><strong>Chi tiết về Docker Volumes, Network & Tùy chọn mở rộng</strong></summary>

- **Dữ liệu & Volumes:** PostgreSQL, Chroma, bộ nhớ khách hàng và cache model nằm trong Docker volumes. Compose dùng DB và Chroma riêng trong Docker, không tự nhập dữ liệu từ `telesale_pgdata` hay `data/chroma_db/`. Memory chỉ được tạo bởi `scripts/migrate_memory.py` từ `dataset/transcript/src/stage-1/input/catalog/crm_seed.json`, trong volume `customer_memory_crm`; không copy hay bind-mount `data/memory-root/users/` trên máy. Image chỉ chứa ba file hướng dẫn agent (`agent.md`, `soul.md`, `tools.md`). Chạy lại sẽ giữ nguyên memory đã có và chỉ tạo thư mục cho khách chưa được seed. Volume memory cũ của cấu hình trước không còn được dùng. Nếu phát hiện catalog/CRM bị seed dở, bước `init` sẽ dừng để kiểm tra thay vì tự xóa dữ liệu.
- **Cổng & DB:** PostgreSQL mở tại `127.0.0.1:5432` trên máy; database/user `telesale`, password `telesale_dev_password`, SSL tắt. Trong mạng Docker, backend dùng `postgres:5432`. Đảm bảo các cổng `5432`, `8000`, `3000` không bị dịch vụ khác sử dụng.
- **URL backend cho web:** Trình duyệt dùng `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`; Next.js tải catalog phía server và chuyển tiếp API qua `API_BACKEND_URL=http://backend:10000`. Image web giữ biến nội bộ này cả khi build lẫn khi chạy, vì `localhost` trong container web không trỏ đến backend.
- **Tùy chọn tích hợp sẵn trong image Docker:**
  - **Upload ghi âm:** Thêm `DOWNLOAD_ASR_MODEL=true` vào `.env` rồi chạy lại `docker compose up --build -d` để `init` tải Zipformer vào volume.
  - **Voice realtime:** Đặt `REALTIME_VOICE_ENABLED=true`, kiểm tra quyền gọi model Live, rồi chạy lại lệnh khởi động (không cần tải Zipformer).
  - **Self-learning:** Cấu hình bucket/khóa S3 (xem bảng biến ở mục 4.1), đặt `KNOWLEDGE_GAP_LOOP_ENABLED=true` và `DEEPAGENT_CHECKPOINT_SCOPE=turn`, rồi chạy lại lệnh khởi động.

</details>

---

## 4. Cài đặt & Chạy thủ công (Windows PowerShell)

Dành cho phát triển trực tiếp trên máy: PostgreSQL chạy trong Docker, Chroma lưu trên ổ đĩa, Backend và Frontend chạy ở cổng `8000` và `3000`.

**Yêu cầu:** **Git**, **Python 3.11+** *(lệnh mẫu dùng 3.12)*, **Node.js 24**, và **Docker Desktop** (Linux containers).

### 4.1. Cài đặt môi trường & Biến cấu hình

Chạy từ thư mục gốc repository:

```powershell
# 1. Tạo virtualenv & cài đặt backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# 2. Cài đặt frontend
Set-Location src/web
npm.cmd ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
Set-Location ../..
```

#### Cấu hình Backend (`.env` ở gốc repo)

Với bản clone mới, bạn chỉ cần điền `GOOGLE_API_KEY` và kiểm tra quyền gọi `LLM_MODEL`. Nếu giữ lại `.env` cũ, hãy đối chiếu các biến dưới đây (khi sửa `.env`, cần khởi động lại backend):

| Biến | Giá trị khuyến nghị cho Local |
| :--- | :--- |
| `GOOGLE_API_KEY` | **Thay bằng key Gemini thật.** Giữ ngoài Git. |
| `LLM_PROVIDER`, `LLM_MODEL` | `gemini` và `gemini-3.6-flash` (model dùng cho Chat). |
| `NLU_THINKING_LEVEL`, `DEEPAGENT_THINKING_LEVEL` | `minimal` (mức suy luận cho bước hiểu yêu cầu và agent trả lời). |
| `DATABASE_URL` | Giữ nguyên mẫu (`postgresql+psycopg2://telesale:telesale_dev_password@localhost:5432/telesale?sslmode=disable`). |
| `ENABLE_VECTOR_RAG`, `KNOWLEDGE_BACKEND`, `CHROMA_DB_DIR` | `true`, `chroma`, `data/chroma_db`. |
| `WEB_ORIGIN`, `CORS_ORIGINS` | `http://localhost:3000`. |
| `SESSION_TTL_DAYS`, `SESSION_COOKIE_SECURE` | `7` và `false` (để cookie đăng nhập hoạt động qua HTTP local). |
| `CUSTOMER_MEMORY_BACKEND` | `file` (nếu lấy `.env` từ bản deploy, đổi về `file` để lưu cục bộ). |
| `API_KEY` | Để trống cho web local (khóa truy cập API riêng, khác key Gemini). |

<details>
<summary><strong>Các biến môi trường nâng cao & tùy chọn trong <code>.env.example</code></strong></summary>

| Nhóm biến | Mục đích & Cấu hình mặc định |
| :--- | :--- |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_WORKSPACE_ID` | Giữ `false` và bỏ trống. Điền đầy đủ nếu bật LangSmith tracing. |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE`, `PINECONE_CLOUD`, `PINECONE_REGION`, `PINECONE_EMBEDDING_MODEL` | Giữ comment khi chạy local bằng Chroma. Dùng khi truy xuất/tạo index policy trên Pinecone. |
| `ASR_MODEL_DIR`, `ASR_NUM_THREADS` | Đường dẫn model Zipformer trong `models/` và `2` luồng CPU. |
| `ASR_MAX_UPLOAD_MB`, `ASR_MAX_DURATION_SECONDS` | Giới hạn file ghi âm: mặc định `25` MB và `120` giây. |
| `ASR_FFMPEG_PATH` | Giữ comment để dùng FFmpeg đi kèm `imageio-ffmpeg`, hoặc trỏ tới `ffmpeg.exe` riêng. |
| `REALTIME_VOICE_ENABLED` | Giữ `false` khi chạy Chat; đổi thành `true` khi bật Voice realtime. |
| `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_API_VERSION`, `GEMINI_LIVE_VOICE` | `gemini-3.8-live`, `v1beta`, `Kore`. |
| `REALTIME_TOOLS_MODE`, `REALTIME_ALLOWED_ORIGINS` | `read_only` và danh sách origin local (`http://localhost:3000`). |
| `REALTIME_MAX_SESSIONS`, `REALTIME_AUDIO_QUEUE_LIMIT` | `4` phiên đồng thời, tối đa `128` khung audio trong hàng đợi. |
| `REALTIME_SESSION_IDLE_TIMEOUT_SECONDS`, `REALTIME_SESSION_MAX_SECONDS`, `REALTIME_TOOL_TIMEOUT_SECONDS` | `120`s idle, `600`s tối đa/phiên, `25`s timeout mỗi lần gọi tool. |
| `KNOWLEDGE_GAP_LOOP_ENABLED` | Giữ `false` ở lần chạy đầu; đổi `true` sau khi cấu hình S3 cho Self-learning. |
| `AGENT_MEMORY_BUCKET`, `CUSTOMER_MEMORY_BUCKET` | Bucket S3 lưu bài học (hệ thống fallback sang `CUSTOMER_MEMORY_BUCKET` nếu có). |
| `AGENT_MEMORY_PREFIX`, `AGENT_LEARNING_RUNTIME_PREFIX` | Giữ theo mẫu (đường dẫn trong bucket cho bài học và kết quả xử lý). |
| `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Thông tin xác thực S3 khi bật Self-learning (Chat cơ bản lưu file local). |

</details>

#### Cấu hình Frontend (`src/web/.env.local`)

Giữ nguyên cả hai dòng từ mẫu (nếu đổi cổng backend, sửa cả hai dòng và khởi động lại frontend):

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
API_BACKEND_URL=http://127.0.0.1:8000
```

- `NEXT_PUBLIC_API_BASE_URL`: URL API mà trình duyệt gọi cho catalog, chat khách và Voice.
- `API_BACKEND_URL`: Đích mà Next.js chuyển tiếp request nội bộ (đăng nhập, lịch sử chat).

---

### 4.2. Khởi tạo Database & Dữ liệu

Mở **Docker Desktop**, đảm bảo cổng `5432` còn trống (hoặc đang dùng bởi container `telesale-postgres`), sau đó chạy từ gốc repo:

```powershell
.\scripts\setup_local_data.ps1
```

Khi thấy thông báo `Local data ready` là hoàn tất. Script sẽ tự động tạo/bật PostgreSQL 16 (volume `telesale_pgdata`) và chạy tuần tự:

| Script | Mục đích |
| :--- | :--- |
| `migrate_catalog.py` | Tạo bảng và seed catalog, tồn kho, khuyến mãi, CRM, đơn mẫu từ `dataset/transcript/src/stage-1/input/catalog/`. Nếu DB đã seed, chỉ chạy `--orders-only` để bổ sung cột đơn hàng còn thiếu. |
| `migrate_app_data.py` | Tạo/cập nhật schema đăng nhập, phiên tài khoản, lịch sử Chat, feedback và vai trò Salesman. |
| `migrate_voice.py` | Tạo journal ghi lượt hội thoại Voice. |
| `migrate_learning.py` | Tạo bảng lưu phiên, lượt chat và hàng đợi cho Self-learning. |
| `migrate_memory.py` | Tạo memory từ `dataset/transcript/src/stage-1/input/catalog/crm_seed.json`: hồ sơ, các phiên cũ và lịch sử đơn hàng. Chỉ tạo cho khách chưa có thư mục, không ghi đè memory hiện có. Docker tự chạy ở bước `init`; chạy thủ công dùng `CUSTOMER_MEMORY_ROOT` hoặc mặc định `data/memory-root/users/`. |
| `ingest_policy.py --if-empty` | Nạp Markdown từ `dataset/organizer/policy/` vào `data/chroma_db/`. *(Lần đầu cần mạng để tải embedding model).* |

> [!NOTE]
> Có thể chạy lại `.\scripts\setup_local_data.ps1` nếu cần bật lại container hoặc hoàn tất bước bị gián đoạn. Nếu catalog bị seed dở, script sẽ dừng để bạn kiểm tra DB trước khi chạy tiếp.

Chạy riêng migration memory khi cần (không cần DB hay gọi LLM):

```powershell
# Trên máy; dùng --memory-root nếu muốn chọn một thư mục mới.
.\.venv\Scripts\python.exe scripts\migrate_memory.py
# Trong Docker; dùng volume riêng đã cấu hình trong Compose.
docker compose run --rm --no-deps init python scripts/migrate_memory.py
```

#### Tùy chọn: Tải model ASR (để upload file ghi âm)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\download_asr_model.py
```

<details>
<summary><strong>Các script migration dữ liệu cũ (chỉ dùng khi nâng cấp dữ liệu legacy)</strong></summary>

- `migrate_order_lines.py`: Bổ sung cột `orders.lines`.
- `migrate_customer_sessions_to_memory.py`: Chuyển phiên khách cũ sang bộ nhớ file.
- `migrate_memory_to_object_storage.py`: Chuyển bộ nhớ file lên object storage.

</details>

---

### 4.3. Khởi động từng thành phần

1. **Bật PostgreSQL** *(nếu chưa bật từ bước 4.2)*:

```powershell
docker start telesale-postgres
docker exec telesale-postgres pg_isready -h 127.0.0.1 -U telesale -d telesale
```

Chờ kết quả `accepting connections` *(thử lại sau vài giây nếu DB chưa sẵn sàng)*. Chroma đọc trực tiếp từ `data/chroma_db/`.

2. **Chạy Backend — Terminal 1** *(tại gốc repo, giữ terminal này mở)*:

```powershell
.\scripts\start_api.ps1 -Reload
```

<details>
<summary>Lệnh thay thế nếu PowerShell chặn chạy file <code>.ps1</code></summary>

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --env-file .env --host 127.0.0.1 --port 8000 --reload
```

</details>

Chờ Uvicorn báo `Application startup complete`. API chạy ở `http://localhost:8000` và tự khởi động MCP.

3. **Chạy Frontend — Terminal 2** *(tại gốc repo)*:

```powershell
Set-Location src/web
npm.cmd run dev -- --port 3000
```

4. **Kiểm tra nhanh sau khi bật:**
   - [`/health`](http://localhost:8000/health) trả về `status: ok`
   - [API catalog](http://localhost:8000/api/catalog/products) có dữ liệu
   - Mở [trang Chat](http://localhost:3000/ai-chat), gửi một tin nhắn để xác nhận kết nối LLM (hoặc xem [Swagger UI](http://localhost:8000/docs))

5. **Dừng hệ thống:** Nhấn `Ctrl+C` ở cả hai terminal, sau đó chạy `docker stop telesale-postgres` nếu muốn tắt DB (dữ liệu PostgreSQL và policy vẫn được giữ nguyên).

---

## 5. Tính năng mở rộng

### 5.1. Self-learning

Schema đã được tạo ở mục 4.2. Để kích hoạt:

1. Cài thêm dependencies:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[learning]"
   ```
2. Điền cấu hình bucket S3 trong `.env` (mục 4.1) và đặt:
   - `KNOWLEDGE_GAP_LOOP_ENABLED=true`
   - `DEEPAGENT_CHECKPOINT_SCOPE=turn`
3. Khởi động lại backend với **1 worker**.

Sau vài lượt Chat, chọn **Cuộc trò chuyện mới → Bắt đầu mới** để kết thúc phiên và đưa vào hàng đợi học. Theo dõi qua log backend hoặc bảng `learning_jobs`; bài học được duyệt sẽ có hiệu lực từ phiên Chat sau.

### 5.2. Real-time Voice (Gemini Live)

Schema journal đã được tạo ở mục 4.2. Để kích hoạt:

1. Cài thêm dependencies:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[realtime]"
   ```
2. Kiểm tra `GOOGLE_API_KEY` có quyền gọi model Live và đặt `REALTIME_VOICE_ENABLED=true` trong `.env`.
3. Khởi động lại backend với **1 worker**.
4. Mở [trang Chat](http://localhost:3000/ai-chat), chọn **Voice → Bắt đầu trò chuyện** và cấp quyền microphone.

---

## 6. Benchmark & Đánh giá

Eval M1 chạy các lượt khách trong kịch bản qua cùng một pipeline tư vấn, ghi một dòng JSONL cho mỗi lượt phản hồi của agent. Hai cấu hình dùng cùng kịch bản, model, CRM và công cụ nghiệp vụ.

- `baseline_no_memory` tắt bộ nhớ học được giữa các cuộc gọi. Agent vẫn giữ lịch sử trong cuộc gọi hiện tại.
- `full` lưu bộ nhớ khách hàng vào thư mục riêng của lần chạy và dùng lại giữa các cuộc gọi trong cùng kịch bản.

Trace chứa câu hỏi, dữ kiện dùng lại, phát ngôn có thể kiểm chứng, tool calls và latency. File `*.metadata.json` ghi cấu hình chạy, phạm vi dữ liệu và kết quả kiểm tra trace. Bộ chấm BTC dùng hai trace để tính Repeat-Question Rate (RQR), Context Carryover Rate (CCR), Task Success Rate (TSR), Hallucination Rate, Calls-to-Close và các chỉ số latency. Runner text đo TTFT, Total và Call Brief, còn TTFA để trống vì cần đầu ra âm thanh.

### 6.1. Chuẩn bị chấm chéo BTC M1

Mở PowerShell ở gốc repo và kích hoạt môi trường đã cài backend ở mục 4.1 bằng `& .\.venv\Scripts\Activate.ps1`. Runner gọi pipeline trực tiếp, có thể chạy khi Web và API đang tắt.

- Trỏ `$datasetDir` tới thư mục chỉ chứa các JSON kịch bản. Dùng `test_set/public_sample` của gói đầy đủ để thử, rồi thay bằng thư mục bộ ẩn khi BTC cung cấp. Runner lấy `scenario_id` bên trong JSON.
- Trỏ `$btcDir` tới gói BTC có bản `eval/reference_eval.py` dùng cho đợt chấm. Dùng đúng script từ gói đó để tái lập điểm chấm chéo.
- Đặt API key trong `.env` theo [mẫu biến môi trường](.env.example). Eval mặc định dùng `gemini-3.6-flash`. Đặt `EVAL_LLM_PROVIDER`, `EVAL_LLM_MODEL` và `EVAL_LLM_ENDPOINT` nếu BTC cấp cấu hình khác, rồi dùng cùng cấu hình cho cả hai lượt.
- Chuẩn bị hai database PostgreSQL dành riêng cho eval, mỗi database có cùng dữ liệu seed catalog và CRM. Với database trống, đặt `DATABASE_URL` trỏ tới database cần seed rồi chạy `python -X utf8 scripts/migrate_catalog.py`. Runner tạo đơn mẫu trong DB của cấu hình đang chạy và dọn các đơn nó đã tạo sau mỗi kịch bản.

### 6.2. Chạy hai cấu hình và chấm điểm

`run_eval.py` ở gốc repo nhận đúng ba tham số bắt buộc theo quy trình BTC gồm `--scenarios`, `--config` và `--out`. Thay các đường dẫn và chuỗi kết nối mẫu dưới đây bằng giá trị đã chuẩn bị.

```powershell
$datasetDir = 'D:\du-lieu\BTC\test_set\public_sample'
$btcDir = 'D:\du-lieu\BTC-cap-nhat-11-2026-v2'
$baselineDbUrl = 'postgresql+psycopg2://telesale:MAT_KHAU@127.0.0.1:5432/telesale_eval_baseline?sslmode=disable'
$fullDbUrl = 'postgresql+psycopg2://telesale:MAT_KHAU@127.0.0.1:5432/telesale_eval_full?sslmode=disable'
$runDir = Join-Path 'outputs/eval' ('btc-m1-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$baselineTrace = Join-Path $runDir 'baseline.jsonl'
$fullTrace = Join-Path $runDir 'full.jsonl'
$btcScorer = Join-Path $btcDir 'eval/reference_eval.py'

python run_eval.py --scenarios $datasetDir --config full --out $fullTrace --preflight-only
if ($LASTEXITCODE -ne 0) { throw 'Đầu vào eval chưa hợp lệ' }

$env:EVAL_DATABASE_URL = $baselineDbUrl
python run_eval.py --scenarios $datasetDir --config baseline_no_memory --out $baselineTrace
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra baseline.metadata.json và log của runner' }

$env:EVAL_DATABASE_URL = $fullDbUrl
python run_eval.py --scenarios $datasetDir --config full --out $fullTrace
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra full.metadata.json và log của runner' }

python -X utf8 $btcScorer --scenarios $datasetDir --trace $fullTrace --baseline $baselineTrace --out (Join-Path $runDir 'btc_report.json')
```

`--preflight-only` kiểm tra danh sách kịch bản, cuộc gọi và lượt khách trước khi chạy agent. Hai lệnh sinh trace mặc định chạy toàn bộ thư mục. Nếu benchmark nội bộ cần đếm đúng các lượt khách có sẵn trong JSON, thêm `--no-closing-turn` vào cả hai lệnh để bỏ lượt kết thúc tự động. Dùng thư mục output mới cho mỗi lần chạy.

### 6.3. Chấm cùng ASR theo quy trình BTC

Cài dependencies voice và tải Zipformer theo mục 4.2. Dùng `asr/ground_truth.json` của BTC và thư mục WAV tương ứng. Mỗi ID cần một WAV nguyên hội thoại, lưu theo dạng `<ID>.wav` hoặc `<ID>/<ID>.wav` trong thư mục audio.

```powershell
$groundTruth = Join-Path $btcDir 'asr/ground_truth.json'
$audioRoot = 'D:\du-lieu\BTC\audio'
$asrDir = Join-Path $runDir 'asr'

python -X utf8 src/eval/run_asr.py --ground-truth $groundTruth --audio-root $audioRoot --out $asrDir
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra ground truth, WAV và model ASR' }

python -X utf8 $btcScorer --scenarios $datasetDir --trace $fullTrace --baseline $baselineTrace --asr $asrDir --out (Join-Path $runDir 'btc_report_with_asr.json')
```

`run_asr.py` chạy nhận dạng cục bộ và xuất `ground_truth.json` cùng `hypotheses.json` cho tham số `--asr`. Đầu ra gồm bản chép và entity theo hội thoại. Để chấm entity theo lượt hoặc diarization, cần bổ sung kết quả phân đoạn tương ứng. Chấm thử bằng audio public D01–D04, rồi dùng ground truth và WAV của đợt chấm khi BTC cung cấp. Xem cách chạy benchmark nội bộ và đọc ngưỡng chất lượng, latency trong [tài liệu eval](src/eval/README.md).

### Các script benchmark khác

| Script | Mục đích sử dụng |
| :--- | :--- |
| `src/eval/run_benchmark.py` | Chạy riêng một kịch bản theo `--scenario-id` hoặc một nhóm theo `--limit` (đặt `--version benchmark_v1` hoặc tên chưa dùng). |
| `src/eval/run_parallel_benchmark.py` | Chạy benchmark text song song với nhiều worker. |
| `scripts/run_self_learning_two_rounds.ps1` | Chạy cùng kịch bản trước và sau khi học bài học *(truyền `-PythonExe .\.venv\Scripts\python.exe` để dùng đúng venv)*. |
