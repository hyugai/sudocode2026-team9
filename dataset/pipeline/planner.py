from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta

from .domain import Domain

PERSONAS = {
    "hesitant": "Khách do dự cần hỏi người nhà trước khi quyết định",
    "price_comparison": "Khách so giá, yêu cầu giải thích tổng chi phí và điều kiện",
    "exchange": "Khách đã mua, liên hệ lại xin đổi size hoặc khiếu nại",
    "many_questions": "Khách hỏi nhiều nhưng chưa muốn mua",
    "impatient_third_call": "Khách gọi lần ba và mất kiên nhẫn",
}
HARD_CASES = {"changed_mind", "contradictory_budget", "expired_promotion", "unknown_information"}
STYLES = ["ngắn gọn, đi thẳng vào ý chính", "thân mật nhưng lịch sự", "thận trọng, hỏi lại điều kiện",
          "khách kể hoàn cảnh trước khi hỏi", "nêu băn khoăn rồi mới nhắc sản phẩm", "so sánh lợi ích trước khi nói giá"]


def validate_config(config: dict) -> None:
    if config.get("version") != 1:
        raise ValueError("config version must be 1")
    p = config["planning"]
    for key in ("customers", "seed"):
        if type(p[key]) is not int or p[key] < 0:
            raise ValueError(f"planning.{key} must be a nonnegative integer")
    if p["customers"] < 1 or not p.get("personas") or any(x not in PERSONAS for x in p["personas"]):
        raise ValueError("customers/personas must be configured and supported")
    multi = p["multichannel_customers"]
    if type(multi) is not int or not 0 <= multi <= p["customers"]:
        raise ValueError("multichannel_customers must be within customer count")
    if any(x not in HARD_CASES for x in p.get("hard_cases", [])):
        raise ValueError("unknown hard case")
    date.fromisoformat(p["start_date"])
    if type(config["generation"]["max_attempts"]) is not int or not 1 <= config["generation"]["max_attempts"] <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    if type(config["generation"]["max_api_calls"]) is not int or config["generation"]["max_api_calls"] < 1:
        raise ValueError("max_api_calls must be positive")
    d = config["duplicates"]
    if not 0 <= d["review_threshold"] < d["reject_threshold"] <= 1:
        raise ValueError("duplicate thresholds must satisfy 0 <= review < reject <= 1")
    if type(d["judge_ambiguous"]) is not bool:
        raise ValueError("judge_ambiguous must be boolean")
    if config["validation"]["min_turns"] < 4 or config["validation"]["max_turns"] < config["validation"]["min_turns"]:
        raise ValueError("turn limits must allow both speakers")
    for key in ("min_turns", "max_turns", "min_words"):
        if type(config["validation"][key]) is not int or config["validation"][key] <= 0:
            raise ValueError(f"validation.{key} must be a positive integer")
    if type(config["generation"]["max_output_tokens"]) is not int or config["generation"]["max_output_tokens"] <= 0:
        raise ValueError("max_output_tokens must be a positive integer")
    if not isinstance(config["review"]["model"], str) or not config["review"]["model"].strip():
        raise ValueError("automated review model must be configured")
    if type(config["review"]["max_output_tokens"]) is not int or config["review"]["max_output_tokens"] <= 0:
        raise ValueError("review.max_output_tokens must be positive")


def build_plans(config: dict, domain: Domain) -> list[dict]:
    validate_config(config)
    cfg = config["planning"]
    rng = random.Random(cfg["seed"])
    catalog = sorted(domain.products, key=lambda p: p["sku"])
    if not catalog:
        raise ValueError("no usable domain products")
    categories = sorted({p["category"].split("/")[0] for p in catalog})
    plans = []
    for i in range(cfg["customers"]):
        domain.reset()
        cid, jid = f"SYN-C{i+1:04d}", f"J{i+1:04d}"
        persona = cfg["personas"][i % len(cfg["personas"])]
        category = categories[i % len(categories)]
        pool = [p for p in catalog if p["category"].split("/")[0] == category]
        if persona == "exchange":
            # An exchange journey needs a product variant when supported by BTC.
            variants = [p for p in catalog if p.get("variant")]
            pool = variants or pool
        start = date.fromisoformat(cfg["start_date"]) + timedelta(days=rng.randrange(10))
        hard = cfg.get("hard_cases", [])[i % len(cfg["hard_cases"])] if cfg.get("hard_cases") and i % 3 == 0 else None
        rng.shuffle(pool)
        first = None
        for product in pool:
            f = domain.facts(product["sku"], start.isoformat(), cid)
            if f["inventory"]["in_stock"] and (hard != "expired_promotion" or f["quote"].get("expired_promos")):
                first = f
                break
        if first is None:
            raise ValueError(f"cannot ground product/hard case for {jid}; adjust config/domain, not model facts")
        channels = (["chat_fanpage" if i % 2 == 0 else "zalo_oa"] if i < cfg["multichannel_customers"] else []) + ["hotline", "hotline"]
        if persona == "impatient_third_call" and len(channels) < 3:
            channels = ["hotline"] * 3
        budget = first["price_vnd"] + rng.choice([100000, 250000, 500000, 1000000])
        sessions = []
        for index, channel in enumerate(channels):
            on = (start + timedelta(days=3 * index)).isoformat()
            facts = domain.facts(first["product"]["sku"], on, cid)
            final = index == len(channels) - 1
            action = "order" if final and persona not in {"many_questions", "exchange"} and not hard else "consultation"
            if persona == "exchange":
                action = "order" if index == 0 else "exchange" if final else "consultation"
            event = domain.event(action, facts, cid, sessions)
            goals = ["Tư vấn và làm rõ nhu cầu, không giả định đã có thông tin từ phiên sau."]
            if persona == "hesitant":
                goals += ["Khách cần hỏi người nhà; chỉ phiên cuối mới xác nhận quyết định nếu còn phù hợp."]
            if persona == "exchange" and index > 0:
                goals += ["Khách tự báo đã nhận hàng; đó là lời khách, không phải trạng thái delivered đã được backend xác minh."]
            if persona == "many_questions":
                goals += ["Khách hỏi thêm nhưng chưa mua; không tuyên bố đã tạo đơn."]
            if persona == "impatient_third_call" and final:
                goals += ["Đây là lần liên hệ thứ ba; khách mất kiên nhẫn, agent dùng ngữ cảnh cũ và hạn chế hỏi lại."]
            if index:
                goals += ["Dùng đúng dữ kiện đã xác nhận của phiên trước; kiểm tra lại giá/tồn kho theo ngày mới."]
            anchors = []
            if hard == "unknown_information":
                goals += ["Khách hỏi chi tiết chưa có nguồn (ví dụ số serial máy sẽ nhận); agent thừa nhận chưa có thông tin, không đoán."]
                anchors = ["không có thông tin", "chưa có thông tin", "chưa xác minh"]
            elif hard == "expired_promotion":
                goals += ["Khách đòi áp một mã trong expired_promos; agent giải thích hết hạn và giữ đúng giá hiện hành."]
                anchors = ["hết hạn", "hết hiệu lực"]
            elif hard == "changed_mind" and final:
                goals += ["Khách đổi ý, chưa mua; không tạo đơn ngoài ý muốn."]
            elif hard == "contradictory_budget" and final:
                budget = max(1, facts["price_vnd"] - 100000)
                goals += ["Khách sửa ngân sách thấp hơn giá; agent ghi nhận giá trị mới, không tự giảm giá để chốt."]
            facts["customer_budget_vnd"] = budget
            session = {"transcript_id": f"{jid}-S{index+1:02d}", "journey_id": jid, "customer_id": cid,
                       "session_index": index + 1, "channel": channel, "date": on, "persona": persona,
                       "hard_case": hard, "style": STYLES[(i + index) % len(STYLES)],
                       "goals": goals, "facts": facts, "reference_event": event,
                       "required_any": anchors, "expected_outcome": event["action"]}
            sessions.append(session)
        plans.append({"journey_id": jid, "customer_id": cid, "persona": persona,
                      "sessions": sessions, "origin": "deterministic_synthetic_plan"})
    return plans


def coverage(plans: list[dict], catalog: list[dict], requirements: dict) -> dict:
    sessions = [s for p in plans for s in p["sessions"]]
    counts = {"transcripts": len(sessions), "customers": len({p["customer_id"] for p in plans}),
              "two_hotline_customers": sum(sum(s["channel"] == "hotline" for s in p["sessions"]) >= 2 for p in plans),
              "call_chat_customers": sum(any(s["channel"] == "hotline" for s in p["sessions"]) and any(s["channel"] != "hotline" for s in p["sessions"]) for p in plans),
              "three_session_customers": sum(len(p["sessions"]) >= 3 for p in plans),
              "journeys": len(plans), "hard_case_journeys": sum(any(s["hard_case"] for s in p["sessions"]) for p in plans),
              "categories": len({s["facts"]["product"]["category"].split("/")[0] for s in sessions}),
              "catalog_skus": len({p["sku"] for p in catalog})}
    failures = [f"{key}: {counts.get(key, 0)} < {minimum}" for key, minimum in requirements.items()
                if key != "required_personas" and counts.get(key, 0) < minimum]
    missing = set(requirements.get("required_personas", [])) - {p["persona"] for p in plans}
    if missing:
        failures.append("missing personas: " + ", ".join(sorted(missing)))
    return {"counts": counts, "channels": dict(Counter(s["channel"] for s in sessions)),
            "personas": dict(Counter(p["persona"] for p in plans)),
            "hard_cases": dict(Counter(s["hard_case"] for s in sessions if s["hard_case"])),
            "reference_actions": dict(Counter(s["reference_event"]["action"] for s in sessions)),
            "requirement_failures": failures,
            "transcript_requirements_met": not failures, "audio_requirements_met": False,
            "note": "Text coverage only; no ASR, audio, simulator or system-performance certification."}
