"""Dataset validation, measured latency and paired acceptance checks."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import statistics
import wave
from datetime import date


# Use the versioned M1 export containing both the scenarios and audit report.
DEFAULT_SCENARIOS = Path(__file__).resolve().parents[2] / "dataset/pipeline/stage-3/output/m1-v1"


def load_scenario_inputs(directory: Path) -> dict:
    scenarios = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scenario = json.loads(path.read_bytes())
        scenario_id = scenario["scenario_id"]
        if scenario_id in scenarios:
            raise ValueError(f"Duplicate scenario_id {scenario_id!r}: {path.name}")
        scenarios[scenario_id] = scenario
    if not scenarios:
        raise ValueError(f"No scenario JSON files in {directory}")
    return scenarios


def closing_turn_keys(scenarios):
    return {
        (sid, call, len(spec.get("customer_turns_asr") or spec.get("customer_turns", [])) + 1)
        for sid, scenario in scenarios.items()
        for call, spec in scenario["calls"].items()
    }


def turn_keys(scenarios, *, include_closing_turn: bool = False):
    keys = {
        (sid, call, turn)
        for sid, scenario in scenarios.items()
        for call, spec in scenario["calls"].items()
        for turn, _ in enumerate(spec.get("customer_turns_asr") or spec.get("customer_turns", []), 1)
    }
    if include_closing_turn:
        keys |= closing_turn_keys(scenarios)
    return keys


def audio_path(root: Path, sid: str, call: str, turn: int) -> Path:
    target = (root / sid / call / f"{sid}_{call}_turn_{turn:03d}.wav").resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Audio path escapes the selected dataset")
    return target


def validate_inputs(scenarios, audio_root: Path | None = None):
    keys = turn_keys(scenarios)
    if not keys:
        raise ValueError("Selected dataset has no customer turns")
    for sid, scenario in scenarios.items():
        if not scenario["calls"]:
            raise ValueError(f"Scenario {sid} has no calls")
        for call, spec in scenario["calls"].items():
            clean = spec.get("customer_turns") or []
            noisy = spec.get("customer_turns_asr") or []
            if not clean and not noisy:
                raise ValueError(f"{sid}/{call} has no customer turns")
            if audio_root is not None and (not clean or (noisy and len(clean) != len(noisy))):
                raise ValueError(f"{sid}/{call} needs a matching clean transcript for WAV validation")
            if spec.get("call_date"):
                date.fromisoformat(spec["call_date"])
            elif spec.get("days_later") is not None:
                int(spec["days_later"])
    manifest = {}
    if audio_root is not None:
        manifest_path = audio_root.parent / "manifest.jsonl"
        if not manifest_path.is_file():
            raise ValueError(f"Missing audio manifest: {manifest_path}")
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                key = (row["scenario_id"], row["call_id"], int(row["turn_number"]))
                if key in manifest:
                    raise ValueError(f"Duplicate audio manifest entry: {key}")
                manifest[key] = row
        for key in sorted(keys):
            path = audio_path(audio_root, *key)
            row = manifest.get(key)
            if not row or row.get("status") != "generated" or not path.is_file():
                raise ValueError(f"Missing/failed audio for {key}: {path}")
            sid, call, turn = key
            spec = scenarios[sid]["calls"][call]
            # Manifest corresponds to the clean source, not ASR-noise text.
            source = spec["customer_turns"][turn - 1]
            if row.get("text_original") != source:
                raise ValueError(f"Audio transcript does not match selected scenario: {key}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row.get("output_sha256"):
                raise ValueError(f"Audio checksum mismatch: {key}")
            with wave.open(str(path), "rb") as wav:
                if not wav.getnframes() or not wav.getframerate():
                    raise ValueError(f"Empty WAV: {path}")
    return {"scenario_ids": list(scenarios), "scenarios": len(scenarios),
            "calls": sum(len(s["calls"]) for s in scenarios.values()),
            "turns": len(keys), "audio_files": len(keys) if audio_root else 0}


def trace_health(scenarios, trace, *, include_closing_turn: bool | None = None):
    rows = [row for group in trace.values() for row in group]
    observed = Counter((r["scenario_id"], r["call"], r["turn"]) for r in rows)
    customer_expected = turn_keys(scenarios)
    closing_expected = closing_turn_keys(scenarios)
    observed_keys = set(observed)
    has_closing = (
        bool(observed_keys & closing_expected)
        if include_closing_turn is None
        else include_closing_turn
    )
    expected = (customer_expected | closing_expected) if has_closing else customer_expected
    errors = sum("_error" in r for r in rows)
    failed = sum(int((r.get("usage") or {}).get("failed_requests", 0)) for r in rows)
    cleanup_errors = sum(bool(r.get("_cleanup_error")) for r in rows)
    invalid_closing = sorted(
        (r["scenario_id"], r["call"], r["turn"])
        for r in rows
        if has_closing
        and (r["scenario_id"], r["call"], r["turn"]) in closing_expected
        and r.get("customer_text", "") != ""
    )
    missing = sorted(expected - observed_keys)
    unexpected = sorted(observed_keys - expected)
    duplicates = sum(max(0, n - 1) for n in observed.values())
    return {"valid": not (missing or unexpected or duplicates or errors or failed or cleanup_errors or invalid_closing),
            "expected_turns": len(expected), "observed_turns": len(rows),
            "closing_turns": len(observed_keys & closing_expected),
            "invalid_closing_turns": invalid_closing,
            "missing_turns": missing, "unexpected_turns": unexpected,
            "duplicate_turns": duplicates, "error_turns": errors,
            "failed_llm_requests": failed,"cleanup_errors":cleanup_errors}


def measured_latency(trace, reference, warmup=3):
    # Insertion order is execution order, not scenario ID sort order.
    all_rows = [r for rows in trace.values() for r in rows]
    marked = any("latency_warmup" in r for r in all_rows)
    measured = [r for i, r in enumerate(all_rows)
                if not (r.get("latency_warmup") if marked else i < warmup)
                and "_error" not in r]
    def stats(values):
        return None if not values else {"n":len(values), "p50_ms":round(statistics.median(values),3),
                                       "p95_ms":reference.p95(values), "max_ms":round(max(values),3)}
    def values(key):
        return [r["latency"][key] for r in measured
                if r.get("latency",{}).get("measurement_mode") in {"non_streaming", "streaming"}
                and r["latency"].get(key) is not None]
    totals = values("total_ms")
    brief = [r["call_brief_latency_ms"] for r in measured
             if r.get("call_brief_latency_ms") is not None
             and r.get("latency",{}).get("measurement_mode") in {"non_streaming", "streaming"}]
    streaming_rows = [r for r in measured if r.get("latency",{}).get("measurement_mode") == "streaming"]
    result = {"n_turns":len(totals), "warmup_turns":warmup,
              "warning":None if len(totals)>=100 else "Need at least 100 measured turns after warm-up",
              "ttft":stats(values("ttft_ms")), "total":stats(totals),
              "ttfa":stats(values("ttfa_ms")), "call_brief":stats(brief),
              "request_complete":stats(values("request_complete_ms")),
              "persistence":stats(values("persistence_ms")),
              "precomputed_parts":sorted({part for row in measured for part in row.get("latency",{}).get("precomputed_parts",[])}),
              "streaming":{"turns":len(streaming_rows),
                           "answer_chunks":sum(r["latency"].get("answer_chunks",0) for r in streaming_rows),
                           "multiple_chunk_turns":sum(r["latency"].get("answer_chunks",0)>1 for r in streaming_rows),
                           "incremental_turns":sum(r["latency"].get("chunks_before_generation_complete",0)>0 for r in streaming_rows),
                           "policies":dict(Counter(r["latency"].get("stream_policy") for r in streaming_rows))},
              "measurement_mode":("streaming: first/last emitted answer; " if streaming_rows else "non_streaming; TTFT=Total; ")
                                  +"ASR excluded; no output audio/TTFA"}
    asr = [(r.get("latency",{}).get("asr_ms"),r.get("audio",{}).get("duration_seconds")) for r in measured]
    asr = [(ms,sec) for ms,sec in asr if ms is not None and sec]
    result["asr"] = {"n":len(asr), "audio_seconds":round(sum(sec for _,sec in asr),3),
                     "ms_per_audio_minute":round(sum(ms for ms,_ in asr)/sum(sec for _,sec in asr)*60,3) if asr else None}
    result["thresholds"] = {
        "ttft_p95_le_3000ms": result["ttft"]["p95_ms"]<=3000 if result["ttft"] else None,
        "total_p95_le_8000ms": result["total"]["p95_ms"]<=8000 if result["total"] else None,
        "call_brief_max_le_5000ms": max(brief)<=5000 if brief else None,
        "ttfa_p95_le_2500ms": None,
        "sufficient_sample": len(totals)>=100,
    }
    return result


def m1_acceptance(reference_report, full, baseline):
    """Check official quality and measured latency with explicit missing evidence."""
    official = reference_report.get("comparison") or {}
    full_latency = full["latency"]["thresholds"]
    quality = {
        "rqr": official.get("meets_rqr_threshold_40pct"),
        "tsr": official.get("meets_tsr_70pct"),
        "price_promo_hr": official.get("meets_hr_price_5pct"),
    }
    wrong_price = reference_report.get("system", {}).get("hallucination_rate", {})
    if not wrong_price.get("price_promo_only", {}).get("total"):
        quality["price_promo_hr"] = None
    sufficient = full_latency["sufficient_sample"] and baseline["latency"]["thresholds"]["sufficient_sample"]
    latency = {
        name: full_latency[name] if sufficient else None
        for name in ("ttft_p95_le_3000ms", "total_p95_le_8000ms", "call_brief_max_le_5000ms")
    }
    checks = [*quality.values(), *latency.values()]
    valid = full["trace_health"]["valid"] and baseline["trace_health"]["valid"]
    if not valid or reference_report.get("error"):
        status = "invalid"
    elif False in checks:
        status = "fail"
    elif None in checks:
        status = "inconclusive"
    else:
        status = "pass"
    return {"status": status, "quality": quality, "latency": latency, "sufficient_sample": sufficient}


def compare_metrics(system, baseline):
    rqr = system["repeat_question_rate"]["value"]
    base = baseline["repeat_question_rate"]["value"]
    if base is not None and base > 0 and rqr is not None:
        reduction = (base - rqr) / base * 100
        rqr_gate = reduction >= 40
        rqr_note = None
    elif base == 0 and rqr is not None:
        reduction = None
        rqr_gate = None if rqr == 0 else False
        rqr_note = (
            "Baseline có RQR = 0 → ngưỡng giảm 40% không áp dụng; "
            "BGK đánh giá bằng CCR (hệ thống không hỏi gì cũng có RQR = 0)."
        )
    else:
        reduction = None
        rqr_gate = None
        rqr_note = None
    tsr = system["task_success_rate"]["value"]
    hr = system["hallucination_rate"]["price_promo_only"]["value"]
    valid = system["trace_health"]["valid"] and baseline["trace_health"]["valid"]
    tsr_gate = tsr >= 70 if tsr is not None else None
    hr_gate = hr <= 5 if hr is not None else None
    gates = {
        "rqr_relative_reduction_ge_40pct": rqr_gate,
        "tsr_ge_70pct": tsr_gate,
        "price_hr_le_5pct": hr_gate,
    }
    status = (
        "invalid"
        if not valid
        else "fail"
        if any(v is False for v in gates.values())
        else "inconclusive"
        if any(v is None for v in gates.values())
        else "pass"
    )
    return {
        "rqr_relative_reduction_pct": round(reduction, 1) if reduction is not None else None,
        "meets_rqr_threshold_40pct": rqr_gate,
        "rqr_note": rqr_note,
        "meets_tsr_70pct": bool(tsr_gate),
        "meets_hr_price_5pct": bool(hr_gate),
        "tsr_delta_percentage_points": round(tsr - baseline["task_success_rate"]["value"], 3)
        if tsr is not None and baseline["task_success_rate"]["value"] is not None
        else None,
        "gates": gates,
        "valid_traces": valid,
        "status": status,
        "note": (
            "HR gate uses price_promo_only <= 5% per BTC reference_eval.py. "
            "Baseline RQR = 0 fails when system RQR > 0 and is inconclusive when system RQR = 0 (evaluate via CCR)."
        ),
    }


def machine_metadata():
    import ctypes
    ram = None
    if platform.system() == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length",ctypes.c_ulong),("load",ctypes.c_ulong)] + [(key,ctypes.c_ulonglong) for key in ("total_phys","avail_phys","total_page","avail_page","total_virtual","avail_virtual","extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram = round(status.total_phys/(1024**3),2)
    return {"platform":platform.platform(), "cpu":platform.processor(),
            "ram_gb":ram,"gpu":"LLM hosted by API provider; local ASR uses CPU", "python":platform.python_version()}
