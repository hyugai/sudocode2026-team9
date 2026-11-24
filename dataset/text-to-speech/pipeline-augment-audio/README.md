# Thêm nền thực tế cho SC-071–SC-100

Mở `add_real_background_noise_SC071_SC100.ipynb`. Đây là notebook độc lập, chạy bằng CPU
trên local hoặc Kaggle, có toàn bộ hàm xử lý bên trong, không cần model TTS/ASR.

Đầu vào hiện tại có **195 WAV / 60 cuộc gọi / 30 scenario**, mono PCM16 / 24 kHz.
Pipeline áp dụng cho toàn bộ audio lượt khách hàng của nhóm này, kể cả các call mà
JSON gốc ghi kênh Fanpage hoặc Zalo. Các trường kịch bản và transcript giữ nguyên.

| Mã DEMAND | Nền được ghi âm | Cuộc gọi | WAV |
| --- | --- | ---: | ---: |
| OOFFICE | Văn phòng có người sử dụng máy tính | 10 | 32 |
| PCAFETER | Căng tin văn phòng đông người | 10 | 33 |
| STRAFFIC | Ngã tư đông xe cộ | 10 | 31 |
| DKITCHEN | Nhà bếp đang chuẩn bị thức ăn | 10 | 33 |
| DWASHING | Máy giặt cửa trước đang hoạt động | 10 | 33 |
| TBUS | Bên trong xe buýt công cộng | 10 | 33 |

Nhãn trên mô tả môi trường của bản ghi nguồn. Không gán nhãn từng tiếng còi, tiếng
bàn phím hay tiếng người cho mọi đoạn nếu chưa nghe/annotate riêng. Tiếng người nền
trong một số nguồn không được bảo đảm là tiếng Việt.

Nguồn chính thức: [DEMAND](https://zenodo.org/records/1227121), Joachim Thiemann,
Nobutaka Ito và Emmanuel Vincent, DOI `10.5281/zenodo.1227121`.
Bản ghi nhiễu có giấy phép CC BY-SA 3.0; nguồn, giấy phép, SHA-256 và các biến đổi được
ghi trong `NOISE_SOURCES.md` và manifest. WAV khách hàng giữ nguồn/giấy phép riêng.

## Cách trộn và cách đọc mức nhiễu

- Lấy một kênh thật `ch01.wav` từ mỗi bản ghi DEMAND 16 kHz, kiểm tra CRC32/SHA-256,
  bỏ DC và resample nền sang 24 kHz. Giọng khách hàng giữ số mẫu và sample rate gốc.
- Mỗi cuộc gọi giữ một loại nền và một hệ số trộn; các lượt lấy những đoạn liên tiếp
  trong bản ghi 300 giây, với khoảng nghỉ giả lập 0.75 giây. Không lặp đoạn ngắn.
- SNR mục tiêu là **20, 15 hoặc 10 dB**, mỗi mức có 20 cuộc gọi. SNR cao hơn nghĩa
  là nền nhẹ hơn. Đo năng lượng trên frame 20 ms có tiếng nói theo ngưỡng -35 dB
  so với frame mạnh nhất; đây là energy gate, không phải mô hình VAD.
- Do nền thực tế biến thiên, SNR của từng lượt có thể khác SNR mục tiêu của cuộc gọi.
  `actual_active_snr_db` được đo trên WAV PCM16 đã ghi, tách theo gain giọng đã lưu.
- Nếu tổng biên độ quá cao, giảm cùng một gain cho cả giọng và nền để peak <= 0.97.
  Hệ số giảm được ghi trong `common_gain_db`, không hard-clip waveform.

## Chạy local

Từ repository, với môi trường có NumPy, SciPy và Requests:

```powershell
.venv/Scripts/python.exe scripts/add_background_noise.py
```

Mặc định đọc `dataset/main/audio/` và `dataset/main/scenarios_complete/`.
Kết quả ở **`dataset/main/noisy_SC071_SC100/`**, gồm:

- `audio/SC-071`–`audio/SC-100`: 195 WAV có nền, giữ tên và thứ tự file.
- `NOISE_NOTES.md`: bảng ghi chú đầy đủ từng WAV và đoạn nhiễu được dùng.
- `noise_manifest.csv`: một dòng mỗi WAV, dễ lọc theo scenario/cuộc gọi/loại nền.
- `noise_manifest.json` / `.jsonl`: checksum, offset, seed, gain, SNR và nguồn.
- `NOISE_SOURCES.md`: attribution, giấy phép và biến đổi của bản ghi nền.
- `validation.json`: kiểm tra nguồn, định dạng, số mẫu, checksum, peak và SNR.
- `noisy_SC071_SC100.zip`: 195 WAV và các báo cáo trên.

`generated` nghĩa là mới trộn; `resumed` nghĩa là đã xác minh và dùng lại WAV cùng
fingerprint/checksum. Khi một lượt nguồn đổi, tính lại hệ số nền và fingerprint cả
cuộc gọi để giữ mức nền nhất quán. Lượt lỗi được ghi rõ và chặn xuất ZIP hoàn chỉnh.

## Chạy trên Kaggle

Gói input đã chuẩn bị ở `outputs/noise-augmentation/sc071_sc100_noise_input.zip`.
Gói này chứa 30 JSON, 195 WAV sạch và sáu bản ghi nền có checksum, không cần tải lại.

1. Upload ZIP thành Kaggle Dataset và Add Input vào notebook.
2. Import `add_real_background_noise_SC071_SC100.ipynb`, giữ các đường dẫn `None`.
3. Chọn Run All. CPU đủ dùng; khi đã có bank trong input thì không cần Internet.
4. Xem `NOISE_NOTES.md` và các cặp nghe trước/sau ở cuối notebook.
5. Lưu version/output trên Kaggle; tải `noisy_SC071_SC100/noisy_SC071_SC100.zip`.

Nếu chỉ attach audio/JSON, bật Internet để lấy nguồn DEMAND. Nếu có nhiều bộ input,
đặt `INPUT_ROOT` tới thư mục chứa trực tiếp `audio/` và `scenarios_complete/`.
Khi input còn là ZIP, notebook giải nén vào vùng tạm; khi đã giải nén thì đọc trực tiếp.

Để tự đóng lại gói input local:

```powershell
.venv/Scripts/python.exe scripts/add_background_noise.py --prepare-input-zip outputs/noise-augmentation/sc071_sc100_noise_input.zip
```

## Kiểm tra và bảo trì

```powershell
.venv/Scripts/python.exe scripts/build_noise_notebook.py
.venv/Scripts/python.exe -m unittest discover -s tests -p test_background_noise.py -v
```

Notebook nhúng code từ `scripts/add_background_noise.py`; chạy lại builder sau khi
sửa module. Các test không gọi mạng, kiểm tra SNR, tránh clipping, resume, provenance,
phạm vi scenario và việc notebook khớp module đã kiểm tra. Chất lượng lời/accent và
độ phù hợp ngữ cảnh vẫn cần kiểm tra nghe/ASR riêng.
