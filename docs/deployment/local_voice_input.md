# Voice input với Zipformer local

Web chat hỗ trợ nhập text hoặc upload một file ghi âm cho mỗi lượt thoại. Backend chạy ASR tiếng Việt trên CPU bằng [hynt/Zipformer-30M-RNNT-6000h](https://huggingface.co/hynt/Zipformer-30M-RNNT-6000h), sau đó đưa transcript vào pipeline DeepAgent hiện tại. Text và voice dùng chung `conversation_id`, số điện thoại khách hàng và lịch sử.

## Cài đặt một lần

Từ thư mục gốc repository, dùng môi trường Python đã cài dependencies của dự án:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\download_asr_model.py
```

Hoặc cài `requirements.txt`, đã bao gồm các thư viện voice. Script tải [bản ONNX INT8 được sherpa-onnx đóng gói từ model của hynt](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/zipformer-transducer-models.html#sherpa-onnx-zipformer-vi-30m-int8-2026-02-09-vietnamese), gồm encoder, decoder, joiner, tokens và file WAV mẫu. Trọng số được lưu trong `models/` và không đưa vào Git.

Chỉ bước cài đặt/tải model cần mạng. Khi nhận dạng, backend đọc trọng số trên ổ đĩa, giải mã bằng FFmpeg local và chạy `sherpa-onnx`; không gửi ghi âm đến Hugging Face hoặc dịch vụ ASR ngoài. Transcript tiếp tục đi vào các bước LLM hiện có của ứng dụng. Model được nạp khi có lượt voice đầu tiên và dùng lại cho các lượt sau. Chat text vẫn hoạt động khi chưa cài/tải ASR.

## Cấu hình

Các giá trị mặc định trong `.env.example`:

```dotenv
ASR_MODEL_DIR=models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09
ASR_NUM_THREADS=2
ASR_MAX_UPLOAD_MB=25
ASR_MAX_DURATION_SECONDS=120
```

Để tải model vào vị trí khác, đặt `ASR_MODEL_DIR` trong `.env` hoặc truyền `--model-dir` cho script, rồi cấu hình backend cùng đường dẫn. Đường dẫn tương đối tính từ thư mục chạy backend. `ASR_FFMPEG_PATH` có thể chỉ đến FFmpeg có sẵn; mặc định dùng executable đóng gói trong `imageio-ffmpeg`.

API đọc các giới hạn từ cấu hình; bộ chọn file trên web áp dụng tối đa 25 MB và hiển thị giới hạn mặc định 120 giây. File quá dài bị từ chối, không âm thầm cắt mất nội dung. WAV, MP3, M4A, FLAC, OGG và WebM được giải mã thành mono 16 kHz. File tạm bị xóa sau khi giải mã; ứng dụng không lưu ghi âm vào lịch sử hoặc memory.

## Chuẩn hóa văn bản sau ASR

Ngay sau ASR, pipeline chuẩn hóa text hoàn toàn local trước bước identity, che PII và perception. Văn bản đã chuẩn hóa được dùng cho LLM, lịch sử hội thoại và trường `transcript` trả về web/Gradio. Tin nhắn gõ tay dùng [bộ chuẩn hóa riêng cho viết tắt, không dấu và Việt–Anh](../agent/text_input_normalization.md). CLI `scripts/transcribe_audio.py` cũng trả text đã chuẩn hóa.

| ASR đầu ra | Text sau chuẩn hóa |
| --- | --- |
| `EM MUỐN MUA ÁO` | `em muốn mua áo` |
| `bốn triệu tám trăm chín mươi` | `4.890.000` |
| `hai trăm bốn chín k` | `249.000` |
| `sáu trăm chín mươi nghìn đồng không` | `690.000 đồng không` |
| `Ngày mười bảy tháng mười năm hai không hai sáu` | `17/10/2026` |
| `Không chín tám bốn bảy hai sáu bảy một bốn` | `0984726714` |

Tiền dùng quy ước bán lẻ trong yêu cầu: phần sau `triệu` không đọc đầy đủ đơn vị được hiểu là phần nghìn (`bốn triệu tám trăm chín mươi` → `4.890.000`, `hai triệu năm` → `2.500.000`). Đơn vị tường minh như `nghìn/ngàn/k/đồng` và tiền thập phân như `2,5 triệu` được nhận diện. Số đếm thiếu dấu hiệu tiền tệ không tự đổi thành tiền. Tên/mã sản phẩm không được tự sửa theo phỏng đoán; chỉ chuyển chữ thường.

Ngày được kiểm tra tính hợp lệ theo lịch, giữ nguyên nếu không hợp lệ; nếu người dùng chưa đọc năm thì chỉ chuẩn hóa thành `dd/mm`, không tự thêm năm. Các mốc tương đối như `ngày mai`, `thứ sáu tuần sau` và giờ hẹn tiếp tục do luồng hội thoại hiện có xử lý. Số điện thoại đủ 10 chữ số bắt đầu bằng `0` được ghép lại, giữ số `0` đầu; `+84`/`cộng tám bốn` được đổi về dạng `0...`. Số điện thoại này vẫn phải qua quy trình xác minh hiện có, không tự ghi đè số điện thoại đã xác thực từ CRM.

Khi `ENABLE_DEBUG_RESPONSE=true`, `debug.raw_asr_transcript` chứa bản ASR ban đầu để đối chiếu. Bước chuẩn hóa không gọi thêm LLM hay dịch vụ ngoài và không sửa giá trong catalog hoặc tự quyết định lịch gọi lại.

## Chạy và sử dụng

Khởi động backend với cấu hình CRM/LLM/MCP hiện có:

```powershell
.\scripts\start_api.ps1 -Reload
```

Script luôn dùng `.venv/Scripts/python.exe` của repository và chạy từ thư mục gốc, tránh gọi nhầm `python`/`uvicorn` của Anaconda hoặc bản Python khác. Có thể đổi cổng bằng `-Port 8001`; bỏ `-Reload` nếu không cần tự khởi động lại khi sửa mã.

Lệnh tương đương khi đang ở thư mục gốc:

```powershell
.\.venv\Scripts\python.exe -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --host 127.0.0.1 --port 8000
```

Trong `src/web`, chạy `npm run dev`. Chọn **Tải file ghi âm**, nghe thử nếu cần, rồi **Gửi ghi âm**. Transcript được hiển thị như câu nói của khách hàng, kèm phản hồi từ agent. Có thể tiếp tục lượt kế bằng text hoặc một file ghi âm khác. Khi lỗi, file vẫn được giữ để thử lại.

Web mặc định gọi `http://localhost:8000` khi development. Có thể đặt `NEXT_PUBLIC_API_BASE_URL` trong `src/web/.env.local` để dùng backend local khác hoặc bản build production, rồi khởi động/build lại web. Nếu frontend và backend khác origin, cấu hình `CORS_ORIGINS` trên backend. Endpoint voice áp dụng cùng `API_KEY`/header `X-API-Key` như endpoint text; web hiện tại phù hợp với backend local không bật `API_KEY`.

Gradio debugger cũng có ô tải file và nút **Gửi ghi âm (ASR local)**, sử dụng cùng adapter/pipeline. Gradio tự quản lý cache file upload của giao diện.

## Lỗi thiếu bộ giải mã local

Nếu gặp `Chưa có bộ giải mã âm thanh local`, kiểm tra và cài thư viện bằng chính Python chạy backend. Thư viện được cài trong `.venv` sẽ không tự có trong Anaconda hoặc một bản Python khác trên `PATH`.

```powershell
.\.venv\Scripts\python.exe -c "import sys, imageio_ffmpeg, sherpa_onnx; print(sys.executable); print(imageio_ffmpeg.get_ffmpeg_exe())"
```

Nếu lệnh trên thành công nhưng giao diện vẫn báo thiếu bộ giải mã, dừng backend cũ bằng `Ctrl+C` và chạy lại bằng `scripts/start_api.ps1`. Nếu lệnh kiểm tra báo thiếu module, cài vào đúng môi trường:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
```

## Gửi liên tiếp và giới hạn token của LLM

Giao diện chỉ cho phép một lượt gửi đang xử lý. Nút gửi chờ backend sẵn sàng; file và nội dung được giữ nếu upload thất bại. Khi Groq/LLM trả HTTP 429, backend trả JSON kèm `Retry-After` và `retry_after_seconds`; web hiển thị đếm ngược và khóa gửi đến khi hết hạn. Backend cũng chặn các request khác trong thời gian chờ, trước khi gọi ASR/LLM. Không tự động gửi lại POST để tránh lặp hành động của agent.

Lỗi 429 ở bước perception sẽ dừng lượt ngay, thay vì tiếp tục gọi main agent trong lúc quota chưa hồi phục. Lỗi 429 ở main agent không cộng thêm câu thoại vào lịch sử hoàn tất và xóa checkpoint tạm của lượt đó khi dùng `DEEPAGENT_CHECKPOINT_SCOPE=turn` (mặc định). Nếu bước memory summarization bị 429 sau khi agent đã trả lời, phản hồi vẫn thành công và gửi kèm thời gian chờ cho lượt kế tiếp. Quota của nhà cung cấp vẫn áp dụng; cơ chế này xử lý giới hạn và thời gian chờ, không tăng quota.

## API

`POST /api/chat/audio`, multipart form:

| Trường | Nội dung |
| --- | --- |
| `conversation_id` | Bắt buộc; dùng ID hiện tại để tiếp tục hội thoại |
| `file` | Bắt buộc; một file ghi âm |
| `customer_phone` | Tùy chọn; giống API text |

```powershell
curl.exe -X POST http://localhost:8000/api/chat/audio -F "conversation_id=demo-voice" -F "customer_phone=0984726714" -F "file=@recording.wav"
```

Kết quả gồm `response` và `transcript`; trường `debug` tuân theo `ENABLE_DEBUG_RESPONSE`. HTTP 413: file quá lớn. HTTP 422: ghi âm rỗng, hỏng, quá dài hoặc không nhận dạng được lời nói. HTTP 503: agent chưa sẵn sàng, thiếu trọng số/thư viện hoặc ASR không khả dụng. Lỗi ASR xảy ra trước khi thêm lượt vào lịch sử và trước khi gọi LLM.

HTTP 429: LLM đang giới hạn yêu cầu/token, kèm thời gian chờ. HTTP 502: lỗi xử lý khác; chi tiết kỹ thuật ghi trong log backend. Các lỗi này có phản hồi JSON và CORS để web hiển thị thông báo rõ ràng.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Trong `src/web`, chạy `npm test` để kiểm tra gửi liên tiếp, cooldown, lỗi kết nối và nội dung upload; `npm run lint` và `npx tsc --noEmit` kiểm tra mã frontend. Bộ test frontend dùng Node.js hỗ trợ TypeScript type stripping (máy dự án đang dùng Node 24).

Các test dùng FFmpeg thật để kiểm tra các định dạng, stereo → mono, resample và giới hạn thời lượng; dùng recognizer/agent giả lập để kiểm tra hợp đồng API và thứ tự text–voice–text mà không gọi LLM/CRM/MCP. Nếu đã tải trọng số và `test_wavs/0.wav`, bộ test tự chạy thêm một lượt upload qua API với Zipformer thật; nếu chưa tải thì bỏ qua riêng test này.

Lệnh kiểm tra ASR riêng, không khởi tạo agent hay gọi LLM:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\transcribe_audio.py models\sherpa-onnx-zipformer-vi-30M-int8-2026-02-09\test_wavs\0.wav
```

Model card của hynt công bố giấy phép **CC BY-NC-ND 4.0**. Cần đối chiếu điều kiện giấy phép của tác giả trước khi triển khai thương mại.
