# SUDO CODE 2026 PROJECT

Synee AI là hệ thống tư vấn bán hàng bằng tiếng Việt. Agent dùng dữ liệu sản phẩm, CRM, tồn kho và chính sách để trả lời khách hàng, đồng thời lưu ngữ cảnh cho các lần tư vấn sau.

## 1. Các chức năng hiện có

| Chức năng | Có thể làm gì |
| --- | --- |
| Chat tư vấn | Nhắn tin và xem danh sách, giá, biến thể, tồn kho sản phẩm lấy từ PostgreSQL. Agent dùng MCP để tra CRM, khuyến mãi, chính sách và xử lý các yêu cầu nghiệp vụ như tạo đơn hoặc hẹn gọi lại theo quyền được cấp. |
| Tải file ghi âm | Zipformer chạy trên CPU để chuyển file audio thành văn bản. Transcript và phản hồi xuất hiện trong cùng cuộc chat. |
| Voice realtime | Trò chuyện qua microphone bằng Gemini Live, có transcript và hỗ trợ ngắt lời. Công cụ của agent trong Voice chỉ đọc. |
| Bộ nhớ khách hàng | Lưu thông tin đã biết từ các lần tư vấn trước và tạo Call Brief để tiếp tục cuộc gọi. |
| Tài khoản và lịch sử | Đăng ký, đăng nhập, xem lại hội thoại và phản hồi câu trả lời. Tài khoản Salesman có trang xem lịch sử riêng. |
| Self-learning | Sau khi kết thúc phiên, hệ thống có thể rút ra bài học từ hội thoại. Chat ở phiên mới có thể dùng các bài học đã duyệt. |
| Benchmark | Chạy kịch bản text hoặc audio, so sánh có/không có bộ nhớ, đo chất lượng tư vấn, độ trễ và lỗi nhận dạng. |

Giỏ hàng, checkout và thanh toán trên storefront là luồng demo. Nghiệp vụ đơn hàng do agent thực hiện qua MCP dùng dữ liệu PostgreSQL.

## 2. Cấu trúc thư mục

```text
src/
├── telesale_agent/       FastAPI, DeepAgent, ASR, hội thoại, bộ nhớ và voice
├── mcp_servers/          Công cụ tra dữ liệu, policy và nghiệp vụ
├── web/                  Frontend Next.js/React
├── self_agent/           Luồng self-learning và công cụ đánh giá bài học
└── eval/                 Script chạy benchmark và chấm kết quả
scripts/                  Lệnh khởi động, migration, ingest policy, tải ASR
dataset/
├── organizer/            JSON catalog/CRM và tài liệu policy gốc
└── main/                 Kịch bản đánh giá, manifest và file audio
data/memory-root/         Hướng dẫn agent và file bộ nhớ khách hàng
tests/                    Kiểm thử backend
docs/                     Tài liệu kiến trúc và triển khai
```

## 3. Hướng dẫn chạy

Hướng dẫn này dùng **Windows PowerShell**. PostgreSQL chạy trong Docker, Chroma lưu trên máy, backend và frontend chạy trực tiếp ở cổng `8000` và `3000`. Làm mục 3.1–3.2 lần đầu, sau đó dùng mục 3.3 mỗi khi mở lại project.

### 3.1. Setup môi trường

Cài **Git**, **Python 3.11+** (lệnh mẫu dùng 3.12), **Node.js 24** và **Docker Desktop** với Linux containers. Mở PowerShell ở gốc repo rồi chạy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Set-Location src/web
npm.cmd ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
Set-Location ../..
```

**Backend — `.env` ở gốc repo.** Với bản clone mới, bạn chỉ cần thay `GOOGLE_API_KEY` bằng key thật và kiểm tra key có quyền gọi `LLM_MODEL`. Các giá trị PostgreSQL và Chroma trong mẫu đã khớp với script ở mục 3.2. Nếu đã có `.env` từ cấu hình cũ, đối chiếu các dòng bên dưới vì lệnh copy giữ nguyên file hiện có.

| Biến | Giá trị cần điền hoặc giữ khi chạy local |
| --- | --- |
| `GOOGLE_API_KEY` | **Thay placeholder bằng key Gemini thật.** Dùng ở backend, giữ ngoài Git. |
| `LLM_PROVIDER`, `LLM_MODEL` | Giữ `gemini` và `gemini-3.6-flash` nếu key dùng được model này. Đây là model cho Chat. |
| `NLU_THINKING_LEVEL`, `DEEPAGENT_THINKING_LEVEL` | Giữ `minimal`. Hai biến điều khiển mức suy luận của bước hiểu yêu cầu và agent trả lời. |
| `DATABASE_URL` | Giữ nguyên dòng mẫu. URL dùng driver `psycopg2`, user `telesale`, mật khẩu local `telesale_dev_password`, database `telesale` trên `localhost:5432` với `sslmode=disable`. |
| `ENABLE_VECTOR_RAG`, `KNOWLEDGE_BACKEND`, `CHROMA_DB_DIR` | Giữ `true`, `chroma` và `data/chroma_db`. Đây là công tắc tra policy, loại kho và thư mục kho. |
| `WEB_ORIGIN`, `CORS_ORIGINS` | Giữ `http://localhost:3000`. Một biến xác định origin cho xác thực, biến còn lại cho phép web gọi API từ origin đó. |
| `SESSION_TTL_DAYS`, `SESSION_COOKIE_SECURE` | Giữ `7` ngày và `false` để cookie đăng nhập hoạt động qua HTTP local. |

Nếu lấy `.env` từ bản deploy, đặt `CUSTOMER_MEMORY_BACKEND=file` để lưu bộ nhớ khách hàng trên máy. Giữ `API_KEY` của backend trống cho web local; đây là khóa truy cập API riêng, khác key Gemini. Khi đổi `.env`, khởi động lại backend.

**Các nhóm biến còn lại trong `.env.example`:**

| Biến | Dùng để làm gì |
| --- | --- |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_WORKSPACE_ID` | Giữ `false` và bỏ trống các dòng còn lại. Nếu bật tracing, cung cấp key, tên project và ID workspace khi cần. |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE` | Giữ comment. Đây là khóa, tên index và namespace để truy xuất policy khi dùng Pinecone. |
| `PINECONE_CLOUD`, `PINECONE_REGION`, `PINECONE_EMBEDDING_MODEL` | Giữ comment. Script Pinecone dùng các giá trị này để chọn cloud, vùng và model embedding khi tạo index. |
| `ASR_MODEL_DIR`, `ASR_NUM_THREADS` | Giữ đường dẫn model Zipformer trong `models/` và `2` luồng CPU. Chỉ tải model nếu muốn gửi file ghi âm (mục 3.2). |
| `ASR_MAX_UPLOAD_MB`, `ASR_MAX_DURATION_SECONDS` | Giới hạn mỗi file ghi âm, mặc định `25` MB và `120` giây. |
| `ASR_FFMPEG_PATH` | Giữ comment để dùng FFmpeg đi kèm `imageio-ffmpeg`. Điền đường dẫn đến `ffmpeg.exe` nếu muốn dùng bản riêng. |
| `REALTIME_VOICE_ENABLED` | Giữ `false` khi chạy Chat. Đổi thành `true` theo mục 3.5 nếu muốn gọi bằng microphone. |
| `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_API_VERSION`, `GEMINI_LIVE_VOICE` | Giữ `gemini-3.8-live`, `v1beta` và `Kore`. Đây là model, phiên bản API và giọng phát cho Voice. |
| `REALTIME_TOOLS_MODE`, `REALTIME_ALLOWED_ORIGINS` | Giữ `read_only` và danh sách origin local trong mẫu. Script start backend dùng `http://localhost:3000`. |
| `REALTIME_MAX_SESSIONS`, `REALTIME_AUDIO_QUEUE_LIMIT` | Giữ `4` phiên đồng thời và tối đa `128` khung audio trong hàng đợi. |
| `REALTIME_SESSION_IDLE_TIMEOUT_SECONDS`, `REALTIME_SESSION_MAX_SECONDS`, `REALTIME_TOOL_TIMEOUT_SECONDS` | Giữ `120` giây không hoạt động, `600` giây tối đa mỗi phiên và `25` giây cho mỗi lần gọi tool. |
| `KNOWLEDGE_GAP_LOOP_ENABLED` | Giữ `false` cho lần chạy đầu. Đổi thành `true` sau khi cấu hình bucket ở mục 3.4. |
| `AGENT_MEMORY_BUCKET`, `CUSTOMER_MEMORY_BUCKET` | Chỉ cần khi cấu hình lưu qua S3. Điền bucket cho bài học vào `AGENT_MEMORY_BUCKET`, hoặc hệ thống dùng `CUSTOMER_MEMORY_BUCKET` nếu đã cấu hình. |
| `AGENT_MEMORY_PREFIX`, `AGENT_LEARNING_RUNTIME_PREFIX` | Giữ theo mẫu. Đây là hai đường dẫn trong bucket cho bài học và kết quả xử lý. |
| `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Khi bật self-learning, điền endpoint nếu nhà cung cấp có endpoint riêng, vùng và cặp khóa S3 của bucket. Chat cơ bản lưu bộ nhớ bằng file local. |

**Frontend — `src/web/.env.local`.** Giữ cả hai dòng từ mẫu:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
API_BACKEND_URL=http://127.0.0.1:8000
```

`NEXT_PUBLIC_API_BASE_URL` là URL API mà trình duyệt gọi cho catalog, chat khách và Voice. `API_BACKEND_URL` là đích mà Next.js chuyển tiếp request nội bộ như đăng nhập và lịch sử chat. Chỉ đặt URL trong `NEXT_PUBLIC_*`. Nếu đổi cổng backend, sửa cả hai dòng và khởi động lại frontend.

### 3.2. Cài đặt data

Mở **Docker Desktop** và chờ Docker Engine chạy. Đảm bảo cổng `5432` còn trống hoặc đang dùng bởi container `telesale-postgres` của project, sau đó chạy từ gốc repo:

```powershell
.\scripts\setup_local_data.ps1
```

Script tạo và bật PostgreSQL 16 với volume `telesale_pgdata`, chờ DB nhận kết nối rồi chạy các bước sau:

| Script | Mục đích |
| --- | --- |
| `migrate_catalog.py` | Tạo bảng và seed từ `dataset/organizer/catalog/` gồm catalog, tồn kho, khuyến mãi, CRM và đơn mẫu. Nếu DB đã seed, chỉ chạy `--orders-only` để bổ sung cột đơn hàng còn thiếu. |
| `migrate_app_data.py` | Tạo hoặc cập nhật schema đăng nhập, phiên tài khoản, lịch sử Chat, feedback và vai trò Salesman. |
| `migrate_voice.py` | Tạo journal ghi lượt hội thoại Voice. |
| `migrate_learning.py` | Tạo bảng lưu phiên, lượt chat và hàng đợi cho self-learning. |
| `ingest_policy.py --if-empty` | Nạp Markdown từ `dataset/organizer/policy/` vào `data/chroma_db/`. Lần đầu cần mạng để tải embedding model. |

Thấy `Local data ready` là xong. Chạy lại cùng lệnh nếu cần bật lại container hoặc hoàn tất một bước bị gián đoạn. Script dùng lại catalog đã seed và collection policy đã có dữ liệu. Nếu phát hiện catalog seed dở, script dừng để bạn kiểm tra DB trước khi chạy tiếp.

Các script `migrate_order_lines.py`, `migrate_customer_sessions_to_memory.py` và `migrate_memory_to_object_storage.py` dành cho dữ liệu cũ: lần lượt bổ sung cột `orders.lines`, chuyển phiên khách cũ sang bộ nhớ file, và chuyển bộ nhớ file lên object storage.

**Tùy chọn: upload ghi âm.** Để gửi file audio trong Chat, tải Zipformer một lần:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\download_asr_model.py
```

[Xem cách thử riêng ASR local](docs/deployment/local_voice_input.md).

### 3.3. Khởi động hệ thống

**Data.** Nếu vừa chạy mục 3.2, PostgreSQL đã bật. Những lần sau, mở Docker Desktop rồi chạy:

```powershell
docker start telesale-postgres
docker exec telesale-postgres pg_isready -h 127.0.0.1 -U telesale -d telesale
```

Chờ `accepting connections`. Nếu chưa sẵn sàng, thử lại lệnh `pg_isready` sau vài giây. Chroma đọc trực tiếp thư mục `data/chroma_db/`.

**Backend — terminal 1 ở gốc repo.**

```powershell
.\scripts\start_api.ps1 -Reload
```

Giữ terminal này mở. Chờ Uvicorn báo `Application startup complete`; lần đầu Chroma có thể mất thêm thời gian nạp embedding model. API chạy ở `http://localhost:8000` và tự khởi động MCP. Có thể thay script bằng lệnh sau nếu PowerShell chặn chạy file `.ps1`:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --env-file .env --host 127.0.0.1 --port 8000 --reload
```

**Frontend — terminal 2 ở gốc repo.**

```powershell
Set-Location src/web
npm.cmd run dev -- --port 3000
```

Mở [localhost:3000](http://localhost:3000) hoặc [trang Chat](http://localhost:3000/ai-chat). Kiểm tra lần lượt [`/health`](http://localhost:8000/health) trả `status: ok`, [API catalog](http://localhost:8000/api/catalog/products) có dữ liệu, rồi gửi một tin nhắn trên web để kiểm tra LLM. [Swagger UI](http://localhost:8000/docs) có danh sách API.

Để dừng, nhấn `Ctrl+C` ở hai terminal rồi chạy `docker stop telesale-postgres` nếu muốn tắt DB. Dữ liệu PostgreSQL vẫn nằm trong volume và policy vẫn nằm trên ổ đĩa.

### 3.4. Bật Self-learning

Schema đã được tạo ở mục 3.2. Cài thêm `.\.venv\Scripts\python.exe -m pip install -e ".[learning]"`, điền cấu hình bucket S3 ở mục 3.1 và đặt `KNOWLEDGE_GAP_LOOP_ENABLED=true`, `DEEPAGENT_CHECKPOINT_SCOPE=turn`.

Khởi động lại backend với một worker. Sau vài lượt Chat, chọn **Cuộc trò chuyện mới → Bắt đầu mới** để kết thúc phiên và đưa phiên vào hàng đợi học. Xem log backend hoặc bảng `learning_jobs`. Bài học được duyệt có thể được dùng từ phiên Chat sau. [Chi tiết self-learning](src/self_agent/README.md).

### 3.5. Bật real-time voice

Schema journal đã được tạo ở mục 3.2. Cài thêm `.\.venv\Scripts\python.exe -m pip install -e ".[realtime]"`, kiểm tra key Gemini có quyền gọi model Live ở mục 3.1 và đặt `REALTIME_VOICE_ENABLED=true`.

Khởi động lại backend với một worker. Mở [trang Chat](http://localhost:3000/ai-chat), chọn **Voice → Bắt đầu trò chuyện** rồi cấp quyền microphone. [Chi tiết Gemini Live](docs/deployment/gemini_live.md).

### 3.6. Script chạy benchmark

Chạy từ gốc repo. Các runner gọi pipeline trực tiếp nên có thể chạy khi web và API đang tắt. Các bài test tư vấn cần DB dev đã seed và API key của model đánh giá. Dùng DB riêng cho benchmark vì một số kịch bản có thể tạo đơn test. Benchmark audio cần thêm model Zipformer từ mục 3.2.

**Thử một kịch bản text trước:**

```powershell
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --input-kinds text --limit 1
```

**Kiểm tra dữ liệu, đo riêng ASR hoặc chạy bộ text + audio:**

```powershell
# Kiểm tra kịch bản, manifest và WAV trước khi gọi LLM.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --preflight-only

# Đo WER/CER của Zipformer local, không gọi LLM.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --asr-only

# Chạy 40 kịch bản text và audio, so sánh hai chế độ bộ nhớ.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --limit 40
```

Dữ liệu mặc định nằm ở `dataset/main/scenarios_complete/`, `dataset/main/audio/` và `dataset/main/manifest.jsonl`. Kết quả nằm trong `outputs/benchmark/<version>/`. Dùng `--llm-provider` và `--llm-model` nếu cần chọn model khác với mặc định của runner.

| Script | Khi nào dùng |
| --- | --- |
| [run_benchmark.py](src/eval/run_benchmark.py) | Chạy riêng một kịch bản theo `--scenario-id` hoặc một nhóm theo `--limit`. Đặt `--version benchmark_v1` hoặc một tên tương tự chưa dùng. |
| [run_parallel_benchmark.py](src/eval/run_parallel_benchmark.py) | Chạy benchmark text với nhiều worker. |
| [run_self_learning_two_rounds.ps1](scripts/run_self_learning_two_rounds.ps1) | Chạy cùng kịch bản trước và sau khi học bài học. Truyền `-PythonExe .\.venv\Scripts\python.exe` để dùng đúng venv. |

Xem [hướng dẫn benchmark](src/eval/README.md) để đọc báo cáo, chấm lại trace và hiểu các chỉ số.
