"""Offline regressions for continuation: no model downloads or external services."""

from __future__ import annotations

import ast
import copy
import gc
import hashlib
import importlib.util
import json
import shutil
import tempfile
import time
import types
import unittest
import unicodedata
import wave
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "dataset/text-to-speech/pipeline-generate-audio/customer_turns_to_omnivoice_vietnamese_vimd_SC041_SC100_kaggle.ipynb"
NOTEBOOK = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("prepare_audio_continuation", ROOT / "scripts/prepare_audio_continuation.py")
PREPARE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREPARE)

BASELINE_CONFIG = {
    "model_repo_id": "splendor1811/omnivoice-vietnamese",
    "model_revision": "f70093f90d78a5b790ff0f066b3629ebcc33cb5d",
    "audio_tokenizer_repo_id": "k2-fsa/OmniVoice",
    "audio_tokenizer_revision": "c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
    "omnivoice_version": "0.2.1",
    "transformers_version": "5.3.0",
    "dtype": "float16",
    "attn_implementation": "sdpa",
    "language": "vi",
    "speed": 1.0,
    "generation_options": {
        "num_step": 32, "guidance_scale": 2.0, "denoise": True, "t_shift": 0.1,
        "position_temperature": 5.0, "class_temperature": 0.0, "layer_penalty_factor": 5.0,
        "preprocess_prompt": False, "postprocess_output": True, "audio_chunk_duration": 15.0,
        "audio_chunk_threshold": 30.0, "pad_duration": 0.1, "fade_duration": 0.1,
    },
    "base_seed": 20261007,
    "reference_preprocessing": "full_audio_with_frame_padding",
    "normalize_text": False,
    "pipeline_version": 2,
}


def wav_info(path):
    with wave.open(str(path), "rb") as audio:
        return types.SimpleNamespace(
            channels=audio.getnchannels(), samplerate=audio.getframerate(),
            frames=audio.getnframes(), duration=audio.getnframes() / audio.getframerate(),
            subtype="PCM_16" if audio.getsampwidth() == 2 else "OTHER",
        )


def write_wav(path, waveform, sample_rate=24000, subtype="PCM_16"):
    assert subtype == "PCM_16"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes((np.asarray(waveform) * 20000).astype("<i2").tobytes())


def functions_namespace():
    namespace = {
        "Path": Path, "json": json, "hashlib": hashlib, "shutil": shutil,
        "zipfile": zipfile, "unicodedata": unicodedata, "re": __import__("re"),
        "np": np, "pd": pd, "time": time, "gc": gc,
        "datetime": datetime, "timezone": timezone,
        "sf": types.SimpleNamespace(info=wav_info, write=write_wav),
        "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)),
        "tqdm": lambda items, **kwargs: items,
        "NORMALIZE_NUMBERS": True, "PRONUNCIATION_REPLACEMENTS": {"COD": "si ô đi"},
        "TEXT_OVERRIDES": {}, "CALL_IDS": None,
        "DIGITS": ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"],
    }
    for cell in NOTEBOOK["cells"]:
        if cell["cell_type"] != "code":
            continue
        definitions = [node for node in ast.parse("".join(cell["source"])).body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(NOTEBOOK_PATH), "exec"), namespace)
    return namespace


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline_temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.baseline_temporary.cleanup)
        cls.baseline = Path(cls.baseline_temporary.name)

        # Simulate the notebook's original 100-scenario input and its 40
        # protected scenarios without requiring the retired source recordings.
        scenario_dir = cls.baseline / "scenarios_complete"
        scenario_dir.mkdir()
        for number in range(1, 101):
            sid = f"SC-{number:03d}"
            scenario = {
                "scenario_id": sid,
                "honorific": "chị" if number % 2 else "anh",
                "calls": {
                    "call_1": {"customer_turns": ["Còn hàng không em?", "Giao ngày mai được không?"]},
                    "call_2": {"customer_turns": ["Cho tôi xác nhận lại đơn."]},
                },
            }
            (scenario_dir / f"{sid}.json").write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")

        namespace = functions_namespace()
        voice_specs = {
            sid: {
                "scenario_id": sid, "gender_label": gender, "gender": 0 if gender == "Nữ" else 1,
                "province_requested": province, "province_key": namespace["province_key"](province),
                "region_requested": region,
            }
            for sid, gender, province, region in PREPARE.base_voice_rows()
        }
        namespace.update(BASE_SEED=BASELINE_CONFIG["base_seed"], INFERENCE_CONFIG=BASELINE_CONFIG,
                         VOICE_SPECS=voice_specs)
        reference = {"audio_sha256": "fixture", "ref_text_tts": "Mẫu giọng thử nghiệm"}
        retained = {}
        for task in namespace["build_tasks"](scenario_dir, list(voice_specs)):
            row = namespace["new_result"](task, reference)
            destination = cls.baseline / row["output_relative"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_wav(destination, [0.2] * 240)
            row.update(status="generated", sample_rate=24000, duration_seconds=0.01,
                       bytes=destination.stat().st_size, output_sha256=PREPARE.sha256_file(destination))
            retained[row["task_id"]] = row

        baseline_manifest = {"inference_config": BASELINE_CONFIG, "scenario_ids": list(voice_specs),
                             "expected_turns": len(retained), "results": retained}
        (cls.baseline / "manifest.json").write_text(
            json.dumps(baseline_manifest, ensure_ascii=False), encoding="utf-8")

    def setUp(self):
        self.ns = functions_namespace()
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def synthetic_run(self):
        old = "SC-001"
        new = "SC-041"
        self.ns.update({
            "OUTPUT_DIR": self.output, "MANIFEST_FILE": self.output / "manifest.json",
            "INFERENCE_CONFIG": {"test": True}, "BASE_SEED": 20261007,
            "VOICE_SPECS": {
                sid: {"scenario_id": sid, "gender_label": "Nữ", "gender": 0,
                      "province_requested": "Nghệ An", "region_requested": "Miền trung"}
                for sid in [old, new]
            },
            "PROTECTED_SCENARIO_IDS": {old}, "ALL_SCENARIO_IDS": [old, new],
            "SELECTED_IDS": [old, new], "DATASET_DIR": self.output / "scenarios_complete",
            "GENERATION_SCENARIO_IDS": [new], "MAX_TURNS": 1, "OVERWRITE": False,
        })
        tasks = []
        for sid, count in [(old, 1), (new, 2)]:
            for index in range(count):
                tasks.append({
                    "task_id": f"{sid}/call_1/{index}", "scenario_id": sid, "call_id": "call_1",
                    "turn_index": index, "turn_number": index + 1,
                    "text_original": f"Chị muốn mua {index + 1} chiếc.",
                    "text_tts": f"chị muốn mua {'một' if index == 0 else 'hai'} chiếc.",
                    "output_relative": f"audio/{sid}/call_1/{sid}_call_1_turn_{index + 1:03d}.wav",
                })
        self.ns["TASKS"] = tasks
        old_ref = {"ref_audio_relative": f"references/{old}/reference.wav", "audio_sha256": "old-reference-missing",
                   "ref_text_tts": "Mẫu cũ", "filename": "old.wav", "speakerID": "old-speaker"}
        new_reference_path = self.output / f"references/{new}/reference.wav"
        new_reference_path.parent.mkdir(parents=True)
        write_wav(new_reference_path, [0.2] * 240)
        new_ref = {"ref_audio_relative": f"references/{new}/reference.wav",
                   "audio_sha256": self.ns["file_sha256"](new_reference_path),
                   "ref_text_tts": "Mẫu mới", "filename": "new.wav", "speakerID": "new-speaker"}
        self.ns["reference_request"] = lambda spec: {"test": spec["scenario_id"]}
        new_ref["request_fingerprint"] = self.ns["fingerprint"]({"test": new})
        self.ns.update({"REFERENCES": {new: new_ref}, "REFERENCE_SCENARIO_IDS": [new]})
        row = self.ns["new_result"](tasks[0], old_ref)
        old_path = self.output / row["output_relative"]
        old_path.parent.mkdir(parents=True)
        write_wav(old_path, [0.25] * 240)
        row.update(status="generated", sample_rate=24000, duration_seconds=0.01,
                   bytes=old_path.stat().st_size, output_sha256=self.ns["file_sha256"](old_path))
        self.ns["atomic_json"](self.ns["MANIFEST_FILE"], {"results": {row["task_id"]: row}})
        previous, verified = self.ns["scan_existing_results"](tasks)
        self.ns.update(PREVIOUS_RESULTS=previous, VERIFIED_RESULTS=verified)
        inference = Mock(return_value=(np.array([0.2] * 240), 24000, {"test": True}))
        self.ns["infer_with_full_reference"] = inference
        return tasks, old_path, inference

    def test_notebook_cells_compile_and_have_no_stored_outputs(self):
        for cell in NOTEBOOK["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), str(NOTEBOOK_PATH), "exec")
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])

    def test_configuration_through_audit_with_zipped_input(self):
        # Execute the actual initialization cells, not just extracted functions.
        # This catches cell ordering and missing globals before any model download.
        input_dir = self.output / "input"
        working_dir = self.output / "working"
        input_dir.mkdir()
        working_dir.mkdir()
        report, manifest, _ = PREPARE.audit_dataset(self.baseline)
        with zipfile.ZipFile(input_dir / "input.zip", "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for number in range(1, 101):
                name = f"SC-{number:03d}.json"
                archive.write(self.baseline / "scenarios_complete" / name, f"scenarios_complete/{name}")
            for row in manifest["results"].values():
                archive.write(self.baseline / row["output_relative"], row["output_relative"])
        self.ns.update(RUNTIME_DIR=self.output / "runtime", OMNIVOICE_PACKAGE_VERSION="0.2.1",
                       TRANSFORMERS_VERSION="5.3.0", display=lambda *args: None)
        for index in [4, 6, 8, 10]:
            source = "".join(NOTEBOOK["cells"][index]["source"])
            source = source.replace("/kaggle/input", input_dir.as_posix()).replace("/kaggle/working", working_dir.as_posix())
            tree = ast.parse(source)
            if index == 6:
                tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
            exec(compile(tree, str(NOTEBOOK_PATH), "exec"), self.ns)
        self.assertEqual(len(self.ns["TASKS"]), 300)
        self.assertEqual(len(self.ns["VERIFIED_RESULTS"]), 120)
        self.assertEqual(self.ns["REFERENCE_SCENARIO_IDS"], ["SC-041"])
        for number in range(41, 101):
            sid = f"SC-{number:03d}"
            scenario = json.loads((self.baseline / f"scenarios_complete/{sid}.json").read_text(encoding="utf-8"))
            self.assertEqual(self.ns["VOICE_SPECS"][sid]["gender_label"],
                             "Nữ" if scenario["honorific"] == "chị" else "Nam")
        self.assertEqual(len(list(self.ns["OUTPUT_DIR"].rglob("*.wav"))), 120)

    def test_partial_dataset_counts_checksums_and_gender_plan(self):
        report, manifest, plan = PREPARE.audit_dataset(self.baseline)
        self.assertEqual((report["expected_calls"], report["expected_turns"],
                          report["existing_verified"], report["missing_turns"]), (200, 300, 120, 180))
        self.assertEqual(len(manifest["results"]), 120)
        self.assertEqual(len(plan), 100)
        voices = PREPARE.base_voice_rows()
        for number in range(41, 101):
            sid = f"SC-{number:03d}"
            scenario = json.loads((self.baseline / f"scenarios_complete/{sid}.json").read_text(encoding="utf-8"))
            row = plan[number - 1]
            self.assertEqual(row["gender"], "Nữ" if scenario["honorific"] == "chị" else "Nam")
            self.assertEqual(row["province_requested"], voices[(number - 41) % 40][2])
            self.assertEqual(row["speaker_id"], "")
            self.assertEqual(row["status"], "planned")

    def test_partial_wavs_resume_without_old_references(self):
        report, manifest, plan = PREPARE.audit_dataset(self.baseline)
        self.ns.update(OUTPUT_DIR=self.baseline, MANIFEST_FILE=self.baseline / "manifest.json",
                       INFERENCE_CONFIG=manifest["inference_config"], BASE_SEED=manifest["inference_config"]["base_seed"],
                       PROTECTED_SCENARIO_IDS={f"SC-{number:03d}" for number in range(1, 41)})
        specs = {}
        for row in plan:
            sid = row["scenario_id"]
            specs[sid] = {"scenario_id": sid, "gender_label": row["gender"], "gender": 0 if row["gender"] == "Nữ" else 1,
                          "province_requested": row["province_requested"], "province_key": self.ns["province_key"](row["province_requested"]),
                          "region_requested": row["region_requested"]}
        self.ns["VOICE_SPECS"] = specs
        tasks = self.ns["build_tasks"](self.baseline / "scenarios_complete", list(specs))
        self.assertEqual(len(tasks), 300)
        _, verified = self.ns["scan_existing_results"](tasks)
        self.assertEqual(len(verified), 120)
        self.assertTrue(all(row["status"] == "resumed" for row in verified.values()))
        self.assertFalse((self.baseline / "references").exists())

    def test_audit_rejects_new_audio_without_manifest_metadata(self):
        # Do not silently accept or invent provenance for the additional WAVs
        # that exposed the old tests' dependency on the live dataset state.
        source = self.output / "untracked-audio"
        shutil.copytree(self.baseline / "scenarios_complete", source / "scenarios_complete")
        shutil.copy2(self.baseline / "manifest.json", source / "manifest.json")
        wav = source / "audio/SC-041/call_1/SC-041_call_1_turn_001.wav"
        wav.parent.mkdir(parents=True)
        write_wav(wav, [0.2] * 240)
        with self.assertRaisesRegex(ValueError, "SC-041/call_1/0: existing audio has missing or stale manifest metadata"):
            PREPARE.audit_dataset(source)

    def test_smoke_then_full_keeps_old_wav_and_pending_rows(self):
        tasks, old_path, inference = self.synthetic_run()
        original = old_path.read_bytes()
        manifest = self.ns["run_generation"](None)
        self.assertEqual(len(manifest["results"]), 3)
        self.assertEqual([row["status"] for row in manifest["results"].values()], ["resumed", "generated", "pending"])
        self.assertEqual(inference.call_count, 1)
        self.ns["export_and_check"](manifest)
        self.assertTrue((self.output / "voice_assignments.csv").is_file())
        self.assertEqual(old_path.read_bytes(), original)
        self.ns["MAX_TURNS"] = None
        _, self.ns["VERIFIED_RESULTS"] = self.ns["scan_existing_results"](tasks)
        manifest = self.ns["run_generation"](None)
        self.assertEqual(inference.call_count, 2)
        self.assertTrue(all(row["status"] in {"generated", "resumed"} for row in manifest["results"].values()))
        self.assertEqual(old_path.read_bytes(), original)
        self.ns["export_and_check"](manifest)
        voices = pd.read_csv(self.output / "voice_assignments.csv", encoding="utf-8-sig")
        self.assertEqual(voices["status"].tolist(), ["complete", "complete"])
        self.assertEqual(voices["speaker_id"].tolist(), ["old-speaker", "new-speaker"])

    def test_changed_or_corrupt_protected_audio_stops(self):
        tasks, old_path, _ = self.synthetic_run()
        old_path.write_bytes(old_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(RuntimeError, "Không sinh lại"):
            self.ns["scan_existing_results"](tasks)

    def test_changed_text_or_config_stops_before_generation(self):
        tasks, _, inference = self.synthetic_run()
        changed = copy.deepcopy(tasks)
        changed[0]["text_original"] += " Thay đổi."
        with self.assertRaises(RuntimeError):
            self.ns["scan_existing_results"](changed)
        self.ns["INFERENCE_CONFIG"] = {"test": False}
        with self.assertRaises(RuntimeError):
            self.ns["scan_existing_results"](tasks)
        inference.assert_not_called()

    def test_failed_new_turn_retains_old_and_can_retry(self):
        tasks, old_path, inference = self.synthetic_run()
        original = old_path.read_bytes()
        inference.side_effect = RuntimeError("test inference failure")
        manifest = self.ns["run_generation"](None)
        self.assertEqual(manifest["results"][tasks[1]["task_id"]]["status"], "error")
        self.assertEqual(old_path.read_bytes(), original)
        inference.side_effect = None
        self.ns["MAX_TURNS"] = None
        manifest = self.ns["run_generation"](None)
        self.assertTrue(all(row["status"] in {"generated", "resumed"} for row in manifest["results"].values()))

    def test_final_zip_contains_all_audio_and_does_not_require_old_reference(self):
        _, old_path, _ = self.synthetic_run()
        original = old_path.read_bytes()
        self.ns["MAX_TURNS"] = None
        self.ns["run_generation"](None)
        scenario_dir = self.ns["DATASET_DIR"]
        scenario_dir.mkdir()
        for sid in self.ns["ALL_SCENARIO_IDS"]:
            (scenario_dir / f"{sid}.json").write_text(json.dumps({"scenario_id": sid}), encoding="utf-8")
        self.ns.update(EXPORT_ZIP=True, RUN_TTS=True)
        exec(compile("".join(NOTEBOOK["cells"][-1]["source"]), str(NOTEBOOK_PATH), "exec"), self.ns)
        with zipfile.ZipFile(self.output / "omnivoice_vietnamese_vimd_SC001_SC100.zip") as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.startswith("audio/")]), 3)
            self.assertIn("voice_assignments.csv", archive.namelist())
            self.assertIn("voice_assignments.md", archive.namelist())
            self.assertNotIn("references/SC-001/reference.wav", archive.namelist())
            self.assertEqual(archive.read(old_path.relative_to(self.output).as_posix()), original)

    def test_final_zip_refuses_unfinished_results(self):
        self.synthetic_run()
        self.ns["run_generation"](None)
        self.ns.update(EXPORT_ZIP=True, RUN_TTS=True)
        with self.assertRaisesRegex(RuntimeError, "chưa hoàn thành"):
            exec(compile("".join(NOTEBOOK["cells"][-1]["source"]), str(NOTEBOOK_PATH), "exec"), self.ns)
        self.assertFalse((self.output / "omnivoice_vietnamese_vimd_SC001_SC100.zip").exists())

    def test_zip_restore_preserves_existing_files_and_rejects_traversal(self):
        archive_path = self.output / "input.zip"
        destination = self.output / "restored"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("manifest.json", '{"results": {}}')
            archive.writestr("audio/SC-001/test.wav", b"old")
            archive.writestr("model.safetensors", b"skip")
        copied = self.ns["restore_previous_output"](archive_path, destination)
        self.assertEqual(copied, 2)
        self.assertFalse((destination / "model.safetensors").exists())
        (destination / "manifest.json").write_text("keep", encoding="utf-8")
        self.assertEqual(self.ns["restore_previous_output"](archive_path, destination), 0)
        self.assertEqual((destination / "manifest.json").read_text(encoding="utf-8"), "keep")
        with zipfile.ZipFile(archive_path, "a") as archive:
            archive.writestr("../escaped.txt", b"bad")
        with self.assertRaisesRegex(ValueError, "không an toàn"):
            self.ns["restore_previous_output"](archive_path, destination)
        self.assertFalse((self.output / "escaped.txt").exists())

    def test_resume_auto_requires_an_unambiguous_input(self):
        for name in ["first", "second"]:
            directory = self.output / name
            (directory / "audio").mkdir(parents=True)
            (directory / "manifest.json").write_text('{"results": {"SC-001/call_1/0": {}}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RESUME_FROM_DIR"):
            self.ns["resolve_resume_source"]("auto", self.output)


if __name__ == "__main__":
    unittest.main()
