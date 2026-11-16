# Transcript hội thoại M2 — 358 cuộc, 156 kịch bản

Bộ này bổ sung **lời khách và lời agent mẫu bằng tiếng Việt** để dùng làm transcript tổng hợp, kịch bản thu âm/TTS và fixture kiểm thử. Yêu cầu được đọc từ `dataset/organizer/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf`, mục C.1, C.4 và Phụ lục B; đối chiếu thêm `DIEU-CHINH-DE.md` và mock cập nhật 11/2026.

**Đã đạt các mức tối thiểu về số lượng transcript và cấu trúc kịch bản. Chưa đạt toàn bộ M2:** chưa thu/sinh audio hai người nói, chưa đo ASR/diarization và chưa chạy agent hoặc simulator. Lời agent trong bộ này là lời mẫu được soạn, có kiểm tra nghiệp vụ bằng mock; không phải kết quả hay điểm số của agent thực tế.

## Đối chiếu yêu cầu

| Hạng mục | Tối thiểu trong PDF | Bộ này | Trạng thái |
|---|---:|---:|---|
| Cuộc hội thoại dạng transcript | 250 | **358**, có cả hai người nói | Đạt về văn bản |
| Khách có ít nhất hai phiên | 60 | **78 khách khác nhau** | Đạt |
| Khách có ít nhất hai cuộc gọi hotline trong một hành trình | 60, theo cách đọc chặt của dòng đa phiên | **62 khách khác nhau** | Đạt cả khi không đếm chat là cuộc gọi |
| Có khách từ ba phiên | Có | **46 khách có hành trình ba phiên** | Đạt |
| Khách có cả cuộc gọi và chat | 30 | **61** trong corpus; **57** có ngay trong một hành trình liên kết | Đạt |
| Ngành hàng | 3 | Gia dụng, thời trang, mẹ và bé | Đạt |
| Persona | 5 loại bắt buộc | Đủ cả 5, tổng 12 loại | Đạt |
| Kịch bản đánh giá | 40 | **156**, mỗi kịch bản hai hoặc ba phiên | Đạt phần kịch bản; simulator còn phải chạy |
| Catalog | 100 SKU | **128 SKU lá còn kinh doanh**, từ catalog BTC | Đạt nếu đếm SKU biến thể; xem cách đếm bên dưới |
| Hội thoại có audio / thời lượng | 100 / 3 giờ | **0 bản ghi khớp transcript mới** | Chưa đạt |
| Giọng vùng miền | Bắc, Trung, Nam | Kế hoạch 74 / 74 / 74 cuộc | Chưa có giọng thu thực tế |
| Audio nhiễu | 20% | Kế hoạch **45/222** cuộc hotline, khoảng 20,3% | Chưa có audio nhiễu thực tế |

Các persona bắt buộc: khách do dự cần hỏi người nhà, khách so giá, khách đã mua gọi đổi size/khiếu nại, khách hỏi nhiều không mua, khách gọi lần ba hết kiên nhẫn. Bộ còn có nhận diện đa kênh, mâu thuẫn giá, dùng chung số, TTL khách cũ, câu hỏi ngoài tài liệu/y tế và giỏ nhiều món.

## Mở và sử dụng

- **Đọc/thu âm:** [scripts/](scripts/) có 156 file Markdown, mỗi file chứa toàn bộ các phiên của một hành trình. Ví dụ [SC-121](scripts/SC-121.md) — hỏi người nhà; [SC-141](scripts/SC-141.md) — đổi size; [SC-161](scripts/SC-161.md) — gọi lần ba; [SC-241](scripts/SC-241.md) — hai máy cùng giá; [SC-243](scripts/SC-243.md) — ba máy nhưng chỉ một lần giảm 50%.
- **Đọc bằng code:** [conversations/](conversations/) có 358 JSON. `utterances` theo thứ tự hội thoại, dùng `speaker: customer|agent` và `text`; phần riêng `private_annotations` chứa nguồn, provenance và tool mock đã thực thi.
- **Chạy agent/evaluator:** [scenarios_complete/](scenarios_complete/) có 156 JSON theo định dạng BTC, `calls.call_1..call_3`, `customer_turns`, điều kiện chấm và ngày cuộc gọi. Không dùng `conversations/` làm thư mục scenario của evaluator.
- **Metadata sinh dữ liệu:** [scenario_metadata.json](scenario_metadata.json) lưu fixture, nguồn scenario gốc và liên kết transcript ngoài các file scenario. Tên file `SC-121.json`–`SC-276.json` khớp `scenario_id` và tiếp nối sau `SC-120.json` của bộ gốc. Mỗi scenario giữ đúng chín trường cấp cao như thư mục tham chiếu `../scenarios_complete/`: `scenario_id`, `level`, `persona`, `hard_case`, `customer_phone`, `customer_name`, `honorific`, `notes`, `calls`; các call chỉ dùng trường có trong bộ tham chiếu.
- **Tìm file và kiểm checksum:** [manifest.jsonl](manifest.jsonl).
- **Xem phân bố và nguồn:** [coverage.json](coverage.json), [requirements.json](requirements.json), [validation_report.json](validation_report.json).
- **Thu âm tiếp:** [recording_plan.jsonl](recording_plan.jsonl) có 222 mục hotline, hai giọng tách biệt, vùng miền và loại nhiễu dự kiến.

Một transcript tương ứng **một phiên hội thoại**, không phải một lượt nói. Một scenario gom hai hoặc ba transcript liên tiếp. Tổng phân bố: **222 hotline, 68 Fanpage, 68 Zalo OA**.

### Nguồn và cách sinh

`m2_transcripts/scenarios_complete/SC-121.json`–`SC-240.json` lần lượt mở rộng từ `SC-001.json`–`SC-120.json` trong `dataset/main/scenarios_complete/`: giữ dữ kiện và điều kiện nghiệp vụ, thêm lời agent và các câu hỏi làm rõ về giá, bảo hành, đổi trả hoặc vận chuyển. Metadata giữ nguyên ID, đường dẫn và checksum của nguồn gốc; chỉ ID của bộ M2 được cộng thêm 120. Hai bộ ở hai thư mục riêng; các file gốc không bị ghi đè. Các phiên tiếp nối dùng chủ đề khác phiên đầu; các cuộc khách bận, khách gọi lần ba và chuyển máy y tế được giữ ngắn. Số lượt khách tối đa hiện tại là 9, dưới giới hạn 12 của simulator BTC. Bản ASR/teencode được giữ đúng vị trí các lượt nguồn và bổ sung lượt tương ứng.

Nguồn cũ chỉ sử dụng **42 customer_id**, dù có 120 scenario. `SC-241`–`SC-276` thêm **36 khách tổng hợp mới**, mỗi người có một phiên chat và hai phiên hotline. Cách này bảo đảm ít nhất 60 người có hai cuộc gọi ngay trong cùng hành trình, kể cả khi đọc dòng đa phiên của PDF theo nghĩa hẹp là cuộc gọi hotline. Không đếm việc đổi scenario ID hay sao chép cùng người thành một khách mới. Các khách mới bắt đầu với kết quả CRM `found: false`; việc nối phiên sau dựa vào định danh khách tự cung cấp và bộ nhớ của hệ thống. `customers.json` là bảng đối chiếu danh tính fixture, không phải dữ liệu cần nạp trước để tiết lộ nhu cầu tương lai.

Ba mươi sáu hành trình mới kiểm tra máy cùng giá, máy khác giá, hai máy cùng SKU, ba máy và COD trên 10 triệu. Phiên chat tư vấn trước; cuộc hotline đầu giữ giỏ trong lúc chờ người nhà; cuộc hotline tiếp theo mới chốt. Giá từng máy do `pricing.quote_order` cung cấp; `order.create(lines=...)` tạo một đơn, mỗi máy một dòng khi cùng SKU có giá khác nhau. Không giả định được giảm 50% cho cả hai máy bằng giá hay cho từng cặp trong đơn ba máy.

Sinh lại và kiểm tra chỉ cần Python 3.11+, không tải dependency và không gọi API:

```bash
# Từ thư mục gốc repository
python3 dataset/main/m2_transcripts/build_corpus.py
python3 dataset/main/m2_transcripts/validate_corpus.py \
  --out dataset/main/m2_transcripts/validation_report.json
python3 -B -m unittest discover -s dataset/main/m2_transcripts/tests -v
```

Generator ghi đè các file do nó tạo trong `m2_transcripts/`. Không chỉnh tay transcript nếu còn cần sinh lại; cập nhật generator rồi kiểm tra lại. Hai thư mục scenario gốc, audio cũ và ba manifest gốc không bị sửa.

### Kiểm chứng

Validator đọc lại file đã lưu, đếm danh tính và phiên, kiểm tra checksum, outline/ASR, giới hạn lượt, nguồn và thứ tự tool. Nó thực thi lại các lệnh mock từ trạng thái sạch ở đầu mỗi scenario, giữ state giữa các call, rồi đối chiếu kết quả đã lưu; số lệnh chính xác ở `validation_report.json`. **358 điều kiện call** đạt bằng lời mẫu; **172 probe âm** xác nhận lỗi tạo đơn/thiếu đơn vị hàng không được chấm đạt. Chín regression test kiểm tra corpus, giá bị sửa, hai máy bằng giá, ba máy, cuộc thứ ba ngắn, giới hạn bảo hành thời trang và cập nhật quyết định người nhà.

Đây là kiểm tra fixture, **không được đưa các số này vào bảng TSR/RQR/CCR/HR của hệ thống**. Cần chạy agent ở `full` và `baseline_no_memory` để tạo trace thật, sau đó mới chấm bằng `dataset/organizer/eval/reference_eval.py`. Khi chạy, chỉ đưa định danh kênh và lượt khách vào agent; `success_if`, `ground_truth_facts`, `fixture`, `private_annotations`, lời agent mẫu và file script phải được giữ riêng để chấm. Với `input_mode` nhiễu, dùng đúng `customer_turns_asr`. Simulator phải áp dụng cơ chế kiên nhẫn của BTC và chạy ba seed riêng; generator này không thay thế simulator.

Reset dữ liệu nghiệp vụ và bộ nhớ **giữa các scenario**, giữ state **giữa các call của cùng scenario**. Không nối mọi scenario cùng khách thành một lịch sử thời gian duy nhất: chúng là các nhánh thử nghiệm độc lập. Khi chia tập huấn luyện/kiểm thử, nhóm theo `customer_id` để tránh rò rỉ cùng khách giữa hai tập.

### Cách đếm catalog

[catalog_skus.json](catalog_skus.json) lấy nguyên dữ liệu BTC: 40 sản phẩm cha, 96 biến thể size/màu trên 6 sản phẩm. SKU lá = 34 sản phẩm không có biến thể + 96 SKU biến thể = **130**; loại 2 SKU ngừng bán còn **128**. Không cộng thêm 6 SKU cha đã được thay bằng biến thể. “Còn kinh doanh” nghĩa là chưa ngừng bán, không có nghĩa mọi SKU đều còn tồn tại mọi ngày.

Không tự tạo sản phẩm/giá/chính sách ngoài nguồn BTC để đủ số. Nếu BTC yêu cầu 100 **mẫu sản phẩm cha** thay vì 100 SKU, catalog hiện tại chỉ có 40 mẫu và chưa đáp ứng cách hiểu đó.

### Audio, vùng miền và quyền riêng tư

Kế hoạch thu âm chứa toàn bộ hai người nói, không có timestamp giả. Cần ghi/sinh audio thật, đo thời lượng, kiểm transcript rồi lấy timestamp speaker từ bản ghi. Nếu chỉ chọn một phần trong 222 cuộc, phần được chọn vẫn phải có ít nhất 100 cuộc, tổng ít nhất 10.800 giây, ba giọng vùng miền và ít nhất 20% cuộc có nhiễu. Giữ bản sạch cùng bản nhiễu; chỉ đếm mỗi cuộc một lần. Thời lượng dự kiến trong kế hoạch dùng số từ cách nhau bằng khoảng trắng và tốc độ giả định 150 từ/phút, **không phải thời lượng đo** và không thay thế ngưỡng ba giờ. Vùng miền là mục tiêu giọng thu, không suy ra từ địa chỉ giao hàng.

250 WAV cũ ở `../audio/` chỉ là các lượt khách của bộ nguồn; tổng khoảng 1.770,87 giây. Chúng không khớp lời thoại mở rộng hai người nói nên **không được đếm thành 250 hội thoại có audio** cho bộ này.

Danh tính và địa chỉ là fixture tổng hợp. Chúng chỉ phục vụ kiểm thử local; không gọi hoặc gửi tin tới các số đó. Lời agent tránh đọc lại đầy đủ số điện thoại và số nhà; tham số tool vẫn có định danh cần cho nghiệp vụ. Trước khi gửi fixture ra dịch vụ/model ngoài, cần token hóa/ẩn thông tin theo pipeline của dự án; corpus này không tự triển khai cơ chế đó. Các quy tắc TTL, supersede, provenance và bảo vệ hồ sơ chung số là **kỳ vọng kiểm thử**, chưa chứng minh backend đã thực hiện chúng. Rà soát ngữ nghĩa thủ công và pilot agent vẫn cần trước khi dùng làm benchmark chính thức.
