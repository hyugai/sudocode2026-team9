# Biên tập transcript M2 bằng LLM

## Mục đích và phạm vi

Luồng mới: **fixture đã kiểm tra → lời thoại nguyên văn và ràng buộc → LLM diễn đạt lại → kiểm tra tự động → người duyệt → bản được chấp nhận**.

[build_corpus.py](build_corpus.py) vẫn tạo baseline bằng quy tắc/câu mẫu và mock BTC. [naturalize_transcripts.py](naturalize_transcripts.py) là bước tùy chọn phía sau, dùng model factory sẵn có của dự án (Gemini/Groq); không chạy sales agent, simulator hoặc TTS. Script không thay baseline, không tự quảng bá candidate thành dataset chính thức, không tạo audio và không chứng nhận đủ M2.

Mỗi request chứa toàn bộ các phiên của **một scenario**, theo thứ tự, để model giữ tiến trình thay đổi ý định. Không nối các scenario độc lập chỉ vì cùng khách. Mặc định chỉ xử lý SC-121; lặp `--scenario` để chọn thêm. Chưa có dữ liệu được model viết lại chỉ từ việc cài thêm script này.

## Đầu vào và ràng buộc

- Baseline ở `conversations/`, `scenarios_complete/`, `scenario_metadata.json`, `coverage.json` và các nguồn BTC; validator baseline phải đạt trước khi bắt đầu.
- [Prompt tiếng Việt](naturalize_prompt.md) cho phép sửa cách nói nhưng giữ ý nghĩa, phủ định, điều kiện, số lượng, đơn vị, xưng hô, kết quả và thời điểm thực hiện nghiệp vụ. Không được thêm/bớt/chuyển lượt nói.
- Request giữ nguyên lời thoại, gồm tên, số điện thoại, địa chỉ hoặc dữ kiện khác nếu có trong lời nói; không có bước masker, token hóa hoặc giải token. Request không chứa toàn bộ CRM, tham số mock hay đáp án chấm thô; nó chỉ chứa ID scenario/transcript, persona, kênh, lời thoại và cờ khóa lượt. Các giá trị định danh/thực thể và cụm chấm đã biết được dùng local để kiểm tra response, không thay văn bản gửi model.
- Lời khách của call có `customer_turns_asr` bị khóa nguyên văn để không làm mất liên kết với bản ASR/teencode. Các lượt khác có thể được biên tập. Script giữ nguyên metadata/tool refs của từng lượt và cập nhật `customer_turns` trong bản scenario candidate riêng.
- Kết quả model chỉ được chứa `scenario_id`, `sessions`, `transcript_id`, `utterances`, `speaker`, `text` theo cấu trúc prompt. Giữ giá trị/cách viết/thứ tự chuỗi chữ số, các thực thể và cụm chấm đã biết trong mỗi lượt; không tự sửa grading conditions để được chấm đạt.

Các quy tắc trên cụ thể hóa một phần [bug-format.md](../bug-format.md) và [bug-quality.md](../bug-quality.md). Script ghi hash của hai tài liệu để truy vết, **không tự đọc Markdown thành luật thực thi**. Channel/persona/hard-case distribution kế thừa baseline; không ép lại các tỷ lệ lịch sử trong báo cáo bug. Sửa metadata ngoài `text` hoặc thay quy mô corpus cần thay đổi riêng. Ba hash lịch sử M1 chưa giải quyết không được coi là đã sửa bởi bước này.

## Cách chạy

Chạy từ gốc repo bằng Python 3.11+. Chế độ chuẩn bị và replay chỉ dùng standard library và mã kiểm tra BTC. Chế độ live cần các dependency dự án đã cài (`python -m pip install -e .`) và credential provider trong môi trường hoặc `.env` local; không đưa khóa vào dòng lệnh hay artifact.

**1. Chuẩn bị offline:** tạo prompt với lời thoại nguyên văn để kiểm tra trước khi dùng dịch vụ ngoài. Không cần credential, không gọi model.

```bash
python3 -B dataset/main/m2_transcripts/naturalize_transcripts.py \
  --output outputs/benchmark/transcript_prepare_v1 \
  --scenario SC-121 --scenario SC-241
```

**2. Gọi LLM:** thay `TEN_MODEL_DA_CHON` bằng model ID provider cho phép sử dụng. Provider/model phải được chỉ định rõ; tham số sampling được ghi lại. Model factory có thể bỏ temperature nếu model dùng sampling cố định. Không hứa kết quả giống từng byte khi gọi lại model.

```bash
python3 -B dataset/main/m2_transcripts/naturalize_transcripts.py \
  --output outputs/benchmark/transcript_live_v1 \
  --scenario SC-121 --scenario SC-241 \
  --generate --provider gemini --model TEN_MODEL_DA_CHON \
  --temperature 0.5 --max-output-tokens 8192
```

Mỗi chế độ tạo một thư mục **mới**; thư mục đã tồn tại sẽ bị từ chối. Chế độ live chuẩn bị lại cùng prompt từ input hiện hành và lưu toàn bộ message thật sự gửi model. Không thay đổi `.env` hoặc cấu hình model của ứng dụng. Không tự retry cả scenario; SDK có thể retry request theo cấu hình đã ghi.

**3. Replay offline:** dùng raw response đã lưu để lặp lại việc kiểm tra/xuất candidate, không gọi API. Script đối chiếu hash input và message với run đã lưu; nếu khác thì từ chối nhận là replay giống nhau.

```bash
python3 -B dataset/main/m2_transcripts/naturalize_transcripts.py \
  --output outputs/benchmark/transcript_replay_v1 \
  --scenario SC-121 --scenario SC-241 \
  --responses outputs/benchmark/transcript_live_v1/raw_responses
```

Có thể import một thư mục response ngoài, mỗi file `SC-xxx.json` đúng schema với lời thoại đáp ứng các ràng buộc từ request. Nếu thiếu `run.json` đi kèm, metadata ghi rõ chưa xác minh lịch sử sinh; không coi import là bằng chứng đã chạy model cụ thể. Raw response lỗi vẫn được lưu để điều tra; không tự sửa JSON hoặc dùng baseline thay thế rồi báo đã sinh thành công. Run cũ dùng masker không thể replay như run mới vì prompt/code/input đã khác; giữ nguyên archive cũ để truy vết và tạo run mới.

## Đầu ra và kiểm tra

| Tệp/thư mục trong run | Nội dung |
| --- | --- |
| `run.json` | Chế độ, status, hash nguồn/code/prompt/bug docs, cấu hình model và phiên bản thư viện khi gọi live; không ghi API key |
| `system_prompt.md`, `requests/`, `messages/` | Prompt và message chính xác, lời thoại nguyên văn theo scenario; không sinh token map |
| `raw_responses/`, `provider_metadata/` | Raw text trả về (kể cả lỗi định dạng), usage và metadata model khi có |
| `validation_report.json` | Kết quả theo scenario, lỗi định dạng/giá trị/thực thể/fixture; không phải điểm chất lượng ngôn ngữ |
| `candidates/conversations/` | Transcript qua kiểm tra tự động, giữ `is_actual_agent_trace: false`, origin `language_variant_reference_dialogue` |
| `candidates/scenarios_complete/` | Scenario tương ứng, chỉ thay lời khách được phép sửa; giữ các điều kiện chấm |
| `manifest.jsonl` | Đường dẫn/checksum candidate, số lượt thay đổi, trạng thái chờ người duyệt; `audio_path: null` |

Kiểm tra tự động: số/thứ tự phiên và lượt; speaker; chuỗi chữ số và thực thể/cụm chấm đã biết trong từng lượt; lượt khách bị khóa; giới hạn độ dài; replay mock BTC theo trạng thái liên phiên; assertions của evaluator; mẫu số điện thoại/số nhà trong lời agent. Scenario bị lỗi không có candidate xuất bản. Run có lỗi trả exit code `2`; run chuẩn bị hoặc candidate qua máy kiểm tra trả `0`. Exit `0` **không** có nghĩa người duyệt đã chấp nhận.

Validator corpus cũ vẫn dành cho baseline có origin/hash cố định, không dùng trực tiếp để chứng nhận thư mục candidate từng phần. Chế độ prepare không xác nhận chất lượng rewrite vì chưa có response.

## Người duyệt và giới hạn

Người duyệt phải xem từng scenario, so sánh trước/sau: lời nói có tự nhiên không; còn lặp template không; đúng persona/xưng hô không; có đổi ý nghĩa, phủ định, số lượng viết bằng chữ hoặc thêm claim không; thông tin phiên sau có lọt vào phiên trước không. Kiểm tra tuân thủ điều kiện chấm không đủ để xác nhận mọi claim là đúng. Một bản echo không thay đổi chữ vẫn có thể qua máy kiểm tra; `changed_turns` giúp phát hiện trường hợp đó.

Chế độ live gửi lời thoại nguyên văn cho provider, bao gồm thông tin cá nhân nếu có trong lời nói; không ẩn tên/số điện thoại/địa chỉ trước khi gửi. Cơ chế này không đáp ứng riêng yêu cầu che PII trước model ngoài của đề; cần đối chiếu yêu cầu đó trước khi dùng làm bằng chứng tuân thủ. Thư mục run vẫn có quyền riêng tư và `.gitignore`, nhưng prompt, raw response và candidate không phải bản công khai đã ẩn danh. Các kiểm tra thực thể/chữ số chỉ bảo vệ tính nhất quán, không tự bảo đảm mọi câu diễn đạt lại đúng nghĩa hoặc không thêm tên/claim mới.

Không có seed provider được gửi ở bước này (`seed: null`). Tính tái lập dựa trên input/code/prompt được ghi hash và **raw response đã lưu**, không dựa vào giả định LLM luôn trả cùng câu. Chỉ nhận bản đã được con người duyệt qua một thay đổi riêng; công cụ hiện tại không có chức năng promote. Audio hoặc fixture thu âm phải được đối chiếu lại nếu sau này dùng lời thoại đã sửa.

Kiểm tra offline (mock provider, không dùng API):

```bash
python3 -B -W ignore::ResourceWarning -m unittest discover \
  -s dataset/main/m2_transcripts/tests -v
```
