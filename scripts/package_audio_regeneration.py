"""Package the prepared audio plan and a Kaggle notebook for remote generation."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from add_background_noise import sha256_file
from regenerate_transcript_audio import DEFAULT_OUTPUT, MAIN, NOTEBOOK, REPO, read_plan


def package(reference_source: Path | None, output: Path, *, inference_config: dict | None = None,
            bundle_name: str = "kaggle_audio_regeneration_input.zip", notebook_path: Path | None = None) -> None:
    plan = read_plan(output)
    source = output / "references"
    bank = json.loads((source / "reference_bank.json").read_text(encoding="utf-8"))
    archive_path = output / bundle_name
    partial_path = archive_path.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ["audio_plan.json", *[f"scenarios_complete/{sid}.json" for sid in plan["scenario_ids"]]]:
            archive.write(output / name, name)
        archive.write(NOTEBOOK, NOTEBOOK.relative_to(REPO).as_posix())
        for name in ["regenerate_transcript_audio.py", "add_background_noise.py"]:
            archive.write(REPO / "scripts" / name, f"scripts/{name}")
        inference = inference_config or json.loads((MAIN / "manifest.json").read_text(encoding="utf-8"))["inference_config"]
        archive.writestr("dataset/main/manifest.json", json.dumps({"inference_config": inference}))
        archive.write(source / "reference_bank.json", "references/reference_bank.json")
        for row in bank.values():
            relative = row["ref_audio_relative"]
            archive.write(output / relative, relative)
        if reference_source is not None:
            archive.write(reference_source / "cache/vimd_metadata.parquet", "cache/vimd_metadata.parquet")
        for file in sorted((output / "runtime/demand16k").rglob("*")):
            if file.is_file() and file.suffix in {".json", ".wav"}:
                archive.write(file, file.relative_to(output).as_posix())
    partial_path.replace(archive_path)
    print(f"Input ZIP: {archive_path} ({len(bank)} verified references)")

    cells = []

    def add(kind: str, source: str) -> None:
        cell = {"cell_type": kind, "id": f"regen-{len(cells):02d}", "metadata": {},
                "source": (source.strip() + "\n").splitlines(keepends=True)}
        if kind == "code":
            compile(source.strip(), "<notebook>", "exec")
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    work_name = plan.get("kaggle_work_dir", "SC001_SC100_regenerated")
    missing = ", ".join(plan["legacy_transcript_scenarios"]) or "không có"
    if plan.get("source_dataset"):
        heading = f"Sinh audio {plan['source_dataset']} trên Kaggle"
        source_note = (f"Lời lấy từ {plan['source_dataset']}, theo tên tệp SC-001.json đến SC-100.json. "
                       "Bảng kết quả ghi cả mã gốc trong JSON và mã tệp. Reference ViMD dùng đúng bảng cũ "
                       "theo mã tệp. Cột xưng hô cho biết khi giới tính giọng khác với transcript. "
                       "Gói input có sẵn reference và nhiễu DEMAND.")
    else:
        heading = "Sinh lại audio SC-001–SC-100"
        source_note = f"Các mã dùng lời từ JSON cũ vì thiếu trong transcript mới gồm {missing}."
    total_calls = len({(row["scenario_id"], row["call_id"]) for row in plan["tasks"]})
    noisy_wavs = sum(row["requires_noise"] for row in plan["tasks"])
    add("markdown", f"""# {heading}

Notebook tạo WAV từ lời khách hàng, dùng bảng giới tính và tỉnh của bộ cũ. SC-071–SC-100
được trộn nền thật DEMAND sau khi sinh WAV sạch. Mỗi lượt khách hàng có một file WAV.

Input gồm {len(plan['scenario_ids'])} kịch bản, {total_calls} cuộc gọi và {len(plan['tasks'])} lượt, trong đó {noisy_wavs} lượt thêm nhiễu.
{source_note}

Upload gói `{bundle_name}` thành Dataset riêng tư rồi chọn Add Input.
Bật Internet và GPU trong Session options. Chạy tất cả các ô. Output gồm ZIP audio và bảng phân bổ.
""")
    add("code", """
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

# Kiểm tra CUDA trong subprocess để pip không đổi thư viện đang được import.
subprocess.check_call([sys.executable, '-c',
    'import torch; assert torch.cuda.is_available(), "Bật GPU trong Session options"; '
    'print(torch.__version__, torch.cuda.get_device_name(0))'])
subprocess.check_call([
    sys.executable, '-m', 'pip', 'install', '--quiet',
    'omnivoice==0.2.1', 'transformers==5.3.0', 'soundfile',
    'pandas', 'pyarrow', 'requests', 'scipy',
])
""")
    add("code", """
from pathlib import PurePosixPath
from hashlib import sha256

INPUTS = Path('/kaggle/input')
WORK = Path('/kaggle/working') / @@WORK_NAME@@
SEED_DIR = Path('/tmp') / WORK.name
INPUT_ZIP = @@INPUT_ZIP@@
PLAN_SHA256 = @@PLAN_SHA256@@
WORK.mkdir(parents=True, exist_ok=True)
files = [path for path in INPUTS.rglob('audio_plan.json')
         if sha256(path.read_bytes()).hexdigest() == PLAN_SHA256]
if len(files) == 1:
    bundle = files[0].parent
elif not files:
    archives = list(INPUTS.rglob(INPUT_ZIP))
    if len(archives) != 1:
        raise RuntimeError(f'Add Input một gói {INPUT_ZIP}.')
    with zipfile.ZipFile(archives[0]) as archive:
        if sha256(archive.read('audio_plan.json')).hexdigest() != PLAN_SHA256:
            raise ValueError('Gói input không khớp với notebook này.')
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if relative.is_absolute() or '..' in relative.parts or chr(92) in info.filename or ':' in info.filename:
                raise ValueError(f'Đường dẫn trong ZIP không hợp lệ: {info.filename}')
            destination = SEED_DIR / Path(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as original, destination.open('wb') as target:
                shutil.copyfileobj(original, target)
    bundle = SEED_DIR
else:
    raise RuntimeError('Có nhiều gói sinh audio. Chỉ giữ một nguồn input.')

for name in ['references', 'scenarios_complete', 'cache', 'runtime']:
    source = bundle / name
    destination = WORK / name
    if source.is_dir():
        for path in source.rglob('*'):
            if path.is_file():
                target = destination / path.relative_to(source)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
shutil.copy2(bundle / 'audio_plan.json', WORK / 'audio_plan.json')
sys.path.insert(0, str(bundle / 'scripts'))
os.environ['HF_HOME'] = '/tmp/regen_audio_hf'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '90'
import regenerate_transcript_audio as pipeline

plan = pipeline.read_plan(WORK)
print('Số WAV dự kiến:', len(plan['tasks']))
""".replace("@@WORK_NAME@@", repr(work_name)).replace("@@INPUT_ZIP@@", repr(bundle_name))
       .replace("@@PLAN_SHA256@@", repr(sha256_file(output / "audio_plan.json"))))
    add("code", """
from huggingface_hub import snapshot_download
import json

if plan.get('source_dataset'):
    bank = json.loads((WORK / 'references/reference_bank.json').read_text(encoding='utf-8'))
    key = pipeline.old_helpers()['province_key']
    bad = [sid for sid, voice in plan['voices'].items()
           if not pipeline.reference_valid(WORK, bank.get(sid), voice, key)]
    if bad:
        raise ValueError(f'Reference tải lên bị thiếu, hỏng hoặc sai nhãn: {bad}. Attach lại gói đúng.')
    print(f'Đã xác minh {len(bank)} reference cũ.')
else:
    pipeline.prepare_references(WORK, WORK, workers=6)
MODEL_DIR = Path('/tmp/regen_audio_model')
snapshot_download(
    'splendor1811/omnivoice-vietnamese',
    revision='f70093f90d78a5b790ff0f066b3629ebcc33cb5d',
    local_dir=MODEL_DIR, allow_patterns=['*.json','*.safetensors','*.jinja'],
)
snapshot_download(
    'k2-fsa/OmniVoice',
    revision='c5fdb5ccb189668d56333f77ba2629f4cd7535f4',
    local_dir=MODEL_DIR, allow_patterns=['audio_tokenizer/**'],
)
""")
    add("code", """
NUM_STEPS = 16
MAX_TURNS = None  # Đặt 3 để thử. Đặt lại None rồi chạy lại ô này để sinh đủ.
pipeline.generate(WORK, MODEL_DIR, limit=MAX_TURNS, num_steps=NUM_STEPS)
""")
    add("code", """
if MAX_TURNS is None:
    pipeline.finalize(WORK, WORK / 'runtime/demand16k')
    print(WORK / 'audio_SC001_SC100.zip')
    print(WORK / 'result/audio_allocation.csv')
    print(WORK / 'result/audio_allocation.md')
else:
    from IPython.display import Audio, display
    for row in plan['tasks'][:MAX_TURNS]:
        wav = WORK / 'clean' / row['path']
        if wav.is_file():
            print(row['task_id'])
            display(Audio(filename=str(wav)))
""")
    add("markdown", f"""
Trong Kaggle dùng **Save Version → Save & Run All** để lưu kết quả cả phiên.
File `{work_name}/audio_SC001_SC100.zip` chỉ xuất hiện khi đã xác minh đủ WAV.
Bảng audio_allocation.csv ghi nguồn lời, giọng mẫu ViMD và SNR từng lượt có nền.
""")
    target = notebook_path or output / "regenerate_SC001_SC100_Kaggle.ipynb"
    notebook = {
        "cells": cells, "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3", "language": "python"}},
    }
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Kaggle notebook: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    package(args.reference_source, args.output)
