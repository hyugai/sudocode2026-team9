"""Prepare the m1-v1 transcript, voice references, and DEMAND inputs for Kaggle."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

from add_background_noise import PROFILES, atomic_json, sha256_file, signature
from package_audio_regeneration import package
from regenerate_transcript_audio import DEFAULT_OUTPUT, IDS, REPO, old_helpers, plan_turns, reference_valid


SOURCE = REPO / "dataset/pipeline/stage-3/output/m1-v1"
NOTEBOOK_PATH = REPO / (
    "dataset/text-to-speech/pipeline-generate-audio/"
    "m1_v1_omnivoice_vietnamese_SC001_SC100_kaggle.ipynb"
)


def prepare(source: Path, previous: Path, output: Path, notebook_path: Path) -> None:
    previous_plan = json.loads((previous / "audio_plan.json").read_text(encoding="utf-8"))
    bank = json.loads((previous / "references/reference_bank.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(previous / "kaggle_audio_regeneration_input.zip") as previous_inputs:
        inference = json.loads(previous_inputs.read("dataset/main/manifest.json"))["inference_config"]
    helpers = old_helpers()
    h_genders = {"anh": "Nam", "ông": "Nam", "chú": "Nam", "chị": "Nữ", "cô": "Nữ", "bà": "Nữ"}
    voices = {sid: previous_plan["voices"][sid] for sid in IDS}
    plan = {
        "scenario_ids": IDS, "new_transcript_scenarios": IDS, "legacy_transcript_scenarios": [],
        "source_dataset": source.name, "report_title": f"Phân bổ audio {source.name} SC-001–SC-100",
        "source_file_sha256": {}, "voices": voices, "tasks": [],
    }
    scenarios, source_ids = {}, set()
    for sid in IDS:
        path = source / f"{sid}.json"
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        source_id = raw["scenario_id"]
        if not re.fullmatch(r"SC-\d{3}", source_id) or source_id in source_ids:
            raise ValueError(f"{path}: invalid or duplicate original scenario ID.")
        source_ids.add(source_id)
        honorific = raw.get("honorific", "")
        gender = h_genders.get(honorific)
        tasks, calls = plan_turns(sid, raw["calls"], "new_transcript", f"{source.name}/{path.name}",
                                 int(sid[3:]) >= 71, helpers["normalize_spoken_text"])
        provenance = {"source_scenario_id": source_id, "source_honorific": honorific,
                      "voice_honorific_mismatch": gender is not None and gender != voices[sid]["gender"]}
        scenarios[sid] = {"scenario_id": sid, **provenance, "calls": calls}
        plan["tasks"].extend({**task, **provenance} for task in tasks)
        plan["source_file_sha256"][path.name] = sha256_file(path)
        if not reference_valid(previous, bank.get(sid), voices[sid], helpers["province_key"]):
            raise ValueError(f"{sid}: existing voice reference failed to match the old allocation.")

    noise_source = previous / "runtime/demand16k"
    noise_bank = json.loads((noise_source / "noise_bank.json").read_text(encoding="utf-8"))
    for profile in PROFILES:
        code = profile["code"]
        metadata = noise_bank[code]
        expected_path = f"{code}/ch01.wav"
        if (metadata.get("relative_path") != expected_path
                or metadata.get("source_sha256") != profile["channel_sha256"]
                or sha256_file(noise_source / expected_path) != profile["channel_sha256"]):
            raise ValueError(f"{code}: local DEMAND reference hash is incorrect.")

    plan["transcript_sha256"] = signature(plan["source_file_sha256"])
    plan["kaggle_work_dir"] = "m1_v1_SC001_SC100_" + plan["transcript_sha256"][:8]
    for sid, scenario in scenarios.items():
        atomic_json(output / "scenarios_complete" / f"{sid}.json", scenario)
    voice_bank = {sid: bank[sid] for sid in IDS}
    for row in voice_bank.values():
        relative = row["ref_audio_relative"]
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(previous / relative, destination)
    atomic_json(output / "references/reference_bank.json", voice_bank)
    for profile in PROFILES:
        relative = f"{profile['code']}/ch01.wav"
        destination = output / "runtime/demand16k" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(noise_source / relative, destination)
    atomic_json(output / "runtime/demand16k/noise_bank.json", noise_bank)
    atomic_json(output / "audio_plan.json", plan)
    package(None, output, inference_config=inference, bundle_name="m1_v1_audio_kaggle_input.zip",
            notebook_path=notebook_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--previous", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "m1-v1-kaggle")
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK_PATH)
    args = parser.parse_args()
    prepare(args.source, args.previous, args.output, args.notebook)
