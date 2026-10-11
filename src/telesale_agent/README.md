# Telesale Agent

Telesale Agent là ứng dụng thử nghiệm hội thoại bán hàng bằng tiếng Việt. Luồng chính sử dụng `DeepAgentHarness`, Groq làm LLM và MCP cho các business tools. LangGraph chỉ còn là dependency nội bộ của thư viện `deepagents`.

## Yêu cầu

- Python 3.11 trở lên
- Tài khoản Groq và một `GROQ_API_KEY` hợp lệ
- Chạy các lệnh bên dưới từ thư mục gốc của repository (thư mục chứa `pyproject.toml`)

## Cài đặt

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
Copy-Item .env.example .env
```

Nếu PowerShell chặn script kích hoạt môi trường ảo, chạy lệnh sau trong cửa sổ hiện tại rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

## Cấu hình biến môi trường

Mở file `.env` vừa tạo và thay giá trị mẫu bằng API key thật:

```dotenv
GROQ_API_KEY=your_groq_api_key_here
```

`GROQ_API_KEY` là biến bắt buộc. Chương trình hiện dùng Groq cho cả bước nhận diện ý định và bước lập kế hoạch phản hồi. Không commit file `.env` hoặc chia sẻ API key.

Các biến `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2` và `LANGCHAIN_PROJECT` chỉ cần thiết khi muốn gửi trace lên LangSmith. Nếu không dùng LangSmith, đặt:

```dotenv
LANGCHAIN_TRACING_V2=false
```

`OPENAI_API_KEY` hiện chưa được sử dụng trong luồng chạy mặc định.

## Chạy giao diện chat Gradio

Sau khi đã kích hoạt môi trường ảo và cấu hình `.env`, chạy:

```powershell
python -m telesale_agent.entrypoints.api.gradio_chat
```

Mở trình duyệt tại [http://localhost:7860](http://localhost:7860). Nhập câu hỏi tiếng Việt vào ô chat; cột bên phải sẽ hiển thị dữ liệu của các bước Perceive, Identity, Retrieve, Call Brief và Agent Loop.

Dừng chương trình bằng `Ctrl+C` trong terminal.

## Xử lý lỗi thường gặp

- **`GROQ_API_KEY is not set`**: kiểm tra file `.env` nằm ở thư mục gốc và key không còn là giá trị mẫu.
- **`No module named telesale_agent`**: kích hoạt đúng môi trường ảo rồi chạy lại `python -m pip install -e .` từ thư mục gốc.
- **Không mở được cổng 7860**: kiểm tra chương trình khác có đang dùng cổng này không; cổng hiện được cấu hình trong `src/telesale_agent/entrypoints/api/gradio_chat.py`.
- **Groq trả về lỗi model/quota**: kiểm tra API key, quota và quyền truy cập các model `openai/gpt-oss-20b` và `openai/gpt-oss-120b` trên tài khoản Groq.

## Chạy lại ở lần sau

Không cần cài lại dependencies. Chỉ cần mở terminal tại thư mục gốc, kích hoạt môi trường ảo và chạy ứng dụng:

```powershell
.\.venv\Scripts\Activate.ps1
python -m telesale_agent.entrypoints.api.gradio_chat
```
