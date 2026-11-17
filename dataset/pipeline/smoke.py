"""Explicit offline test fixture. Never used as a fallback for a live provider."""
from __future__ import annotations

import json
from pathlib import Path

from .common import file_hash, read, write
from .providers import ReplayProvider
from .review import CRITERIA
from .runner import generate_run, plan_run, verify_run


class SmokeProvider:
    metadata = {"provider": "OFFLINE_TEST_FIXTURE_ONLY", "model": "no-real-model"}

    def request(self, request: dict) -> dict:
        payload = json.loads(request["messages"][1]["content"])
        if request["kind"] == "duplicate":
            value = {"duplicate": False, "reason": "Offline test fixture only."}
        elif request["kind"] == "quality_review":
            turns = payload["transcripts"]
            evidence = [{"transcript_id": t["transcript_id"], "turn_index": 0,
                         "quote": t["utterances"][0]["text"]} for t in turns]
            value = {"journey_id": payload["journey_plan"]["journey_id"], "checks": [
                {"criterion": c, "verdict": "pass", "reason": "Simulated test assertion, not real LLM review.",
                 "evidence": evidence if c == "continuity" else evidence[:1]} for c in sorted(CRITERIA)]}
        else:
            s = payload["session_plan"]
            context = "Chị đang tìm hiểu lần đầu cho phòng khách." if s["session_index"] == 1 else "Chị gọi tiếp sau lần trao đổi trước và đã hỏi người nhà."
            value = {"transcript_id": s["transcript_id"], "customer_id": s["customer_id"],
                     "session_index": s["session_index"], "channel": s["channel"], "outcome": s["expected_outcome"],
                     "utterances": [
                         {"speaker": "customer", "text": f"{context} Em tư vấn {s['facts']['product']['name']} nhé."},
                         {"speaker": "agent", "text": f"Dạ giá hiện tại là {s['facts']['price_vnd']} đồng, em tư vấn theo nhu cầu mình."},
                         {"speaker": "customer", "text": "Chị sẽ cân nhắc thêm, lần này chưa đặt hàng ngay."},
                         {"speaker": "agent", "text": "Dạ em ghi nhận, chị cần thêm thông tin thì mình tiếp tục nhé."}]}
        return {"completed": True, "text": json.dumps(value, ensure_ascii=False),
                "raw": {"OFFLINE_TEST_FIXTURE_ONLY": True}, "metadata": {"model": "no-real-model"}}


def run_smoke(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    write(output / "domain/catalog.json", {"reference_date": "2026-10-15", "products": [
        {"sku": "SMOKE-A", "name": "Sản phẩm kiểm thử", "category": "kiem-thu", "price_vnd": 123000, "stock": 10}]})
    config = {"version": 1, "domain": {"kind": "json", "root": "domain", "policies": []},
              "planning": {"seed": 17, "start_date": "2026-10-15", "customers": 1,
                           "multichannel_customers": 0, "personas": ["hesitant"], "hard_cases": []},
              "generation": {"model": "OFFLINE_TEST_ONLY", "max_output_tokens": 1000, "max_attempts": 2, "max_api_calls": 10},
              "review": {"model": "SAME_AS_GENERATOR", "max_output_tokens": 1000},
              "duplicates": {"review_threshold": .999999, "reject_threshold": 1, "judge_ambiguous": True},
              "validation": {"min_turns": 4, "max_turns": 12, "min_words": 8},
              "requirements": {"transcripts": 2, "two_hotline_customers": 1, "catalog_skus": 1}}
    write(output / "config.json", config)
    plan_run(output / "config.json", output / "plan")
    result = generate_run(output / "plan", output / "generation", SmokeProvider())
    verified = verify_run(output / "generation")
    generate_run(output / "generation/plan", output / "replay", ReplayProvider(output / "generation"))
    verify_run(output / "replay")
    a, b = read(output / "generation/manifest.json"), read(output / "replay/manifest.json")
    if a != b or any(file_hash(output / "generation" / r["path"]) != file_hash(output / "replay" / r["path"]) for r in a):
        raise ValueError("offline replay artifacts differ")
    if result["status"] != "automated_release" or verified["transcripts"] != 2:
        raise ValueError("offline smoke did not produce two verified fixture transcripts")
    report = {"status": "passed", "mode": "OFFLINE_TEST_FIXTURE_ONLY", "api_calls": 0,
              "fixture_transcripts": 2, "production_transcripts": 0, "byte_identical_replay": True}
    write(output / "smoke_report.json", report)
    return report
