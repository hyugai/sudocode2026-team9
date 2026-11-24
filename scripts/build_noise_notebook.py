"""Build the standalone, local/Kaggle background-noise notebook from its tested module."""

from __future__ import annotations

import ast
import json
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
DESTINATION = REPOSITORY / "dataset/text-to-speech/pipeline-augment-audio/add_real_background_noise_SC071_SC100.ipynb"


def build_notebook() -> Path:
    source = (REPOSITORY / "scripts/add_background_noise.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    embedded = "\n".join(source.splitlines()[:main.lineno - 1]).replace("import argparse\n", "").rstrip() + "\n"
    cells = []

    def add(kind: str, body: str) -> None:
        cell = {"cell_type": kind, "id": f"noise-{len(cells):02d}", "metadata": {},
                "source": (body.strip() + "\n").splitlines(keepends=True)}
        if kind == "code":
            compile("".join(cell["source"]), str(DESTINATION), "exec")
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    add("markdown", """# Thêm nhiễu nền thực tế cho SC-071–SC-100

Tạo **195 WAV có nhiễu / 60 cuộc gọi / 30 scenario**, từ các WAV khách hàng đã sinh.
Dùng các bản ghi môi trường thật **DEMAND**, không tạo nhiễu trắng thay thế.
Kết quả nằm trong thư mục riêng, giữ tên file và cấu trúc `audio/SC-xxx/call_x/`.
Mỗi WAV giữ đúng sample rate 24 kHz, mono PCM16, số mẫu và thứ tự lượt gốc.

**Chạy trên Kaggle:** upload `sc071_sc100_noise_input.zip` thành Dataset, Add Input,
import notebook này rồi **Run All**. CPU đủ dùng; không cần GPU. Gói input đã kèm sáu
bản ghi nền và checksum nên có thể chạy không tải lại. Nếu chỉ attach audio/JSON,
bật Internet để notebook tự lấy các bản ghi từ Zenodo.

**Chạy local:** mở notebook từ repository, giữ các đường dẫn `None` và Run All.
Hoặc đặt `INPUT_ROOT` tới thư mục chứa trực tiếp `audio/` và `scenarios_complete/`.

Output: `audio/`, `noise_manifest.json/csv/jsonl`, **`NOISE_NOTES.md` ghi từng file**,
`NOISE_SOURCES.md`, `validation.json` và `noisy_SC071_SC100.zip`.
Chỉ xử lý SC-071–SC-100, bao gồm mọi customer_turns của mọi kênh có WAV.
Không sửa `input_mode`, transcript, các JSON đánh giá hoặc manifest TTS gốc.

Nguồn: [DEMAND, Thiemann–Ito–Vincent](https://zenodo.org/records/1227121),
giấy phép bản ghi nền **CC BY-SA 3.0**, attribution và các biến đổi được ghi trong output.
Một số môi trường có tiếng người nền; không bảo đảm đó là tiếng Việt.
Nhãn mô tả môi trường được ghi âm, không phải nhận diện từng sự kiện trong từng đoạn.
""")
    add("markdown", """## 1. Dependency

Chỉ dùng NumPy, SciPy và Requests. Ô này chỉ cài package còn thiếu; không tải model TTS/ASR.
""")
    add("code", """import importlib.util
from pathlib import Path
import subprocess
import sys

missing = [name for name in ['numpy', 'scipy', 'requests'] if importlib.util.find_spec(name) is None]
if missing:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
print('Python:', sys.version.split()[0])
print('Xử lý bằng CPU; không cần model hoặc GPU.')
""")
    add("markdown", """## 2. Cấu hình và tìm input

`INPUT_ROOT=None`: tìm thư mục `dataset/main` khi chạy local hoặc input Kaggle.
Input ZIP được đọc vào vùng tạm. `NOISE_DIR=None`: ưu tiên bank trong gói input,
sau đó cache local/tạm. `OUTPUT_DIR=None`: `dataset/main/noisy_SC071_SC100` ở local,
hoặc `/kaggle/working/noisy_SC071_SC100` trên Kaggle.

SNR mục tiêu 20/15/10 dB được phân bổ đều cho 60 cuộc gọi: cao hơn nghĩa là nền nhẹ hơn.
Mỗi cuộc gọi dùng cùng một nền và hệ số trộn. Các lượt lấy đoạn liên tiếp, có khoảng nghỉ
giả lập 0.75 giây; không lặp nguồn ngắn. Peak <= 0.97 bằng cách giảm gain chung của cả
giọng và nền khi cần, tránh vỡ tiếng. SNR thực tế từng file được đo sau ghi PCM16.
""")
    add("code", r"""import json
import shutil
import tempfile
import zipfile
from pathlib import PurePosixPath

INPUT_ROOT = None  # Path('/kaggle/input/<dataset>') hoặc đường dẫn local.
OUTPUT_DIR = None
NOISE_DIR = None
BASE_SEED = 20261118
SNR_LEVELS_DB = (20.0, 15.0, 10.0)
PEAK_CEILING = 0.97
EXPORT_ZIP = True

ON_KAGGLE = Path('/kaggle/input').is_dir() and Path('/kaggle/working').is_dir()
RUNTIME_DIR = Path(tempfile.gettempdir()) / 'sc071_sc100_noise_runtime'
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

def find_input_root(configured=None):
    def valid(root):
        return all((root / 'scenarios_complete' / f'SC-{i:03d}.json').is_file()
                   and (root / 'audio' / f'SC-{i:03d}').is_dir() for i in range(71, 101))
    if configured is not None:
        root = Path(configured)
        if not valid(root):
            raise FileNotFoundError(f'INPUT_ROOT phải chứa audio/ và scenarios_complete/ đủ SC-071–SC-100: {root}')
        return root.resolve()
    if not ON_KAGGLE:
        for parent in [Path.cwd(), *Path.cwd().parents]:
            root = parent / 'dataset' / 'main'
            if valid(root):
                return root.resolve()
        raise FileNotFoundError('Mở notebook từ repository hoặc đặt INPUT_ROOT rõ ràng.')
    search = Path('/kaggle/input')
    roots = sorted({p.parent.parent for p in search.rglob('SC-071')
                    if p.is_dir() and p.parent.name == 'audio' and valid(p.parent.parent)})
    if len(roots) == 1:
        return roots[0]
    if len(roots) > 1:
        raise ValueError(f'Có nhiều input audio: {roots}. Đặt INPUT_ROOT rõ ràng.')
    archives = []
    for path in search.rglob('*.zip'):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for name in names:
                if name.endswith('scenarios_complete/SC-071.json'):
                    prefix = name[:-len('scenarios_complete/SC-071.json')]
                    if all(prefix + f'scenarios_complete/SC-{i:03d}.json' in names for i in range(71, 101)):
                        archives.append((path, prefix))
    if len(archives) != 1:
        raise ValueError(f'Cần một gói input SC-071–SC-100, tìm thấy {archives}. Add Input đúng ZIP hoặc giải nén và đặt INPUT_ROOT.')
    path, prefix = archives[0]
    destination = RUNTIME_DIR / 'input'
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = PurePosixPath(info.filename[len(prefix):])
            if (relative.is_absolute() or '..' in relative.parts or chr(92) in str(relative)
                    or ':' in str(relative)):
                raise ValueError('Đường dẫn ZIP không an toàn.')
            if not relative.parts or relative.parts[0] not in {'audio', 'scenarios_complete', 'noise_sources'}:
                continue
            if info.file_size > 128 * 1024 ** 2:
                raise ValueError('File input quá lớn so với định dạng dự kiến.')
            target = destination / str(relative)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Đường dẫn input nằm ngoài vùng tạm.')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    if not valid(destination):
        raise FileNotFoundError('ZIP thiếu audio/ hoặc JSON của SC-071–SC-100.')
    return destination

INPUT_ROOT = find_input_root(INPUT_ROOT)
if OUTPUT_DIR is None:
    OUTPUT_DIR = (Path('/kaggle/working') if ON_KAGGLE else INPUT_ROOT) / 'noisy_SC071_SC100'
OUTPUT_DIR = Path(OUTPUT_DIR)
if NOISE_DIR is None:
    attached_bank = INPUT_ROOT / 'noise_sources' / 'demand16k'
    if (attached_bank / 'noise_bank.json').is_file():
        NOISE_DIR = attached_bank
    elif not ON_KAGGLE:
        NOISE_DIR = INPUT_ROOT.parent / 'text-to-speech' / 'noise_sources' / 'demand16k'
    else:
        NOISE_DIR = RUNTIME_DIR / 'demand16k'
NOISE_DIR = Path(NOISE_DIR)
print('Input:', INPUT_ROOT)
print('Nhiễu thật:', NOISE_DIR)
print('Output:', OUTPUT_DIR)
""")
    add("markdown", """## 3. Hàm tải nguồn, trộn và ghi báo cáo

Ô dưới chứa toàn bộ pipeline, chạy độc lập không cần upload file `.py` từ repository.
Chỉ tải kênh `ch01.wav` của sáu bản ghi DEMAND, kiểm tra CRC32 và SHA-256,
giữ metadata và giấy phép nguồn. Tải lỗi sẽ dừng; không thay bằng nhiễu tổng hợp.
WAV đã có chỉ được dùng lại khi fingerprint input/cấu hình và checksum output khớp.
""")
    add("code", embedded)
    add("markdown", """## 4. Kiểm tra danh sách trước khi trộn

Các nhãn: văn phòng, căng tin đông người, giao thông, nhà bếp, máy giặt và xe buýt.
Bản đầy đủ có 195 WAV; mỗi loại nền dùng cho 10 cuộc gọi.
""")
    add("code", """from collections import Counter

CALL_PLAN = build_calls(INPUT_ROOT, snr_levels_db=SNR_LEVELS_DB)
print('Số cuộc gọi:', len(CALL_PLAN))
print('Số WAV:', sum(len(call['tasks']) for call in CALL_PLAN))
print('Loại nền theo cuộc gọi:', dict(Counter(call['noise_code'] for call in CALL_PLAN)))
print('SNR mục tiêu theo cuộc gọi:', dict(Counter(call['target_call_snr_db'] for call in CALL_PLAN)))
""")
    add("markdown", """## 5. Thêm nhiễu vào đủ SC-071–SC-100

Chỉ ghi vào output riêng. Khi bị gián đoạn, chạy lại cùng cấu hình để dùng lại file đã xác minh.
Mọi file lỗi được ghi vào manifest và chặn export ZIP đầy đủ.
""")
    add("code", """MANIFEST = run_pipeline(
    INPUT_ROOT, OUTPUT_DIR, NOISE_DIR,
    base_seed=BASE_SEED, snr_levels_db=SNR_LEVELS_DB,
    peak_ceiling=PEAK_CEILING, export_zip=EXPORT_ZIP,
)
""")
    add("markdown", """## 6. Xem ghi chú từng WAV và nghe trước/sau

`NOISE_NOTES.md` liệt kê mọi file. `noise_manifest.csv` có thêm checksum nguồn/đích,
file nhiễu, URL nguồn, offset, hệ số trộn, gain và SNR đo trên WAV đã ghi.
Kiểm tra kỹ nội dung/độ rõ lời bằng nghe hoặc ASR riêng; pipeline kiểm tra tín hiệu và tính toàn vẹn.
""")
    add("code", """from IPython.display import Audio, Markdown, display

display(Markdown((OUTPUT_DIR / 'NOISE_NOTES.md').read_text(encoding='utf-8')))
for row in list(MANIFEST['results'].values())[:3]:
    print(row['task_id'], row['noise_note_vi'])
    print('Trước:')
    display(Audio(filename=str(INPUT_ROOT / row['input_relative'])))
    print('Sau:')
    display(Audio(filename=str(OUTPUT_DIR / row['output_relative'])))
""")
    add("markdown", """## 7. Tải kết quả

Trên Kaggle, mở Output và tải `noisy_SC071_SC100/noisy_SC071_SC100.zip`.
ZIP chứa 195 WAV đã thêm nền và báo cáo theo từng file, không trộn lẫn với input sạch.
Để lưu phiên Kaggle đầy đủ, dùng Save Version → Save & Run All; phiên mới đọc lại input đã attach.
Không giải nén ZIP đè lên `dataset/main/audio` nếu vẫn cần so sánh với bản sạch.
""")
    add("code", """validation = json.loads((OUTPUT_DIR / 'validation.json').read_text(encoding='utf-8'))
print(json.dumps(validation, ensure_ascii=False, indent=2))
print('ZIP:', OUTPUT_DIR / 'noisy_SC071_SC100.zip')
print('Bảng từng WAV:', OUTPUT_DIR / 'noise_manifest.csv')
print('Ghi chú dễ đọc:', OUTPUT_DIR / 'NOISE_NOTES.md')
""")
    notebook = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                             "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return DESTINATION


if __name__ == "__main__":
    print(build_notebook())
