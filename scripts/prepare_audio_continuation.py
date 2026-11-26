"""Audit customer-turn audio and prepare the SC-001..SC-100 Kaggle input.

Uses only the standard library. It never modifies scenarios, audio or manifests
under dataset/main. The ZIP includes existing, verified WAVs and their manifest.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import wave
import zipfile
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO_ROOT / "dataset/text-to-speech/pipeline-generate-audio"
BASE_NOTEBOOK = PIPELINE_DIR / "customer_turns_to_omnivoice_vietnamese_vimd_40_scenarios_kaggle.ipynb"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_voice_rows() -> list:
    notebook = json.loads(BASE_NOTEBOOK.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "VOICE_ROWS"
                for target in node.targets
            ):
                return ast.literal_eval(node.value)
    raise ValueError("Base notebook has no VOICE_ROWS.")


def audit_dataset(dataset_dir: Path) -> tuple[dict, dict, list]:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    previous = manifest["results"]
    planned = []
    per_scenario = []
    retained = {}
    voices = base_voice_rows()
    for number in range(1, 101):
        sid = f"SC-{number:03d}"
        scenario = json.loads(
            (dataset_dir / "scenarios_complete" / f"{sid}.json").read_text(encoding="utf-8-sig")
        )
        if scenario.get("scenario_id") != sid:
            raise ValueError(f"{sid}: scenario_id does not match filename.")
        if number <= 40:
            _, gender, province, region = voices[number - 1]
        else:
            _, _, province, region = voices[(number - 41) % len(voices)]
            honorific = scenario.get("honorific")
            if honorific not in {"anh", "chị"}:
                raise ValueError(f"{sid}: unsupported honorific {honorific!r}; assign a voice explicitly.")
            gender = "Nữ" if honorific == "chị" else "Nam"
        counts = Counter(expected=0, completed=0, missing=0)
        scenario_rows = []
        calls = scenario.get("calls")
        if not isinstance(calls, dict) or not calls:
            raise ValueError(f"{sid}: calls must be a non-empty object.")
        for cid, call in calls.items():
            turns = call.get("customer_turns")
            if not isinstance(turns, list) or not turns:
                raise ValueError(f"{sid}/{cid}: customer_turns must be a non-empty list.")
            for index, text in enumerate(turns):
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"{sid}/{cid}/{index}: empty/invalid customer turn.")
                key = f"{sid}/{cid}/{index}"
                relative = f"audio/{sid}/{cid}/{sid}_{cid}_turn_{index + 1:03d}.wav"
                path = dataset_dir / relative
                counts["expected"] += 1
                if not path.is_file():
                    counts["missing"] += 1
                    continue
                row = previous.get(key, {})
                if (row.get("status") not in {"generated", "resumed"}
                        or row.get("task_id") != key or row.get("output_relative") != relative
                        or row.get("text_original") != text):
                    raise ValueError(f"{key}: existing audio has missing or stale manifest metadata.")
                if sha256_file(path) != row.get("output_sha256"):
                    raise ValueError(f"{key}: WAV checksum differs from manifest.")
                with wave.open(str(path), "rb") as audio:
                    if (audio.getnchannels() != 1 or audio.getframerate() != 24000
                            or audio.getsampwidth() != 2 or audio.getnframes() <= 0):
                        raise ValueError(f"{key}: expected non-empty mono PCM16 / 24 kHz WAV.")
                counts["completed"] += 1
                retained[key] = row
                scenario_rows.append(row)
        if scenario_rows:
            if any(row["voice_requested"] != scenario_rows[0]["voice_requested"]
                   or row["reference"] != scenario_rows[0]["reference"] for row in scenario_rows):
                raise ValueError(f"{sid}: existing calls do not use one consistent voice/reference.")
            spec = scenario_rows[0]["voice_requested"]
            gender, province, region = spec["gender_label"], spec["province_requested"], spec["region_requested"]
        reference = scenario_rows[0]["reference"] if scenario_rows else {}
        planned.append({
            "scenario_id": sid, "gender": gender,
            "province_requested": province, "region_requested": region,
            "status": "existing_verified" if counts["completed"] == counts["expected"] else "planned",
            "province_vimd": reference.get("province_name", ""),
            "region_vimd": reference.get("region", ""),
            "speaker_id": reference.get("speakerID", ""),
            "reference_filename": reference.get("filename", ""),
        })
        per_scenario.append({"scenario_id": sid, "calls": len(calls), **counts})
    bundled_manifest = {**manifest, "results": retained,
                        "scenario_ids": sorted({row["scenario_id"] for row in retained.values()}),
                        "expected_turns": len(retained)}
    report = {
        "scenario_range": ["SC-001", "SC-100"],
        "expected_calls": sum(row["calls"] for row in per_scenario),
        "expected_turns": sum(row["expected"] for row in per_scenario),
        "existing_verified": len(retained),
        "missing_turns": sum(row["missing"] for row in per_scenario),
        "scenarios": per_scenario,
    }
    return report, bundled_manifest, planned


def prepare(dataset_dir: Path, output_dir: Path, check_only: bool = False) -> dict:
    report, manifest, plan = audit_dataset(dataset_dir)
    print(json.dumps({key: value for key, value in report.items() if key != "scenarios"}, ensure_ascii=False))
    if check_only:
        return report
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audio_coverage_before.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output_dir / "SC001_SC100_voice_plan.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(plan[0]))
        writer.writeheader()
        writer.writerows(plan)
    lines = ["# Bảng giọng SC-001–SC-100", "",
             "`existing_verified`: giọng đã dùng trong WAV được xác minh; `planned`: phân công, chưa sinh audio.",
             "Speaker/reference của dòng planned sẽ được điền trong voice_assignments.csv sau khi chạy Kaggle.", "",
             "| Scenario | Giới tính | Tỉnh yêu cầu | Vùng yêu cầu | Trạng thái | Tỉnh ViMD | Vùng ViMD | Speaker ViMD đã dùng | Reference |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in plan:
        keys = ["scenario_id", "gender", "province_requested", "region_requested", "status", "province_vimd", "region_vimd", "speaker_id", "reference_filename"]
        lines.append("| " + " | ".join(row[key] for key in keys) + " |")
    (output_dir / "SC001_SC100_voice_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    archive_path = output_dir / "sc001_sc100_kaggle_input.zip"
    partial = archive_path.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for number in range(1, 101):
            name = f"SC-{number:03d}.json"
            archive.write(dataset_dir / "scenarios_complete" / name, f"scenarios_complete/{name}")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for row in manifest["results"].values():
            archive.write(dataset_dir / row["output_relative"], row["output_relative"])
        archive.write(output_dir / "SC001_SC100_voice_plan.csv", "SC001_SC100_voice_plan.csv")
        archive.write(output_dir / "SC001_SC100_voice_plan.md", "SC001_SC100_voice_plan.md")
        archive.write(output_dir / "audio_coverage_before.json", "audio_coverage_before.json")
    partial.replace(archive_path)
    print(f"Kaggle input: {archive_path} ({archive_path.stat().st_size / 1024 ** 2:.1f} MiB)")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=REPO_ROOT / "dataset/main")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "outputs/audio-continuation")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    prepare(args.dataset_dir, args.output_dir, args.check_only)


if __name__ == "__main__":
    main()
