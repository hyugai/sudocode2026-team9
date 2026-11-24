"""Mix recorded DEMAND backgrounds into copies of SC-071..SC-100 customer WAVs.

The source audio and scenario JSONs are read-only. Only the output directory is
written. Reports describe an environmental recording, not independently annotated
sound events. This module is also embedded in the standalone companion notebook.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import struct
import time
import wave
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from scipy.signal import resample_poly


PIPELINE_VERSION = 1
DEMAND_URL = "https://zenodo.org/records/1227121"
DEMAND_LICENSE = "CC-BY-SA-3.0"
DEMAND_ATTRIBUTION = "Joachim Thiemann, Nobutaka Ito, Emmanuel Vincent; DEMAND; doi:10.5281/zenodo.1227121"
PROFILES = [
    {"code": "OOFFICE", "label_vi": "Văn phòng",
     "description_vi": "Nền văn phòng có người sử dụng máy tính",
     "archive_md5": "7b61cc2d182d5a654cb9c3101ddd4041",
     "channel_sha256": "a831879b26e15732ed511a8d3bf72e23aa1689383aac6c5ba76bcaaa528bc2f2"},
    {"code": "PCAFETER", "label_vi": "Căng tin đông người",
     "description_vi": "Nền căng tin văn phòng đông người, có âm thanh sinh hoạt và tiếng người nền",
     "archive_md5": "99927d148128254141a9417d051510bb",
     "channel_sha256": "854dd0e5ef334a66abdd02d6d2b3e9d01b685df033d0acd1cd06e471c062550b"},
    {"code": "STRAFFIC", "label_vi": "Giao thông",
     "description_vi": "Nền ngã tư đông xe cộ",
     "archive_md5": "2efa87262f272bbf9ba578088e81939c",
     "channel_sha256": "8fa49dcf3996af655a3ecef8d06f0d9ef217c35410e3adce3d461da797987dbb"},
    {"code": "DKITCHEN", "label_vi": "Nhà bếp",
     "description_vi": "Nền nhà bếp trong lúc chuẩn bị thức ăn",
     "archive_md5": "7ffbf52d7f4699f96927846103dc8788",
     "channel_sha256": "94eda18f9461348d1d070ca69d001e7fa9e51604731509026b4905d2e321561d"},
    {"code": "DWASHING", "label_vi": "Máy giặt",
     "description_vi": "Nền phòng giặt có máy giặt cửa trước đang hoạt động",
     "archive_md5": "7e5ee9437ce9409c5f9a779b6212a240",
     "channel_sha256": "da02faca8c6523d24ee86aae6c6889c950bb34d559f1379cc87e7e3b75690f4d"},
    {"code": "TBUS", "label_vi": "Trong xe buýt",
     "description_vi": "Nền bên trong xe buýt công cộng",
     "archive_md5": "706b11b0d8504f9f3b3f3211e91b3863",
     "channel_sha256": "d3a0412801945488cab88dc23125b1cccaf31f0579ce9037aad5cdcc667810b6"},
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def atomic_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def pcm_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as stream:
        info = {"sample_rate": stream.getframerate(), "channels": stream.getnchannels(),
                "sample_width": stream.getsampwidth(), "frames": stream.getnframes()}
        if stream.getcomptype() != "NONE":
            raise ValueError(f"Expected uncompressed PCM WAV: {path}")
    if info["sample_width"] != 2 or info["channels"] != 1 or info["frames"] <= 0:
        raise ValueError(f"Expected non-empty mono PCM16 WAV: {path}")
    return info


def read_pcm(path: Path) -> tuple[np.ndarray, int]:
    info = pcm_info(path)
    with wave.open(str(path), "rb") as stream:
        raw = stream.readframes(info["frames"])
    if len(raw) != info["frames"] * 2:
        raise ValueError(f"Truncated WAV: {path}")
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0, info["sample_rate"]


def write_pcm(path: Path, audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) >= 1:
        raise ValueError("Non-finite or clipping waveform; refusing to write.")
    quantized = np.rint(audio * 32768.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".partial.wav")
    try:
        with wave.open(str(temporary), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(sample_rate)
            stream.writeframes(quantized.tobytes())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return quantized.astype(np.float64) / 32768.0


def http_range(session: requests.Session, url: str, byte_range: str) -> tuple[bytes, int]:
    # Read a single channel, not all 16 channels in each 80-130 MB archive.
    for attempt in range(3):
        try:
            with session.get(url, headers={"Range": f"bytes={byte_range}", "Accept-Encoding": "identity"},
                             stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if response.status_code != 206 or not match:
                    raise RuntimeError("Server did not honor HTTP Range. Attach a prepared DEMAND noise bank instead.")
                start, end, _ = map(int, match.groups())
                if not byte_range.startswith("-"):
                    expected_start, expected_end = map(int, byte_range.split("-"))
                    if start != expected_start or end != expected_end:
                        raise RuntimeError("HTTP Range response does not match the requested segment.")
                data = response.content
                if len(data) != end - start + 1:
                    raise ValueError("Incomplete HTTP Range response.")
                return data, start
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("Unreachable")


def download_demand_channel(profile: dict, destination: Path, session: requests.Session) -> dict:
    code = profile["code"]
    url = f"{DEMAND_URL}/files/{code}_16k.zip?download=1"
    tail, tail_start = http_range(session, url, "-65536")
    with zipfile.ZipFile(io.BytesIO(tail)) as archive:
        members = [info for info in archive.infolist() if info.filename == f"{code}/ch01.wav"]
        if len(members) != 1:
            raise ValueError(f"{code}: cannot identify ch01.wav in official ZIP.")
        member = members[0]
    if member.flag_bits & 1 or member.file_size > 32 * 1024 ** 2:
        raise ValueError("Unexpected encrypted or oversized DEMAND channel.")
    # zipfile adjusts offsets relative to the tail buffer; restore absolute offset.
    offset = tail_start + member.header_offset
    header, _ = http_range(session, url, f"{offset}-{offset + 29}")
    fields = struct.unpack("<4s5H3I2H", header)
    if fields[0] != b"PK\x03\x04" or fields[3] != member.compress_type:
        raise ValueError("ZIP local header does not match directory.")
    payload_start = offset + 30 + fields[-2] + fields[-1]
    compressed, _ = http_range(session, url, f"{payload_start}-{payload_start + member.compress_size - 1}")
    if member.compress_type == zipfile.ZIP_DEFLATED:
        raw = zlib.decompress(compressed, -zlib.MAX_WBITS)
    elif member.compress_type == zipfile.ZIP_STORED:
        raw = compressed
    else:
        raise ValueError("Unsupported ZIP compression.")
    if len(raw) != member.file_size or zlib.crc32(raw) & 0xffffffff != member.CRC:
        raise ValueError(f"{code}: channel length/CRC32 failed.")
    checksum = hashlib.sha256(raw).hexdigest()
    if profile.get("channel_sha256") and checksum != profile["channel_sha256"]:
        raise ValueError(f"{code}: channel SHA-256 differs from the pinned recording.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.write_bytes(raw)
    try:
        info = pcm_info(temporary)
        if info["sample_rate"] != 16000:
            raise ValueError("Expected the 16 kHz DEMAND recording.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {**profile, "relative_path": f"{code}/ch01.wav", "source_url": url,
            "source_archive_member": member.filename, "source_sha256": checksum,
            "source_crc32": f"{member.CRC:08x}", "archive_md5_verified": False,
            "sample_rate": info["sample_rate"], "frames": info["frames"],
            "duration_seconds": info["frames"] / info["sample_rate"],
            "license": DEMAND_LICENSE, "attribution": DEMAND_ATTRIBUTION}


def prepare_noise_bank(noise_dir: Path) -> dict:
    noise_dir = Path(noise_dir)
    manifest_path = noise_dir / "noise_bank.json"
    bank = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    with requests.Session() as session:
        for profile in PROFILES:
            code = profile["code"]
            destination = noise_dir / code / "ch01.wav"
            prior = bank.get(code, {})
            if (destination.is_file() and prior.get("source_sha256") == sha256_file(destination)
                    and (not profile.get("channel_sha256") or prior["source_sha256"] == profile["channel_sha256"])):
                pcm_info(destination)
                print(f"Noise cache verified: {code}", flush=True)
                continue
            print(f"Downloading real DEMAND background: {code}/ch01.wav", flush=True)
            bank[code] = download_demand_channel(profile, destination, session)
            atomic_json(manifest_path, bank)
    return {profile["code"]: bank[profile["code"]] for profile in PROFILES}


def build_calls(input_root: Path, start: int = 71, end: int = 100,
                snr_levels_db: tuple[float, ...] = (20.0, 15.0, 10.0)) -> list[dict]:
    if not 71 <= start <= end <= 100:
        raise ValueError("This pipeline only processes SC-071..SC-100.")
    if not snr_levels_db or not all(math.isfinite(value) for value in snr_levels_db):
        raise ValueError("SNR levels must be finite and non-empty.")
    counters = {profile["code"]: 0 for profile in PROFILES}
    calls = []
    for number in range(start, end + 1):
        sid = f"SC-{number:03d}"
        path = input_root / "scenarios_complete" / f"{sid}.json"
        scenario = json.loads(path.read_text(encoding="utf-8-sig"))
        if scenario.get("scenario_id") != sid or not isinstance(scenario.get("calls"), dict) or not scenario["calls"]:
            raise ValueError(f"{path}: invalid scenario_id/calls.")
        for call_index, (cid, call) in enumerate(scenario["calls"].items()):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", cid):
                raise ValueError(f"Unsafe call_id: {cid!r}")
            turns = call.get("customer_turns")
            if not isinstance(turns, list) or not turns:
                raise ValueError(f"{sid}/{cid}: no customer_turns.")
            profile_index = (number - 71 + 2 * call_index) % len(PROFILES)
            profile = PROFILES[profile_index]
            code = profile["code"]
            snr = float(snr_levels_db[(profile_index + counters[code]) % len(snr_levels_db)])
            counters[code] += 1
            tasks = []
            for index, text in enumerate(turns):
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"{sid}/{cid}/{index}: invalid customer turn.")
                relative = f"audio/{sid}/{cid}/{sid}_{cid}_turn_{index + 1:03d}.wav"
                audio = input_root / relative
                info = pcm_info(audio)
                if info["sample_rate"] != 24000:
                    raise ValueError(f"{audio}: expected the existing 24 kHz customer WAV.")
                tasks.append({"task_id": f"{sid}/{cid}/{index}", "scenario_id": sid, "call_id": cid,
                              "turn_index": index, "turn_number": index + 1, "text_original": text,
                              "channel": call.get("channel"), "input_mode": call.get("input_mode"),
                              "input_relative": relative, "output_relative": relative,
                              "input_sha256": sha256_file(audio), **info})
            calls.append({"scenario_id": sid, "call_id": cid, "noise_code": code,
                          "target_call_snr_db": snr, "tasks": tasks})
    return calls


def speech_energy_mask(audio: np.ndarray, sample_rate: int, gate_db: float = -35.0) -> np.ndarray:
    frame_length = max(1, round(0.02 * sample_rate))
    squared = np.pad(audio * audio, (0, (-len(audio)) % frame_length))
    energies = squared.reshape(-1, frame_length).mean(axis=1)
    threshold = max(float(energies.max()) * 10 ** (gate_db / 10), 1e-10)
    mask = np.repeat(energies >= threshold, frame_length)[:len(audio)]
    if not mask.any() or np.mean(audio[mask] ** 2) < 1e-10:
        raise ValueError("Source speech is silent; refusing to invent a speech SNR.")
    return mask


def load_resampled_noise(path: Path, target_rate: int) -> np.ndarray:
    audio, source_rate = read_pcm(path)
    audio -= np.mean(audio)
    if source_rate != target_rate:
        divisor = math.gcd(source_rate, target_rate)
        audio = resample_poly(audio, target_rate // divisor, source_rate // divisor)
    if not np.isfinite(audio).all() or np.mean(audio ** 2) < 1e-12:
        raise ValueError("Noise recording is silent or non-finite.")
    return audio.astype(np.float32)


def prepare_call_mix(call: dict, input_root: Path, background: np.ndarray, base_seed: int,
                     gap_seconds: float = 0.75, fade_seconds: float = 0.01) -> tuple[list[dict], dict]:
    sample_rate = call["tasks"][0]["sample_rate"]
    gap_frames = round(gap_seconds * sample_rate)
    required = sum(task["frames"] for task in call["tasks"]) + gap_frames * (len(call["tasks"]) - 1)
    if required > len(background):
        raise ValueError("The call exceeds the real noise recording. Use a longer source; no synthetic looping is applied.")
    call_seed = int(signature({"seed": base_seed, "call": f"{call['scenario_id']}/{call['call_id']}"})[:16], 16)
    start_frame = int(np.random.default_rng(call_seed).integers(0, len(background) - required + 1))
    position = start_frame
    prepared = []
    speech_energy, noise_energy = 0.0, 0.0
    for task in call["tasks"]:
        speech, _ = read_pcm(input_root / task["input_relative"])
        noise = background[position:position + len(speech)].astype(np.float64)
        fade = min(round(fade_seconds * sample_rate), len(noise) // 2)
        if fade:
            ramp = np.linspace(0.0, 1.0, fade)
            noise[:fade] *= ramp
            noise[-fade:] *= ramp[::-1]
        mask = speech_energy_mask(speech, sample_rate)
        speech_energy += float(np.sum(speech[mask] ** 2))
        noise_energy += float(np.sum(noise[mask] ** 2))
        prepared.append({"task": task, "speech": speech, "noise": noise, "mask": mask,
                         "noise_start_frame": position, "noise_end_frame": position + len(speech)})
        position += len(speech) + gap_frames
    if noise_energy < 1e-12:
        raise ValueError("Selected real background segment has no measurable energy.")
    noise_gain = math.sqrt(speech_energy / noise_energy) / 10 ** (call["target_call_snr_db"] / 20.0)
    stats = {"call_seed": call_seed, "noise_gain": noise_gain, "call_noise_start_frame": start_frame,
             "target_call_snr_db": call["target_call_snr_db"], "gap_seconds": gap_seconds,
             "fade_seconds": fade_seconds, "speech_gate_db": -35.0,
             "pre_headroom_call_snr_db": 10 * math.log10(speech_energy / (noise_energy * noise_gain ** 2))}
    return prepared, stats


def snr_db(signal: np.ndarray, noise: np.ndarray, mask: np.ndarray) -> float:
    return 10 * math.log10(float(np.sum(signal[mask] ** 2)) / max(float(np.sum(noise[mask] ** 2)), 1e-30))


def export_reports(output_dir: Path, manifest: dict) -> None:
    rows = list(manifest["results"].values())
    columns = ["task_id", "scenario_id", "call_id", "turn_number", "input_relative", "output_relative",
               "status", "noise_code", "noise_label_vi", "noise_description_vi", "target_call_snr_db",
               "actual_active_snr_db", "noise_start_seconds", "noise_end_seconds", "noise_gain",
               "common_gain_db", "sample_rate", "frames", "duration_seconds", "peak", "clipped_samples",
               "noise_note_vi", "noise_source_file", "noise_source_sha256", "noise_source_url", "noise_license",
               "input_sha256", "output_sha256", "text_original", "error"]
    with (output_dir / "noise_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "noise_manifest.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    lines = ["# Nhiễu nền đã thêm vào SC-071–SC-100", "",
             "Mỗi dòng là một WAV. Nhãn mô tả môi trường gốc; không khẳng định từng sự kiện âm thanh xuất hiện trong mọi đoạn.",
             "SNR mục tiêu được đặt theo cuộc gọi bằng năng lượng các frame có tiếng nói. SNR từng lượt có thể khác vì nền biến thiên tự nhiên.",
             "SNR cao hơn nghĩa là tiếng nền nhẹ hơn. Cùng một nền và một hệ số trộn được giữ trong mỗi cuộc gọi.", "",
             "| File WAV (tương đối trong output) | Nền thực tế | SNR cuộc gọi / lượt (dB) | Đoạn nguồn (s) | Trạng thái |",
             "| --- | --- | --- | --- | --- |"]
    for row in rows:
        actual = f"{row['actual_active_snr_db']:.2f}" if row.get("actual_active_snr_db") is not None else "—"
        segment = (f"{row['noise_start_seconds']:.3f}–{row['noise_end_seconds']:.3f}"
                   if row.get("noise_start_seconds") is not None else "—")
        lines.append(f"| {row['output_relative']} | {row['noise_description_vi']} ({row['noise_code']}) | "
                     f"{row['target_call_snr_db']:g} / {actual} | {segment} | {row['status']} |")
    (output_dir / "NOISE_NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    license_lines = ["# Nguồn và ghi nhận bản ghi nhiễu", "", DEMAND_ATTRIBUTION, "", DEMAND_URL,
                     "", "Giấy phép bản ghi nền: CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/", "",
                     "Biến đổi: lấy kênh ch01 của bản 16 kHz, bỏ DC, resample sang 24 kHz, lấy đoạn, fade 10 ms,",
                     "trộn theo SNR và giảm gain chung khi cần tránh clipping. Giữ nguyên số mẫu và nhịp lời khách hàng.",
                     "Bản ghi môi trường có thể chứa tiếng người nền; không bảo đảm ngôn ngữ nền là tiếng Việt.", "",
                     "Các WAV nguồn của khách hàng giữ nguồn/giấy phép riêng; tệp này ghi nhận phần nhiễu DEMAND.", ""]
    for code, source in manifest["noise_sources"].items():
        license_lines += [f"- {code}: {source['source_url']}", f"  SHA-256 ch01.wav: {source['source_sha256']}"]
    (output_dir / "NOISE_SOURCES.md").write_text("\n".join(license_lines) + "\n", encoding="utf-8")


def validate_results(input_root: Path, output_dir: Path, manifest: dict) -> dict:
    issues = []
    seen = set()
    for row in manifest["results"].values():
        try:
            if row["output_relative"] in seen:
                raise ValueError("Duplicate output path.")
            seen.add(row["output_relative"])
            if row["status"] not in {"generated", "resumed"}:
                raise ValueError(row.get("error", "Audio not generated."))
            clean_path, output_path = input_root / row["input_relative"], output_dir / row["output_relative"]
            if sha256_file(clean_path) != row["input_sha256"]:
                raise ValueError("Source audio changed.")
            if sha256_file(output_path) != row["output_sha256"]:
                raise ValueError("Noisy output checksum mismatch.")
            info = pcm_info(output_path)
            if any(info[key] != row[key] for key in ["sample_rate", "frames", "channels", "sample_width"]):
                raise ValueError("Output WAV format/duration differs from source.")
            audio, _ = read_pcm(output_path)
            if not np.isfinite(audio).all() or np.max(np.abs(audio)) > manifest["peak_ceiling"] + 1 / 32768:
                raise ValueError("Invalid/clipped output.")
            clean, _ = read_pcm(clean_path)
            if np.array_equal(clean, audio):
                raise ValueError("Output has no added background.")
            mask = speech_energy_mask(clean, info["sample_rate"])
            gain = 10 ** (row["common_gain_db"] / 20)
            measured = snr_db(clean * gain, audio - clean * gain, mask)
            if abs(measured - row["actual_active_snr_db"]) > 0.001:
                raise ValueError("Recorded SNR does not match the written WAV.")
        except (ValueError, OSError, KeyError, wave.Error) as exc:
            issues.append({"task_id": row["task_id"], "error": str(exc)})
    report = {"expected": manifest["expected_files"], "completed": len(manifest["results"]) - len(issues),
              "source_checksums_unchanged": not any("Source audio changed" in issue["error"] for issue in issues),
              "issues": issues}
    if len(manifest["results"]) != manifest["expected_files"]:
        report["issues"].append({"error": "Manifest row count differs from expected file count."})
    atomic_json(output_dir / "validation.json", report)
    return report


def run_pipeline(input_root: Path, output_dir: Path, noise_dir: Path, *, start: int = 71, end: int = 100,
                 base_seed: int = 20261118, snr_levels_db: tuple[float, ...] = (20.0, 15.0, 10.0),
                 peak_ceiling: float = 0.97, export_zip: bool = True) -> dict:
    input_root, output_dir, noise_dir = Path(input_root).resolve(), Path(output_dir).resolve(), Path(noise_dir).resolve()
    if (output_dir == input_root or output_dir.is_relative_to(input_root / "audio")
            or (output_dir / "audio").resolve() == (input_root / "audio").resolve()):
        raise ValueError("Choose a separate output directory; source WAVs/manifests must remain unchanged.")
    if not 0 < peak_ceiling < 0.999:
        raise ValueError("peak_ceiling must be between 0 and 0.999.")
    calls = build_calls(input_root, start, end, snr_levels_db)
    expected = sum(len(call["tasks"]) for call in calls)
    print(f"Found {end - start + 1} scenarios / {len(calls)} calls / {expected} source WAVs.", flush=True)
    bank = prepare_noise_bank(noise_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "noise_manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("results", {}) if manifest_path.is_file() else {}
    results = {}
    for call in calls:
        for task in call["tasks"]:
            profile = next(profile for profile in PROFILES if profile["code"] == call["noise_code"])
            source = bank[call["noise_code"]]
            results[task["task_id"]] = {**task, "noise_code": call["noise_code"], "noise_label_vi": profile["label_vi"],
                                        "noise_description_vi": profile["description_vi"],
                                        "target_call_snr_db": call["target_call_snr_db"],
                                        "noise_source_file": source["relative_path"], "noise_source_sha256": source["source_sha256"],
                                        "noise_source_url": source["source_url"], "noise_license": source["license"], "status": "pending"}
    manifest = {"pipeline_version": PIPELINE_VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "scenario_ids": [f"SC-{i:03d}" for i in range(start, end + 1)],
                "expected_files": expected, "base_seed": base_seed, "peak_ceiling": peak_ceiling,
                "snr_levels_db": list(snr_levels_db), "snr_definition": "energy-gated 20 ms frames, -35 dB relative frame energy; one noise gain per call",
                "noise_sources": bank, "results": results}
    backgrounds = {}
    atomic_json(manifest_path, manifest)
    for call in calls:
        code = call["noise_code"]
        if code not in backgrounds:
            backgrounds[code] = load_resampled_noise(noise_dir / bank[code]["relative_path"], 24000)
        try:
            prepared, stats = prepare_call_mix(call, input_root, backgrounds[code], base_seed)
            call_fingerprint = signature({"version": PIPELINE_VERSION, "source_sha256": bank[code]["source_sha256"],
                                          "input_sha256": [task["input_sha256"] for task in call["tasks"]],
                                          "peak_ceiling": peak_ceiling, **stats})
            for item in prepared:
                task = item["task"]
                row = results[task["task_id"]]
                path = output_dir / task["output_relative"]
                fingerprint = signature({"call": call_fingerprint, "task_id": task["task_id"]})
                prior = previous.get(task["task_id"], {})
                if (prior.get("input_fingerprint") == fingerprint and prior.get("status") in {"generated", "resumed"}
                        and path.is_file() and sha256_file(path) == prior.get("output_sha256")):
                    results[task["task_id"]] = {**prior, **row, "status": "resumed"}
                    continue
                speech, noise, mask = item["speech"], item["noise"], item["mask"]
                unscaled = speech + stats["noise_gain"] * noise
                common_gain = min(1.0, peak_ceiling / max(float(np.max(np.abs(unscaled))), 1e-12))
                written = write_pcm(path, unscaled * common_gain, task["sample_rate"])
                actual_snr = snr_db(speech * common_gain, written - speech * common_gain, mask)
                row.update({"status": "generated", "input_fingerprint": fingerprint, **stats,
                            "noise_start_seconds": item["noise_start_frame"] / task["sample_rate"],
                            "noise_end_seconds": item["noise_end_frame"] / task["sample_rate"],
                            "actual_active_snr_db": actual_snr, "common_gain_db": 20 * math.log10(common_gain),
                            "duration_seconds": len(written) / task["sample_rate"],
                            "peak": float(np.max(np.abs(written))),
                            "clipped_samples": int(np.sum((written >= 32767 / 32768) | (written <= -1))),
                            "output_sha256": sha256_file(path)})
                row["noise_note_vi"] = (f"{row['noise_description_vi']}; {code}/ch01.wav; "
                                        f"đoạn {row['noise_start_seconds']:.3f}–{row['noise_end_seconds']:.3f} s; "
                                        f"SNR mục tiêu cuộc gọi {row['target_call_snr_db']:g} dB, "
                                        f"SNR thực tế lượt {actual_snr:.2f} dB.")
            print(f"{call['scenario_id']}/{call['call_id']}: {code}, target {call['target_call_snr_db']:g} dB, {len(prepared)} WAV", flush=True)
        except Exception as exc:
            for task in call["tasks"]:
                if results[task["task_id"]]["status"] == "pending":
                    results[task["task_id"]].update(status="error", error=f"{type(exc).__name__}: {exc}")
            print(f"ERROR {call['scenario_id']}/{call['call_id']}: {exc}", flush=True)
        finally:
            atomic_json(manifest_path, manifest)
    export_reports(output_dir, manifest)
    validation = validate_results(input_root, output_dir, manifest)
    if validation["issues"]:
        raise RuntimeError(f"{len(validation['issues'])} validation issues; see {output_dir / 'validation.json'}")
    if export_zip:
        archive_path = output_dir / f"noisy_SC{start:03d}_SC{end:03d}.zip"
        temporary = archive_path.with_name(archive_path.name + ".partial")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for row in results.values():
                archive.write(output_dir / row["output_relative"], row["output_relative"])
            for name in ["noise_manifest.json", "noise_manifest.csv", "noise_manifest.jsonl", "NOISE_NOTES.md", "NOISE_SOURCES.md", "validation.json"]:
                archive.write(output_dir / name, name)
        temporary.replace(archive_path)
        print(f"ZIP: {archive_path}", flush=True)
    print(f"Validated {expected}/{expected} noisy WAVs; report: {output_dir / 'NOISE_NOTES.md'}", flush=True)
    return manifest


def prepare_input_zip(input_root: Path, noise_dir: Path, destination: Path) -> Path:
    """Package clean target WAVs, scenarios and the verified noise bank for Kaggle."""
    calls = build_calls(input_root)
    bank = prepare_noise_bank(noise_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for number in range(71, 101):
            name = f"SC-{number:03d}.json"
            archive.write(input_root / "scenarios_complete" / name, f"scenarios_complete/{name}")
        for call in calls:
            for task in call["tasks"]:
                archive.write(input_root / task["input_relative"], task["input_relative"])
        for source in bank.values():
            relative = source["relative_path"]
            archive.write(noise_dir / relative, f"noise_sources/demand16k/{relative}")
        archive.writestr("noise_sources/demand16k/noise_bank.json", json.dumps(bank, ensure_ascii=False, indent=2))
    temporary.replace(destination)
    print(f"Kaggle input: {destination} ({destination.stat().st_size / 1024 ** 2:.1f} MiB)", flush=True)
    return destination


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=repository / "dataset/main")
    parser.add_argument("--output-dir", type=Path, default=repository / "dataset/main/noisy_SC071_SC100")
    parser.add_argument("--noise-dir", type=Path, default=repository / "dataset/text-to-speech/noise_sources/demand16k")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--prepare-input-zip", type=Path)
    args = parser.parse_args()
    if args.download_only:
        prepare_noise_bank(args.noise_dir)
    elif args.prepare_input_zip:
        prepare_input_zip(args.input_root, args.noise_dir, args.prepare_input_zip)
    else:
        run_pipeline(args.input_root, args.output_dir, args.noise_dir, export_zip=not args.no_zip)


if __name__ == "__main__":
    main()
