#!/usr/bin/env python3
"""One-command text/audio evaluation of the first 40 scenarios and baseline."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,"reconfigure"):
        stream.reconfigure(encoding="utf-8",line_buffering=True)
os.environ["PYTHONIOENCODING"] = "utf-8"
from dotenv import load_dotenv
from eval.benchmark_support import (validate_inputs, turn_keys, trace_health,
                                    FreshCallBrief, compare_metrics, machine_metadata)
from eval.team_eval import REFERENCE, evaluate_team, select_scenarios
from eval.model_config import configure_eval_model, permanent_provider_error


def write_json(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(path)


def print_metrics(label, report):
    print(f"\n=== {label} ===",flush=True)
    for key in ("repeat_question_rate","context_carryover_rate","task_success_rate","hallucination_rate","tool_call_accuracy"):
        print(f"{key}: {report[key]['value']}%",flush=True)
    print(f"HR price only: {report['hallucination_rate']['price_only']['value']}%")
    print(f"Calls-to-close: {report['calls_to_close']['value']}; avg turns/call: {report['avg_turns_per_call']}")
    print(f"Guardrail violations: {report['guardrail_violations']['total']}")
    checks = report["memory_checks"]
    print(f"Memory checks: {sum(c['verdict']=='likely_ok' for c in checks)}/{len(checks)} likely_ok")
    print(f"MWQ: {report['memory_write_quality'].get('status')}; aggregate: {json.dumps(report['memory_write_quality'].get('aggregate'))}")
    cost = report["estimated_cost_per_call"]
    print(f"Estimated cost/call USD: {cost['average_per_call_usd']} (pricing configured: {cost['configured']})")
    print(f"HR price/promo: {report['hallucination_rate']['price_promo_only']['value']}%")
    for key in ("ttft","total","ttfa","call_brief","request_complete","persistence"):
        print(f"Latency {key}: {json.dumps(report['latency'][key])}")
    print(f"Streaming: {json.dumps(report['latency']['streaming'])}")
    print(f"ASR: {json.dumps(report['latency']['asr'])}")
    if "asr" in report:
        print(f"ASR WER: {report['asr']['WER']}%; CER: {report['asr']['CER']}%; coverage: {json.dumps(report['asr']['coverage'])}")
    print(f"Trace valid: {report['trace_health']['valid']}; errors: {report['trace_health']['error_turns']}; failed LLM requests: {report['trace_health']['failed_llm_requests']}",flush=True)


def asr_report(scenarios,trace,out):
    gt, hy = [], {}
    for sid,scenario in scenarios.items():
        for call,spec in scenario["calls"].items():
            for turn,text in enumerate(spec.get("customer_turns",[]),1):
                key = f"{sid}/{call}/{turn}"
                gt.append({"id":key,"full_text":text,"noisy":spec.get("input_mode")=="noisy"})
    for (sid,call),rows in trace.items():
        for row in rows:
            if "_error" not in row:
                hy[f"{sid}/{call}/{row['turn']}"] = {"text":row.get("normalized_customer_text",row["customer_text"])}
    out.mkdir(exist_ok=True)
    write_json(out / "ground_truth.json",{"dialogues":gt})
    write_json(out / "hypotheses.json",hy)
    report = REFERENCE.wer_cer(str(out))
    report["coverage"] = {"expected":len(gt),"observed":len(hy)}
    report["note"] = "Per-turn offline ASR; entities/speaker ground truth is not supplied by this audio manifest."
    return report


async def run_arm(args,scenarios,kind,config,run_dir):
    from eval.generate_traces import run_scenario
    from telesale_agent.bootstrap import build_deepagent_harness
    from telesale_agent.adapters.db.client import db_client
    arm_dir = run_dir / kind / config
    arm_dir.mkdir(parents=True)
    os.environ["CUSTOMER_MEMORY_ROOT"] = str(arm_dir / "memory")
    trace = defaultdict(list)
    total_rows = 0
    started = time.perf_counter()
    arm_error = None
    fatal_error = False
    consecutive_failed = 0
    try:
        async with build_deepagent_harness(memory_mode="durable" if config=="full" else "disabled") as harness:
            harness.call_brief = FreshCallBrief(harness.call_brief,db_client)
            with (arm_dir / "trace.jsonl").open("w",encoding="utf-8") as out:
                for index,(sid,scenario) in enumerate(scenarios.items(),1):
                    print(f"[Suite] {kind}/{config} {index}/{len(scenarios)} {sid}",flush=True)
                    try:
                        rows = await run_scenario(scenario,harness,config,args.version,
                                                  sleep_turn=args.sleep,max_retries=1,cleanup_orders=True,
                                                  input_kind=kind,audio_root=args.audio_root,
                                                  streaming=args.streaming)
                    except Exception as exc:
                        rows = [{"scenario_id":sid,"call":call,"turn":turn,"agent_text":"","customer_text":"",
                                 "tool_calls":[],"claims":[],"facts_used":[],"questions":[],"memory_writes":[],
                                 "latency":{},"_error":f"scenario setup failed: {type(exc).__name__}: {exc}"}
                                for s,call,turn in sorted(turn_keys({sid:scenario}))]
                    for row in rows:
                        row["latency_warmup"] = total_rows < 3
                        total_rows += 1
                        trace[(sid,row["call"])].append(row)
                        out.write(json.dumps(row,ensure_ascii=False)+"\n")
                    out.flush()
                    permanent_failure = next((row.get("_error") for row in rows if row.get("_fatal_provider_error")),None)
                    if permanent_failure:
                        fatal_error = True
                        arm_error = permanent_failure
                        print("[Suite ERROR] Permanent provider error; stopping this benchmark without further API calls.",flush=True)
                        break
                    failed = bool(rows) and all("_error" in row for row in rows)
                    consecutive_failed = consecutive_failed+1 if failed else 0
                    if consecutive_failed >= args.max_consecutive_failures:
                        arm_error = "Stopped after consecutive scenarios with all turns failing; remaining turns are missing."
                        break
    except Exception as exc:
        arm_error = f"{type(exc).__name__}: {exc}"
        fatal_error = permanent_provider_error(exc)
        print(f"[Suite ERROR] {kind}/{config}: {arm_error}",flush=True)
    pricing = {key:args.pricing.get(key) for key in ("input_per_million","output_per_million","tool_call","memory_write","storage_per_mb","fixed_call")}
    report = evaluate_team(scenarios,trace,pricing=pricing)
    if kind == "audio":
        report["asr"] = asr_report(scenarios,trace,arm_dir / "asr")
    judge = None
    if args.judge_memory and config == "full" and report["trace_health"]["valid"]:
        judge_path = arm_dir / "memory_judge.json"
        command = [sys.executable,str(ROOT / "src/eval/memory_judge.py"),"--scenarios",str(args.scenarios),
                   "--scenario-id",next(iter(scenarios)),"--trace",str(arm_dir / "trace.jsonl"),"--out",str(judge_path)]
        # Judge the same prefix, rather than the first scenario only.
        command[command.index("--scenario-id"):command.index("--scenario-id")+2] = ["--limit",str(args.limit)]
        judge = subprocess.run(command,cwd=ROOT,check=False).returncode
        if judge_path.exists():
            report["memory_write_quality"] = json.loads(judge_path.read_text(encoding="utf-8"))
    wrapped = {"evaluator":"team_eval_v2","n_scenarios":len(scenarios),"input_kind":kind,"config":config,
               "wall_seconds":round(time.perf_counter()-started,3),"error":arm_error,
               "fatal_provider_error":fatal_error,"judge_exit_code":judge,"system":report}
    write_json(arm_dir / "report.json",wrapped)
    print_metrics(f"{kind}/{config}",report)
    return wrapped


async def run(args,scenarios,run_dir,metadata):
    reports,comparisons = {},{}
    blocked_reason = None
    for kind in args.input_kinds:
        reports[kind] = {}
        for config in ("baseline_no_memory","full"):
            if blocked_reason:
                empty = evaluate_team(scenarios,{},pricing=args.pricing)
                reports[kind][config] = {"input_kind":kind,"config":config,"system":empty,
                                       "error":blocked_reason,"skipped":True,"fatal_provider_error":True}
                write_json(run_dir / kind / config / "report.json",reports[kind][config])
            else:
                reports[kind][config] = await run_arm(args,scenarios,kind,config,run_dir)
                if reports[kind][config].get("fatal_provider_error"):
                    blocked_reason = reports[kind][config]["error"]
            write_json(run_dir / "results.partial.json",reports)
        comparisons[kind] = compare_metrics(reports[kind]["full"]["system"],reports[kind]["baseline_no_memory"]["system"])
        print(f"\n[Acceptance {kind}] {json.dumps(comparisons[kind],ensure_ascii=False)}",flush=True)
    finished = datetime.now().astimezone().isoformat()
    metadata["precomputed_parts"] = sorted({part for modes in reports.values() for arm in modes.values()
                                             for part in arm["system"]["latency"].get("precomputed_parts",[])})
    all_valid = all(arm["system"]["trace_health"]["valid"] and not arm["error"] for modes in reports.values() for arm in modes.values())
    result = {"metadata":{**metadata,"finished_at":finished},
              "status":"blocked_provider" if blocked_reason else "completed" if all_valid else "completed_with_errors",
              "blocked_reason":blocked_reason,
              "reports":reports,"comparison":comparisons}
    write_json(run_dir / "report.json",result)
    metadata["finished_at"] = finished
    write_json(run_dir / "metadata.json",metadata)
    print(f"\n[Suite] {result['status']}: {run_dir / 'report.json'}",flush=True)
    if not all_valid:
        return 2
    return 0 if all(c["status"]=="pass" for c in comparisons.values()) else 3


async def run_asr_only(args,scenarios,run_dir,metadata):
    from telesale_agent.adapters.asr import ZipformerASREngine
    from telesale_agent.application.asr_normalization import normalize_asr_transcript
    from telesale_agent.core.models import TurnInput,TurnContext,ConversationState
    from eval.benchmark_support import audio_path,measured_latency
    import wave
    engine = ZipformerASREngine()
    trace = defaultdict(list)
    with (run_dir / "asr_trace.jsonl").open("w",encoding="utf-8") as output:
        for index,(sid,call,turn) in enumerate(sorted(turn_keys(scenarios))):
            path = audio_path(args.audio_root,sid,call,turn)
            with wave.open(str(path),"rb") as wav:
                duration = wav.getnframes()/wav.getframerate()
            item = TurnInput(conversation_id=f"{sid}/{call}",audio=path.read_bytes())
            row = {"scenario_id":sid,"call":call,"turn":turn,"latency_warmup":index<3,
                   "audio":{"path":str(path),"duration_seconds":duration}}
            started = time.perf_counter()
            try:
                text = await engine.transcribe(TurnContext(input=item,state=ConversationState(item.conversation_id)))
                row.update(customer_text=text,normalized_customer_text=normalize_asr_transcript(text),
                           latency={"asr_ms":(time.perf_counter()-started)*1000,"measurement_mode":"asr_only"})
            except Exception as exc:
                row.update(customer_text="",latency={},_error=f"{type(exc).__name__}: {exc}")
            trace[(sid,call)].append(row)
            output.write(json.dumps(row,ensure_ascii=False)+"\n")
            output.flush()
            if index%10==0:
                print(f"[ASR] {index+1}/{len(turn_keys(scenarios))} {sid}/{call}/{turn}",flush=True)
    result = {"mode":"asr_only","metadata":metadata,"asr":asr_report(scenarios,trace,run_dir / "asr"),
              "latency":measured_latency(trace,REFERENCE),"trace_health":trace_health(scenarios,trace)}
    asr_stats = result["latency"]["asr"]
    result["latency"] = {"asr":asr_stats,"warmup_turns":3,"sufficient_asr_sample":asr_stats["n"]>=100,
                         "note":"ASR-only run; chat TTFT/Total, CallBrief and voice-output TTFA are not measured."}
    result["metadata"]["finished_at"] = datetime.now().astimezone().isoformat()
    write_json(run_dir / "report.json",result)
    print(json.dumps({"mode":"asr_only","WER":result["asr"]["WER"],"CER":result["asr"]["CER"],
                      "latency":result["latency"]["asr"],"coverage":result["asr"]["coverage"],
                      "report":str(run_dir / "report.json")},ensure_ascii=False,indent=2),flush=True)
    return 0 if result["trace_health"]["valid"] else 2


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",default="benchmark_v"+datetime.now().strftime("%Y%m%d%H%M%S"))
    parser.add_argument("--scenarios",type=Path,default=ROOT / "dataset/iterative-refinement/scenarios_complete dataset")
    parser.add_argument("--audio-root",type=Path,default=ROOT / "dataset/iterative-refinement/audio")
    parser.add_argument("--output-root",type=Path,default=ROOT / "outputs/benchmark")
    parser.add_argument("--limit",type=int,default=40)
    parser.add_argument("--input-kinds",nargs="+",choices=["text","audio"],default=["text","audio"])
    parser.add_argument("--llm-provider",help="Eval provider (default: gemini; override with EVAL_LLM_PROVIDER)")
    parser.add_argument("--llm-model",help="Eval model (default: gemini-3.6-flash; override with EVAL_LLM_MODEL)")
    parser.add_argument("--request-timeout",type=float,default=30)
    parser.add_argument("--memory-persister-mode",choices=["turn","llm_learning","llm_episode","deterministic"],default=os.environ.get("MEMORY_PERSISTER_MODE","llm_learning"))
    parser.add_argument("--judge-memory",action="store_true")
    parser.add_argument("--sleep",type=float,default=0)
    parser.add_argument("--max-consecutive-failures",type=int,default=3)
    parser.add_argument("--preflight-only",action="store_true")
    parser.add_argument("--asr-only",action="store_true",help="Evaluate all selected WAVs locally without LLM calls")
    parser.add_argument("--streaming",action=argparse.BooleanOptionalAction,default=True,
                        help="Consume actual guarded answer events; --no-streaming measures complete non-streamed turns")
    parser.add_argument("--request-interval",type=float,default=None,help="Shared seconds between model requests; default 30 for Groq GPT-OSS, otherwise 0")
    parser.add_argument("--model-retries",type=int,default=2,help="Provider-request retries; never replay a complete mutation turn")
    parser.add_argument("--reasoning-effort",choices=["low","medium","high"],default=None)
    parser.add_argument("--thinking-level",choices=["minimal","low","medium","high"],default=None,
                        help="Optional Gemini thinking level; default follows the application environment")
    args = parser.parse_args()
    if args.limit<=0 or args.sleep<0 or args.request_timeout<=0 or args.max_consecutive_failures<1 or args.model_retries<0 or (args.request_interval is not None and args.request_interval<0):
        parser.error("limit/timeout/failure threshold must be positive; sleep must be nonnegative")
    if not args.version or Path(args.version).name!=args.version or args.version in (".",".."):
        parser.error("version must be a single directory name")
    args.input_kinds = list(dict.fromkeys(args.input_kinds))
    if args.asr_only:
        args.input_kinds = ["audio"]
    if args.thinking_level:
        os.environ["LLM_THINKING_LEVEL"] = args.thinking_level
    os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = str(args.request_timeout)
    os.environ["LLM_MAX_RETRIES"] = str(args.model_retries)
    os.environ["MEMORY_PERSISTER_MODE"] = args.memory_persister_mode
    # External tracing is unnecessary for an on-disk reproducible benchmark.
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    try:
        model = configure_eval_model(args.llm_provider,args.llm_model,request_interval=args.request_interval)
    except ValueError as exc:
        parser.error(str(exc))
    scenarios = select_scenarios(REFERENCE.load_scenarios(str(args.scenarios)),limit=args.limit)
    if len(scenarios)!=args.limit:
        parser.error("Dataset contains fewer scenarios than requested")
    try:
        selection = validate_inputs(scenarios,args.audio_root if "audio" in args.input_kinds else None)
    except (ValueError,OSError) as exc:
        parser.error(str(exc))
    print(f"[Preflight] {json.dumps(selection,ensure_ascii=False)}",flush=True)
    if args.preflight_only:
        print(f"[Model] {model.provider}/{model.model}; request interval={os.environ['EVAL_REQUEST_INTERVAL_SECONDS']}s; sleep/turn={args.sleep:g}s",flush=True)
        return 0
    run_dir = args.output_root / args.version
    if run_dir.exists():
        parser.error(f"Output already exists: {run_dir}; choose a new --version")
    if not model.api_key and not args.asr_only:
        key_name = "GOOGLE_API_KEY or GEMINI_API_KEY" if model.provider=="gemini" else "GROQ_API_KEY"
        parser.error(f"No API key configured for {model.provider}; set {key_name} in .env")
    interval = float(os.environ["EVAL_REQUEST_INTERVAL_SECONDS"])
    reasoning = (args.reasoning_effort or os.environ.get("GROQ_REASONING_EFFORT") or "low") if model.provider=="groq" and "gpt-oss" in model.model else None
    if reasoning:
        os.environ["GROQ_REASONING_EFFORT"] = reasoning
    run_dir.mkdir(parents=True)
    rates = {"input_per_million":"EVAL_INPUT_USD_PER_MILLION","output_per_million":"EVAL_OUTPUT_USD_PER_MILLION",
             "tool_call":"EVAL_TOOL_CALL_USD","memory_write":"EVAL_MEMORY_WRITE_USD",
             "storage_per_mb":"EVAL_MEMORY_STORAGE_USD_PER_MB","fixed_call":"EVAL_FIXED_CALL_USD"}
    args.pricing = {k:float(os.environ[v]) if os.environ.get(v) else None for k,v in rates.items()}
    metadata = {"started_at":datetime.now().astimezone().isoformat(),"hardware":machine_metadata(),
                "selection":selection,"dataset_sha256":hashlib.sha256(json.dumps(scenarios,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                "provider":model.provider,"model":model.model,
                "temperature":None if model.provider=="gemini" and model.model=="gemini-3.6-flash" else 0.3,
                "temperature_policy":"provider default (fixed sampling)" if model.provider=="gemini" and model.model=="gemini-3.6-flash" else "explicit 0.3",
                "thinking_level":os.environ.get("LLM_THINKING_LEVEL") if model.provider=="gemini" else None,
                "request_timeout_seconds":model.timeout,
                "max_output_tokens":model.max_output_tokens,"model_max_retries":model.max_retries,
                "request_interval_seconds":interval,"asr_only":args.asr_only,
                "reasoning_effort":reasoning,
                "memory_persister_mode":args.memory_persister_mode,"warmup_turns_per_arm":3,
                "input_kinds":args.input_kinds,"command":subprocess.list2cmdline([sys.executable,*sys.argv]),
                "streaming":args.streaming,
                "timing_boundary":"harness entry to first/last emitted answer; offline ASR subtracted; persistence reported separately",
                "latency_guide":"dataset/BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md",
                "precomputed_parts":[],"precomputed_parts_policy":"observed per turn before current-turn persistence",
                "freshness":"CRM/profile/order history reloaded at call entry; remembered SKU inventory/promotions rechecked; cross-channel interaction source unavailable"}
    source_paths = sorted((ROOT / "src/eval").glob("*.py")) + [
        ROOT / "src/telesale_agent/application/deepagent" / name
        for name in ("streaming.py", "turn.py", "harness.py")]
    source_paths += [ROOT / "src/telesale_agent/entrypoints/api/chat.py",
                     ROOT / "src/telesale_agent/application/deepagent/tools/routing.py"]
    metadata["source_sha256"] = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    metadata["git_commit"] = subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    write_json(run_dir / "metadata.json",metadata)
    print(f"[Model] {model.provider}/{model.model}; request interval={interval:g}s; sleep/turn={args.sleep:g}s",flush=True)
    return asyncio.run(run_asr_only(args,scenarios,run_dir,metadata) if args.asr_only else run(args,scenarios,run_dir,metadata))


if __name__ == "__main__":
    raise SystemExit(main())
