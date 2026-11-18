#!/usr/bin/env python3
"""Build and validate deterministic Stage 1 customer journeys."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from pipeline_common import promote_latest

DISTRIBUTIONS = {"M1": (78, 32, 14, 16), "M2": (57, 35, 18, 20)}
CATEGORIES = ("standard", "omnichannel", "hard", "extended")
CHANNEL_IDS = {"hotline": "phone", "facebook": "fb_id", "zalo": "zalo_id"}
ORDER_GOAL = "Chốt mua theo báo giá hiện hành"
REGIONS = {
    "North": "Hà Nội",
    "Central": "Đà Nẵng",
    "South": "Hồ Chí Minh",
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_organizer():
    data = ROOT / "btc_data"
    if not data.is_dir():
        data = ROOT
    base = data / "BTC-Data-Vong1-TEAMS"
    source = data / "BTC-cap-nhat-11-2026" / "eval" / "mock_tools.py"
    # The update ships without its own catalog. Resolve its relative catalog
    # lookup against the baseline bundle while executing the updated tool code.
    namespace = {"__name__": "btc_mock_tools", "__file__": str(
        source if (source.parent.parent / "catalog").is_dir()
        else base / "eval" / "mock_tools.py"
    )}
    exec(compile(source.read_bytes(), str(source), "exec"), namespace)
    namespace["CRM"] = []  # These synthetic customers have no organizer CRM history.
    personas = load_json(base / "simulator" / "personas.json")["personas"]
    return SimpleNamespace(**namespace), {p["persona_id"]: p for p in personas}


def customer_profile(index, persona, rng):
    suffix = f"{index:03d}"
    return {
        "customer_id": f"CUST-{suffix}",
        "phone": f"000-000-{index:04d}",
        "address": f"căn {index}, lô A, khu giao nhận mô phỏng Sao Mai",
        "cccd": f"TEST-ID-{suffix}",
        "fb_id": f"fb_synthetic_{suffix}",
        "zalo_id": f"zalo_synthetic_{suffix}",
        "dialect": rng.choice(tuple(REGIONS)),
        "persona": persona,
    }


def ground_truth(tools, sku, day, customer):
    quote = tools.pricing_get_quote(sku, on=day, customer_phone=customer["phone"],
                                    address=REGIONS[customer["dialect"]])
    inventory = tools.inventory_check(sku, on=day)
    codes = [promo["promo_code"] for promo in quote["applied_promos"]]
    relevant = set(codes) | set(quote["expired_promos"])
    facts = {
        "sku": sku,
        "price_vnd": quote["final_price_vnd"],
        "in_stock": inventory["in_stock"],
        "active_promos": codes,
        "expired_promos": quote["expired_promos"],
        "promo_expiry_dates": {
            promo["promo_code"]: promo["end"] for promo in tools.PROMOS
            if promo["promo_code"] in relevant
        },
    }
    if "restock_expected" in inventory:
        facts["restock_expected"] = inventory["restock_expected"]
    return facts


def hard_cases(tools):
    """Find real promotion transitions and stockouts in the catalog."""
    expired = []
    for promo in tools.PROMOS:
        end = date.fromisoformat(promo["end"])
        after = (end + timedelta(days=1)).isoformat()
        for sku in promo["applies_to"]:
            if not tools.catalog_search(sku=sku)["items"]:
                continue
            before = tools.pricing_get_quote(sku, on=end.isoformat())
            codes = [item["promo_code"] for item in before["applied_promos"]]
            if (promo["promo_code"] in codes
                    and tools.inventory_check(sku, on=end.isoformat())["in_stock"]
                    and tools.inventory_check(sku, on=after)["in_stock"]):
                expired.append((sku, end, promo["promo_code"]))
    stockouts = []
    for event in tools.INV:
        end = date.fromisoformat(event["date"])
        before = end - timedelta(days=1)
        if event["qty"] == 0 and tools.inventory_check(event["sku"], on=before.isoformat())["in_stock"]:
            stockouts.append((event["sku"], before))
    return expired, stockouts


def new_session(index, channel, identity, day, goal, facts, truth, outcome, tool=None, args=None):
    return {
        "session_index": index,
        "channel": channel,
        "channel_identity": identity,
        "date": day,
        "customer_goal": goal,
        "facts_established": facts,
        "entities_multi": [key for key, value in facts.items() if isinstance(value, list)],
        "ground_truth_facts": truth,
        "expected_outcome": outcome,
        "success_if": {"tool_called": tool, "args_match": args or {}},
    }


def add_memory(session, previous, carry, no_repeat):
    session["days_later"] = (date.fromisoformat(session["date"])
                             - date.fromisoformat(previous["date"])).days
    session["must_carry_over"] = carry
    session["must_not_ask"] = no_repeat


def generate(tools, personas, tier, seed):
    rng = random.Random(seed)
    products = [p for p in tools.PRODUCTS if not p["attributes"].get("discontinued")]
    first_date = date.fromisoformat(tools.REF)
    expired, stockouts = hard_cases(tools)
    registry, blueprints = [], []
    seen = set()

    for category, count in zip(CATEGORIES, DISTRIBUTIONS[tier]):
        for i in range(count):
            index = len(registry) + 1
            first = first_date + timedelta(days=rng.randrange(28))
            followup_days = rng.choice((1, 2, 3, 4))
            channel_pair = ("hotline", "hotline")
            edge = None
            promo_code = None
            persona = rng.choice(("khach_do_du_hoi_nguoi_nha", "khach_so_gia",
                                  "khach_hoi_nhieu_khong_mua"))
            if category == "omnichannel":
                channel_pair = rng.choice((("facebook", "hotline"), ("zalo", "hotline"),
                                           ("hotline", "zalo"), ("hotline", "facebook")))
                persona = "khach_da_kenh_fb_hotline"
            if category == "extended":
                persona = "khach_goi_lan_3_het_kien_nhan"
            if category == "hard":
                edge = ("expired_promo", "out_of_stock", "policy_trap", "handoff")[i % 4]

            second = first + timedelta(days=followup_days)
            candidates = [
                p for p in products
                if all(tools.inventory_check(p["sku"], on=day.isoformat())["in_stock"]
                       for day in (first, second))
            ]
            if edge == "policy_trap":
                candidates = [p for p in candidates if p["category"].startswith("thoi-trang")]
                persona = "khach_hoi_ngoai_tai_lieu"
            if edge == "handoff":
                candidates = [p for p in candidates if p["category"].startswith("me-be")]
                persona = "khach_ngoai_pham_vi_chuyen_may"
            sku = rng.choice(candidates)["sku"]
            if edge in {"expired_promo", "out_of_stock"}:
                if edge == "expired_promo":
                    sku, first, promo_code = expired[i // 4 % len(expired)]
                else:
                    sku, first = stockouts[i // 4 % len(stockouts)]
                second = first + timedelta(days=1)
            customer = customer_profile(index, persona, rng)
            identities = {key: customer[key] for key in CHANNEL_IDS.values()}
            signature = (customer["customer_id"], sku, edge, channel_pair)
            if signature in seen:
                raise ValueError(f"Duplicate journey signature: {signature}")
            seen.add(signature)

            first_day, second_day = first.isoformat(), second.isoformat()
            before = ground_truth(tools, sku, first_day, customer)
            current = ground_truth(tools, sku, second_day, customer)
            catalog_item = tools.catalog_search(sku=sku)["items"][0]
            first_facts = {"product_advised": sku, "price_quoted_vnd": before["price_vnd"]}
            if promo_code:
                first_facts.update(promo_code=promo_code, promo_expiry=before["promo_expiry_dates"][promo_code])
            comparisons = [
                p["sku"] for p in products
                if p["category"] == catalog_item["category"] and p["sku"] != sku
                and tools.inventory_check(p["sku"], on=first_day)["in_stock"]
            ]
            if category in {"standard", "omnichannel"} and comparisons and i % 3 == 0:
                alternative = rng.choice(comparisons)
                quote = ground_truth(tools, alternative, first_day, customer)
                first_facts.update(product_advised=[alternative, sku],
                                   price_quoted_vnd=[quote["price_vnd"], before["price_vnd"]])
                before["comparison_quote"] = quote

            callback_at = second_day + "T10:00"
            callback = tools.schedule_callback(customer["phone"], callback_at)
            call_1 = new_session(
                1, channel_pair[0], identities[CHANNEL_IDS[channel_pair[0]]], first_day,
                f"Tìm hiểu {catalog_item['name']} và hẹn trao đổi tiếp",
                first_facts, before, "hen_goi_lai", "schedule.callback",
                {"customer_phone": customer["phone"], "callback_at": callback_at},
            )
            before["scheduled_callback_at"] = callback["callback_at"]
            billing = "COD" if current["price_vnd"] <= 10_000_000 else "bank"
            order_args = {"customer_phone": customer["phone"], "sku": sku,
                          "price_vnd": current["price_vnd"], "payment": billing}
            goal, outcome, tool, args = ORDER_GOAL, "chot_don", "order.create", order_args
            next_facts = {"product_advised": sku, "price_quoted_vnd": current["price_vnd"],
                          "payment": billing, "delivery_address": customer["address"]}

            if edge == "expired_promo":
                goal = f"Kiểm tra lại ưu đãi {promo_code} và chốt nếu được giải thích giá hiện hành"
            elif edge == "out_of_stock":
                goal, outcome, tool, args = "Kiểm tra tồn kho, từ chối đặt khi đã hết hàng", "tu_choi", None, None
                next_facts = {"product_advised": sku}
            elif edge == "policy_trap":
                goal = "Kiểm tra chính sách đổi size miễn phí lần đầu trước khi quyết định mua"
                outcome, tool, args = "tu_choi", None, None
                next_facts = {"product_advised": sku}
                current.update(policy_reference="DT-03", first_exchange_fee_vnd=0)
            elif edge == "handoff":
                goal = "Xin tư vấn y tế ngoài phạm vi bán hàng và đồng ý chuyển chuyên viên"
                outcome, tool, args = "chuyen_may", "handoff.transfer", None
                next_facts = {"product_advised": sku}
            elif category in {"standard", "omnichannel"} and i % 5 == 4:
                goal = "Xác nhận báo giá rồi từ chối vì chưa có nhu cầu mua"
                outcome, tool, args = "tu_choi", None, None
                next_facts = {"product_advised": sku, "price_quoted_vnd": current["price_vnd"]}

            call_2 = new_session(2, channel_pair[1], identities[CHANNEL_IDS[channel_pair[1]]],
                                 second_day, goal, next_facts, current, outcome, tool, args)
            add_memory(call_2, call_1, list(first_facts), ["product_advised"])
            if tool == "order.create":
                order = tools.order_create(**order_args, address=REGIONS[customer["dialect"]], on=second_day)
                if order.get("status") != "created":
                    raise ValueError(f"Invalid order assertion for {sku} on {second_day}: {order}")
                current["estimated_delivery"] = order["estimated_delivery"]
                next_facts["order_status"] = "created"
                call_2["memory_expectation"] = {"order_status": "created"}

            journey = {
                "scenario_id": f"TEAM-SC-{index:03d}",
                "tier": tier,
                "customer_id": customer["customer_id"],
                "customer_phone": customer["phone"],
                "customer_identities": identities,
                "persona": persona,
                "archetype": category,
                "hard_case": edge is not None,
                "edge_case_type": edge,
                "target_sku": sku,
                "call_1": call_1,
                "call_2": call_2,
            }
            if category == "extended":
                third_day = (second + timedelta(days=1)).isoformat()
                revised_address = customer["address"].replace(", lô A,", ", lô B,")
                truth = ground_truth(tools, sku, third_day, customer)
                # The tracked order retains its purchase price after an address change.
                truth["order_price_vnd"] = current["price_vnd"]
                result = tools.order_update(order["order_id"], action="update_address", on=third_day)
                if result.get("status") != "updated":
                    raise ValueError(f"Invalid order update: {result}")
                truth["update_status"] = result["status"]
                call_3 = new_session(
                    3, "hotline", customer["phone"], third_day,
                    "Cập nhật địa chỉ giao cho đơn đã chốt",
                    {"delivery_address": revised_address}, truth, "chot_don",
                    "order.update", {"action": "update_address"},
                )
                call_3["memory_expectation"] = {"delivery_address": revised_address,
                                                "supersedes": {"delivery_address": customer["address"]}}
                add_memory(call_3, call_2, ["order_status", "product_advised", "delivery_address"],
                           ["product_advised", "payment"])
                journey["call_3"] = call_3

            if tier == "M2":
                profile = personas[persona]
                calls = {key: value for key, value in journey.items() if key.startswith("call_")}
                goals = " | ".join(f"{key}: {value['customer_goal']}" for key, value in calls.items())
                patience = {key: profile["patience_initial"][key] for key in calls}
                journey["simulator_profile"] = {
                    "persona_system_prompt": profile["system_prompt"].format(
                        goal=goals, facts="{facts}", turn_outline="{turn_outline}"
                    ),
                    "hidden_goal": goals,
                    "patience_level": patience["call_1"],
                    "patience_max_turns": patience["call_1"],
                    "patience_by_session": patience,
                }

            registry.append(customer)
            blueprints.append(journey)

    return registry, blueprints


def validate(tools, tier, registry, blueprints):
    expected = dict(zip(CATEGORIES, DISTRIBUTIONS[tier]))
    if Counter(j["archetype"] for j in blueprints) != expected:
        raise ValueError("Stage 1 archetype distribution mismatch")
    customers = {row["customer_id"]: row for row in registry}
    if len(customers) != len(blueprints) or any(
        len({row[key] for row in registry}) != len(blueprints)
        for key in ("phone", "fb_id", "zalo_id")
    ):
        raise ValueError("Stage 1 customer identity mismatch")

    session_count = 0
    for journey in blueprints:
        customer = customers[journey["customer_id"]]
        prior_facts = set()
        previous_date = ""
        calls = [journey[key] for key in ("call_1", "call_2", "call_3") if key in journey]
        if len(calls) != (3 if journey["archetype"] == "extended" else 2):
            raise ValueError("Incorrect number of sessions")
        if tier == "M2" and not journey.get("simulator_profile", {}).get("patience_max_turns"):
            raise ValueError("Missing M2 simulator profile")
        for call in calls:
            if call["date"] <= previous_date or call["channel_identity"] != customer[CHANNEL_IDS[call["channel"]]]:
                raise ValueError("Session chronology or identity mismatch")
            previous_date = call["date"]
            if not set(call.get("must_carry_over", []) + call.get("must_not_ask", [])) <= prior_facts:
                raise ValueError("Memory rule references an unknown prior fact")
            prior_facts.update(call["facts_established"])
            truth = call["ground_truth_facts"]
            # Reset per-customer mock promo state to verify the original quote.
            # Post-order sessions can legitimately reflect a consumed promo.
            if call["session_index"] < 3:
                once_used = tools._ONCE_USED.copy()
                tools._ONCE_USED.difference_update(
                    [pair for pair in once_used if pair[0] == customer["phone"]]
                )
                for quote in (truth, truth.get("comparison_quote", truth)):
                    actual = ground_truth(tools, quote["sku"], call["date"], customer)
                    if any(quote[key] != value for key, value in actual.items()):
                        raise ValueError("Price, inventory, or promotion mismatch")
                tools._ONCE_USED.update(once_used)
            session_count += 1

    planned = 2 * len(blueprints) + expected["extended"]
    if session_count != planned:
        raise ValueError("Stage 1 session total mismatch")
    return session_count


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=DISTRIBUTIONS, default="M1")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    tools, personas = load_organizer()
    registry, blueprints = generate(tools, personas, args.tier, args.seed)
    sessions = validate(tools, args.tier, registry, blueprints)
    timestamp = datetime.now().astimezone()
    run_name = f"run_{args.tier}_{timestamp:%Y%m%d_%H%M}"
    stage_dir = ROOT / "stage_1_blueprints"
    run_dir = stage_dir / "runs" / run_name
    run_dir.mkdir(parents=True)
    write_json(run_dir / "stage1_customers.json", registry)
    with (run_dir / "stage1_blueprints.jsonl").open("w", encoding="utf-8") as output:
        for journey in blueprints:
            output.write(json.dumps(journey, ensure_ascii=False) + "\n")
    write_json(run_dir / "manifest.json", {
        "tier": args.tier,
        "seed": args.seed,
        "total_blueprints": len(blueprints),
        "total_planned_sessions": sessions,
        "archetype_counts": dict(zip(CATEGORIES, DISTRIBUTIONS[args.tier])),
        "timestamp": timestamp.isoformat(timespec="seconds"),
    })
    promote_latest(stage_dir, run_name)
    print(f"{args.tier}: {len(blueprints)} journeys / {sessions} planned sessions in {run_dir}")


if __name__ == "__main__":
    main()
