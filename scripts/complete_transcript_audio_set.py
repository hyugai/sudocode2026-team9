"""Complete the 100-scenario transcript-only audio set with SC-101..SC-140."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path

from add_background_noise import atomic_json, export_reports, pcm_info, run_pipeline, sha256_file
from regenerate_transcript_audio import (
    DEFAULT_OUTPUT,
    MAIN,
    allocation_row,
    generate,
    has_full_scale_sample,
    old_helpers,
    plan_turns,
    read_plan,
    read_transcripts,
    reference_valid,
    transcript_calls,
    write_allocation,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(base: Path, output: Path, transcript: Path) -> dict:
    previous = read_plan(base)
    if previous["transcript_sha256"] != sha256_file(transcript):
        raise ValueError("Use the same transcript file as the already generated audio.")
    records = read_transcripts(transcript)
    candidates = defaultdict(deque)
    for number in range(101, 141):
        sid = f"SC-{number:03d}"
        if sid not in records:
            continue
        metadata = MAIN / "scenarios_complete" / f"{sid}.json"
        if not metadata.is_file():
            metadata = MAIN / "m2_transcripts/scenarios_complete" / f"{sid}.json"
        if metadata.is_file():
            honorific = load_json(metadata).get("honorific")
            if honorific in {"anh", "chị"}:
                candidates["Nam" if honorific == "anh" else "Nữ"].append(sid)

    previous_bank = load_json(base / "references/reference_bank.json")
    helpers = old_helpers()
    normalize = helpers["normalize_spoken_text"]
    removed = set(previous["legacy_transcript_scenarios"])
    previous_noise = {task["scenario_id"] for task in previous["tasks"] if task["requires_noise"]}
    replacements, voices, bank, tasks = {}, {}, {}, []
    additions = output / "additions"

    for sid in previous["legacy_transcript_scenarios"]:
        voice = previous["voices"][sid]
        available = candidates[voice["gender"]]
        if not available:
            raise ValueError(f"No matching new transcript for {sid} ({voice['gender']}).")
        replacement = available.popleft()
        replacements[sid] = replacement
        voices[replacement] = voice
        reference = previous_bank[sid]
        if not reference_valid(base, reference, voice, helpers["province_key"]):
            raise ValueError(f"Invalid original reference for {sid}.")
        reference_path = f"references/{replacement}/reference.wav"
        destination = additions / reference_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / reference["ref_audio_relative"], destination)
        bank[replacement] = {**reference, "scenario_id": replacement, "ref_audio_relative": reference_path,
                             "reused_reference_from": sid}
        new_tasks, calls = plan_turns(replacement, transcript_calls(records[replacement]),
                                     "new_transcript", transcript.name, sid in previous_noise, normalize)
        tasks.extend({**task, "replaces_scenario_id": sid} for task in new_tasks)
        atomic_json(additions / "scenarios_complete" / f"{replacement}.json",
                    {"scenario_id": replacement, "calls": calls})
        print(f"{sid} -> {replacement} | {voice['gender']} / {voice['province']} | "
              f"{'DEMAND' if sid in previous_noise else 'clean'} | {len(new_tasks)} WAV", flush=True)

    selected = sorted(voices)
    tasks.sort(key=lambda row: (row["scenario_id"], row["call_id"], row["turn"]))
    added_plan = {
        "scenario_ids": selected, "new_transcript_scenarios": selected, "legacy_transcript_scenarios": [],
        "scenario_replacements": replacements, "transcript_sha256": previous["transcript_sha256"],
        "voices": voices, "tasks": tasks,
    }
    atomic_json(additions / "references/reference_bank.json", bank)
    atomic_json(additions / "audio_plan.json", added_plan)
    kept = [task for task in previous["tasks"] if task["scenario_id"] not in removed]
    finals = sorted(set(previous["scenario_ids"]) - removed | set(selected))
    final_voices = {**{sid: previous["voices"][sid] for sid in finals if sid not in voices}, **voices}
    plan = {
        **added_plan, "scenario_ids": finals, "new_transcript_scenarios": finals,
        "voices": final_voices, "tasks": kept + tasks,
        "report_title": "Phân bổ audio 100 kịch bản dùng transcript mới",
    }
    assert len(finals) == 100
    assert len({row["scenario_id"] for row in plan["tasks"] if row["requires_noise"]}) == 30
    categories = ("gender", "province", "region")
    assert Counter(tuple(v[k] for k in categories) for v in final_voices.values()) == Counter(
        tuple(v[k] for k in categories) for v in previous["voices"].values()
    )
    atomic_json(output / "audio_plan.json", plan)
    print(f"{len(tasks)} WAV to synthesize; {len(plan['tasks'])} WAV planned for the complete set.", flush=True)
    return plan


def finalize(base: Path, output: Path, transcript: Path) -> Path:
    plan = read_plan(output)
    additions = output / "additions"
    added_plan = read_plan(additions)
    new_ids = set(added_plan["scenario_ids"])
    new_ledger = load_json(additions / "render_manifest.json")
    bank = load_json(additions / "references/reference_bank.json")
    clean = additions / "clean"
    for task in added_plan["tasks"]:
        row = new_ledger.get(task["task_id"], {})
        reference = bank[task["scenario_id"]]
        path = clean / task["path"]
        if (row.get("status") != "generated" or row.get("text_original") != task["text_original"]
                or row.get("sampling_steps") != 16 or row.get("reference_sha256") != reference["audio_sha256"]
                or sha256_file(path) != row["sha256"] or has_full_scale_sample(path)):
            raise ValueError(f"Invalid synthesis result for {task['task_id']}.")

    shutil.copytree(additions / "scenarios_complete", clean / "scenarios_complete", dirs_exist_ok=True)
    new_noisy_ids = sorted({t["scenario_id"] for t in added_plan["tasks"] if t["requires_noise"]})
    mixed = run_pipeline(clean, additions / "mixed", base / "runtime/demand16k", export_zip=False,
                         scenario_ids=new_noisy_ids)
    old_rows = {row["task_id"]: row for row in load_json(base / "result/audio_manifest.json")["results"]}
    old_noise = load_json(base / "result/noise_manifest.json")
    retained = {}
    final = output / "result"
    records = read_transcripts(transcript)
    rows = []
    for task in plan["tasks"]:
        sid, key = task["scenario_id"], task["task_id"]
        source_text = transcript_calls(records[sid])[task["call_id"]]["customer_turns"][task["turn"] - 1]
        if source_text != task["text_original"]:
            raise ValueError(f"Transcript does not match the audio plan for {key}.")
        if sid in new_ids:
            noise = mixed["results"].get(key, {})
            assert bool(noise) == task["requires_noise"]
            source = (additions / "mixed" if noise else clean) / task["path"]
            wav_hash = noise["output_sha256"] if noise else new_ledger[key]["sha256"]
            row = allocation_row(task, plan["voices"][sid], bank[sid], new_ledger[key], noise, wav_hash)
        else:
            row = old_rows[key]
            source = base / "result" / task["path"]
            if task["requires_noise"]:
                retained[key] = old_noise["results"][key]
        if row["text_original"] != source_text or row["transcript_source"] != "new_transcript":
            raise ValueError(f"Final metadata does not match the supplied transcript for {key}.")
        if bool(row["noise"]) != task["requires_noise"] or sha256_file(source) != row["sha256"]:
            raise ValueError(f"Invalid noise assignment or checksum for {key}.")
        if has_full_scale_sample(source):
            raise ValueError(f"Full-scale PCM sample in {key}.")
        info = pcm_info(source)
        if info["sample_rate"] != 24000 or abs(info["frames"] / 24000 - row["duration_seconds"]) > 1e-6:
            raise ValueError(f"Unexpected format or duration for {key}.")
        destination = final / task["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        rows.append(row)
    assert len({row["scenario_id"] for row in rows}) == 100
    assert len({row["scenario_id"] for row in rows if row["noise"]}) == 30
    assert len({row["path"] for row in rows}) == len(rows)
    write_allocation(final, plan, rows)
    noise_manifest = {**old_noise, "results": {**retained, **mixed["results"]}}
    noise_manifest["scenario_ids"] = sorted({row["scenario_id"] for row in noise_manifest["results"].values()})
    noise_manifest["expected_files"] = len(noise_manifest["results"])
    atomic_json(final / "noise_manifest.json", noise_manifest)
    export_reports(final, noise_manifest)

    archive = output / "audio_100_transcripts_30_noisy.zip"
    partial = archive.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for row in rows:
            bundle.write(final / row["path"], row["path"])
        for name in ("audio_allocation.csv", "audio_allocation.md", "audio_manifest.json",
                     "NOISE_NOTES.md", "NOISE_SOURCES.md", "noise_manifest.json"):
            bundle.write(final / name, name)
        for sid in plan["scenario_ids"]:
            scenario = f"scenarios_complete/{sid}.json"
            source_dir = additions if sid in new_ids else base
            bundle.write(source_dir / scenario, scenario)
    partial.replace(archive)
    print(f"{len(rows)} verified WAV, {len(noise_manifest['results'])} noisy WAV. {archive}", flush=True)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "generate", "finalize"])
    parser.add_argument("--base", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--transcript", type=Path, required=True)
    args = parser.parse_args()
    base = args.base.resolve()
    output = base / "100-transcripts"
    if args.stage == "prepare":
        prepare(base, output, args.transcript)
    elif args.stage == "generate":
        generate(output / "additions", base / "runtime/model", limit=None, num_steps=16)
    else:
        finalize(base, output, args.transcript)


if __name__ == "__main__":
    main()
