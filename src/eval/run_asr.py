"""Evaluate local ASR on full BTC WAV dialogues without using an LLM."""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
import wave
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.asr_entities import DEFAULT_CATALOG, extract_asr_entities, load_product_aliases
from eval.team_eval import REFERENCE, reference_sha256


def dialogue_ids(ground_truth: Path) -> list[str]:
    ids = [dialogue["id"] for dialogue in json.loads(ground_truth.read_bytes())["dialogues"]]
    if not ids or any(not isinstance(sid, str) or not re.fullmatch(r"[\w-]+", sid) for sid in ids):
        raise ValueError("Ground truth must contain unique, nonempty dialogue IDs")
    if len(ids) != len(set(ids)):
        raise ValueError("Ground truth contains duplicate dialogue IDs")
    return ids


def validate_btc_asr(directory: Path) -> dict:
    expected = set(dialogue_ids(directory / "ground_truth.json"))
    hypotheses = json.loads((directory / "hypotheses.json").read_bytes())
    if not isinstance(hypotheses, dict):
        raise ValueError("hypotheses.json must map dialogue IDs to hypotheses")
    missing, extra = expected - hypotheses.keys(), hypotheses.keys() - expected
    if missing or extra:
        raise ValueError(f"ASR IDs do not match ground truth: missing={sorted(missing)}, extra={sorted(extra)}")
    for sid, hypothesis in hypotheses.items():
        if not isinstance(hypothesis, dict) or not isinstance(hypothesis.get("text"), str):
            raise ValueError(f"ASR {sid}: hypothesis must have a text string")
        if not isinstance(hypothesis.get("entities"), dict):
            raise ValueError(f"ASR {sid}: hypothesis must have an entities object")
    return {"expected": len(expected), "observed": len(hypotheses)}


def dialogue_wav(audio_root: Path, sid: str) -> Path:
    root = audio_root.resolve()
    for candidate in (root / f"{sid}.wav", root / sid / f"{sid}.wav"):
        path = candidate.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"WAV for {sid} resolves outside the audio directory")
        if path.is_file():
            return path
    raise ValueError(f"Missing full-dialogue WAV for {sid}")


async def run_dialogue_asr(ground_truth, audio_root, output, engine, aliases, *, reference_date=None):
    from telesale_agent.core.models import ConversationState, TurnContext, TurnInput

    paths = {sid: dialogue_wav(audio_root, sid) for sid in dialogue_ids(ground_truth)}
    durations = {}
    for sid, path in paths.items():
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            if not duration:
                raise ValueError(f"Empty WAV for {sid}")
            durations[sid] = duration

    output.mkdir(parents=True)
    (output / "ground_truth.json").write_bytes(ground_truth.read_bytes())
    hypotheses, errors, audio_sha256 = {}, {}, {}
    started = time.perf_counter()
    asr_seconds = 0.0
    for sid, path in paths.items():
        audio = path.read_bytes()
        audio_sha256[sid] = hashlib.sha256(audio).hexdigest()
        context = TurnContext(input=TurnInput(conversation_id=sid, audio=audio), state=ConversationState(sid))
        try:
            asr_started = time.perf_counter()
            transcript = await engine.transcribe(context) or ""
            asr_seconds += time.perf_counter() - asr_started
            hypotheses[sid] = {
                "text": transcript,
                "entities": extract_asr_entities(transcript, aliases, reference_date=reference_date),
            }
        except Exception as exc:
            errors[sid] = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    (output / "hypotheses.json").write_text(json.dumps(hypotheses, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "reference_sha256": reference_sha256(),
        "audio_sha256": audio_sha256,
        "ground_truth_sha256": hashlib.sha256((output / "ground_truth.json").read_bytes()).hexdigest(),
        "elapsed_seconds": round(elapsed, 3),
        "finished_at": datetime.now().astimezone().isoformat(),
        "reference_date": reference_date.isoformat() if reference_date else None,
        "coverage": {"expected": len(paths), "observed": len(hypotheses)},
        "errors": errors,
    }
    if not errors:
        validate_btc_asr(output)
        report["asr"] = REFERENCE.wer_cer(str(output))
        report["ms_per_audio_minute"] = round(asr_seconds * 60_000 / sum(durations.values()), 3)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"coverage": report["coverage"], "failed": len(errors), "report": str(output / "report.json")}
    if "asr" in report:
        summary.update({key: report["asr"][key] for key in ("WER", "CER", "entity_accuracy")})
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--reference-date", type=date.fromisoformat, default=date(2026, 10, 15))
    args = parser.parse_args()
    from telesale_agent.adapters.asr import ZipformerASREngine

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    try:
        return asyncio.run(run_dialogue_asr(
            args.ground_truth, args.audio_root, args.out, ZipformerASREngine(), load_product_aliases(args.catalog),
            reference_date=args.reference_date,
        ))
    except (OSError, ValueError, KeyError, wave.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
