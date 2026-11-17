# Mô tả bộ dữ liệu transcript và audio

Đối chiếu tệp local ngày **16/11/2026**. Dữ liệu phục vụ phát triển và kiểm thử agent telesales tiếng Việt. Các số dưới đây mô tả dữ liệu đang có; không phải kết quả đánh giá chất lượng agent.

## Mô tả ngắn để bàn giao

- **Cách sinh dữ liệu:** transcript M2 được dựng bằng quy tắc/câu mẫu từ kịch bản và dữ liệu nghiệp vụ BTC, có lời khách và agent mẫu, kiểm tra bằng mock. Audio cũ được manifest ghi nhận sinh bằng OmniVoice Vietnamese với giọng tham chiếu ViMD; không phải cuộc gọi khách hàng thực tế.
- **Phân bố:** M2 có 358 transcript/156 kịch bản/78 khách, gồm 222 phiên hotline, 68 Fanpage và 68 Zalo OA, bao phủ 12 persona và ba ngành hàng tham chiếu. Audio hiện có gồm 250 lượt khách của 80 phiên thuộc bộ gốc, tổng 29 phút 30,87 giây; metadata chọn giọng có Bắc, Trung, Nam. M2 chưa có audio khớp transcript mới.
- **Hạn chế:** dữ liệu tổng hợp, có lặp template và chồng lấp nguồn; không phải trace agent thực tế. Audio thiếu lời agent, chưa xác minh accent/nhiễu bằng nghe đánh giá; thiếu tệp giọng tham chiếu local và còn sai khác hash nguồn. Khi chia tập cần giữ cùng khách và kịch bản dẫn xuất cùng nhóm.
- **Thông tin cá nhân:** artifact mô tả danh tính tổng hợp; generator chỉ che một số mẫu số điện thoại/số nhà trong lời agent, vẫn giữ định danh trong lời khách và metadata. Chưa có bản xuất ẩn danh toàn bộ; quyền dùng/phân phối giọng chưa xác minh độc lập. Trước chia sẻ cần rà soát định danh trong cả văn bản lẫn audio và xác nhận quyền sử dụng nguồn giọng.

Phần dưới ghi chi tiết và căn cứ cho bản mô tả ngắn; các khoảng trống được giữ nguyên để người nhận không nhầm là đã hoàn tất thu âm hoặc xử lý quyền riêng tư.

## Phụ lục đối chiếu

### Phạm vi và đơn vị đếm

Một **kịch bản** gom các phiên thuộc một hành trình kiểm thử; một **transcript** chứa lời khách và lời agent của một phiên; một **lượt nói** là phát ngôn của một người. Một WAV hiện có chỉ chứa một lượt khách, không phải toàn bộ hội thoại.

| Thành phần | Vị trí và mục đích | Quy mô đã đối chiếu |
| --- | --- | --- |
| Nguồn BTC | [organizer/](organizer/): CRM seed, catalog, policy, schema, mock và evaluator | Nguồn tham chiếu nghiệp vụ; không cộng vào số hội thoại nhóm tạo |
| Kịch bản gốc của nhóm | [main/scenarios_complete/](main/scenarios_complete/); bản seed tương ứng ở [scenarios_prefilled/](main/scenarios_prefilled/) | 120 kịch bản SC-001–SC-120, 250 phiên, 812 lượt khách; không có đầy đủ lời agent |
| Transcript M2 của nhóm | [conversations/](main/m2_transcripts/conversations/), [manifest.jsonl](main/m2_transcripts/manifest.jsonl); [scripts/](main/m2_transcripts/scripts/) để đọc/thu âm | 358 transcript, 156 kịch bản SC-121–SC-276; có cả khách và agent mẫu |
| Audio của nhóm | [main/audio/](main/audio/); [manifest.csv](main/manifest.csv), [manifest.json](main/manifest.json), [manifest.jsonl](main/manifest.jsonl) | 250 WAV lượt khách, thuộc 80 phiên của 40 kịch bản SC-001–SC-040 |

Manifest là bảng kê đường dẫn và metadata: audio liên kết bằng `scenario_id`, `call_id`, `turn_index` (từ 0), cùng `text_original`, `text_tts`, đường dẫn, thời lượng và SHA-256. Đường dẫn audio tính từ `main/`; đường dẫn trong manifest M2 tính từ `main/m2_transcripts/`.

**Liên kết và độ bao phủ:** 250/812 lượt khách và 80/250 phiên gốc có audio cho lời khách (30,79% lượt; 32% phiên), chưa có lời agent thành tiếng. Bộ M2 có `audio_path: null` ở cả 358 mục manifest và không có tệp audio local; độ bao phủ audio hai người nói là **0/358**. Không ghép WAV cũ với transcript M2 để báo đủ hội thoại có audio.

**Tránh đếm trùng:** 120 kịch bản M2 SC-121–SC-240 mở rộng từ SC-001–SC-120; 36 kịch bản SC-241–SC-276 dùng khách tổng hợp bổ sung. Không cộng 250 phiên gốc và 358 transcript rồi gọi đó là các hội thoại độc lập. Metadata nguồn nằm tại [scenario_metadata.json](main/m2_transcripts/scenario_metadata.json).

### 1. Cách sinh dữ liệu

**Transcript:** bộ gốc có seed cố định và `fields_to_generate`, kết hợp hồ sơ khách, persona, sản phẩm và dữ kiện nghiệp vụ BTC ([hướng dẫn](main/README.md)). Chưa xác minh được model/prompt/lịch sử chạy đã tạo lời thoại gốc; hướng dẫn dùng LLM không phải bằng chứng đã dùng một model cụ thể. Bộ M2 được dựng bằng quy tắc và câu mẫu trong [build_corpus.py](main/m2_transcripts/build_corpus.py), mở rộng lời khách và thêm lời agent, dùng mock BTC để tính giá, tồn kho và thao tác nghiệp vụ. Generator này không chạy agent hoặc gọi TTS; lời agent là đáp án mẫu, không phải trace hệ thống.

Có thêm [bước biên tập ngôn ngữ bằng LLM](main/m2_transcripts/NATURALIZATION.md) sau baseline: gửi lời thoại nguyên văn cùng ràng buộc, lưu prompt/response, kiểm tra và xuất candidate riêng để người duyệt. Bước này không có masker; khi gọi live, tên/số điện thoại/địa chỉ có trong lời thoại sẽ được gửi nguyên văn cho provider. Chưa gọi model thật trong lần triển khai; các số liệu corpus trong tài liệu này vẫn thuộc baseline, không phải dữ liệu đã được LLM biên tập.

**Audio:** [manifest.json](main/manifest.json) ghi model `splendor1811/omnivoice-vietnamese`, revision `f70093f90d78a5b790ff0f066b3629ebcc33cb5d`, OmniVoice `0.2.1`, ngôn ngữ `vi`, tốc độ `1.0`, seed gốc `20261007` và seed từng clip. [Notebook tương ứng](text-to-speech/pipeline-generate-audio/customer_turns_to_omnivoice_vietnamese_vimd_40_scenarios_kaggle.ipynb) chọn một giọng tham chiếu ViMD theo tỉnh/giới tính cho mỗi kịch bản; nguồn `nguyendv02/ViMD_Dataset`, revision `3a5b30157034e7eadd5c75fae1a820c6f9383398`. `text_original` lưu câu gốc, `text_tts` lưu câu đưa vào TTS, có thể đổi chữ số thành cách đọc. Đây là nguồn ghi trong artifact, chưa tái chạy TTS để xác nhận tái lập âm thanh.

**Kiểm tra:** lần rà soát này mở được 250 WAV, đối chiếu SHA-256, thời lượng với manifest và `text_original` với đúng lượt khách nguồn: không có sai lệch. CSV và JSONL tương ứng; 14 trường dùng chung giữa các bản ghi JSON và JSONL nhất quán (cấu trúc/metadata bổ sung khác nhau). Manifest M2 có đủ đường dẫn transcript/kịch bản/script và checksum hợp lệ. Chạy lại validator M2 đạt: 2.021 lệnh mock, 358 điều kiện call và 172 probe âm. Đây là kiểm tra fixture, chưa kiểm tra nghe thủ công toàn bộ audio hoặc chất lượng phản hồi agent.

### 2. Phân bố dữ liệu

| Chỉ tiêu | Kết quả hiện có và đơn vị đếm |
| --- | --- |
| Transcript M2 | 358 phiên, 4.308 lượt nói: 2.154 lượt khách và 2.154 lượt agent |
| Khách M2 | 78 `customer_id` khác nhau: 42 kế thừa nguồn, 36 bổ sung; cả 78 có ít nhất hai phiên trong corpus |
| Hành trình M2 | 46 khách có hành trình ba phiên; 62 có hai cuộc hotline trong cùng hành trình; 61 có cả gọi và chat trên corpus, trong đó 57 có ngay trong một hành trình |
| Kênh M2 | 222 hotline (62,01%), 68 Fanpage (18,99%), 68 Zalo OA (18,99%) |
| Kênh bộ gốc | 150 hotline (60%), 50 Fanpage (20%), 50 Zalo OA (20%) |
| Ngành hàng tham chiếu | Gia dụng, thời trang, mẹ và bé; catalog có 40 mẫu cha, 128 SKU lá chưa ngừng bán khi tính cả biến thể, không đồng nghĩa luôn còn tồn kho |
| Audio đo từ header WAV | 250 clip; tổng **1.770,87 giây = 29 phút 30,87 giây**; mono, PCM 16-bit, 24.000 Hz |
| Vùng miền audio theo metadata | Bắc: 86 clip/14 kịch bản; Trung: 107/17; Nam: 57/9. Đây là nhãn yêu cầu/chọn giọng, chưa chứng minh chất giọng đầu ra qua nghe đánh giá |
| Người nói audio theo metadata | 40 `speakerID` tham chiếu khác nhau; 125 clip nhãn Nữ, 125 nhãn Nam. Không suy ra đây là 40 người tham gia thu âm cho dự án |
| Audio nhiễu hiện có | Chưa có nhãn/đo kiểm xác nhận tỷ lệ nhiễu; không báo 0% hay đạt 20% |

Phân bố **kịch bản** theo persona (không phải số phiên):

| Persona | Bộ gốc | M2 |
| --- | ---: | ---: |
| Do dự, hỏi người nhà | 10 | 10 |
| So giá | 10 | 10 |
| Đã mua, đổi size | 10 | 10 |
| Hỏi nhiều không mua | 10 | 10 |
| Gọi lần ba hết kiên nhẫn | 10 | 10 |
| Đa kênh Fanpage–hotline | 10 | 10 |
| Ngoài phạm vi, chuyển máy | 10 | 10 |
| Hỏi ngoài tài liệu | 10 | 10 |
| Đa kênh có mâu thuẫn | 10 | 10 |
| Hai người chung số điện thoại | 10 | 10 |
| Quay lại sau tám tháng | 10 | 10 |
| Mua nhiều món | 10 | 46 |

**Chỉ là kế hoạch:** [recording_plan.jsonl](main/m2_transcripts/recording_plan.jsonl) có 222 phiên hotline chờ thu/sinh, chia Bắc/Trung/Nam 74/74/74; 45 phiên dự kiến có nhiễu. Thời lượng ước tính trong kế hoạch không phải thời lượng đo và không cộng vào tổng audio hiện có. Nguồn phân bố: [coverage gốc](main/coverage.json), [coverage M2](main/m2_transcripts/coverage.json), manifest và các tệp thực tế.

### 3. Hạn chế

- Lời thoại tổng hợp dựa trên câu mẫu, luân phiên khách–agent; chưa đại diện đầy đủ cho ngắt lời, hội thoại tự nhiên hoặc lỗi ASR ngoài thực tế. M2 thiên về persona mua nhiều món (46/156 kịch bản); mỗi persona còn lại chỉ có 10.
- Audio cũ chỉ bao phủ bốn nhóm persona đầu ở SC-001–SC-040, thiếu lời agent. M2 chưa có audio hai người nói; theo [requirements.json](main/m2_transcripts/requirements.json), phần audio tối thiểu 100 hội thoại/10.800 giây chưa đạt. Chưa đo chất lượng TTS, accent, nhiễu hoặc diarization trong lần rà soát này.
- Không tìm thấy 40 tệp `reference_audio_relative` mà manifest audio trỏ tới trong cây local `main/`; chúng không thuộc 250 WAV đầu ra đã kiểm tra. Không thể dùng riêng cây local hiện tại để nghe lại toàn bộ giọng tham chiếu hoặc bảo đảm tái lập TTS. Chưa kiểm tra nội dung/quyền truy cập thư mục Google Drive được liên kết trong README.
- Ba hash nguồn gốc được lưu cho `schemas/tools.schema.json`, `eval/mock_tools.py`, `eval/reference_eval.py` khác tệp BTC hiện tại; [coverage gốc](main/coverage.json) ghi nhận chưa tìm được phiên bản nguồn tương ứng. Không thay hash lịch sử để che sai khác.
- Lời agent mẫu, lệnh mock và kiểm tra fixture không chứng minh TSR/RQR/CCR/HR của hệ thống. Rà soát ngữ nghĩa thủ công và chạy agent/simulator cho bộ M2 vẫn được tài liệu nguồn ghi là chờ thực hiện.
- Khi chia tập, giữ cùng khách và các kịch bản dẫn xuất từ cùng nguồn trong một tập; với ca chung số, giữ nhóm định danh liên quan cùng nhau. Không coi các nhánh scenario cùng khách là một lịch sử liên tục. Giữ `success_if`, `ground_truth_facts`, `private_annotations` và lời agent mẫu ngoài đầu vào của agent được đánh giá.

### 4. Xử lý thông tin cá nhân

**Nguồn và hiện trạng:** [customers.json](main/m2_transcripts/customers.json) mô tả danh tính fixture tổng hợp; generator kế thừa 42 hồ sơ nguồn và tạo 36 danh tính bổ sung. Có tên, số điện thoại, định danh kênh và địa chỉ trong scenario, lời khách hoặc tham số/kết quả mock. Đây là bằng chứng về mục đích tạo fixture, không xác nhận số điện thoại/địa chỉ không trùng người thật và không phải giấy phép liên hệ họ.

**Biện pháp đã có:** hàm `scrub()` trong generator thay số điện thoại dạng 10 chữ số bằng bốn số cuối và bỏ số nhà của mẫu “đường Kiểm Thử” trong **lời agent M2**. Validator kiểm tra hai mẫu này. Rà soát regex `(?<!\d)0\d{9}(?!\d)` trên 4.308 lượt M2 tìm thấy 258 lượt khách chứa số đầy đủ và 0 lượt agent; không hiển thị các giá trị đó trong tài liệu này. Corpus **chưa được ẩn danh toàn bộ**. Bộ mã runtime có [mask_pii](../src/telesale_agent/adapters/rules/pii_utils.py), nhưng điều đó không chứng minh mọi file dataset/metadata đã đi qua cơ chế này.

**Audio và giọng tham chiếu:** manifest giữ `speakerID`, tỉnh/vùng, giới tính, câu tham chiếu và đường dẫn tham chiếu. Manifest/notebook ghi các nhãn giấy phép nguồn: ViMD `CC-BY-NC-ND-4.0`, checkpoint/code OmniVoice `Apache-2.0`, tokenizer `Boson Higgs Audio 2 Community License Agreement`. Đây chỉ là nhãn được artifact ghi lại; lần rà soát local chưa xác minh độc lập điều khoản, sự đồng ý dùng giọng hoặc quyền phân phối audio dẫn xuất. Không suy từ nhãn giấy phép thành quyền dùng giọng cho mọi mục đích.

**Việc còn cần trước khi chia sẻ:** xác minh nguồn/quyền dùng giọng; rà soát tên, số, địa chỉ và định danh kênh trên transcript, script, manifest, `customers.json` và `private_annotations`. Nếu cần xuất bản che thông tin, dùng bảng ánh xạ ổn định theo khách/hồ sơ để giữ liên kết đa phiên, không gộp người chỉ vì chung số. Kiểm tra cả thông tin đọc thành lời trong audio, kể cả số viết bằng chữ; thay văn bản không tự thay được nội dung WAV. Chưa tạo bản xuất đã che thông tin, chưa nghe rà soát toàn bộ audio, và không cam kết đây là bộ dữ liệu công khai đã xử lý xong quyền riêng tư.

### Cách đọc và kiểm tra lại

Đọc transcript theo thứ tự `utterances` (`speaker: customer|agent`); chạy evaluator bằng thư mục `scenarios_complete/` thích hợp, không đưa thư mục `conversations/` vào bộ nạp scenario. Khi kiểm thử: giữ state giữa các call của một scenario, reset giữa các scenario. Không chạy generator nếu chỉ muốn đọc/kiểm tra, vì generator ghi đè artifact.

Từ gốc repo, kiểm tra fixture mà không sinh lại dữ liệu:

```bash
python3 -B dataset/main/m2_transcripts/validate_corpus.py
python3 -B -m unittest discover -s dataset/main/m2_transcripts/tests -v
```

Lần rà soát 16/11/2026 đã chạy validator: **pass**, không có lỗi; kết quả khớp [validation_report.json](main/m2_transcripts/validation_report.json) đã lưu. **9/9 regression test đạt**; mã mock/evaluator BTC phát `ResourceWarning` do file đọc chưa đóng, không gây test thất bại. Các phép đếm, SHA-256 và đo thời lượng WAV nêu trên được đối chiếu bằng Python standard library (`json`, `csv`, `hashlib`, `wave`), không gọi dịch vụ ngoài. Việc xác minh quyền dùng giọng, đánh giá nghe/ngữ nghĩa, bổ sung audio và tạo bản xuất che thông tin vẫn là các khoảng trống thực tế; hoàn thành tài liệu không có nghĩa đã hoàn thành các việc đó.
