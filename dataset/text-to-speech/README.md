# Tổng hợp giọng nói (TTS) cho dữ liệu telesales

Đồ án dùng TTS để chuyển lời khách hàng trong kịch bản bán hàng tiếng Việt thành audio đầu vào cho các thử nghiệm nhận dạng giọng nói. Mỗi tệp WAV tương ứng với một lượt lời của khách hàng. Một phiên có nhiều lượt sẽ có nhiều tệp WAV, kể cả khi kênh được ghi trong JSON là Fanpage hoặc Zalo. [Tổng quan bộ dữ liệu hội thoại](../transcript/README.md)

## Quy trình tạo audio M1

1. **Đọc và chuẩn hóa lời thoại.** Notebook lấy từng câu từ `calls.<call_id>.customer_turns` trong các JSON `SC-001` đến `SC-100`. Số tiền, ngày giờ và số điện thoại được chuyển sang cách đọc tiếng Việt. Manifest ghi cả câu gốc và câu đã chuẩn hóa. [Transcript M1](../transcript/M1/)
2. **Chọn giọng tham chiếu.** Pipeline dùng checkpoint `splendor1811/omnivoice-vietnamese` của OmniVoice và mẫu giọng từ bộ dữ liệu ViMD. Bản `m1-v1` dùng lại bảng phân giọng theo tỉnh và giới tính của bộ trước. Mỗi kịch bản dùng cùng một mẫu giọng qua mọi phiên. Bảng kết quả đánh dấu trường hợp giới tính giọng khác với cách xưng hô trong transcript.
3. **Sinh WAV theo lượt.** OmniVoice nhận câu đã chuẩn hóa, mẫu giọng và transcript của mẫu để tạo WAV mono, PCM 16-bit, 24 kHz. Đường dẫn giữ mã kịch bản, mã phiên và thứ tự lượt, ví dụ `audio/SC-001/call_1/SC-001_call_1_turn_001.wav`.
4. **Thêm nhiễu và kiểm tra đầu ra.** Các lượt thuộc `SC-071` đến `SC-100` được trộn với bản ghi âm thanh môi trường từ DEMAND, gồm văn phòng, căng tin, đường phố, nhà bếp, máy giặt và xe buýt. Mỗi phiên dùng một loại nền với tỷ lệ tín hiệu trên nhiễu (SNR) mục tiêu 20, 15 hoặc 10 dB. SNR thực tế được đo theo từng WAV. Pipeline xác minh đủ lượt và đối chiếu checksum trước khi xuất ZIP. [Cách trộn và đo nhiễu](pipeline-augment-audio/README.md)

Kế hoạch `m1-v1` gồm **100 kịch bản, 211 phiên và 805 lượt lời**. Trong đó, **30 kịch bản, 62 phiên và 255 lượt lời** được cấu hình thêm nhiễu nền.

## Chạy bản `m1-v1` trên Kaggle

1. Tải `m1_v1_audio_kaggle_input.zip` từ `outputs/audio-regeneration/m1-v1-kaggle/` lên Kaggle dưới dạng dataset riêng tư và chọn **Add Input**. Script đóng gói tập hợp transcript M1, mẫu giọng ViMD và bản ghi nền DEMAND đã chuẩn bị từ lần chạy trước. [Script đóng gói](../../scripts/package_m1_audio_kaggle.py)
2. Import notebook, bật Internet và GPU. Đặt `MAX_TURNS = 3` để sinh và nghe thử ba lượt đầu. [Notebook M1](pipeline-generate-audio/m1_v1_omnivoice_vietnamese_SC001_SC100_kaggle.ipynb)
3. Đặt lại `MAX_TURNS = None` và chọn **Save Version → Save & Run All**. Khi chạy đủ, tải `audio_SC001_SC100.zip` từ Output. Trong phiên chạy, `clean/audio/` chứa WAV sạch và `result/audio/` chứa bản xuất cuối, gồm audio sạch của `SC-001`–`SC-070` và audio có nhiễu của `SC-071`–`SC-100`.

Trong ZIP, `audio_allocation.csv` giúp tra từng WAV theo kịch bản, phiên, nguồn câu thoại, giọng ViMD và SNR. `audio_manifest.json` lưu thêm câu gốc, câu đọc, thời lượng và SHA-256 của tệp. Nguồn bản ghi nền và ghi chú trộn nằm trong `NOISE_SOURCES.md` và `NOISE_NOTES.md`.

## Notebook cho bộ transcript trước đó

- **Sinh tiếp audio `SC-041`–`SC-100`.** Notebook tạo 402 WAV mới và dùng lại 250 WAV của `SC-001`–`SC-040` sau khi xác minh, cho tổng cộng 652 WAV. [Hướng dẫn chạy tiếp](pipeline-generate-audio/README_SC041_SC100.md)
- **Trộn nhiễu riêng cho `SC-071`–`SC-100`.** Notebook chạy bằng CPU trên máy cá nhân hoặc Kaggle. Với bộ transcript trước đó, bước này xử lý 195 WAV của 60 phiên và xuất bộ có nhiễu vào thư mục riêng. [Hướng dẫn thêm nhiễu](pipeline-augment-audio/README.md)
