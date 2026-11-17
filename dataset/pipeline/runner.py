from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .checks import validate_schema, validate_transcript
from .common import HERE, code_hashes, file_hash, files_manifest, fingerprint, new_directory, read, runtime, verify_files, write
from .domain import load_domain, source_paths
from .duplicates import DuplicateIndex
from .planner import build_plans, coverage, validate_config
from .providers import ProviderFailure, Recorder
from .review import review_record, validate_review

JUDGE_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["duplicate", "reason"],
                "properties": {"duplicate": {"type": "boolean"}, "reason": {"type": "string"}}}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_dataset_card(output: Path, report: dict, status: str, provider: dict) -> None:
    counts = report["counts"]
    (output / "DATASET_CARD.md").write_text(
        "# Bộ transcript telesales tổng hợp\n\n"
        "## Cách sinh dữ liệu\n\n"
        "Kế hoạch được tạo từ cấu hình, seed và bản chụp dữ liệu nghiệp vụ; không dùng M1 prefilled/complete làm đầu vào. "
        "LLM viết từng phiên theo thứ tự; kết quả qua kiểm tra định dạng, dữ kiện và trùng lặp, có số lần thử giới hạn. "
        f"Chế độ/provider ghi nhận: `{provider.get('provider', 'unknown')}`. Xem `run.json`, `calls/` và kế hoạch nguồn để truy vết; "
        "nếu đây là bản replay/release, đối chiếu run nguồn thay vì coi là lần gọi model mới.\n\n"
        "## Phân bố\n\n"
        f"Có {counts['transcripts']} transcript, {counts['customers']} khách tổng hợp, {counts['journeys']} hành trình; "
        f"{counts['two_hotline_customers']} khách có hai phiên hotline, {counts['call_chat_customers']} khách gọi và chat. "
        f"Phân bố kênh: `{json.dumps(report['channels'], ensure_ascii=False)}`. "
        "Mỗi transcript là một tệp JSON. Chi tiết persona và phần thiếu so yêu cầu ở `coverage_report.json`.\n\n"
        "## Hạn chế\n\n"
        f"Trạng thái: `{status}`. Đây là hội thoại tham chiếu tổng hợp, không phải trace agent thực tế. "
        "Kiểm tra số/thực thể, similarity và model judge không chứng minh mọi câu đúng nghĩa hoặc không còn trùng ngữ nghĩa. "
        "Review tự động bằng rubric LLM có bằng chứng trích dẫn, không có bước người duyệt bắt buộc. "
        "Review tự động vẫn có thể sai; không sinh audio, không đo ASR/diarization hoặc kết quả simulator. "
        "Replay dùng response đã lưu; gọi lại model không đảm bảo cùng từng byte.\n\n"
        "## Thông tin cá nhân\n\n"
        "Pipeline tạo định danh khách thử nghiệm, không phát sinh số điện thoại để liên hệ người thật. "
        "Không có masker: nội dung và dữ kiện được chọn gửi nguyên văn cho provider; prompt/response lưu local có thể chứa dữ kiện gốc. "
        "Chỉ cấu hình nguồn được phép sử dụng, không đưa credential vào config; kiểm tra thông tin cá nhân và quyền sử dụng trước chia sẻ. "
        "Công cụ không chứng nhận tuân thủ toàn bộ yêu cầu PII của đề.\n",
        encoding="utf-8")


def plan_run(config_path: Path, output: Path, references: list[Path] | None = None) -> dict:
    config = read(config_path)
    validate_config(config)
    # Credentials belong to the environment, never the reproducibility config.
    def check_keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if any(s in k.lower() for s in ("api_key", "secret", "password", "access_token")):
                    raise ValueError("credentials are forbidden in pipeline config")
                check_keys(v)
        elif isinstance(value, list):
            for v in value:
                check_keys(v)
    check_keys(config)
    root = (config_path.resolve().parent / config["domain"]["root"]).resolve()
    sources = source_paths(root, config["domain"])
    # Read and validate before creating output, so absent sources fail without mutation.
    for p in sources:
        if not p.is_file():
            raise ValueError("a configured domain source is missing")
    reference_files = []
    for directory in references or []:
        for path in sorted(directory.glob("*.json")):
            data = read(path)
            if not isinstance(data, dict) or not isinstance(data.get("utterances"), list) or not data["utterances"]:
                raise ValueError("reference directories must contain only transcript JSON files")
            if not isinstance(data.get("transcript_id"), str) or any(not isinstance(t, dict) or t.get("speaker") not in {"customer", "agent"}
                       or not isinstance(t.get("text"), str) for t in data["utterances"]):
                raise ValueError("invalid reference transcript")
            reference_files.append(path)
    output = new_directory(output)
    for path in sources:
        dest = output / "snapshot/domain" / path.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    for i, path in enumerate(reference_files):
        write(output / "snapshot/references" / f"{i:06d}.json", read(path))
    frozen = json.loads(json.dumps(config))
    frozen["domain"]["root"] = "snapshot/domain"
    write(output / "config.json", frozen)
    domain = load_domain(output / "snapshot/domain", frozen["domain"])
    plans = build_plans(frozen, domain)
    report = coverage(plans, domain.products, frozen["requirements"])
    report["scope"] = "planned coverage; no transcripts generated"
    write(output / "catalog.json", domain.products)
    write(output / "plans.json", plans)
    write(output / "coverage_report.json", report)
    write(output / "run.json", {"kind": "plan", "created_at": stamp(), "config_sha256": file_hash(config_path),
                                "code_sha256": code_hashes(), "runtime": runtime(),
                                "status": "planned" if not report["requirement_failures"] else "planned_with_coverage_gaps",
                                "source_dependency": "configured domain sources only; no M1 scenario files",
                                "reference_transcripts": len(reference_files)})
    write(output / "seal.json", {"files": files_manifest(output)})
    return report


def verify_plan(root: Path) -> tuple[dict, list[dict], list[dict]]:
    verify_files(root, read(root / "seal.json")["files"])
    if read(root / "run.json")["code_sha256"] != code_hashes():
        raise ValueError("pipeline code/prompts/schema changed; create a new plan run")
    config = read(root / "config.json")
    domain = load_domain(root / "snapshot/domain", config["domain"])
    plans = read(root / "plans.json")
    if build_plans(config, domain) != plans:
        raise ValueError("frozen plans cannot be reproduced from their domain/config")
    return config, plans, read(root / "catalog.json")


def parse_response(response: dict):
    if response.get("completed") is not True:
        raise ValueError("response refused, incomplete or empty")
    return json.loads(response["text"])


def request(kind: str, payload: dict, schema: dict) -> dict:
    names = {"generate": ("generate.md", "transcript"), "duplicate": ("duplicate.md", "duplicate_decision"),
             "quality_review": ("review.md", "journey_review")}
    filename, schema_name = names[kind]
    prompt = (HERE / "prompts" / filename).read_text(encoding="utf-8")
    return {"kind": kind, "schema_name": schema_name,
            "schema": schema, "messages": [{"role": "system", "content": prompt},
                                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]}


def entity_values(session: dict) -> list[str]:
    p = session["facts"]["product"]
    return [p["name"], p["sku"], session["customer_id"], p.get("parent_sku", "")]


def duplicate_check(candidate: dict, session: dict, index: DuplicateIndex, cfg: dict, provider: Recorder) -> tuple[list[str], dict]:
    result = index.compare(candidate, entity_values(session), cfg)
    if result["decision"] == "reject":
        return ["duplicate: wording/structure too close to " + result["matches"][0]["transcript_id"] + "; vary narrative and phrasing, preserve facts"], result
    if result["decision"] == "review":
        if not cfg["judge_ambiguous"]:
            return ["duplicate: ambiguous similarity requires an automated judge or a more distinct rewrite"], result
        for match in result["matches"]:
            response = provider.request(request("duplicate", {"candidate": {"utterances": candidate["utterances"]},
                                                               "reference": match["reference"]}, JUDGE_SCHEMA))
            try:
                decision = parse_response(response)
                if not isinstance(decision, dict) or set(decision) != {"duplicate", "reason"} or type(decision["duplicate"]) is not bool or not isinstance(decision["reason"], str) or not decision["reason"].strip():
                    raise ValueError("invalid duplicate judge schema")
            except (ValueError, TypeError, KeyError):
                return ["duplicate: judge response invalid; no automatic acceptance"], result
            match["judge"] = decision
            if decision["duplicate"]:
                return ["duplicate: " + decision["reason"]], result
    return [], result


def automated_review(plan: dict, transcripts: list[dict], provider: Recorder) -> dict:
    req = request("quality_review", {"journey_plan": plan, "transcripts": transcripts}, read(HERE / "review.schema.json"))
    response = provider.request(req)
    decision = None
    try:
        decision = parse_response(response)
        errors = validate_review(decision, plan["journey_id"], transcripts)
    except (ValueError, TypeError, KeyError):
        errors = ["review: incomplete or invalid rubric response; cannot automatically approve"]
    return review_record(plan, transcripts, req, response, decision, errors)


def journey_artifacts(plan: dict, history: list[dict], decisions: list[dict], review_sha256: str,
                      schema: dict) -> tuple[list[dict], list[str]]:
    """Build exports only for a fully validated and reviewed journey."""
    artifacts = []
    for candidate, decision in zip(history, decisions):
        session = plan["sessions"][candidate["session_index"] - 1]
        artifact = {**candidate, "journey_id": plan["journey_id"], "language": "vi",
                    "date": session["date"], "persona": plan["persona"], "hard_case": session["hard_case"],
                    "previous_transcript_id": plan["sessions"][candidate["session_index"] - 2]["transcript_id"] if candidate["session_index"] > 1 else None,
                    "origin": "synthetic_llm_reference", "is_actual_agent_trace": False,
                    "review_status": "automated_approved",
                    "provenance": {"plan_sha256": fingerprint(plan), "request_sha256": decision["request_sha256"],
                                   "automated_review_sha256": review_sha256}}
        errors = validate_schema(artifact, schema)
        if errors:
            return [], errors
        artifacts.append(artifact)
    return artifacts, []


def generate_run(plan_root: Path, output: Path, provider, *, limit: int | None = 1) -> dict:
    config, all_plans, catalog = verify_plan(plan_root)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be positive or None for all")
    plans = all_plans if limit is None else all_plans[:limit]
    output = new_directory(output)
    shutil.copytree(plan_root, output / "plan")
    schema = read(HERE / "response.schema.json")
    export_schema = read(HERE / "transcript.schema.json")
    for name in ("response.schema.json", "transcript.schema.json", "review.schema.json"):
        write(output / "schemas" / name, read(HERE / name))
    index = DuplicateIndex()
    catalog_entities = [p["name"] for p in catalog] + [p["sku"] for p in catalog]
    for path in sorted((plan_root / "snapshot/references").glob("*.json")):
        index.add(read(path), catalog_entities, f"reference:{path.name}")
    recorder = Recorder(provider, output, config["generation"]["max_api_calls"])
    metadata = {"kind": "generation", "created_at": stamp(), "status": "running", "runtime": runtime(),
                "provider": provider.metadata, "plan_seal_sha256": file_hash(plan_root / "seal.json"),
                "code_sha256": code_hashes(), "selected_journeys": len(plans), "limit": limit,
                "input_handling": "original synthetic dialogue/facts; no masker",
                "review_mode": "automated_llm_rubric_and_deterministic_checks", "audio_generated": False}
    write(output / "run.json", metadata)
    accepted, manifest, audit, rejected, review_audit = [], [], [], [], []
    stopped = None
    for plan in plans:
        feedback = []
        success = False
        for attempt in range(1, config["generation"]["max_attempts"] + 1):
            temp_index = index.copy()
            history = []
            decisions = []
            for session in plan["sessions"]:
                payload = {"session_plan": session, "previous_sessions": history,
                           "validation_feedback": feedback,
                           "limits": config["validation"]}
                attempt_path = output / "attempts" / plan["journey_id"] / f"{attempt:02d}" / f"{session['transcript_id']}.json"
                model_request = request("generate", payload, schema)
                try:
                    response = recorder.request(model_request)
                    candidate = parse_response(response)
                    errors = validate_transcript(candidate, session, history, config["validation"])
                    similarity = None
                    if not errors:
                        errors, similarity = duplicate_check(candidate, session, temp_index, config["duplicates"], recorder)
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    candidate, errors, similarity = None, ["format: response is incomplete or not valid transcript JSON"], None
                except ProviderFailure as exc:
                    stopped = str(exc)
                    candidate, errors, similarity = None, ["provider: stopped without inventing a response"], None
                record = {"transcript_id": session["transcript_id"], "attempt": attempt,
                          "request_sha256": fingerprint(model_request), "errors": errors,
                          "duplicate_result": similarity}
                write(attempt_path, record)
                decisions.append(record)
                if errors:
                    feedback = [f"{session['transcript_id']}: {error}" for error in errors]
                    break
                history.append(candidate)
                temp_index.add(candidate, entity_values(session), f"run:{plan['journey_id']}")
            audit.extend(decisions)
            if stopped:
                break
            if len(history) == len(plan["sessions"]):
                try:
                    review = automated_review(plan, history, recorder)
                except ProviderFailure as exc:
                    stopped = str(exc)
                    feedback = ["review: provider stopped; no automatic approval"]
                    break
                review_path = output / "reviews" / plan["journey_id"] / f"attempt_{attempt:02d}.json"
                write(review_path, review)
                review_audit.append({"journey_id": plan["journey_id"], "attempt": attempt,
                                     "status": review["status"], "path": str(review_path.relative_to(output)),
                                     "errors": review["errors"]})
                if review["errors"]:
                    feedback = review["errors"]
                    continue
                artifacts, export_errors = journey_artifacts(plan, history, decisions, file_hash(review_path), export_schema)
                if export_errors:
                    feedback = export_errors
                    continue
                # Commit only after every session and the whole-journey review passed.
                index = temp_index
                accepted.append(plan)
                for candidate in artifacts:
                    path = output / "transcripts" / f"{candidate['transcript_id']}.json"
                    write(path, candidate)
                    manifest.append({"transcript_id": candidate["transcript_id"], "customer_id": candidate["customer_id"],
                                     "journey_id": plan["journey_id"], "path": str(path.relative_to(output)),
                                     "sha256": file_hash(path), "audio_path": None, "review_status": "automated_approved",
                                     "review_path": str(review_path.relative_to(output))})
                success = True
                break
        if not success:
            rejected.append({"journey_id": plan["journey_id"], "errors": feedback, "status": "quarantined"})
        # Persist progress without claiming unfinished journeys are accepted.
        write(output / "manifest.json", manifest)
        write(output / "quarantine.json", rejected)
        if stopped:
            break
    report = coverage(accepted, catalog, config["requirements"])
    report["scope"] = "generated transcripts passing deterministic checks and automated LLM review"
    if hasattr(provider, "finish") and not stopped:
        try:
            provider.finish()
        except ProviderFailure as exc:
            stopped = str(exc)
    status = "provider_stopped" if stopped else "quarantined" if rejected else "automated_release" if report["transcript_requirements_met"] else "automated_partial_coverage"
    metadata.update(status=status, model_calls=recorder.count, stop_reason=stopped)
    write(output / "coverage_report.json", report)
    write(output / "validation_report.json", {"status": status, "accepted_journeys": len(accepted),
                                               "exported_transcripts": len(manifest), "quarantined": rejected,
                                               "review_mode": "automated", "semantic_equivalence_proven": False})
    write(output / "automated_review_report.json", {"mode": "automated_llm_rubric", "reviews": review_audit,
                                                     "policy": "all seven criteria must pass with valid citations; otherwise retry/quarantine"})
    write(output / "duplicate_report.json", {"algorithm": "normalized_word_trigram_jaccard_v1",
                                              "thresholds": config["duplicates"], "attempts": audit,
                                              "limitation": "Approximate detection plus model judgment; no guarantee all semantic duplicates are found."})
    write(output / "manifest.json", manifest)
    write(output / "quarantine.json", rejected)
    write(output / "run.json", metadata)
    write_dataset_card(output, report, status, provider.metadata)
    write(output / "seal.json", {"files": files_manifest(output)})
    return {"status": status, "exported_transcripts": len(manifest), "accepted_journeys": len(accepted),
            "model_calls": recorder.count, "coverage": report}


def verify_run(root: Path) -> dict:
    """Check output JSON, whole journeys, review evidence and archive links."""
    verify_files(root, read(root / "seal.json")["files"])
    metadata = read(root / "run.json")
    if metadata["kind"] == "plan":
        verify_plan(root)
        return {"status": "verified_plan", "transcripts": 0}
    if metadata["kind"] != "generation":
        raise ValueError("unsupported run kind")
    schema = read(root / "schemas/transcript.schema.json")
    review_schema = read(root / "schemas/review.schema.json")
    manifest = read(root / "manifest.json")
    if not isinstance(manifest, list):
        raise ValueError("manifest must be a JSON array")
    ids = [r["transcript_id"] for r in manifest]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate transcript IDs in manifest")
    paths = {r["path"] for r in manifest}
    if paths != {str(p.relative_to(root)) for p in (root / "transcripts").glob("*.json")}:
        raise ValueError("manifest does not match the transcript JSON files")
    all_plans = {p["journey_id"]: p for p in read(root / "plan/plans.json")}
    by_journey = {}
    call_records = {}
    for p in sorted((root / "calls").glob("*.json")):
        call = read(p)
        call_records.setdefault(call["request_sha256"], []).append(call)
    for row in manifest:
        path = root / row["path"]
        if row["path"] != f"transcripts/{row['transcript_id']}.json" or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("transcript path is invalid")
        artifact = read(path)
        errors = validate_schema(artifact, schema)
        if errors:
            raise ValueError("; ".join(errors))
        if file_hash(path) != row["sha256"] or any(artifact[k] != row[k] for k in ("transcript_id", "customer_id", "journey_id", "review_status")):
            raise ValueError("manifest metadata/checksum differs from transcript")
        if artifact["review_status"] != "automated_approved":
            raise ValueError("transcript lacks automated approval")
        by_journey.setdefault(artifact["journey_id"], []).append((artifact, row))
        matching = call_records.get(artifact["provenance"]["request_sha256"], [])
        body = {k: artifact[k] for k in read(root / "schemas/response.schema.json")["required"]}
        found = False
        for call in matching:
            try:
                found |= call["request"]["kind"] == "generate" and parse_response(call["response"]) == body
            except (KeyError, ValueError, TypeError):
                pass
        if not found:
            raise ValueError("transcript does not match an archived generation response")
    selected = []
    for jid, rows in by_journey.items():
        if jid not in all_plans:
            raise ValueError("unplanned journey in output")
        plan = all_plans[jid]
        selected.append(plan)
        rows.sort(key=lambda pair: pair[0]["session_index"])
        transcripts = [t for t, _ in rows]
        if [t["transcript_id"] for t in transcripts] != [s["transcript_id"] for s in plan["sessions"]]:
            raise ValueError("output contains a partial or reordered journey")
        review_paths = {row["review_path"] for _, row in rows}
        if len(review_paths) != 1:
            raise ValueError("journey review is inconsistent")
        rp = root / next(iter(review_paths))
        if not rp.resolve().is_relative_to(root.resolve()):
            raise ValueError("review path escapes run")
        record = read(rp)
        if record.get("status") != "automated_approved" or record.get("errors"):
            raise ValueError("journey lacks a passing automated review")
        errors = validate_review(record["decision"], jid, transcripts, review_schema)
        if errors:
            raise ValueError("; ".join(errors))
        recorded_review = False
        for call in call_records.get(record["request_sha256"], []):
            try:
                recorded_review |= (call["request"]["kind"] == "quality_review"
                                    and fingerprint(call["response"]) == record["response_sha256"]
                                    and parse_response(call["response"]) == record["decision"])
            except (KeyError, ValueError, TypeError):
                pass
        if not recorded_review:
            raise ValueError("review does not match an archived review response")
        for i, (t, _) in enumerate(rows):
            expected_previous = transcripts[i-1]["transcript_id"] if i else None
            if t["previous_transcript_id"] != expected_previous or t["customer_id"] != plan["customer_id"]:
                raise ValueError("broken customer/session linkage")
            if t["date"] != plan["sessions"][i]["date"]:
                raise ValueError("transcript date differs from plan")
            if t["provenance"]["plan_sha256"] != fingerprint(plan) or t["provenance"]["automated_review_sha256"] != file_hash(rp):
                raise ValueError("transcript review/plan provenance differs")
    counts = coverage(selected, read(root / "plan/catalog.json"), read(root / "plan/config.json")["requirements"])["counts"]
    if counts != read(root / "coverage_report.json")["counts"]:
        raise ValueError("coverage counts differ from actual transcript journeys")
    return {"status": "verified_automated_output", "transcripts": len(manifest), "journeys": len(selected)}

