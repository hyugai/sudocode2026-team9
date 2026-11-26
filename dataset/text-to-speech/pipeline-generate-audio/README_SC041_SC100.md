# Tạo tiếp audio SC-041–SC-100 trên Kaggle

Dùng `customer_turns_to_omnivoice_vietnamese_vimd_SC041_SC100_kaggle.ipynb`.
Notebook 40 scenario gốc được giữ nguyên.

| Phạm vi | Scenario | Call | WAV lượt khách hàng |
| --- | ---: | ---: | ---: |
| Đã có và xác minh | SC-001–SC-040 | 80 | 250 |
| Cần sinh tiếp | SC-041–SC-100 | 130 | 402 |
| Bộ đầy đủ | SC-001–SC-100 | 210 | 652 |

Các con số trên tính toàn bộ `customer_turns`, bao gồm call hotline, Fanpage và Zalo.
JSON không có lời agent; kết quả là audio từng lượt khách hàng, chưa phải hội thoại hai người.

Từ thư mục gốc repository:

```powershell
python scripts/prepare_audio_continuation.py
```

Script xác minh câu gốc, WAV header và SHA-256 của audio có sẵn; không thay đổi
`dataset/main`. Gói input và bảng phân công được tạo ở `outputs/audio-continuation/`:

- `sc001_sc100_kaggle_input.zip`: 100 JSON, manifest và 250 WAV cũ.
- `SC001_SC100_voice_plan.csv` / `.md`: 40 giọng đã dùng và 60 giọng dự kiến.
- `audio_coverage_before.json`: số call/lượt đã đủ hoặc còn thiếu theo scenario.

Upload ZIP thành Kaggle Dataset, Add Input và import notebook mới. Bật Internet/GPU.
Input có thể còn là ZIP hoặc đã giải nén. Mặc định tự tìm JSON và manifest/audio;
nếu attach nhiều bộ, đặt `DATASET_DIR` và `RESUME_FROM_DIR` rõ ràng.

1. Giữ `RUN_MODE='smoke'`, chạy từ đầu: kiểm tra 250 WAV cũ, chọn giọng SC-041,
   sinh và nghe ba lượt đầu của SC-041.
2. Đổi `RUN_MODE='full'`, chạy lại từ phần 2: sinh 402 lượt mới; dùng lại các lượt
   đã hoàn thành khi fingerprint/checksum khớp. Manifest luôn giữ đủ 652 lượt.
3. Chọn Save Version → Save & Run All ở chế độ full để lưu output phiên hoàn chỉnh.
4. Tải `omnivoice_vietnamese_vimd_SC001_SC100.zip`. Chỉ xuất khi đủ và xác minh mọi WAV.
   Sao lưu manifest cũ rồi giải nén kết quả vào `dataset/main/`.

SC-041–SC-100 luân phiên thứ tự 40 tỉnh của bộ cũ; giới tính theo `honorific` trong JSON.
Một scenario giữ một reference qua mọi call. Tỉnh và speaker có thể lặp giữa scenario.
Đổi từng giọng mới qua `NEW_VOICE_OVERRIDES` trước khi sinh nếu cần.
`voice_assignments.csv` / `.md` trong ZIP kết quả ghi speaker, reference và nhãn ViMD
thực tế; `planned` là chưa sinh, `partial` là chưa đủ lượt, `complete` là đã đủ.

250 WAV cũ không cần các file reference đã mất. Notebook chỉ dùng lại sau khi khớp
câu gốc/câu đọc, cấu hình suy luận, fingerprint, checksum và PCM16 mono/24 kHz.
Sai khác ở SC-001–SC-040 sẽ dừng sớm để giữ bộ cũ. Notebook không sinh lại nhóm này.

Để tiếp tục trong phiên Kaggle mới, attach output mới nhất thay cho bản input cũ,
hoặc trỏ `RESUME_FROM_DIR` tới thư mục/ZIP output đó. Trong cùng session, chỉ cần chạy
lại từ phần 2. Đừng attach đồng thời nhiều manifest mà không chọn đường dẫn cụ thể.

Kiểm tra offline:

```powershell
python scripts/prepare_audio_continuation.py --check-only
python -m unittest discover -s tests -p test_omnivoice_continuation.py -v
```

Các kiểm tra offline không xác nhận chất lượng giọng hay suy luận GPU trên Kaggle.
