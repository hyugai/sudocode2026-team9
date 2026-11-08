"""Dataset validation, measured latency and paired acceptance checks."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import statistics
import wave


def turn_keys(scenarios):
    return {
        (sid, call, turn)
        for sid, scenario in scenarios.items()
        for call, spec in scenario["calls"].items()
        for turn, _ in enumerate(spec.get("customer_turns_asr") or spec.get("customer_turns", []), 1)
    }


def audio_path(root: Path, sid: str, call: str, turn: int) -> Path:
    target = (root / sid / call / f"{sid}_{call}_turn_{turn:03d}.wav").resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Audio path escapes the selected dataset")
    return target


def validate_inputs(scenarios, audio_root: Path | None = None):
    keys = turn_keys(scenarios)
    if not keys:
        raise ValueError("Selected dataset has no customer turns")
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


def trace_health(scenarios, trace):
    rows = [row for group in trace.values() for row in group]
    observed = Counter((r["scenario_id"], r["call"], r["turn"]) for r in rows)
    expected = turn_keys(scenarios)
    errors = sum("_error" in r for r in rows)
    failed = sum(int((r.get("usage") or {}).get("failed_requests", 0)) for r in rows)
    cleanup_errors = sum(bool(r.get("_cleanup_error")) for r in rows)
    missing = sorted(expected - set(observed))
    unexpected = sorted(set(observed) - expected)
    duplicates = sum(max(0, n - 1) for n in observed.values())
    return {"valid": not (missing or unexpected or duplicates or errors or failed or cleanup_errors),
            "expected_turns": len(expected), "observed_turns": len(rows),
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


def compare_metrics(system, baseline):
    rqr = system["repeat_question_rate"]["value"]
    base = baseline["repeat_question_rate"]["value"]
    reduction = (base-rqr)/base*100 if base is not None and base>0 and rqr is not None else None
    tsr = system["task_success_rate"]["value"]
    hr = system["hallucination_rate"]["price_only"]["value"]
    valid = system["trace_health"]["valid"] and baseline["trace_health"]["valid"]
    gates = {"rqr_relative_reduction_ge_40pct": reduction>=40 if reduction is not None else None,
             "tsr_ge_70pct":tsr>=70 if tsr is not None else None,
             "price_hr_le_5pct":hr<=5 if hr is not None else None}
    return {"rqr_relative_reduction_pct":round(reduction,3) if reduction is not None else None,
            "tsr_delta_percentage_points": round(tsr-baseline["task_success_rate"]["value"],3) if tsr is not None and baseline["task_success_rate"]["value"] is not None else None,
            "gates":gates, "valid_traces":valid,
            "status":"invalid" if not valid else "inconclusive" if any(v is None for v in gates.values()) else "pass" if all(gates.values()) else "fail",
            "note":"Zero baseline RQR or no verifiable price claims is inconclusive, not a pass."}


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
