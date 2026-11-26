#!/usr/bin/env python3
"""Build and validate deterministic Stage 1 customer journeys."""

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import random
import re
import shutil
import sys
from types import SimpleNamespace

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
INPUT = STAGE / "input"
sys.path[:0] = [str(STAGE / "src"), str(ROOT)]
from common import BLUEPRINTS_FILE, CUSTOMERS_FILE, run_name

DISTRIBUTIONS = {"M1": (78, 32, 14, 16), "M2": (60, 40, 20, 30)}
CATEGORIES = ("standard", "omnichannel", "hard", "extended")
M2_MIN_BLUEPRINTS = sum(DISTRIBUTIONS["M2"])
CHANNEL_PAIRS = (("facebook", "hotline"), ("zalo", "hotline"),
                 ("hotline", "zalo"), ("hotline", "facebook"))
CRM_DISTRIBUTION = {"omnichannel": 12, "standard": 10, "hard": 8, "extended": 20}
CRM_VARIANT_DISTRIBUTION = {"omnichannel": 18, "hard": 8, "standard": 44}
CRM_DIALECTS = {"bac": "North", "trung": "Central", "nam": "South"}
CONSIDER = "consider_and_decide"
CROSS_CHANNEL = "continue_across_channels"
BUSINESS_CHANGE = "return_after_price_or_stock_change"
POST_PURCHASE = "return_for_post_purchase_support"
IDENTITY = "resume_with_uncertain_identity_or_history"
TRANSFER = "transfer_with_context"
FAMILY = "khach_do_du_hoi_nguoi_nha"
PRICE = "khach_so_gia"
EXCHANGE = "khach_da_mua_doi_size"
IMPATIENT = "khach_goi_lan_3_het_kien_nhan"
CRM_PLAN = (
    (CONSIDER, FAMILY, "decision", 14), (CONSIDER, PRICE, "decision", 14),
    (CONSIDER, "khach_hoi_nhieu_khong_mua", "defer", 4),
    (CONSIDER, "khach_hoi_ngoai_tai_lieu", "unsupported_question", 2),
    (CROSS_CHANNEL, "khach_da_kenh_fb_hotline", "decision", 9),
    (CROSS_CHANNEL, "khach_da_kenh_mau_thuan", "conflicting_quotes", 6),
    (CROSS_CHANNEL, PRICE, "decision", 5), (CROSS_CHANNEL, FAMILY, "decision", 4),
    (CROSS_CHANNEL, EXCHANGE, "size_exchange", 3),
    (BUSINESS_CHANGE, PRICE, "expired_promo", 6), (BUSINESS_CHANGE, PRICE, "out_of_stock", 3),
    (BUSINESS_CHANGE, PRICE, "restock", 2), (BUSINESS_CHANGE, FAMILY, "expired_promo", 2),
    (BUSINESS_CHANGE, FAMILY, "out_of_stock", 2), (BUSINESS_CHANGE, FAMILY, "restock", 2),
    (BUSINESS_CHANGE, "khach_mua_nhieu_mon", "basket_restock", 6),
    (BUSINESS_CHANGE, EXCHANGE, "exchange_after_restock", 3),
    (POST_PURCHASE, EXCHANGE, "exchange_after_consultation", 8),
    (POST_PURCHASE, EXCHANGE, "size_exchange", 8), (POST_PURCHASE, EXCHANGE, "order_status", 5),
    (POST_PURCHASE, EXCHANGE, "address_update", 3),
    (POST_PURCHASE, IMPATIENT, "order_status", 3), (POST_PURCHASE, IMPATIENT, "address_update", 3),
    (IDENTITY, "khach_quay_lai_sau_8_thang", "stale_address", 6),
    (IDENTITY, "hai_nguoi_chung_sdt", "shared_phone", 4),
    (IDENTITY, EXCHANGE, "verify_order_identity", 2),
    (TRANSFER, "khach_ngoai_pham_vi_chuyen_may", "handoff", 11),
)
CRM_HARD_CASES = {
    "unsupported_question", "conflicting_quotes", "expired_promo", "out_of_stock", "restock",
    "basket_restock", "exchange_after_restock", "stale_address", "shared_phone",
    "verify_order_identity", "handoff",
}
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
    source = INPUT / "eval" / "mock_tools.py"
    namespace = {"__name__": "btc_mock_tools", "__file__": str(source)}
    exec(compile(source.read_bytes(), str(source), "exec"), namespace)
    namespace["CRM"] = []  # Simulate the new journeys with isolated mock order state.
    personas = load_json(INPUT / "simulator" / "personas.json")["personas"]
    return SimpleNamespace(**namespace), {p["persona_id"]: p for p in personas}


def fictional_address(index: int) -> str:
    return f"căn {index}, lô A, khu giao nhận mô phỏng Sao Mai"


def customer_profile(index, persona, rng):
    suffix = f"{index:03d}"
    return {
        "customer_id": f"CUST-{suffix}",
        "phone": f"000-000-{index:04d}",
        "address": fictional_address(index),
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


def generation_distribution(tier, crm_backed, blueprint_count=None):
    if blueprint_count is not None and tier != "M2":
        raise ValueError("Blueprint count is configurable for M2 only.")
    if crm_backed:
        return dict(Counter(CRM_DISTRIBUTION) + Counter(CRM_VARIANT_DISTRIBUTION))
    distribution = dict(zip(CATEGORIES, DISTRIBUTIONS[tier]))
    if blueprint_count is not None:
        if not isinstance(blueprint_count, int) or blueprint_count < M2_MIN_BLUEPRINTS:
            raise ValueError(f"M2 requires at least {M2_MIN_BLUEPRINTS} blueprints.")
        distribution["standard"] += blueprint_count - M2_MIN_BLUEPRINTS
    return distribution


def blueprint_signature(journey):
    """Describe the session goals and state changes using structured fields."""
    sessions = []
    previous = None
    for key in ("call_1", "call_2", "call_3"):
        if key not in journey:
            continue
        call = journey[key]
        success = call["success_if"]
        truth = call["ground_truth_facts"]
        products = call["facts_established"].get("product_advised")
        previous_promos = set(previous.get("active_promos", ())) if previous else set()
        price_changed = previous is not None and previous.get("price_vnd") != truth.get("price_vnd")
        sessions.append((
            call["channel"], call["expected_outcome"], success["tool_called"],
            success["args_match"].get("action"),
            len(products) if isinstance(products, list) else 1,
            truth.get("in_stock"), price_changed,
            bool(previous_promos.intersection(truth.get("expired_promos", ()))),
            truth.get("policy_reference"),
        ))
        previous = truth
    return journey["target_sku"], tuple(sessions)


def read_m1_reference(path: Path):
    signatures, scenario_numbers = set(), set()
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            scenario_id = row.get("scenario_id") if isinstance(row, dict) else None
            match = re.fullmatch(r"(?:TEAM-)?SC-([0-9]+)", scenario_id) if isinstance(scenario_id, str) else None
            if not match or row.get("tier") != "M1" or not {"call_1", "call_2"} <= row.keys():
                raise ValueError(f"Expected a Stage 1 M1 blueprint in {path}, line {number}.")
            scenario_number = int(match[1])
            if scenario_number in scenario_numbers:
                raise ValueError(f"Duplicate M1 scenario number in {path}, line {number}.")
            scenario_numbers.add(scenario_number)
            signatures.add(blueprint_signature(row))
    if not scenario_numbers:
        raise ValueError(f"The M1 reference has no blueprints: {path}")
    return signatures, max(scenario_numbers)


def reset_mock_state(tools):
    for collection in (tools._ORDERS, tools._ONCE_USED, tools._CALLBACKS, tools._TICKETS, tools.CRM):
        collection.clear()


def generate(tools, personas, tier, seed, crm_customers=None, *, blueprint_count=None,
             m1_signatures=(), scenario_offset=0):
    if crm_customers is not None:
        return generate_crm_journeys(tools, seed, crm_customers)
    rng = random.Random(seed)
    products = [p for p in tools.PRODUCTS if not p["attributes"].get("discontinued")]
    first_date = date.fromisoformat(tools.REF)
    expired, stockouts = hard_cases(tools)
    registry, blueprints = [], []
    seen = set()

    for category, count in generation_distribution(tier, False, blueprint_count).items():
        i = retries = 0
        while i < count:
            index = len(blueprints) + 1
            if tier == "M2":
                reset_mock_state(tools)
            first = first_date + timedelta(days=rng.randrange(28))
            followup_days = rng.choice((1, 2, 3, 4))
            channel_pair = ("hotline", "hotline")
            edge = None
            promo_code = None
            persona = rng.choice(("khach_do_du_hoi_nguoi_nha", "khach_so_gia",
                                  "khach_hoi_nhieu_khong_mua"))
            if category == "omnichannel":
                channel_pair = rng.choice(CHANNEL_PAIRS)
                persona = "khach_da_kenh_fb_hotline"
            if category == "extended":
                persona = "khach_goi_lan_3_het_kien_nhan"
            if category == "hard":
                edge = ("expired_promo", "out_of_stock", "policy_trap", "handoff")[i % 4]
                if retries:
                    channel_pair = CHANNEL_PAIRS[(retries - 1) % len(CHANNEL_PAIRS)]

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
                event_index = i // 4 + retries
                if edge == "expired_promo":
                    sku, first, promo_code = expired[event_index % len(expired)]
                else:
                    sku, first = stockouts[event_index % len(stockouts)]
                second = first + timedelta(days=1)
            customer = customer_profile(index, persona, rng)
            identities = {key: customer[key] for key in CHANNEL_IDS.values()}
            signature = (customer["customer_id"], sku, edge, channel_pair)
            if signature in seen:
                raise ValueError(f"Duplicate journey signature: {signature}")

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
                "scenario_id": f"SC-{scenario_offset + index:03d}",
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
                if blueprint_signature(journey) in m1_signatures:
                    retries += 1
                    if retries == 64:
                        raise ValueError(
                            f"Could not generate a {category} M2 blueprint distinct from M1 after {retries} attempts."
                        )
                    continue
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

            seen.add(signature)
            registry.append(customer)
            blueprints.append(journey)
            i += 1
            retries = 0

    return registry, blueprints


def generate_crm_journeys(tools, seed, crm_customers):
    rng = random.Random(seed)
    registry = [{**row, "dialect": CRM_DIALECTS[row["region"]]} for row in crm_customers]
    rng.shuffle(registry)
    # Reserve the limited two-handle and shared-phone records before allocating general journeys.
    plan = [(pattern, persona, kind, index) for pattern, persona, kind, count in CRM_PLAN for index in range(count)]
    def priority(index):
        pattern, _, kind, _ = plan[index]
        if kind == "shared_phone":
            return 0
        if kind == "conflicting_quotes":
            return 1
        return 2 if pattern == CROSS_CHANNEL else 3
    uses = Counter()
    assigned = {}
    for index in sorted(range(len(plan)), key=priority):
        pattern, _, kind, _ = plan[index]
        eligible = (row for row in registry if (
            bool(row["shared_phone_with"]) if kind == "shared_phone"
            else bool(row["fb_id"] and row["zalo_id"]) if kind == "conflicting_quotes"
            else bool(row["fb_id"] or row["zalo_id"]) if pattern == CROSS_CHANNEL
            else True
        ))
        customer = min(eligible, key=lambda row: uses[row["customer_id"]], default=None)
        if customer is None:
            raise ValueError(f"No CRM customer has the identities required for {kind}")
        uses[customer["customer_id"]] += 1
        assigned[index] = customer

    expired, stockouts = hard_cases(tools)
    restocks = []
    for event in tools.INV:
        day = date.fromisoformat(event["date"])
        before = (day - timedelta(days=1)).isoformat()
        if event["qty"] > 0 and not tools.inventory_check(event["sku"], on=before)["in_stock"]:
            restocks.append((event["sku"], day))
    products = [p for p in tools.PRODUCTS if not p["attributes"].get("discontinued")]
    shoe_variants = [v for p in products if p["sku"] == "SKU-SN-CAS" for v in p["variants"] if v["stock"] > 0]
    rows = []
    for index, (pattern, persona, kind, variant) in enumerate(plan):
        customer = assigned[index]
        reset_mock_state(tools)
        day = date.fromisoformat(tools.REF) + timedelta(days=index % 21)
        next_day = day + timedelta(days=1 + variant % 4)
        channel = ["hotline", "hotline", "hotline"]
        if pattern == CROSS_CHANNEL:
            social = [key for key in ("facebook", "zalo") if customer[CHANNEL_IDS[key]]]
            if kind == "conflicting_quotes":
                channel = ["facebook", "zalo", "hotline"]
            else:
                channel[:2] = [rng.choice(social), "hotline"]
                if variant % 2:
                    channel[:2] = channel[:2][::-1]
        elif kind == "shared_phone":
            channel[0] = "facebook" if customer["fb_id"] else "zalo"

        promo = None
        replacement = None
        if kind == "expired_promo":
            sku, day, promo = expired[index % len(expired)]
            next_day = day + timedelta(days=1)
        elif kind == "out_of_stock":
            sku, day = stockouts[variant % len(stockouts)]
            next_day = day + timedelta(days=1)
        elif kind == "restock":
            sku, next_day = restocks[variant % len(restocks)]
            day = next_day - timedelta(days=1)
        elif kind == "basket_restock":
            appliance_restocks = [(item, on) for item, on in restocks if item.startswith(("SKU-AP-", "SKU-XM-"))]
            sku, next_day = appliance_restocks[variant % len(appliance_restocks)]
            day = next_day - timedelta(days=1)
        elif kind == "exchange_after_restock":
            sku, replacement = "SKU-SN-RUN2-43-DEN", "SKU-SN-RUN2-41-DEN"
            day, next_day = date(2026, 10, 18), date(2026, 10, 24)
        elif kind in {"size_exchange", "exchange_after_consultation"}:
            original = rng.choice(shoe_variants)
            options = [v for v in shoe_variants if v["color"] == original["color"] and v["size"] > original["size"]]
            if not options:
                options = [v for v in shoe_variants if v["color"] == original["color"] and v["size"] < original["size"]]
            sku, replacement = original["variant_sku"], rng.choice(options)["variant_sku"]
            next_day = day + timedelta(days=4)
        else:
            if kind == "stale_address":
                day, next_day = date(2026, 2, 15) + timedelta(days=variant), date(2026, 10, 15) + timedelta(days=variant)
            eligible = [p["sku"] for p in products if (kind != "handoff" or p["category"].startswith("me-be"))
                        and all(tools.inventory_check(p["sku"], on=value.isoformat())["in_stock"] for value in (day, next_day))]
            sku = rng.choice(eligible)

        calls = []

        def add(purpose, on, goal, facts, truth, outcome, tool=None, args=None, **assertions):
            index = len(calls)
            call = new_session(index + 1, channel[index], customer[CHANNEL_IDS[channel[index]]], on.isoformat(),
                               goal, facts, truth, outcome, tool, args)
            call["session_purpose"] = purpose
            call["success_if"].update(assertions)
            if calls:
                known = list(calls[-1]["facts_established"])
                add_memory(call, calls[-1], known, [key for key in ("product_advised", "variant_sku") if key in known])
            calls.append(call)
            return call

        def quote(on):
            # Stage 3 checks catalog truth without orders from other scenarios.
            used = tools._ONCE_USED.copy()
            tools._ONCE_USED.clear()
            truth = ground_truth(tools, sku, on.isoformat(), customer)
            tools._ONCE_USED.update(used)
            return truth

        def consultation():
            nonlocal next_day
            truth = quote(day)
            requested = next_day.isoformat() + "T10:00"
            callback = tools.schedule_callback(customer["phone"], requested)
            truth["scheduled_callback_at"] = callback["callback_at"]
            next_day = date.fromisoformat(callback["callback_at"][:10])
            facts = {"product_advised": sku, "price_quoted_vnd": truth["price_vnd"]}
            if promo:
                facts.update(promo_code=promo, promo_expiry=truth["promo_expiry_dates"][promo])
            purpose = "inquiry"
            goal = "Hỏi về sản phẩm và hẹn xem lại"
            if persona == FAMILY:
                purpose, goal = "consult_family", "Xem sản phẩm trong ngân sách và hỏi ý kiến người nhà"
                facts["budget_vnd"] = (truth["price_vnd"] // 500_000 + 1 + variant % 4) * 500_000
            elif persona == PRICE:
                purpose, goal = "compare_price", "So báo giá với nơi khác trước khi quyết định"
                facts["competitor_price_vnd"] = max(1_000, truth["price_vnd"] - (variant + 1) * 20_000)
            elif persona == "khach_hoi_nhieu_khong_mua":
                purpose, goal = "research_product", "Hỏi kỹ cách sử dụng và cân nhắc thêm trước khi mua"
            return add(purpose, day, goal, facts, truth, "hen_goi_lai",
                       "schedule.callback", {"customer_phone": customer["phone"], "callback_at": requested})

        def purchase(on, basket=None):
            truth = quote(on)
            if basket:
                items = [{"sku": item} for item in basket]
                priced = tools.pricing_quote_order(items, on.isoformat(), customer["phone"], REGIONS[customer["dialect"]])
                order_lines = [{"sku": item["sku"], "qty": 1, "price_vnd": item["final_price_vnd"]} for item in priced["units"]]
                total = priced["total_vnd"]
            else:
                order_lines = None
                total = truth["price_vnd"]
            payment = "COD" if total <= 10_000_000 else "bank"
            order = tools.order_create(customer["phone"], sku=sku, price_vnd=truth["price_vnd"], payment=payment,
                                       on=on.isoformat(), address=REGIONS[customer["dialect"]], lines=order_lines)
            if order.get("status") != "created":
                raise ValueError(f"Mock purchase failed for {sku}: {order.get('error')}")
            truth["estimated_delivery"] = order["estimated_delivery"]
            facts = {"product_advised": sku, "price_quoted_vnd": truth["price_vnd"], "payment": payment,
                     "delivery_address": customer["address"], "order_status": "created"}
            args = {"sku": sku, "price_vnd": truth["price_vnd"]}
            checks = {}
            if basket:
                facts.update(basket_skus=basket, basket_total_vnd=total)
                truth["basket_lines"] = order_lines
                args = {"sku": sku}
                checks = {"also_ordered": basket[1:], "total_match_vnd": total}
            call = add("basket_purchase" if basket else ("purchase_after_expiry" if promo else "purchase"),
                       on, "Chốt đơn theo báo giá và điều kiện hiện hành", facts, truth, "chot_don",
                       "order.create", args, **checks)
            call["memory_expectation"] = {"order_status": "created"}
            return order

        order_workflows = {"size_exchange", "exchange_after_consultation", "exchange_after_restock", "order_status",
                           "address_update", "verify_order_identity", "stale_address"}
        if kind in order_workflows:
            if kind == "exchange_after_consultation" or persona == IMPATIENT:
                consultation()
                order = purchase(next_day)
                follow_up = next_day + timedelta(days=4 if replacement else 1)
            else:
                order = purchase(day)
                follow_up = next_day
            truth = quote(follow_up)
            oid = order["order_id"]
            args = {"order_id": oid}
            if replacement:
                availability = tools.inventory_check(replacement, on=follow_up.isoformat())
                if kind == "exchange_after_restock":
                    initial = tools.inventory_check(replacement, on=day.isoformat())
                    if initial["in_stock"] or not availability["in_stock"]:
                        raise ValueError("The requested replacement must restock between sessions")
                    calls[0]["facts_established"]["requested_replacement_sku"] = replacement
                    calls[0]["ground_truth_facts"]["replacement_in_stock"] = False
                args.update(action="exchange_size", new_variant_sku=replacement)
                exchange = tools.order_update(**args, on=follow_up.isoformat())
                if exchange.get("status") != "pickup_scheduled":
                    raise ValueError(f"Mock size exchange failed: {exchange.get('error')}")
                truth.update(replacement_in_stock=availability["in_stock"], exchange_fee_vnd=exchange["fee_vnd"],
                             policy_reference="DT-03")
                add("size_exchange", follow_up, "Đổi sang size khác sau khi nhận hàng", {"new_variant_sku": replacement},
                    truth, "chot_don", "order.update", args)
            elif kind == "address_update":
                args["action"] = "update_address"
                if tools.order_update(**args, on=follow_up.isoformat()).get("status") != "updated":
                    raise ValueError("Mock address update failed")
                address = customer["alternate_address"]
                call = add("address_update", follow_up, "Cập nhật nơi giao cho đơn đã mua",
                           {"delivery_address": address}, truth, "chot_don", "order.update", args)
                call["memory_expectation"] = {"delivery_address": address, "supersedes": {"delivery_address": customer["address"]}}
            else:
                if not tools.order_status(order_id=oid)["orders"]:
                    raise ValueError("Order status has no matching purchase")
                goal = "Kiểm tra đơn đã mua" if kind == "order_status" else "Xác nhận thông tin người nhận trước khi tra đơn cũ"
                add(kind, follow_up, goal, {}, truth, "chot_don", "order.status", args,
                    **({"must_say_any": ["xác nhận", "địa chỉ"]} if kind != "order_status" else {}))
            if persona == IMPATIENT:
                calls[-1]["success_if"]["max_agent_questions"] = 1
        else:
            first = consultation()
            truth = quote(next_day)
            if kind == "conflicting_quotes":
                reported = truth["price_vnd"] + (variant + 1) * 100_000
                add("conflicting_quote", next_day, "Hỏi về mức giá khác đã được báo qua kênh khác",
                    {"reported_price_vnd": reported}, truth, "hen_goi_lai")
                purchase(next_day + timedelta(days=1))
                calls[-1]["session_purpose"] = "resolve_quotes"
                calls[-1]["must_carry_over"].append("price_quoted_vnd")
            elif kind == "shared_phone":
                tools.CRM.extend(row for row in registry if row["phone"] == customer["phone"])
                lookup = tools.crm_get_customer(phone=customer["phone"])
                tools.CRM.clear()
                if not lookup.get("ambiguous"):
                    raise ValueError("Expected two CRM identities for the shared phone")
                call = add("shared_phone", next_day, "Xác nhận đúng người đang gọi trước khi dùng lịch sử",
                           {}, truth, "hen_goi_lai", "crm.get_customer", {"phone": customer["phone"]},
                           must_say_any=["xác nhận", "đang nói chuyện", "đang trao đổi"])
                call["identity_expectation"] = {"customer_id": customer["customer_id"],
                                                "shared_phone_with": customer["shared_phone_with"],
                                                "verified_channel": channel[0]}
                call["memory_expectation"] = {"customer_id": customer["customer_id"],
                                              "must_not_write_to": customer["shared_phone_with"]}
                call["must_carry_over"] = []
                call["must_not_ask"] = []
            elif kind == "handoff":
                add("handoff", next_day, "Hỏi về an toàn sử dụng ngoài phạm vi bán hàng và yêu cầu chuyên viên",
                    {}, truth, "chuyen_may", "handoff.transfer", brief_must_contain=list(tools.REQUIRED_BRIEF))
            elif kind in {"out_of_stock", "defer", "unsupported_question"} or kind == "decision" and variant % 5 == 4:
                purpose = kind if kind != "decision" else "defer"
                goal = {"out_of_stock": "Kiểm tra tồn kho và hoãn mua khi hết hàng",
                        "unsupported_question": "Yêu cầu thông tin không có trong tài liệu",
                        "defer": "Xem lại báo giá và hoãn quyết định mua"}[purpose]
                add(purpose, next_day, goal, {"product_advised": sku}, truth, "tu_choi",
                    **({"agent_must_say": "không có thông tin"} if kind == "unsupported_question" else {}))
            else:
                basket = None
                if kind == "basket_restock":
                    eligible = [item["sku"] for item in products if item["sku"] != sku
                                and item["category"].startswith("gia-dung")
                                and tools.inventory_check(item["sku"], on=next_day.isoformat())["in_stock"]]
                    basket = [sku, rng.choice(eligible)]
                    first["facts_established"]["basket_skus"] = basket
                    first["entities_multi"].append("basket_skus")
                    first["session_purpose"] = "basket_inquiry"
                purchase(next_day, basket)
                if kind == "restock":
                    calls[-1]["session_purpose"] = "purchase_after_restock"
        rows.append({
            "scenario_id": f"SC-{index + 1:03d}", "tier": "M1", "customer_id": customer["customer_id"],
            "customer_phone": customer["phone"], "customer_identities": {key: customer[key] for key in CHANNEL_IDS.values()},
            "persona": persona, "journey_pattern": pattern, "target_sku": sku, "hard_case": kind in CRM_HARD_CASES,
            "edge_case_type": kind if kind in CRM_HARD_CASES else None,
            "archetype": "extended" if len(calls) == 3 else "hard" if kind in CRM_HARD_CASES
                         else "omnichannel" if pattern == CROSS_CHANNEL else "standard",
            **{f"call_{i}": call for i, call in enumerate(calls, 1)},
        })
    tools.CRM.clear()
    return sorted(registry, key=lambda row: row["customer_id"]), rows


def validate(tools, tier, registry, blueprints, crm_backed=False, *, blueprint_count=None):
    expected = generation_distribution(tier, crm_backed, blueprint_count)
    patterned = crm_backed and any("journey_pattern" in row for row in blueprints)
    if patterned:
        allocations = Counter()
        for pattern, persona, _, count in CRM_PLAN:
            allocations[pattern, persona] += count
        if Counter((row["journey_pattern"], row["persona"]) for row in blueprints) != allocations:
            raise ValueError("Stage 1 persona and pattern allocation mismatch")
        if [row["scenario_id"] for row in blueprints] != [f"SC-{i:03d}" for i in range(1, len(blueprints) + 1)]:
            raise ValueError("Stage 1 scenario IDs must be consecutive SC-XXX IDs")
    elif Counter(j["archetype"] for j in blueprints) != expected:
        raise ValueError("Stage 1 archetype distribution mismatch")
    customers = {row["customer_id"]: row for row in registry}
    if len(customers) != len(registry) or {
        row["customer_id"] for row in blueprints
    } != customers.keys():
        raise ValueError("Stage 1 customer identity mismatch")
    if len({row["scenario_id"] for row in blueprints}) != len(blueprints):
        raise ValueError("Stage 1 scenario IDs must be unique")
    if crm_backed:
        phones = Counter(row["phone"] for row in registry)
        for row in registry:
            shared_id = row["shared_phone_with"]
            other = customers.get(shared_id)
            if not row["phone"] or phones[row["phone"]] != (2 if shared_id else 1) or (
                shared_id and (other is None or shared_id == row["customer_id"]
                               or other["phone"] != row["phone"]
                               or other["shared_phone_with"] != row["customer_id"])
            ):
                raise ValueError("CRM seed phone sharing must link distinct customer IDs reciprocally")
    else:
        if len(blueprints) != len(registry) or any(
            len({row[key] for row in registry}) != len(registry) for key in CHANNEL_IDS.values()
        ):
            raise ValueError("Stage 1 synthetic channel identities must be unique")

    session_count = 0
    for journey in blueprints:
        customer = customers[journey["customer_id"]]
        if journey["customer_phone"] != customer["phone"] or any(
            journey["customer_identities"][key] != customer[key] for key in CHANNEL_IDS.values()
        ):
            raise ValueError("Stage 1 blueprint does not match the customer registry")
        prior_facts = set()
        previous_date = ""
        calls = [journey[key] for key in ("call_1", "call_2", "call_3") if key in journey]
        if len(calls) != (3 if journey["archetype"] == "extended" else 2):
            raise ValueError("Incorrect number of sessions")
        if patterned:
            pattern = journey["journey_pattern"]
            last = calls[-1]["success_if"]
            actions = [call["success_if"]["tool_called"] for call in calls]
            first_truth, last_truth = (calls[index]["ground_truth_facts"] for index in (0, -1))
            changed = (first_truth["in_stock"] != last_truth["in_stock"]
                       or first_truth.get("replacement_in_stock") is False and last_truth.get("replacement_in_stock") is True
                       or bool(set(first_truth["active_promos"]) & set(last_truth["expired_promos"])))
            covered = {
                CONSIDER: actions[0] == "schedule.callback" and calls[-1]["expected_outcome"] in {"chot_don", "tu_choi"},
                CROSS_CHANNEL: len({call["channel"] for call in calls}) > 1,
                BUSINESS_CHANGE: changed,
                POST_PURCHASE: "order.create" in actions[:-1] and actions[-1] in {"order.update", "order.status"},
                IDENTITY: bool(calls[-1].get("identity_expectation")) or calls[-1]["session_purpose"] in {"stale_address", "verify_order_identity"},
                TRANSFER: actions[-1] == "handoff.transfer" and set(last.get("brief_must_contain", [])) == set(tools.REQUIRED_BRIEF),
            }
            persona = journey["persona"]
            if not covered[pattern] or (persona == IMPATIENT and len(calls) != 3):
                raise ValueError(f"Journey does not exercise its persona or pattern: {journey['scenario_id']}")
            if persona == EXCHANGE and ("order.create" not in actions[:-1] or actions[-1] not in {"order.update", "order.status"}):
                raise ValueError("The returning customer must have an existing order")
        if tier == "M2" and not journey.get("simulator_profile", {}).get("patience_max_turns"):
            raise ValueError("Missing M2 simulator profile")
        for call in calls:
            identity = customer[CHANNEL_IDS[call["channel"]]]
            if not identity or call["date"] <= previous_date or call["channel_identity"] != identity:
                raise ValueError("Session chronology or identity mismatch")
            previous_date = call["date"]
            if not set(call.get("must_carry_over", []) + call.get("must_not_ask", [])) <= prior_facts:
                raise ValueError("Memory rule references an unknown prior fact")
            if crm_backed and "delivery_address" in call["facts_established"]:
                updating = call["session_purpose"] == "address_update"
                expected_address = customer["alternate_address"] if updating else customer["address"]
                if call["facts_established"]["delivery_address"] != expected_address:
                    raise ValueError("Stage 1 delivery address does not match the customer registry")
                if updating and call["memory_expectation"] != {
                    "delivery_address": expected_address, "supersedes": {"delivery_address": customer["address"]},
                }:
                    raise ValueError("Stage 1 address update must supersede the original delivery address")
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

    planned = 2 * len(blueprints) + (20 if patterned else expected["extended"])
    if session_count != planned:
        raise ValueError("Stage 1 session total mismatch")
    return session_count


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_crm_seed_registry() -> list[dict]:
    source_customers = load_json(INPUT / "catalog/crm_seed.json")["customers"]
    address_catalog = load_json(INPUT / "catalog/public-delivery-addresses.json")
    if Counter(row["region"] for row in address_catalog) != Counter(
        CRM_DIALECTS[row["region"]] for row in source_customers
    ):
        raise ValueError("The delivery address catalog must cover every CRM customer by region")
    address_values = [row[key] for row in address_catalog for key in ("address", "alternate_address")]
    normalized = {" ".join(address.casefold().split()) for address in address_values}
    if "" in normalized or len(normalized) != len(address_values):
        raise ValueError("The delivery address catalog must contain distinct, nonempty addresses")
    if len({row["reference_id"] for row in address_catalog}) != len(address_catalog):
        raise ValueError("The delivery address catalog must use each reference once")

    by_dialect = defaultdict(deque)
    for row in address_catalog:
        by_dialect[row["region"]].append(row)
    fields = ("customer_id", "name", "honorific", "phone", "fb_id", "zalo_id", "region", "shared_phone_with")
    registry = []
    for source_customer in source_customers:
        if not re.fullmatch(r"C[0-9]+", source_customer["customer_id"]):
            raise ValueError("Organizer CRM customer IDs must have the form C followed by digits")
        address = by_dialect[CRM_DIALECTS[source_customer["region"]]].popleft()
        registry.append({
            **{field: source_customer.get(field) for field in fields},
            "address": address["address"],
            "alternate_address": address["alternate_address"],
            "address_reference_id": address["reference_id"],
        })

    return registry


def write_crm_seed_registry(tier: str, timestamp: datetime, registry: list[dict]) -> Path:
    run = STAGE / "runs" / "crm_seed" / run_name(tier, timestamp)
    run.mkdir(parents=True)
    write_json(run / CUSTOMERS_FILE, registry)
    return run


def publish_output(run: Path) -> None:
    output = STAGE / "output"
    work = STAGE / ".output-publish"
    work.mkdir()
    staged = work / "next"
    previous = work / "previous"
    keep_backup = False
    try:
        shutil.copytree(run, staged)
        try:
            output.rename(previous)
        except FileNotFoundError:
            pass
        try:
            staged.rename(output)
        except BaseException:
            if previous.exists():
                keep_backup = True
                previous.rename(output)
                keep_backup = False
            raise
    finally:
        if not keep_backup:
            shutil.rmtree(work)


def build_dataset(tier: str, seed: int = 2026, crm_customers: list[dict] | None = None, *,
                  blueprint_count: int | None = None, m1_blueprints: Path | None = None):
    if crm_customers is not None and tier != "M1":
        raise ValueError("CRM-backed blueprints currently support M1 only")
    if tier != "M2" and m1_blueprints is not None:
        raise ValueError("An M1 reference is used for M2 generation only.")
    generation_distribution(tier, crm_customers is not None, blueprint_count)
    signatures, scenario_offset = set(), 0
    if tier == "M2":
        if m1_blueprints is None:
            published = STAGE / "output" / BLUEPRINTS_FILE
            m1_blueprints = published if published.is_file() else INPUT / "m1-blueprints.jsonl"
        if not m1_blueprints.is_file():
            raise ValueError(f"M1 blueprints are required for M2 generation: {m1_blueprints}")
        signatures, scenario_offset = read_m1_reference(m1_blueprints)
    tools, personas = load_organizer()
    registry, blueprints = generate(
        tools, personas, tier, seed, crm_customers, blueprint_count=blueprint_count,
        m1_signatures=signatures, scenario_offset=scenario_offset,
    )
    sessions = validate(
        tools, tier, registry, blueprints, crm_customers is not None, blueprint_count=blueprint_count,
    )
    return registry, blueprints, sessions


def write_dataset(directory: Path, registry: list[dict], blueprints: list[dict]) -> None:
    write_json(directory / CUSTOMERS_FILE, registry)
    with (directory / BLUEPRINTS_FILE).open("w", encoding="utf-8") as output:
        for journey in blueprints:
            output.write(json.dumps(journey, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=DISTRIBUTIONS, default="M1")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--blueprint-count", type=int,
                        help=f"M2 blueprint count, at least {M2_MIN_BLUEPRINTS} (default: {M2_MIN_BLUEPRINTS}).")
    parser.add_argument("--m1-blueprints", type=Path, help="Stage 1 M1 blueprints to compare with M2 candidates.")
    parser.add_argument("--identity-source", choices=("synthetic", "crm-seed"), default="synthetic",
                        help="Use crm-seed for organizer-backed identities. Add --publish to build M1 blueprints.")
    parser.add_argument("--publish", action="store_true", help="Copy the validated blueprint run to output/.")
    args = parser.parse_args()

    crm_customers = None
    if args.identity_source == "crm-seed":
        if args.publish and args.tier != "M1":
            parser.error("CRM-backed blueprint publication currently supports M1 only")
        crm_customers = load_crm_seed_registry()
        if not args.publish:
            run = write_crm_seed_registry(args.tier, datetime.now().astimezone(), crm_customers)
            print(f"{args.tier}: {len(crm_customers)} organizer CRM customers in {run}")
            return

    try:
        registry, blueprints, sessions = build_dataset(
            args.tier, args.seed, crm_customers, blueprint_count=args.blueprint_count,
            m1_blueprints=args.m1_blueprints,
        )
    except ValueError as error:
        parser.error(str(error))
    timestamp = datetime.now().astimezone()
    run_dir = STAGE / "runs" / run_name(args.tier, timestamp)
    run_dir.mkdir(parents=True)
    write_dataset(run_dir, registry, blueprints)
    if args.publish:
        publish_output(run_dir)
    print(f"{args.tier}: {len(blueprints)} journeys / {sessions} planned sessions in {run_dir}")


if __name__ == "__main__":
    main()
