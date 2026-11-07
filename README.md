# Telesale Agent tiếng Việt

Hệ thống tư vấn bán hàng có bộ nhớ khách hàng, được xây dựng cho dự án `sudo_code_2026-group_9`. Người dùng có thể nhắn tin, tải một file ghi âm hoặc trò chuyện bằng microphone theo thời gian thực. Agent kết hợp dữ liệu CRM, catalog, tồn kho, giá và chính sách để tư vấn và thực hiện các thao tác nghiệp vụ qua MCP.

Frontend dùng Next.js/React với giao diện Synee AI; backend dùng FastAPI, DeepAgents/LangGraph và PostgreSQL. Hướng dẫn dưới đây ưu tiên **chạy local trên Windows bằng PowerShell**, với Python của chính repository để tránh nhầm môi trường Anaconda hoặc Python hệ thống.

## Mục lục

- [Chức năng và phạm vi hiện tại](#chức-năng-và-phạm-vi-hiện-tại)
- [Kiến trúc và cấu trúc thư mục](#kiến-trúc-và-cấu-trúc-thư-mục)
- [Yêu cầu môi trường](#yêu-cầu-môi-trường)
- [Cài đặt và chạy local](#cài-đặt-và-chạy-local)
- [Sử dụng hệ thống](#sử-dụng-hệ-thống)
- [Bật tải ghi âm và voice realtime](#bật-tải-ghi-âm-và-voice-realtime)
- [Cấu hình môi trường](#cấu-hình-môi-trường)
- [API và ví dụ gọi trực tiếp](#api-và-ví-dụ-gọi-trực-tiếp)
- [Kiểm thử và benchmark](#kiểm-thử-và-benchmark)
- [Chạy backend bằng Docker](#chạy-backend-bằng-docker)
- [Xử lý lỗi thường gặp](#xử-lý-lỗi-thường-gặp)
- [Tài liệu chi tiết](#tài-liệu-chi-tiết)

## Chức năng và phạm vi hiện tại

| Thành phần | Hành vi hiện có |
| --- | --- |
| Chat text | Chuẩn hóa tiếng Việt gõ tay, xác định ý định, truy xuất ngữ cảnh và trả lời qua DeepAgent. |
| Tải ghi âm trong Chat | Zipformer chạy local trên CPU chuyển audio thành chữ; transcript đi tiếp qua cùng pipeline tư vấn và dùng chung `conversation_id` với text. |
| Voice realtime | Gemini Live nhận và phát audio trực tiếp, hỗ trợ transcript và ngắt lời; cần bật riêng. Tool ở chế độ `off` hoặc `read_only`. |
| Bộ nhớ khách hàng | Lưu thông tin học được giữa các cuộc gọi dưới dạng Markdown; dựng Call Brief gồm tóm tắt, nhu cầu, phản đối và vấn đề chưa giải quyết. |
| Nghiệp vụ qua MCP | Tra sản phẩm, tồn kho, giá/khuyến mãi, đơn hàng, chính sách; tạo/cập nhật đơn, hẹn gọi lại hoặc chuyển tiếp theo luồng và policy của agent. Thao tác ghi thực hiện ở luồng chat/upload, không mở cho realtime. |
| Catalog trên web | Danh sách và chi tiết sản phẩm đọc từ PostgreSQL qua API catalog; báo lỗi nếu API không khả dụng. |
| Gradio | Giao diện riêng để quan sát các bước xử lý và dữ liệu ngữ cảnh khi phát triển. |
| Đánh giá | Phát lại kịch bản, ghi trace, so sánh baseline/full và đo RQR, CCR, TSR, HR, tool-call accuracy, latency, WER/CER. |

Các trang đăng nhập/đăng ký hiện là **demo giao diện**, chưa có API xác thực tài khoản. Giỏ hàng, checkout, hóa đơn và tracking trên web dùng adapter demo riêng, chưa kết nối đơn hàng hoặc thanh toán thật. Các trang này không phản ánh kết quả thao tác đơn hàng của agent trong PostgreSQL. Số điện thoại dùng để tra cứu khách tư vấn, không phải cơ chế đăng nhập.

## Kiến trúc và cấu trúc thư mục

```text
Next.js web hoặc Gradio
  ├─ Text / file ghi âm
  │    → FastAPI hoặc harness Gradio
  │    → ASR local nếu có audio → chuẩn hóa → định danh và truy xuất ngữ cảnh
  │    → Call Brief → DeepAgent + LLM → kiểm tra policy → phản hồi và lưu memory
  └─ Voice realtime trên web
       → FastAPI voice controller ↔ Gemini Live
       → kiểm tra identity/policy → tool chỉ đọc và lưu memory

Dữ liệu dùng chung
  PostgreSQL                 catalog, CRM, tồn kho, khuyến mãi và đơn hàng
  MCP servers                công cụ database, knowledge và workflow
  Pinecone hoặc Chroma        truy xuất tài liệu chính sách
  data/memory-root/           hướng dẫn agent và bộ nhớ khách hàng
```

Backend tự khởi chạy và kết nối các MCP server qua **stdio subprocess**, dùng cùng Python đang chạy API. Không cần mở thêm terminal hoặc cổng HTTP cho từng MCP server.

```text
src/
  telesale_agent/
    core/                    Models, interface và hợp đồng domain
    application/             DeepAgent, hội thoại, Call Brief, memory và voice
    adapters/                LLM, ASR, PostgreSQL, CRM, MCP, RAG và guardrail
    entrypoints/api/          FastAPI, catalog, voice và Gradio
  mcp_servers/               MCP database, knowledge, workflow và memory tools
  web/                       Next.js app, utilities, assets và frontend tests
  eval/                      Runner, evaluator và công cụ benchmark
scripts/                     Khởi động API, seed database, ingest policy, tải ASR
dataset/                     Catalog, policy, kịch bản và audio đánh giá
data/memory-root/            Hướng dẫn agent và learned memory
tests/                       Backend regression tests
evaluation/                  Notebook và thí nghiệm đánh giá
outputs/benchmark/           Trace và báo cáo của từng lần chạy
docs/                        Kiến trúc, hướng dẫn triển khai và báo cáo
```

## Yêu cầu môi trường

| Thành phần | Yêu cầu |
| --- | --- |
| Python | 3.11 trở lên; Python 3.12 được dùng trong CI và ví dụ bên dưới. |
| Node.js | Node 24 cho frontend và bộ test có TypeScript type stripping; npm đi kèm. |
| PostgreSQL | Database đã có schema và seed catalog/CRM. Hướng dẫn dùng Docker `postgres:16`; có thể thay bằng PostgreSQL cài sẵn. |
| LLM | API key hợp lệ và quyền truy cập model tương ứng. Mẫu `.env.example` cấu hình Gemini; code cũng hỗ trợ Groq. |
| Knowledge | Chọn Chroma local hoặc Pinecone đã có dữ liệu policy. |
| Audio upload | Thêm dependencies `voice` và trọng số Zipformer; không bắt buộc nếu chỉ chạy text. |
| Voice realtime | Thêm dependencies `realtime`, migration journal và quyền truy cập Gemini Live. |
| Docker Desktop | Cần nếu dùng lệnh tạo PostgreSQL hoặc chạy backend container trong hướng dẫn. |

Database nghiệp vụ và LLM vẫn cần thiết khi chạy text. Chỉ phần nhận dạng file audio được xử lý local; transcript vẫn có thể đi đến nhà cung cấp LLM để agent trả lời.

Một số tài nguyên như `dataset/BTC-Data-Vong1-TEAMS/`, trọng số trong `models/`, Chroma DB và kết quả benchmark nằm trong ignore rules, nên có thể không đi kèm bản clone. Chuẩn bị dữ liệu trước khi seed hoặc đánh giá. Backend cũng cần các file `agent.md`, `soul.md`, `tools.md` trong `data/memory-root/agents/telesales_agent/`.

## Cài đặt và chạy local

Chạy các lệnh từ thư mục gốc repository, trừ phần frontend có chỉ dẫn `Set-Location`. Các bước 1–4 chỉ cần làm khi thiết lập môi trường mới; những lần sau chỉ cần bật database và chạy hai terminal backend/frontend.

### 1. Lấy mã nguồn và cài Python dependencies

Nếu chưa có repository:

```powershell
git clone https://github.com/hyugai/sudo_code_2026-group_9.git
Set-Location sudo_code_2026-group_9
```

Nếu đã clone, mở PowerShell tại thư mục gốc rồi chạy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,voice]"

if (-not (Test-Path -LiteralPath '.env')) {
  Copy-Item .env.example .env
}
```

Không cần activate `.venv` khi dùng đường dẫn Python tường minh. Nếu chỉ chạy text, có thể cài `.[dev]`; nếu dùng cả voice realtime, cài `.[dev,voice,realtime]`. Giữ `.env` ngoài Git và điền credential của môi trường bạn.

### 2. Cấu hình backend

Mở `.env`, thay các giá trị tương ứng. Ví dụ dưới chọn **Chroma local** để có thể tự nạp policy; `.env.example` ban đầu chọn Pinecone nên cần đổi `KNOWLEDGE_BACKEND` khi theo ví dụ này.

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
GOOGLE_API_KEY=your_google_api_key_here
NLU_THINKING_LEVEL=minimal
DEEPAGENT_THINKING_LEVEL=minimal

DATABASE_URL=postgresql+psycopg2://telesale:telesale_dev_password@localhost:5432/telesale?sslmode=disable

KNOWLEDGE_RETRIEVAL_MODE=mcp
KNOWLEDGE_BACKEND=chroma
ENABLE_VECTOR_RAG=true
CHROMA_DB_DIR=data/chroma_db

CUSTOMER_MEMORY_BACKEND=file
MEMORY_PERSISTER_MODE=llm_learning
REALTIME_VOICE_ENABLED=false
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ENABLE_DEBUG_RESPONSE=false
```

Tên model trên là cấu hình của repository; API key phải có quyền sử dụng model đó. Nếu cần đổi provider/model, xem [bảng cấu hình](#cấu-hình-môi-trường). Mỗi khi đổi `.env`, khởi động lại backend.

### 3. Tạo PostgreSQL và nạp catalog cùng CRM

Với Docker Desktop đang chạy, tạo container **một lần**:

```powershell
docker run --name telesale-postgres `
  -e POSTGRES_USER=telesale `
  -e POSTGRES_PASSWORD=telesale_dev_password `
  -e POSTGRES_DB=telesale `
  -p 127.0.0.1:5432:5432 `
  -v telesale_pgdata:/var/lib/postgresql/data `
  -d postgres:16

docker logs telesale-postgres --tail 20
```

Chờ log `database system is ready to accept connections`, sau đó seed database mới:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_catalog.py
docker exec telesale-postgres psql -U telesale -d telesale -c "SELECT count(*) AS products FROM products; SELECT count(*) AS customers FROM customers;"
```

Script đọc `products.json`, `promotions.json`, `inventory_timeline.json`, `crm_seed.json` trong `dataset/BTC-Data-Vong1-TEAMS/catalog/`, tạo schema và nạp cả đơn hàng có sẵn trong seed. Script từ chối seed nếu đã có bảng ứng dụng để tránh ghi đè dữ liệu. Với database đã chuẩn bị sẵn, bỏ qua bước tạo/seed và chỉ cấu hình đúng `DATABASE_URL`.

Những lần mở máy sau dùng `docker start telesale-postgres`, không chạy lại `docker run` hoặc seed. Để dừng database dùng `docker stop telesale-postgres`; dữ liệu được giữ trong volume. Xem [hướng dẫn PostgreSQL](docs/deployment/postgresql_self_hosting.md) để kiểm tra chi tiết.

### 4. Chuẩn bị kho chính sách

**Chroma local**, theo cấu hình ở bước 2:

```powershell
# Script ingest dùng TextLoader từ gói này, chưa được khai báo trong pyproject.toml.
.\.venv\Scripts\python.exe -m pip install langchain-community
.\.venv\Scripts\python.exe scripts\ingest_policy.py
```

Script đọc Markdown trong `dataset/BTC-Data-Vong1-TEAMS/policy/`, chia đoạn, tạo embedding bằng `keepitreal/vietnamese-sbert` và ghi vào `data/chroma_db/`. Lần đầu cần mạng để tải embedding model. Script bỏ hai file bẫy nội bộ/hết hiệu lực được liệt kê trong mã; Knowledge MCP còn lọc nguồn khi truy xuất. Chạy ingest trên kho mới; script không có cơ chế tự loại các chunk trùng do chạy lại.

**Pinecone**, nếu đã có index policy được nạp sẵn: thay cấu hình Chroma bằng các dòng sau và bỏ qua lệnh ingest local:

```dotenv
KNOWLEDGE_BACKEND=pinecone
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=policy-telesale
PINECONE_NAMESPACE=policy-prod
KNOWLEDGE_MCP_PREWARM=false
```

Index cần hỗ trợ truy vấn text và có metadata như `chunk_text`, `source_file`, `section`, `chunk_id`, `audience`, `is_expired`; namespace phải khớp dữ liệu đã nạp. `scripts/ingest_policy.py` chỉ tạo Chroma, không tạo hoặc upload index Pinecone. Nếu chưa có index sẵn, dùng luồng Chroma ở trên.

### 5. Khởi động backend

Trong terminal thứ nhất, từ gốc repository:

```powershell
.\scripts\start_api.ps1 -Reload
```

Script dùng đúng `.venv/Scripts/python.exe`, tự chuyển về gốc repository và mặc định lắng nghe `127.0.0.1:8000`. Nếu PowerShell không cho chạy script, dùng lệnh tương đương:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

Đổi cổng bằng `-Port 8001`; bỏ `-Reload` khi không cần theo dõi mã nguồn. Chờ khởi tạo MCP hoàn tất rồi kiểm tra ở terminal khác:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/catalog/products
```

`/health` trả `{"status":"ok"}` khi harness đã khởi tạo. Health không kiểm tra đầy đủ kết nối database, dữ liệu policy hoặc quyền gọi model; cần kiểm tra catalog và gửi một lượt chat. Swagger UI ở [http://localhost:8000/docs](http://localhost:8000/docs).

### 6. Khởi động frontend

Trong terminal thứ hai, bắt đầu từ gốc repository:

```powershell
Set-Location src/web
npm ci

if (-not (Test-Path -LiteralPath '.env.local')) {
  Copy-Item .env.example .env.local
}

npm run dev
```

Kiểm tra `src/web/.env.local` có:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Mở [http://localhost:3000](http://localhost:3000), hoặc vào thẳng [http://localhost:3000/ai-chat](http://localhost:3000/ai-chat). Nếu đổi cổng backend, sửa URL này rồi khởi động lại frontend. Khi frontend dùng origin khác, thêm origin đó vào `CORS_ORIGINS` của backend.

`NEXT_PUBLIC_*` được đưa vào mã trình duyệt: chỉ đặt URL công khai, không đặt API key. Bản production cần đặt `NEXT_PUBLIC_API_BASE_URL` **trước khi build** để tránh dùng URL mặc định của một môi trường khác.

Để chạy frontend theo bản build:

```powershell
# Chạy trong src/web.
npm run build
npm run start
```

Trên macOS/Linux, tạo venv bằng `python3 -m venv .venv`, dùng `.venv/bin/python` thay cho `.venv\Scripts\python.exe` và chạy Uvicorn trực tiếp; các lệnh npm tương tự. Dùng `cp` thay `Copy-Item` và cú pháp shell tương ứng cho lệnh nhiều dòng.

## Sử dụng hệ thống

1. Mở trang chủ hoặc `/ai-chat`, nhập số điện thoại có trong CRM để gắn ngữ cảnh khách hàng. Bộ seed có khách mẫu `0984726714`.
2. Chọn **Chat**, nhập câu hỏi và gửi. Có thể xem Call Brief để theo dõi nhu cầu và các vấn đề đang trao đổi.
3. Nếu đã chuẩn bị ASR, dùng nút **Tải file audio**, nghe thử/xóa file nếu cần, rồi gửi. Transcript và câu trả lời xuất hiện trong lịch sử chung với text.
4. Tiếp tục nhiều lượt với cùng khách và cùng hội thoại. Khi thực hiện nghiệp vụ như đặt hàng, cung cấp thông tin và xác nhận theo yêu cầu của agent.
5. Khi cần bắt đầu lại, dùng thao tác tạo cuộc hội thoại mới và xác nhận trên giao diện. Xem chẩn đoán ở `/account/conversations` khi bật debug.

Chat/upload trả JSON hoàn chỉnh, không stream token. Trong khi xử lý, giao diện ngăn gửi trùng. Khi lỗi, giữ nội dung hoặc audio để thử lại thủ công; khi HTTP 429 có đếm ngược, chờ hết thời gian rồi mới gửi lại.

Lịch sử phiên API đang lưu trong RAM; khởi động lại backend làm mất phiên đang hoạt động. Learned memory của khách được lưu riêng dưới `data/memory-root/users/` theo mặc định. Xóa một session hoặc mở hội thoại mới không đồng nghĩa xóa bộ nhớ khách đã lưu.

Để xem luồng xử lý bằng Gradio, chạy từ gốc repository:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m telesale_agent.entrypoints.api.gradio_chat
```

Mở [http://localhost:7860](http://localhost:7860). Gradio tự khởi tạo harness riêng khi có lượt tương tác đầu tiên, dùng cùng cấu hình database/LLM/memory; không cần FastAPI chạy trước để sử dụng Gradio.

## Bật tải ghi âm và voice realtime

### File ghi âm qua Zipformer local

Từ gốc repository:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\download_asr_model.py
```

Cấu hình trong `.env`:

```dotenv
ASR_MODEL_DIR=models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09
ASR_NUM_THREADS=2
ASR_MAX_UPLOAD_MB=25
ASR_MAX_DURATION_SECONDS=120
```

Khởi động lại backend. WAV, MP3, M4A, FLAC, OGG và WebM được giải mã local thành mono 16 kHz; FFmpeg mặc định lấy từ `imageio-ffmpeg`. Có thể đặt `ASR_FFMPEG_PATH` nếu cần executable riêng. Mặc định nhận tối đa 25 MB và 120 giây mỗi file; web có giới hạn chọn file 25 MB. Model được nạp ở lượt audio đầu tiên, nên lượt đầu có thể chậm hơn.

Kiểm tra ASR riêng, không gọi agent/LLM:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\transcribe_audio.py models\sherpa-onnx-zipformer-vi-30M-int8-2026-02-09\test_wavs\0.wav
```

Ghi âm upload không được lưu vào lịch sử hoặc customer memory; transcript được dùng cho hội thoại. Xem [hướng dẫn voice input](docs/deployment/local_voice_input.md) để biết chuẩn hóa tiền, ngày và số điện thoại.

### Microphone và Gemini Live

Luồng này dùng native audio Gemini Live, không yêu cầu trọng số Zipformer:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[realtime]"
.\.venv\Scripts\python.exe scripts\migrate_voice.py
```

Migration tạo bảng `voice_turn_journal` trong database đã cấu hình. Sau đó sửa `.env` và khởi động lại backend:

```dotenv
REALTIME_VOICE_ENABLED=true
GEMINI_LIVE_MODEL=gemini-3.8-live
GEMINI_LIVE_API_VERSION=v1beta
GEMINI_LIVE_VOICE=Kore
REALTIME_TOOLS_MODE=read_only
REALTIME_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

Trong `/ai-chat`, chọn **Voice** rồi **Bắt đầu trò chuyện** và cấp quyền microphone. Trình duyệt cần HTTPS hoặc `localhost` và hỗ trợ AudioWorklet. Nếu backend bật `API_KEY`, ô **Mã truy cập** của voice dùng khóa backend này, không dùng Google API key.

Chạy **một backend worker** cho realtime hiện tại. Tool ghi như tạo/sửa đơn, hẹn gọi và handoff bị khóa; chuyển về Chat để thực hiện các thao tác này. `REALTIME_TOOLS_MODE` chỉ hỗ trợ `off` hoặc `read_only`. Frontend dùng Wave từ thư viện LiveKit nhưng không yêu cầu một LiveKit server riêng. Xem [cấu hình và giới hạn Gemini Live](docs/deployment/gemini_live.md).

## Cấu hình môi trường

Backend đọc `.env` ở gốc repository; frontend đọc `src/web/.env.local`. Bảng dưới gồm giá trị mẫu hoặc mặc định được chỉ rõ, không thay thế `.env.example`.

| Biến | Ý nghĩa và giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` | `gemini` trong cấu hình mẫu; cũng hỗ trợ `groq`. Đặt tường minh vì mặc định trong code là Groq. |
| `LLM_MODEL` | Model text; mẫu dùng `gemini-3.6-flash`. Khi đổi provider cần đổi model tương ứng. |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Credential Gemini; ưu tiên `GOOGLE_API_KEY`. Groq dùng `GROQ_API_KEY`. |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Timeout mỗi request model, mặc định 30 giây. |
| `LLM_MAX_OUTPUT_TOKENS` / `LLM_MAX_RETRIES` | Giới hạn output và retry ở cấp request; mặc định code là 1.024 token và 0 retry. |
| `NLU_THINKING_LEVEL` | Thinking riêng cho bước nhận thức ý định; mẫu đặt `minimal`. |
| `DEEPAGENT_THINKING_LEVEL` | Thinking riêng cho main agent; mẫu đặt `minimal`. |
| `LLM_THINKING_LEVEL` | Cấu hình thinking chung khi thành phần không có override; LLM persister vẫn dùng cấu hình chung. |
| `DATABASE_URL` | URL PostgreSQL; dùng `postgresql+psycopg2://...` để đồng nhất với driver đã cài. |
| `KNOWLEDGE_BACKEND` | `chroma` hoặc `pinecone`; code mặc định Chroma, `.env.example` chọn Pinecone. |
| `KNOWLEDGE_RETRIEVAL_MODE` | Mặc định `mcp`, truy xuất policy qua Knowledge MCP; `direct` dùng retriever Chroma trong process ứng dụng. |
| `CHROMA_DB_DIR` | Kho Chroma, mặc định `data/chroma_db`; script ingest hiện ghi vào đúng thư mục này. |
| `PINECONE_API_KEY` / `PINECONE_INDEX_NAME` / `PINECONE_NAMESPACE` | Credential và vị trí policy khi chọn Pinecone. |
| `ENABLE_VECTOR_RAG` | Mặc định `true`; `false` tắt truy xuất vector/policy. |
| `KNOWLEDGE_MCP_PREWARM` | Warm-up policy khi khởi tạo; mặc định bật với Chroma, tắt với Pinecone. |
| `CUSTOMER_MEMORY_BACKEND` | Mặc định `file`; có adapter `object_storage`/`s3` với cấu hình riêng. |
| `CUSTOMER_MEMORY_ROOT` | Mặc định `data/memory-root/users/`; chỉ nơi lưu learned memory, không phải database CRM. |
| `AGENT_INSTRUCTIONS_ROOT` | Mặc định `data/memory-root/agents/telesales_agent/`, chứa `agent.md`, `soul.md`, `tools.md`. |
| `MEMORY_PERSISTER_MODE` | Mặc định `llm_learning`; dùng `turn` nếu muốn persister dựa trên dữ liệu lượt thay vì LLM learning. |
| `ASR_*` | Đường dẫn model, thread, dung lượng và thời lượng audio upload. |
| `REALTIME_VOICE_ENABLED` / `GEMINI_LIVE_*` | Bật và cấu hình Gemini Live riêng với model text. |
| `REALTIME_ALLOWED_ORIGINS` | Danh sách origin được phép mở voice WebSocket, phân tách bằng dấu phẩy. |
| `CORS_ORIGINS` | Origin web được phép gọi HTTP API; nên khớp URL frontend đang chạy. |
| `API_KEY` | Nếu đặt, chat/upload và xóa session yêu cầu header `X-API-Key`. Web Chat hiện chưa có ô nhập khóa này; voice có **Mã truy cập** riêng. |
| `ENABLE_DEBUG_RESPONSE` | Mặc định `false`; `true` trả thêm intent, CRM, tool calls, memory và usage trong `debug`. Call Brief gọn vẫn được trả khi debug tắt. |
| `NEXT_PUBLIC_API_BASE_URL` | URL backend cho frontend; đặt trong `src/web/.env.local`. |

Khi bỏ trống override thinking riêng, thành phần đó kế thừa `LLM_THINKING_LEVEL` hoặc mặc định provider. File `.env` không ghi đè các biến đã có trong môi trường process; nếu cấu hình không đổi như mong đợi, kiểm tra terminal đang chạy và khởi động lại dịch vụ.

## API và ví dụ gọi trực tiếp

| Method | Đường dẫn | Chức năng |
| --- | --- | --- |
| `GET` | `/health` | Readiness của harness. |
| `GET` | `/api/catalog/products` | Catalog từ PostgreSQL, trả `items`. |
| `GET` | `/api/catalog/products/{sku}` | Chi tiết một SKU và biến thể/tồn kho. |
| `POST` | `/api/chat` | Gửi text bằng JSON. |
| `POST` | `/api/chat/audio` | Gửi một file audio bằng multipart form. |
| `DELETE` | `/api/sessions/{conversation_id}` | Xóa state phiên text/upload trong RAM, không xóa learned memory. |
| `GET` | `/api/voice/capabilities` | Trạng thái bật/tắt và cấu hình voice có thể công khai. |
| `POST` | `/api/voice/sessions` | Tạo phiên realtime khi tính năng đã bật. |
| `GET` / `DELETE` | `/api/voice/sessions/{session_id}` | Xem trạng thái hoặc đóng phiên voice theo token owner. |
| `WebSocket` | `/api/voice/sessions/{session_id}/stream` | Kênh audio realtime, dùng ticket được cấp khi tạo phiên. |

Gửi text bằng PowerShell:

```powershell
$chatPayload = @{
  conversation_id = 'demo-chat-001'
  customer_phone = '0984726714'
  message = 'Chào em, chị muốn tìm máy lọc không khí.'
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/chat' `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($chatPayload))
```

Phản hồi có `response`, `normalized_message`, `call_brief`, `latency` và `call_brief_latency_ms`. Lượt audio trả `transcript` thay `normalized_message`. `debug` chỉ xuất hiện khi bật cấu hình tương ứng.

Gửi file ở lượt tiếp theo, giữ cùng ID và số điện thoại; thay `recording.wav` bằng đường dẫn file có thật:

```powershell
curl.exe -X POST http://localhost:8000/api/chat/audio `
  -F "conversation_id=demo-chat-001" `
  -F "customer_phone=0984726714" `
  -F "file=@recording.wav"
```

Nếu đã bật `API_KEY`, thêm `-Headers @{ 'X-API-Key' = 'your_backend_api_key' }` vào lệnh PowerShell hoặc `-H "X-API-Key: your_backend_api_key"` vào curl. Chi tiết schema và mã lỗi xem Swagger tại `/docs`; voice còn dùng token owner/ticket sau bước bootstrap, không chỉ header API key.

## Kiểm thử và benchmark

Backend regression, từ gốc repository:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s src\eval -p 'test_*.py' -v
```

Test mock các dịch vụ bên ngoài; test ASR thật có thể bỏ qua nếu chưa có weights. Đây là kiểm thử mã, không thay thế kiểm tra kết nối LLM/database thực tế.

Frontend, chạy trong `src/web/`:

```powershell
npm test
npm run lint
npx next typegen
npx tsc --noEmit
npm run build
```

Kiểm tra dữ liệu benchmark trước, không gọi API model:

```powershell
# Chạy từ gốc repository; cần dataset, manifest và WAV đúng đường dẫn.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --preflight-only
```

Đo riêng ASR hoặc chạy pilot một kịch bản:

```powershell
# Chỉ ASR, không gọi LLM.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --asr-only

# Pilot cả text/audio, baseline/full; gọi LLM và business tool thật.
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --limit 1
```

Chạy bộ 40 kịch bản ở cả text và audio:

```powershell
.\.venv\Scripts\python.exe -X utf8 src\eval\run_suite.py --limit 40
```

Hoặc chạy riêng text full bằng hai worker, đặt tên output theo thời điểm chạy:

```powershell
$benchmarkVersion = 'benchmark_v' + (Get-Date -Format 'yyyyMMddHHmmss')
.\.venv\Scripts\python.exe -X utf8 src\eval\run_parallel_benchmark.py `
  --version $benchmarkVersion --limit 40 --workers 2 --config full `
  --llm-provider gemini --llm-model gemini-3.6-flash
```

Chọn `--version` mới mỗi lần chạy; parallel runner nhận dạng `benchmark_v` theo sau bởi chữ số. Cấu hình model của eval có mặc định riêng là Gemini, không tự đổi theo provider của ứng dụng; dùng `--llm-provider` và `--llm-model` để chọn tường minh. Benchmark gọi LLM thật, có thể tạo đơn test và cleanup đơn runner đã tạo; nên dùng database dành cho đánh giá. `--asr-only` chỉ đo nhận dạng audio, không chứng minh chất lượng toàn luồng voice. Pilot một kịch bản không đủ mẫu để kết luận p95/SLA.

Các chỉ số chính: **RQR** là tỷ lệ hỏi thừa/lặp, **CCR** là mức sử dụng lại ngữ cảnh, **TSR** là tỷ lệ hoàn thành tác vụ, **HR** là tỷ lệ phát biểu sai kiểm chứng được; **WER/CER** đo lỗi từ/ký tự của ASR. Điểm chất lượng và ngưỡng latency được xét riêng. Xem [hướng dẫn evaluator](src/eval/README.md) để biết định nghĩa, điều kiện đầu vào và các artifact.

[Báo cáo Word benchmark 2026110202 và 2026110203](docs/bao_cao_benchmark_2026110202_2026110203.docx) giải thích kết quả text và ASR ngày 02/11/2026, kèm đối chiếu trace và giới hạn phép đo. Các thư mục kết quả thô trong `outputs/benchmark/` có thể chỉ có trên máy đã chạy benchmark.

## Chạy backend bằng Docker

`compose.yaml` hiện chỉ dựng **backend**, ánh xạ cổng host `8000` vào cổng container `10000`. Nó không tự tạo PostgreSQL, seed dữ liệu hoặc chạy frontend. Dockerfile dùng bộ dependency gọn `requirements-render.txt`, có Gemini Live nhưng không có bộ ASR upload local và trọng số Zipformer; hướng dẫn chạy bằng `.venv` phía trên là luồng có đủ phần ASR.

Để chạy cấu hình container hiện có:

1. Chuẩn bị database đã seed và Pinecone policy đã nạp sẵn.
2. Tạo `.env` trên host với credential và URL truy cập được từ container. Trên Docker Desktop Windows, PostgreSQL ở host dùng `host.docker.internal:5432` thay `localhost:5432`; `localhost` bên trong container là chính container. Cấu hình `KNOWLEDGE_BACKEND=pinecone` và `KNOWLEDGE_RETRIEVAL_MODE=mcp`.
3. Chạy từ gốc repository:

```powershell
docker compose build

# Chỉ khi bật realtime: tạo journal trước khi nhận phiên voice.
docker compose run --rm backend python scripts/migrate_voice.py

docker compose up
```

Compose bind `.env` vào `/app/.env` ở chế độ chỉ đọc. Memory ghi trong filesystem container; compose hiện chưa gắn volume bền vững cho customer memory. Nếu cần giữ memory khi tạo lại container, bổ sung volume cho `/app/data/memory-root/users/`. Tắt bằng `docker compose down`; chạy frontend riêng bằng npm như phần local. Khi quay về chạy Python trên host, dùng lại `DATABASE_URL` phù hợp với host.

## Xử lý lỗi thường gặp

| Triệu chứng | Kiểm tra và xử lý |
| --- | --- |
| Thiếu module dù đã cài | Dùng `.venv/Scripts/python.exe` và `scripts/start_api.ps1`; kiểm tra bằng `.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"`. |
| Không có `DATABASE_URL` hoặc không kết nối được DB | Chạy từ gốc repository, kiểm tra `.env`, trạng thái container/service, port và credential. Nếu container đã tồn tại, dùng `docker start telesale-postgres`. |
| Seed báo đã có bảng ứng dụng | Đây là cơ chế bảo vệ dữ liệu. Với database đã seed, bỏ qua seed; nâng schema orders riêng khi cần bằng `scripts/migrate_catalog.py --orders-only`. |
| `Chroma directory does not exist` / policy không có nguồn | Ingest policy, kiểm tra `KNOWLEDGE_BACKEND`, `CHROMA_DB_DIR` hoặc index/namespace Pinecone; ingest local không nạp dữ liệu lên Pinecone. |
| Ingest thiếu `langchain_community` | Cài bổ sung bằng `.\.venv\Scripts\python.exe -m pip install langchain-community`. |
| UI báo backend chưa sẵn sàng hoặc catalog lỗi | Xem log backend, kiểm tra `/health`, sau đó `/api/catalog/products`. Health thành công chưa bảo đảm database hoặc LLM hoạt động. |
| CORS hoặc frontend gọi sai API | Sửa `NEXT_PUBLIC_API_BASE_URL`, `CORS_ORIGINS`, khởi động/build lại frontend; phân biệt `localhost` và `127.0.0.1`. |
| HTTP 401 khi gửi Chat | Kiểm tra `API_KEY` và `X-API-Key`. Web Chat chưa có giao diện nhập khóa backend; các ví dụ local mặc định không đặt `API_KEY`. |
| LLM trả 401/402/403/404 | Kiểm tra provider, tên model, quyền API key và billing của project. Không tự đổi model mà vẫn dùng kết quả benchmark cũ. |
| LLM trả 429 | Chờ `Retry-After`/`retry_after_seconds`, rồi thử lại thủ công; không gửi liên tiếp để tránh lặp nghiệp vụ. |
| Audio trả 413/422/503 | Kiểm tra giới hạn 25 MB/120 giây, file hợp lệ, dependencies voice, model và FFmpeg. Chạy `scripts/transcribe_audio.py` để tách lỗi ASR khỏi agent. |
| Voice không bật hoặc microphone không mở | Kiểm tra extra `realtime`, migration, `REALTIME_VOICE_ENABLED`, origin được phép, HTTPS/localhost và quyền microphone; chỉ chạy một worker. |
| Turbopack lỗi CSS worker trên Windows | Thử `npm run dev -- --webpack` hoặc `npm run build -- --webpack` trong `src/web/`. |

## Tài liệu chi tiết

- [Kiến trúc DeepAgent](docs/agent/deep_agent_architecture.md)
- [Luồng ngữ cảnh và customer memory](docs/agent/deepagent_context_memory_flow.md)
- [Chuẩn hóa tin nhắn gõ tay](docs/agent/text_input_normalization.md)
- [Thiết lập PostgreSQL local](docs/deployment/postgresql_self_hosting.md)
- [Cài đặt và sử dụng ghi âm Zipformer](docs/deployment/local_voice_input.md)
- [Cấu hình và giới hạn Gemini Live](docs/deployment/gemini_live.md)
- [Kịch bản demo Call Brief](docs/deployment/call_brief_demo.md)
- [Frontend và kiểm tra giao diện](src/web/README.md)
- [Đánh giá và benchmark](src/eval/README.md)
- [Trạng thái demo đăng nhập và kế hoạch xác thực](docs/Login%20and%20register/authentication-setup.md)
- [Báo cáo benchmark dạng Word](docs/bao_cao_benchmark_2026110202_2026110203.docx)
