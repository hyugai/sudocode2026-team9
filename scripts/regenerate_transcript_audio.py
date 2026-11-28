"""Regenerate the SC-001..SC-100 customer audio from a transcript JSONL."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import shutil
import time
import unicodedata
import wave
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from add_background_noise import assign_noise, atomic_json, pcm_info, sha256_file, signature

REPO = Path(__file__).resolve().parents[1]
MAIN = REPO / "dataset/main"
DEFAULT_OUTPUT = REPO / "outputs/audio-regeneration"
NOTEBOOK = REPO / (
    "dataset/text-to-speech/pipeline-generate-audio/"
    "customer_turns_to_omnivoice_vietnamese_vimd_SC041_SC100_kaggle.ipynb"
)
IDS = [f"SC-{number:03d}" for number in range(1, 101)]
REFERENCE_LICENSE = "CC-BY-NC-ND-4.0"


def old_helpers() -> dict:
    """Load only selected definitions from the established generation notebook."""
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    names = {"VOICE_ROWS", "DIGITS", "province_key", "read_triplet", "read_integer",
             "normalize_spoken_text", "AudioGroupReader", "audio_metrics",
             "reference_duration_is_valid", "get_voice_prompt", "infer_with_full_reference"}
    namespace = {
        "re": __import__("re"), "unicodedata": unicodedata, "Path": Path,
        "NORMALIZE_NUMBERS": True, "PRONUNCIATION_REPLACEMENTS": {"COD": "si ô đi"},
        "REF_MIN_SECONDS": 15.0, "REF_MAX_SECONDS": 20.0,
        "fingerprint": signature, "file_sha256": sha256_file,
    }
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        nodes = [node for node in tree.body if (
            isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        )]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
    return namespace


def read_transcripts(path: Path) -> dict:
    records = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        sid = record["scenario_id"]
        if sid in records:
            raise ValueError(f"Duplicate {sid} in {path.name}, line {line_number}")
        records[sid] = record
    return records


def transcript_calls(payload: dict) -> dict:
    import re

    if "calls" in payload:
        return payload["calls"]
    return {key: value for key, value in payload.items() if re.fullmatch(r"call_\d+", key)}


def plan_turns(sid: str, calls: dict, source: str, source_file: str, requires_noise: bool,
               normalize) -> tuple[list[dict], dict]:
    import re

    if not isinstance(calls, dict) or not calls:
        raise ValueError(f"{sid}: no calls in {source_file}")
    tasks, export_calls = [], {}
    for cid, call in calls.items():
        if not re.fullmatch(r"call_\d+", cid) or not isinstance(call, dict):
            raise ValueError(f"{sid}: invalid call {cid!r}")
        turns = call["customer_turns"]
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"{sid}/{cid}: missing customer_turns")
        for index, text in enumerate(turns, 1):
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{sid}/{cid}/{index}: empty or non-text customer turn")
            tasks.append({
                "task_id": f"{sid}/{cid}/{index-1}", "scenario_id": sid, "call_id": cid,
                "turn": index, "channel": call.get("channel"), "text_original": text,
                "text_tts": normalize(text), "transcript_source": source, "source_file": source_file,
                "path": f"audio/{sid}/{cid}/{sid}_{cid}_turn_{index:03d}.wav",
                "requires_noise": requires_noise,
            })
        export_calls[cid] = {"channel": call.get("channel"), "customer_turns": turns}
    return tasks, export_calls


def prepare_plan(transcript: Path, output: Path, supplement: Path | None = None) -> dict:
    incoming = read_transcripts(transcript)
    sources = {sid: transcript.name for sid in incoming}
    if supplement:
        additional = read_transcripts(supplement)
        overlap = (incoming.keys() & additional.keys()) & set(IDS)
        if overlap:
            raise ValueError(f"Supplement duplicates rows in the main transcript: {sorted(overlap)}")
        incoming.update(additional)
        sources.update({sid: supplement.name for sid in additional})
    helpers = old_helpers()
    original_voices = helpers["VOICE_ROWS"]
    plan = {"scenario_ids": IDS, "new_transcript_scenarios": [], "legacy_transcript_scenarios": [],
            "transcript_sha256": sha256_file(transcript), "ignored_ids": sorted(incoming.keys() - set(IDS)),
            "voices": {}, "tasks": []}
    if supplement:
        plan["supplement_sha256"] = sha256_file(supplement)
    scenario_dir = output / "scenarios_complete"
    for number, sid in enumerate(IDS, 1):
        original_path = MAIN / "scenarios_complete" / f"{sid}.json"
        original = json.loads(original_path.read_text(encoding="utf-8-sig"))
        if number <= 40:
            _, gender, province, region = original_voices[number - 1]
        else:
            _, _, province, region = original_voices[(number - 41) % 40]
            gender = {"chị": "Nữ", "anh": "Nam"}[original["honorific"]]
        plan["voices"][sid] = {"gender": gender, "gender_id": int(gender == "Nam"),
                               "province": province, "province_key": helpers["province_key"](province),
                               "region": region}
        if sid in incoming:
            calls = transcript_calls(incoming[sid])
            source = "new_transcript"
            source_file = sources[sid]
        else:
            calls = original["calls"]
            source = "legacy_scenario"
            source_file = f"scenarios_complete/{sid}.json"
        plan[f"{'new' if sid in incoming else 'legacy'}_transcript_scenarios"].append(sid)
        tasks, export_calls = plan_turns(sid, calls, source, source_file, number >= 71,
                                        helpers["normalize_spoken_text"])
        plan["tasks"].extend(tasks)
        atomic_json(scenario_dir / f"{sid}.json", {"scenario_id": sid, "calls": export_calls})
    atomic_json(output / "audio_plan.json", plan)
    print(f"{len(plan['tasks'])} WAV / {len({(r['scenario_id'], r['call_id']) for r in plan['tasks']})} calls, "
          f"{len(plan['legacy_transcript_scenarios'])} scenarios using legacy text.", flush=True)
    return plan


def read_plan(output: Path) -> dict:
    return json.loads((output / "audio_plan.json").read_text(encoding="utf-8"))


def has_full_scale_sample(path: Path) -> bool:
    import numpy as np

    with wave.open(str(path), "rb") as stream:
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    return bool(np.any((pcm == -32768) | (pcm == 32767)))


def reference_valid(root: Path, row: dict | None, voice: dict, province_key) -> bool:
    if not row or row.get("gender") != voice["gender_id"]:
        return False
    if province_key(row.get("province_name", "")) != voice["province_key"]:
        return False
    path = root / row["ref_audio_relative"]
    if not path.is_file() or sha256_file(path) != row.get("audio_sha256"):
        return False
    info = pcm_info(path)
    return info["sample_rate"] == 24000 and 15 <= info["frames"] / 24000 <= 20


def prepare_references(output: Path, source: Path, workers: int, reuse_only: bool = False) -> None:
    voices = read_plan(output)["voices"]
    helpers = old_helpers()
    province_key = helpers["province_key"]
    bank_file = output / "references/reference_bank.json"
    ready = json.loads(bank_file.read_text(encoding="utf-8")) if bank_file.is_file() else {}
    old_bank = json.loads((source / "references/reference_bank.json").read_text(encoding="utf-8"))

    def reuse(sid, old_sid, old_row):
        path = f"references/{sid}/reference.wav"
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / old_row["ref_audio_relative"], destination)
        return {**old_row, "scenario_id": sid, "ref_audio_relative": path, "reused_reference_from": old_sid}

    for sid, voice in voices.items():
        if reference_valid(output, ready.get(sid), voice, province_key):
            continue
        if reference_valid(source, old_bank.get(sid), voice, province_key):
            ready[sid] = reuse(sid, sid, old_bank[sid])
            continue
        for old_sid, old_row in old_bank.items():
            if reference_valid(source, old_row, voice, province_key):
                ready[sid] = reuse(sid, old_sid, old_row)
                break
    atomic_json(bank_file, ready)
    print(f"{len(ready)} original or cached reference WAVs verified.", flush=True)
    missing = [sid for sid, voice in voices.items() if not reference_valid(output, ready.get(sid), voice, province_key)]
    if not missing or reuse_only:
        return
    import gc
    import io

    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import HfFileSystem
    from scipy.signal import resample_poly

    helpers.update(gc=gc, io=io, pq=pq, sf=sf, np=np)

    class ReferenceFileSystem(HfFileSystem):
        def open(self, path, mode="rb", **kwargs):
            # PyArrow can request a whole audio column in one read. Bound each
            # HTTP range so an interrupted transfer retries a small block.
            kwargs.update(block_size=8 * 1024 ** 2, cache_type="blockcache",
                          cache_options={"maxblocks": 4})
            return super().open(path, mode, **kwargs)

    metadata = pd.read_parquet(source / "cache/vimd_metadata.parquet")
    metadata["province_key"] = metadata.province_name.map(province_key)
    metadata["distance"] = (metadata.text.fillna("").str.split().str.len() - 60).abs()
    plans = {}
    for sid in missing:
        voice = voices[sid]
        pool = metadata[(metadata.province_key == voice["province_key"])
                        & (metadata.gender.astype(int) == voice["gender_id"])]
        pool = pool[pool.text.notna() & pool.text.str.strip().ne("") & pool.speakerID.notna()]
        pool = pool.sort_values(["distance", "filename", "split"], kind="stable")
        if pool.empty:
            raise ValueError(f"{sid}: no ViMD records for {voice}")
        plans[sid] = pool

    def select(sid):
        reader = helpers["AudioGroupReader"](ReferenceFileSystem())
        pool = plans[sid]
        skipped = []
        for (parquet, group), _ in list(pool.groupby(["source_parquet", "row_group"], sort=False))[:12]:
            group_pool = pool[(pool.source_parquet == parquet) & (pool.row_group == group)]
            candidate = None
            for row in group_pool.to_dict("records"):
                waveform, sample_rate = reader.get(row)
                metrics = helpers["audio_metrics"](waveform, sample_rate)
                if not 15 <= metrics["duration_seconds"] <= 20:
                    continue
                if metrics["rms"] < 0.005 or metrics["clipping_fraction"] > 0.01:
                    continue
                rank = (abs(metrics["duration_seconds"] - 17), row["filename"])
                if candidate is None or rank < candidate[0]:
                    candidate = rank, row, waveform, sample_rate, metrics
            if candidate is None:
                skipped.append(f"{parquet}:{group}")
                continue
            _, row, waveform, sample_rate, metrics = candidate
            divisor = math.gcd(sample_rate, 24000)
            audio = resample_poly(waveform, 24000 // divisor, sample_rate // divisor)
            relative = f"references/{sid}/reference.wav"
            path = output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".partial.wav")
            sf.write(temp, audio, 24000, subtype="PCM_16")
            temp.replace(path)
            fields = ["filename", "speakerID", "province_name", "region", "split", "source_parquet"]
            return {**{key: row[key] for key in fields}, "scenario_id": sid,
                    "gender": int(row["gender"]), "row_group": int(row["row_group"]),
                    "row_in_group": int(row["row_in_group"]), "ref_audio_relative": relative,
                    "ref_text_tts": row["text"].strip(), "audio_sha256": sha256_file(path), "metrics": metrics}
        raise ValueError(f"{sid}: no valid ViMD reference among {len(skipped)} groups")

    def choose(sid):
        voice = voices[sid]
        for attempt in range(2):
            try:
                return sid, select(sid), None
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt == 0:
                    time.sleep(2)
        return sid, None, error

    failures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(choose, sid) for sid in missing]):
            sid, reference, error = future.result()
            if reference:
                ready[sid] = reference
                atomic_json(bank_file, ready)
                print(f"{sid}: {reference['filename']} ({len(ready)}/100)", flush=True)
            else:
                failures[sid] = error
                print(f"{sid}: {error}", flush=True)
    atomic_json(output / "reference_errors.json", failures)
    if failures:
        raise RuntimeError(f"{len(failures)} references missing; see reference_errors.json")


def generate(output: Path, model_dir: Path, limit: int | None, num_steps: int, batch_size: int = 4) -> None:
    import random

    import numpy as np
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig

    plan = read_plan(output)
    helpers = old_helpers()
    config = json.loads((MAIN / "manifest.json").read_text(encoding="utf-8"))["inference_config"]
    config["generation_options"]["num_step"] = num_steps
    helpers.update(np=np, sf=sf, torch=torch, LANGUAGE_ID=config["language"], SPEED=config["speed"],
                   GENERATION_OPTIONS=config["generation_options"], engine_configuration=lambda: config)

    bank_file = output / "references/reference_bank.json"
    manifest_path = output / "render_manifest.json"
    results = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    if not torch.cuda.is_available():
        raise RuntimeError("OmniVoice generation requires a working PyTorch CUDA runtime for this run.")
    print(f"Loading model on {torch.cuda.get_device_name(0)} with {num_steps} sampling steps", flush=True)
    engine = OmniVoice.from_pretrained(str(model_dir), device_map="cuda:0", dtype=torch.float16,
                                       attn_implementation="sdpa", load_asr=False)
    engine.eval()
    if engine.sampling_rate != 24000:
        raise ValueError("Expected 24 kHz OmniVoice model")
    generation_config = OmniVoiceGenerationConfig(**config["generation_options"])

    clean = output / "clean"
    started = time.monotonic()
    active = 0
    tasks = plan["tasks"][:limit] if limit is not None else plan["tasks"]
    if batch_size < 1:
        raise ValueError("Batch size must be positive")
    for position in range(0, len(tasks), batch_size * 8):
        bank = json.loads(bank_file.read_text(encoding="utf-8"))
        pending = []
        for task in tasks[position:position + batch_size * 8]:
            sid, key = task["scenario_id"], task["task_id"]
            reference = bank.get(sid)
            if not reference:
                continue
            path = clean / task["path"]
            seed = (config["base_seed"] + int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)) % (2 ** 31)
            fingerprint = signature({"text_tts": task["text_tts"], "ref": reference["audio_sha256"],
                                     "ref_text": reference["ref_text_tts"], "seed": seed, "config": config})
            existing = results.get(key, {})
            if (existing.get("fingerprint") == fingerprint and existing.get("status") == "generated"
                    and path.is_file() and sha256_file(path) == existing.get("sha256")
                    and not has_full_scale_sample(path)):
                continue
            pending.append({**task, "fingerprint": fingerprint, "sampling_steps": num_steps, "seed": seed,
                            "reference_sha256": reference["audio_sha256"]})
        pending.sort(key=lambda item: len(item["text_tts"]))
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            seed = batch[0]["seed"]
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            try:
                prompts = []
                for row in batch:
                    reference = bank[row["scenario_id"]]
                    prompt, _ = helpers["get_voice_prompt"](
                        engine, output / reference["ref_audio_relative"], reference["ref_text_tts"])
                    prompts.append(prompt)
                with torch.inference_mode():
                    audios = engine.generate(text=[row["text_tts"] for row in batch], language=config["language"],
                                             speed=config["speed"], voice_clone_prompt=prompts,
                                             generation_config=generation_config, normalize_text=False)
                if len(audios) != len(batch):
                    raise ValueError("Model returned the wrong batch size")
            except Exception as exc:
                print(f"Batch failed ({type(exc).__name__}); retrying each turn separately", flush=True)
                audios = None
            if audios is None:
                torch.cuda.empty_cache()
            for index, row in enumerate(batch):
                key = row["task_id"]
                path = clean / row["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".partial.wav")
                try:
                    if audios is None:
                        reference = bank[row["scenario_id"]]
                        audio, _, _ = helpers["infer_with_full_reference"](
                            engine, ref_file=output / reference["ref_audio_relative"],
                            ref_text=reference["ref_text_tts"], gen_text=row["text_tts"], seed=row["seed"])
                        row["batch_seed"] = row["seed"]
                    else:
                        audio = audios[index]
                        row["batch_seed"] = seed
                    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                        raise ValueError("Invalid model waveform")
                    peak = float(np.max(np.abs(audio)))
                    if peak < 1e-6:
                        raise ValueError("Silent model waveform")
                    render_gain = min(1.0, 0.97 / peak)
                    sf.write(temporary, audio * render_gain, 24000, subtype="PCM_16")
                    info = pcm_info(temporary)
                    temporary.replace(path)
                    row.update(status="generated", sha256=sha256_file(path), duration_seconds=info["frames"] / 24000,
                               render_gain_db=20 * math.log10(render_gain))
                    active += 1
                except Exception as exc:
                    row.update(status="error", error=f"{type(exc).__name__}: {exc}")
                    print(f"{key}: {row['error']}", flush=True)
                finally:
                    temporary.unlink(missing_ok=True)
                results[key] = row
            atomic_json(manifest_path, results)
            if active and (active <= batch_size or active % (batch_size * 5) < len(batch)):
                print(f"{active} newly rendered in {time.monotonic() - started:.1f}s", flush=True)
    print(f"{sum(row['status'] == 'generated' for row in results.values())}/{len(plan['tasks'])} rendered", flush=True)


def finalize(output: Path, noise_dir: Path) -> None:
    from add_background_noise import run_pipeline

    plan = read_plan(output)
    rendered = json.loads((output / "render_manifest.json").read_text(encoding="utf-8"))
    bank = json.loads((output / "references/reference_bank.json").read_text(encoding="utf-8"))
    clean = output / "clean"
    wavs = {}
    sampling_steps = set()
    for task in plan["tasks"]:
        row = rendered.get(task["task_id"], {})
        path = clean / task["path"]
        if row.get("status") != "generated" or row.get("text_original") != task["text_original"]:
            raise RuntimeError(f"Pending render for {task['task_id']}")
        if row.get("reference_sha256") != bank[task["scenario_id"]]["audio_sha256"]:
            raise RuntimeError(f"Voice reference changed for {task['task_id']}; rerun generate")
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Invalid WAV for {task['task_id']}")
        if has_full_scale_sample(path):
            raise RuntimeError(f"Full-scale PCM samples in {task['task_id']}; rerun generate")
        sampling_steps.add(row["sampling_steps"])
        wavs[task["task_id"]] = path
    if len(sampling_steps) != 1:
        raise RuntimeError("Audio contains multiple sampling-step settings; finish generation with one setting.")
    shutil.copytree(output / "scenarios_complete", clean / "scenarios_complete", dirs_exist_ok=True)
    final = output / "result"
    noise_manifest = run_pipeline(clean, final, noise_dir, export_zip=False)
    rows = []
    for task in plan["tasks"]:
        sid, key = task["scenario_id"], task["task_id"]
        voice, reference = plan["voices"][sid], bank[sid]
        noise = noise_manifest["results"].get(key, {})
        path = final / task["path"]
        if not task["requires_noise"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wavs[key], path)
        wav_hash = sha256_file(path)
        if wav_hash != (noise.get("output_sha256") if task["requires_noise"] else rendered[key]["sha256"]):
            raise ValueError(f"Final WAV mismatch {key}")
        rows.append(allocation_row(task, voice, reference, rendered[key], noise, wav_hash))
    write_allocation(final, plan, rows)
    files = [final / row["path"] for row in rows]
    files += [final / name for name in ["audio_allocation.csv", "audio_allocation.md", "audio_manifest.json",
                                       "NOISE_SOURCES.md", "NOISE_NOTES.md"]]
    files += list((output / "scenarios_complete").glob("SC-*.json"))
    manifest = "audio_SC001_SC100.zip"
    partial = output / (manifest + ".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(final if path.is_relative_to(final) else output)
            archive.write(path, relative.as_posix())
    partial.replace(output / manifest)
    print(f"Verified and packaged {len(rows)} WAV: {output / manifest}", flush=True)


def allocation_row(task: dict, voice: dict, reference: dict, rendered: dict, noise: dict, wav_hash: str) -> dict:
    return {
        **task, "gender": voice["gender"], "province": voice["province"], "region": voice["region"],
        "vimd_province": reference["province_name"], "vimd_region": reference["region"],
        "speaker_id": reference["speakerID"], "reference_filename": reference["filename"],
        "duration_seconds": rendered["duration_seconds"],
        "noise_code": noise.get("noise_code"), "noise": noise.get("noise_label_vi"),
        "noise_start_seconds": noise.get("noise_start_seconds"), "noise_end_seconds": noise.get("noise_end_seconds"),
        "snr_target_db": noise.get("target_call_snr_db"), "snr_actual_db": noise.get("actual_active_snr_db"),
        "sha256": wav_hash, "clean_sha256": rendered["sha256"],
        "sampling_steps": rendered["sampling_steps"], "reference_sha256": reference["audio_sha256"],
        "render_gain_db": rendered.get("render_gain_db", 0.0),
    }


def write_allocation(directory: Path, plan: dict, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    columns = ["scenario_id", "call_id", "turn", "channel", "path", "transcript_source", "source_file",
               "gender", "province", "region", "vimd_province", "vimd_region", "speaker_id", "reference_filename",
               "replaces_scenario_id",
               "noise", "noise_code", "noise_start_seconds", "noise_end_seconds", "snr_target_db", "snr_actual_db",
               "duration_seconds", "sampling_steps", "render_gain_db", "sha256"]
    if plan.get("source_dataset"):
        columns[1:1] = ["source_scenario_id", "source_honorific", "voice_honorific_mismatch"]
    with (directory / "audio_allocation.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    atomic_json(directory / "audio_manifest.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "reference_license": REFERENCE_LICENSE,
        "transcript_sha256": plan["transcript_sha256"], "legacy_transcript_scenarios": plan["legacy_transcript_scenarios"],
        "scenario_replacements": plan.get("scenario_replacements", {}),
        "source_dataset": plan.get("source_dataset"),
        "source_file_sha256": plan.get("source_file_sha256", {}),
        "expected_wavs": len(plan["tasks"]), "actual_wavs": sum(bool(row.get("sha256")) for row in rows),
        "results": rows,
    })
    planned = any(not row.get("sha256") for row in rows)
    calls = {(r["scenario_id"], r["call_id"]) for r in rows}
    noisy_scenarios = {row["scenario_id"] for row in rows if row["requires_noise"]}
    lines = [f"# {plan.get('report_title', 'Phân bổ audio SC-001–SC-100')}", "",
             (f"Dự kiến {len(rows)} WAV cho {len(calls)} cuộc gọi." if planned
              else f"Đã sinh và xác minh {len(rows)} WAV cho {len(calls)} cuộc gọi."),
             f"{len(noisy_scenarios)} kịch bản gồm {sum(row['requires_noise'] for row in rows)} lượt có nền DEMAND.",
             f"Kịch bản dùng lời từ JSON cũ ({len(plan['legacy_transcript_scenarios'])}): "
             + (", ".join(plan["legacy_transcript_scenarios"]) or "không có") + ".", "",
             "| Nhóm | Kịch bản | WAV |", "| --- | ---: | ---: |"]
    if not planned:
        lines.insert(3, f"OmniVoice Vietnamese dùng {rows[0]['sampling_steps']} bước lấy mẫu cho toàn bộ WAV.")
    if plan.get("source_dataset"):
        source_ids = {row["scenario_id"] for row in rows if row["source_scenario_id"] != row["scenario_id"]}
        mismatches = {row["scenario_id"] for row in rows if row["voice_honorific_mismatch"]}
        lines[3:3] = [f"Nguồn lời là `{plan['source_dataset']}`. Mã audio lấy từ tên tệp xuất bản.",
                      f"{len(source_ids)} kịch bản có mã gốc khác tên tệp. "
                      f"{len(mismatches)} kịch bản có xưng hô khác giới tính giọng theo bảng cũ."]
    labels = {"new_transcript": "Transcript mới", "legacy_scenario": "JSON kịch bản cũ"}
    for field in ["gender", "region", "province", "transcript_source"]:
        for value, count in sorted(Counter(row[field] for row in rows).items()):
            scenarios = {row["scenario_id"] for row in rows if row[field] == value}
            lines.append(f"| {labels.get(value, value)} | {len(scenarios)} | {count} |")
    headers = ["Scenario", "Giới tính", "Tỉnh", "Vùng", "Nguồn lời", "Số WAV", "Speaker", "Reference"]
    if plan.get("source_dataset"):
        headers[1:1] = ["Mã gốc", "Xưng hô nguồn", "Khác giới tính giọng"]
    lines += ["", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for sid in plan["scenario_ids"]:
        group = [row for row in rows if row["scenario_id"] == sid]
        first = group[0]
        values = [
            sid, first["gender"], first["province"], first["region"], labels[first["transcript_source"]],
            len(group), first.get("speaker_id") or "—", first.get("reference_filename") or "—",
        ]
        if plan.get("source_dataset"):
            values[1:1] = [first["source_scenario_id"], first["source_honorific"],
                           "Có" if first["voice_honorific_mismatch"] else "Không"]
        lines.append("| " + " | ".join(map(str, values)) + " |")
    if any(row.get("noise") for row in rows):
        lines += ["", ("| Nền dự kiến | WAV |" if planned else "| Nền đã thêm | WAV |"), "| --- | ---: |"]
        for value, count in sorted(Counter(row.get("noise") or "Audio sạch" for row in rows).items()):
            lines.append(f"| {value} | {count} |")
    if plan.get("scenario_replacements"):
        lines += ["", "| Kịch bản thiếu transcript mới | Kịch bản bổ sung | Nền DEMAND |",
                  "| --- | --- | --- |"]
        for original, replacement in plan["scenario_replacements"].items():
            noise = "Có" if replacement in noisy_scenarios else "Không"
            lines.append(f"| {original} | {replacement} | {noise} |")
    (directory / "audio_allocation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_planned(output: Path, plan: dict) -> None:
    bank_file = output / "references/reference_bank.json"
    bank = json.loads(bank_file.read_text(encoding="utf-8")) if bank_file.is_file() else {}
    rows = []
    noise_assignments = {}
    noise_counts = {}
    call_counts = Counter()
    for task in plan["tasks"]:
        sid = task["scenario_id"]
        voice = plan["voices"][sid]
        ref = bank.get(sid, {})
        noise = {}
        if task["requires_noise"]:
            call_key = (sid, task["call_id"])
            if call_key not in noise_assignments:
                profile, snr = assign_noise(int(sid[3:]), call_counts[sid], noise_counts)
                noise_assignments[call_key] = {"noise": profile["label_vi"], "noise_code": profile["code"],
                                               "snr_target_db": snr}
                call_counts[sid] += 1
            noise = noise_assignments[call_key]
        rows.append({**task, **{key: voice[key] for key in ["gender", "province", "region"]}, **noise,
                     "vimd_province": ref.get("province_name"), "vimd_region": ref.get("region"),
                     "speaker_id": ref.get("speakerID"), "reference_filename": ref.get("filename")})
    write_allocation(output / "planned", plan, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "references", "generate", "finalize", "report"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--reference-source", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--reuse-only", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--num-steps", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == "plan":
        if args.transcript is None:
            parser.error("--transcript is required")
        write_planned(out, prepare_plan(args.transcript, out, args.supplement))
    elif args.stage == "references":
        if args.reference_source is None:
            parser.error("--reference-source is required")
        prepare_references(out, args.reference_source, args.workers, args.reuse_only)
        write_planned(out, read_plan(out))
    elif args.stage == "generate":
        generate(out, args.model or out / "runtime/model", args.limit, args.num_steps, args.batch_size)
    elif args.stage == "finalize":
        finalize(out, out / "runtime/demand16k")
    else:
        write_planned(out, read_plan(out))


if __name__ == "__main__":
    main()
