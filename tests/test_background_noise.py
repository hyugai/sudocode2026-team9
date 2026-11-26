"""Verify real-noise extraction/mixing and per-file provenance without network."""

from __future__ import annotations

import ast
import collections
import importlib.util
import io
import json
import math
import shutil
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("background_noise", ROOT / "scripts/add_background_noise.py")
NOISE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOISE)
NOTEBOOK = ROOT / "dataset/text-to-speech/pipeline-augment-audio/add_real_background_noise_SC071_SC100.ipynb"


class BackgroundNoiseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "clean"
        self.output = self.root / "noisy"
        self.bank_dir = self.root / "noise_sources"

    def fixture(self):
        calls = {"call_1": {"customer_turns": ["Chị muốn mua một chiếc.", "Giá bao nhiêu em?"]},
                 "call_2": {"customer_turns": ["Chốt đơn giúp chị."]}}
        scenario_dir = self.input / "scenarios_complete"
        scenario_dir.mkdir(parents=True)
        (scenario_dir / "SC-071.json").write_text(json.dumps({"scenario_id": "SC-071", "calls": calls}), encoding="utf-8")
        snapshots = {}
        for cid, call in calls.items():
            for number, _ in enumerate(call["customer_turns"], 1):
                relative = f"audio/SC-071/{cid}/SC-071_{cid}_turn_{number:03d}.wav"
                samples = np.arange(6000) / 24000
                audio = np.sin(2 * math.pi * 200 * samples) * 0.5
                audio[:800] = 0
                audio[-800:] = 0
                NOISE.write_pcm(self.input / relative, audio, 24000)
                snapshots[relative] = NOISE.sha256_file(self.input / relative)
        bank = {}
        for index, profile in enumerate(NOISE.PROFILES):
            code = profile["code"]
            path = self.bank_dir / code / "ch01.wav"
            rng = np.random.default_rng(index)
            audio = rng.normal(0, 0.035, 64000)
            NOISE.write_pcm(path, audio, 16000)
            bank[code] = {**profile, "relative_path": f"{code}/ch01.wav", "source_sha256": NOISE.sha256_file(path),
                          "source_url": f"https://example.invalid/{code}.zip", "license": NOISE.DEMAND_LICENSE}
        return bank, snapshots

    def test_balanced_real_dataset_plan_has_195_wavs_and_only_target_range(self):
        source = ROOT / "dataset/main"
        manifest = json.loads((source / "noisy_SC071_SC100/noise_manifest.json").read_text(encoding="utf-8"))
        scenarios = {}
        rows = sorted(manifest["results"].values(), key=lambda row: (
            row["scenario_id"], row["call_id"], row["turn_index"],
        ))
        for row in rows:
            sid, cid = row["scenario_id"], row["call_id"]
            scenario = scenarios.setdefault(sid, {"scenario_id": sid, "calls": {}})
            call = scenario["calls"].setdefault(cid, {
                "customer_turns": [], "channel": row["channel"], "input_mode": row["input_mode"],
            })
            self.assertEqual(row["turn_index"], len(call["customer_turns"]))
            call["customer_turns"].append(row["text_original"])
            target = self.input / row["input_relative"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / row["input_relative"], target)

        scenario_dir = self.input / "scenarios_complete"
        scenario_dir.mkdir()
        for sid, scenario in scenarios.items():
            (scenario_dir / f"{sid}.json").write_text(json.dumps(scenario), encoding="utf-8")

        calls = NOISE.build_calls(self.input)
        self.assertEqual(len(calls), 60)
        self.assertEqual(sum(len(call["tasks"]) for call in calls), 195)
        self.assertEqual(collections.Counter(call["noise_code"] for call in calls),
                         {profile["code"]: 10 for profile in NOISE.PROFILES})
        self.assertEqual(collections.Counter(call["target_call_snr_db"] for call in calls), {20.0: 20, 15.0: 20, 10.0: 20})
        self.assertTrue(all(71 <= int(call["scenario_id"].split("-")[1]) <= 100 for call in calls))
        for call in calls:
            for task in call["tasks"]:
                previous = manifest["results"][task["task_id"]]
                self.assertEqual(task["input_sha256"], previous["input_sha256"])
        with self.assertRaises(ValueError):
            NOISE.build_calls(self.input, start=70)

    def test_call_noise_is_contiguous_and_snr_is_controlled(self):
        bank, _ = self.fixture()
        call = NOISE.build_calls(self.input, start=71, end=71)[0]
        background = NOISE.load_resampled_noise(self.bank_dir / bank[call["noise_code"]]["relative_path"], 24000)
        items, stats = NOISE.prepare_call_mix(call, self.input, background, 123)
        self.assertAlmostEqual(stats["pre_headroom_call_snr_db"], call["target_call_snr_db"], places=9)
        self.assertEqual(items[1]["noise_start_frame"] - items[0]["noise_end_frame"], round(0.75 * 24000))
        again, again_stats = NOISE.prepare_call_mix(call, self.input, background, 123)
        self.assertEqual(stats, again_stats)
        self.assertTrue(np.array_equal(items[0]["noise"], again[0]["noise"]))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            NOISE.prepare_call_mix(call, self.input, background[:10], 123)

    def test_mixing_reports_source_integrity_and_resume(self):
        bank, snapshots = self.fixture()
        with patch.object(NOISE, "prepare_noise_bank", return_value=bank):
            manifest = NOISE.run_pipeline(self.input, self.output, self.bank_dir, start=71, end=71)
            first_hashes = {key: row["output_sha256"] for key, row in manifest["results"].items()}
            manifest = NOISE.run_pipeline(self.input, self.output, self.bank_dir, start=71, end=71)
        self.assertEqual(len(manifest["results"]), 3)
        self.assertTrue(all(row["status"] == "resumed" for row in manifest["results"].values()))
        for key, row in manifest["results"].items():
            self.assertEqual(first_hashes[key], row["output_sha256"])
            self.assertEqual(NOISE.sha256_file(self.input / row["input_relative"]), snapshots[row["input_relative"]])
            self.assertNotEqual(row["output_sha256"], row["input_sha256"])
            self.assertEqual(row["clipped_samples"], 0)
            self.assertLessEqual(row["peak"], 0.97 + 1 / 32768)
            self.assertIn(row["noise_code"], row["noise_note_vi"])
            self.assertEqual(NOISE.pcm_info(self.output / row["output_relative"]), NOISE.pcm_info(self.input / row["input_relative"]))
        report = json.loads((self.output / "validation.json").read_text(encoding="utf-8"))
        self.assertEqual(report["completed"], 3)
        self.assertEqual(report["issues"], [])
        self.assertTrue(report["source_checksums_unchanged"])
        notes = (self.output / "NOISE_NOTES.md").read_text(encoding="utf-8")
        for row in manifest["results"].values():
            self.assertIn(row["output_relative"], notes)
        with zipfile.ZipFile(self.output / "noisy_SC071_SC071.zip") as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.endswith(".wav")]), 3)
            self.assertIn("noise_manifest.csv", archive.namelist())

    def test_change_in_one_turn_invalidates_the_entire_call_mix(self):
        bank, _ = self.fixture()
        with patch.object(NOISE, "prepare_noise_bank", return_value=bank):
            first = NOISE.run_pipeline(self.input, self.output, self.bank_dir, start=71, end=71, export_zip=False)
            changed_path = self.input / first["results"]["SC-071/call_1/0"]["input_relative"]
            audio, sample_rate = NOISE.read_pcm(changed_path)
            NOISE.write_pcm(changed_path, audio * 0.5, sample_rate)
            second = NOISE.run_pipeline(self.input, self.output, self.bank_dir, start=71, end=71, export_zip=False)
        self.assertEqual(second["results"]["SC-071/call_1/0"]["status"], "generated")
        self.assertEqual(second["results"]["SC-071/call_1/1"]["status"], "generated")
        self.assertEqual(second["results"]["SC-071/call_2/0"]["status"], "resumed")

    def test_clipping_prevention_scales_both_components(self):
        bank, _ = self.fixture()
        with patch.object(NOISE, "prepare_noise_bank", return_value=bank):
            manifest = NOISE.run_pipeline(self.input, self.output, self.bank_dir, start=71, end=71,
                                          snr_levels_db=(-10.0,), export_zip=False)
        self.assertTrue(all(row["common_gain_db"] < 0 for row in manifest["results"].values()))
        self.assertTrue(all(row["clipped_samples"] == 0 for row in manifest["results"].values()))
        self.assertEqual(NOISE.validate_results(self.input, self.output, manifest)["issues"], [])

    def test_silent_speech_and_unsafe_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "silent"):
            NOISE.speech_energy_mask(np.zeros(100), 24000)
        for destination in [self.input, self.input / "audio", self.input / "audio/SC-071"]:
            with self.assertRaisesRegex(ValueError, "separate output"):
                NOISE.run_pipeline(self.input, destination, self.bank_dir)

    def test_selected_member_can_be_extracted_and_crc_verified_without_network(self):
        source = self.root / "source.wav"
        NOISE.write_pcm(source, np.sin(np.arange(1600)) * 0.2, 16000)
        raw = source.read_bytes()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("TEST/ch01.wav", raw)
            archive.writestr("TEST/ch02.wav", raw)
        entire = buffer.getvalue()

        def fake_range(session, url, requested):
            if requested.startswith("-"):
                start = max(0, len(entire) - int(requested[1:]))
                return entire[start:], start
            start, end = map(int, requested.split("-"))
            return entire[start:end + 1], start

        profile = {"code": "TEST", "archive_md5": "not-checked"}
        with patch.object(NOISE, "http_range", side_effect=fake_range):
            result = NOISE.download_demand_channel(profile, self.root / "download.wav", Mock())
        self.assertEqual((self.root / "download.wav").read_bytes(), raw)
        self.assertEqual(result["source_sha256"], NOISE.sha256_file(source))
        self.assertFalse(result["archive_md5_verified"])

    def test_http_server_ignoring_ranges_fails_before_a_full_download(self):
        session = MagicMock()
        response = session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {}
        with self.assertRaisesRegex(RuntimeError, "HTTP Range"):
            NOISE.http_range(session, "https://example.invalid/noise.zip", "-65536")
        self.assertEqual(session.get.call_count, 1)

    def test_notebook_is_standalone_and_matches_tested_module(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = (ROOT / "scripts/add_background_noise.py").read_text(encoding="utf-8")
        main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")
        expected = "\n".join(source.splitlines()[:main.lineno - 1]).replace("import argparse\n", "").strip()
        embedded = []
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                body = "".join(cell["source"])
                compile(body, str(NOTEBOOK), "exec")
                self.assertEqual(cell["outputs"], [])
                if "PIPELINE_VERSION =" in body:
                    embedded.append(body.strip())
        self.assertEqual(embedded, [expected])


if __name__ == "__main__":
    unittest.main()
