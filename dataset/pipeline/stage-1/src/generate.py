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
from tempfile import TemporaryDirectory
from types import SimpleNamespace

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
INPUT = STAGE / "input"
DUPLICATE_REFERENCES = INPUT / "duplicate-references"
sys.path[:0] = [str(STAGE / "src"), str(ROOT)]
from blueprint_duplicates import blueprint_signature, is_duplicate_blueprint, read_blueprint_reference
from common import BLUEPRINTS_FILE, CUSTOMERS_FILE, run_name

SYNTHETIC_M1_DISTRIBUTION = {"standard": 78, "omnichannel": 32, "hard": 14, "extended": 16}
CHANNEL_PAIRS = (("facebook", "hotline"), ("zalo", "hotline"),
                 ("hotline", "zalo"), ("hotline", "facebook"))
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
RESEARCHER = "khach_hoi_nhieu_khong_mua"
UNSUPPORTED = "khach_hoi_ngoai_tai_lieu"
RETURNING = "khach_quay_lai_sau_8_thang"
MULTI_ITEM = "khach_mua_nhieu_mon"
M1_REGIONS = ("trung", "nam")
M1_SKU_COUNT = 45
M1_RUN_NAME = re.compile(r"m1-([0-9]{8})-v([1-9][0-9]*)")
M1_CRM_PLAN = (
    (CONSIDER, FAMILY, "decision", 12), (CONSIDER, PRICE, "decision", 10),
    (CONSIDER, EXCHANGE, "exchange_after_consultation", 3),
    (CONSIDER, RESEARCHER, "defer", 3), (CONSIDER, UNSUPPORTED, "unsupported_question", 2),
    (CROSS_CHANNEL, FAMILY, "decision", 5), (CROSS_CHANNEL, PRICE, "decision", 5),
    (CROSS_CHANNEL, EXCHANGE, "size_exchange", 5), (CROSS_CHANNEL, RESEARCHER, "defer", 4),
    (CROSS_CHANNEL, "khach_da_kenh_fb_hotline", "decision", 12),
    (CROSS_CHANNEL, UNSUPPORTED, "unsupported_question", 5),
    (CROSS_CHANNEL, "khach_da_kenh_mau_thuan", "conflicting_quotes", 6),
    (BUSINESS_CHANGE, FAMILY, "expired_promo", 6), (BUSINESS_CHANGE, PRICE, "expired_promo", 7),
    (BUSINESS_CHANGE, PRICE, "out_of_stock", 1), (BUSINESS_CHANGE, PRICE, "restock", 1),
    (BUSINESS_CHANGE, EXCHANGE, "exchange_after_promo", 5),
    (BUSINESS_CHANGE, RESEARCHER, "research_price_change", 2),
    (BUSINESS_CHANGE, IMPATIENT, "third_call_price_change", 2),
    (BUSINESS_CHANGE, RETURNING, "return_after_promo", 2),
    (BUSINESS_CHANGE, MULTI_ITEM, "basket_reprice", 4),
    (POST_PURCHASE, FAMILY, "order_status", 2), (POST_PURCHASE, PRICE, "order_status", 2),
    (POST_PURCHASE, EXCHANGE, "size_exchange", 16),
    (POST_PURCHASE, EXCHANGE, "exchange_after_consultation", 3),
    (POST_PURCHASE, RESEARCHER, "order_status", 2),
    (POST_PURCHASE, IMPATIENT, "order_status", 5), (POST_PURCHASE, IMPATIENT, "address_update", 5),
    (POST_PURCHASE, RETURNING, "stale_address", 3), (POST_PURCHASE, MULTI_ITEM, "basket_follow_up", 2),
    (IDENTITY, EXCHANGE, "verify_order_identity", 4), (IDENTITY, IMPATIENT, "verify_order_identity", 2),
    (IDENTITY, "hai_nguoi_chung_sdt", "shared_phone", 2), (IDENTITY, RETURNING, "stale_address", 10),
    (TRANSFER, PRICE, "handoff", 2), (TRANSFER, EXCHANGE, "order_handoff", 2),
    (TRANSFER, IMPATIENT, "third_call_handoff", 2),
    (TRANSFER, "khach_ngoai_pham_vi_chuyen_may", "handoff", 7),
    (TRANSFER, UNSUPPORTED, "handoff", 2),
)
M2_CRM_PLAN = (
    (CONSIDER, FAMILY, "decision", 12), (CONSIDER, PRICE, "decision", 12),
    (CONSIDER, "khach_hoi_nhieu_khong_mua", "defer", 4),
    (CONSIDER, "khach_hoi_ngoai_tai_lieu", "unsupported_question", 2),
    (CROSS_CHANNEL, "khach_da_kenh_fb_hotline", "decision", 11),
    (CROSS_CHANNEL, "khach_da_kenh_mau_thuan", "conflicting_quotes", 9),
    (CROSS_CHANNEL, PRICE, "decision", 8), (CROSS_CHANNEL, FAMILY, "decision", 7),
    (CROSS_CHANNEL, EXCHANGE, "size_exchange", 5),
    (BUSINESS_CHANGE, PRICE, "expired_promo", 6), (BUSINESS_CHANGE, PRICE, "out_of_stock", 3),
    (BUSINESS_CHANGE, PRICE, "restock", 2), (BUSINESS_CHANGE, FAMILY, "expired_promo", 2),
    (BUSINESS_CHANGE, FAMILY, "out_of_stock", 2), (BUSINESS_CHANGE, FAMILY, "restock", 2),
    (BUSINESS_CHANGE, "khach_mua_nhieu_mon", "basket_restock", 6),
    (BUSINESS_CHANGE, EXCHANGE, "exchange_after_restock", 4),
    (POST_PURCHASE, EXCHANGE, "exchange_after_consultation", 20),
    (POST_PURCHASE, EXCHANGE, "size_exchange", 2),
    (POST_PURCHASE, IMPATIENT, "order_status", 5), (POST_PURCHASE, IMPATIENT, "address_update", 5),
    (IDENTITY, "khach_quay_lai_sau_8_thang", "stale_address", 6),
    (IDENTITY, "hai_nguoi_chung_sdt", "shared_phone", 4),
    (IDENTITY, EXCHANGE, "verify_order_identity", 2),
    (TRANSFER, "khach_ngoai_pham_vi_chuyen_may", "handoff", 9),
)
M1_MIN_BLUEPRINTS = sum(count for _, _, _, count in M1_CRM_PLAN)
M2_MIN_BLUEPRINTS = sum(count for _, _, _, count in M2_CRM_PLAN)
DEFAULT_BLUEPRINT_COUNTS = {"M1": 180, "M2": 180}
CRM_HARD_CASES = {
    "unsupported_question", "conflicting_quotes", "expired_promo", "out_of_stock", "restock",
    "basket_restock", "exchange_after_restock", "stale_address", "shared_phone",
    "verify_order_identity", "handoff",
    "exchange_after_promo", "research_price_change", "third_call_price_change", "return_after_promo",
    "basket_reprice", "order_handoff", "third_call_handoff",
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


def m1_hotline_capacities(by_region, reserved_chat, blueprint_count):
    if blueprint_count == M1_MIN_BLUEPRINTS:
        return {key: 5 - chat_slots for key, chat_slots in reserved_chat.items()}

    hotline_count = blueprint_count - sum(reserved_chat.values())
    per_customer, extra = divmod(hotline_count, len(reserved_chat))
    capacity = dict.fromkeys(reserved_chat, per_customer)
    available = {region: deque(row["customer_id"] for row in rows) for region, rows in by_region.items()}
    regional_counts = {
        region: sum(per_customer + reserved_chat[key] for key in customers)
        for region, customers in available.items()
    }
    for _ in range(extra):
        region = min((region for region in available if available[region]), key=regional_counts.__getitem__)
        capacity[available[region].popleft()] += 1
        regional_counts[region] += 1
    return capacity


def m1_assign_customers(registry, plan):
    by_region = {region: [row for row in registry if row["region"] == region] for region in M1_REGIONS}
    reserved_chat = {row["customer_id"]: 2 if row["fb_id"] or row["zalo_id"] else 0 for row in registry}
    hotline_capacity = m1_hotline_capacities(by_region, reserved_chat, len(plan))
    assigned = {}
    for cross_channel in (True, False):
        capacities = reserved_chat.copy() if cross_channel else hotline_capacity
        groups = defaultdict(list)
        for index, (pattern, persona, _, _) in enumerate(plan):
            if (pattern == CROSS_CHANNEL) == cross_channel:
                groups[pattern, persona].append(index)

        central, south = M1_REGIONS
        split, unassigned = {}, []
        for indexes in groups.values():
            kind = plan[indexes[0]][2]
            if kind in {"shared_phone", "conflicting_quotes"}:
                pivot = len(indexes) // 2
                split.update((index, central) for index in indexes[:pivot])
                split.update((index, south) for index in indexes[pivot:])
            else:
                split[indexes[0]], split[indexes[1]] = central, south
                unassigned.extend(indexes[2:])
        remaining = {
            region: sum(capacities[row["customer_id"]] for row in customers)
            - sum(value == region for value in split.values())
            for region, customers in by_region.items()
        }
        if min(remaining.values()) < 0 or sum(remaining.values()) != len(unassigned):
            raise ValueError("M1 regional allocation does not match the BTC roster")
        for index in unassigned:
            region = max(remaining, key=remaining.get)
            split[index] = region
            remaining[region] -= 1

        special = {"shared_phone", "conflicting_quotes"}
        used_special = set()
        for index in sorted(split, key=lambda i: (plan[i][2] not in special, i)):
            kind = plan[index][2]
            eligible = [row for row in by_region[split[index]] if capacities[row["customer_id"]]]
            if kind == "shared_phone":
                eligible = [row for row in eligible if row["shared_phone_with"]]
            elif kind == "conflicting_quotes":
                eligible = [row for row in eligible if row["fb_id"] and row["zalo_id"]]
            if kind in special:
                eligible = [row for row in eligible if row["customer_id"] not in used_special]
            customer = max(eligible, key=lambda row: capacities[row["customer_id"]], default=None)
            if customer is None:
                raise ValueError(f"No M1 CRM profile in {split[index]} for {kind}")
            customer_id = customer["customer_id"]
            capacities[customer_id] -= 1
            if kind in special:
                used_special.add(customer_id)
            assigned[index] = customer
    return assigned


M1_PROMO_CASES = {
    "expired_promo", "exchange_after_promo", "research_price_change",
    "third_call_price_change", "return_after_promo", "basket_reprice",
}


def m1_fashion_scope(tools, rng):
    variants = {
        variant["variant_sku"]: (product, variant)
        for product in tools.PRODUCTS
        if product["category"].split("/")[0] == "thoi-trang" and not product["attributes"].get("discontinued")
        for variant in product["variants"]
        if tools.inventory_check(variant["variant_sku"], on=tools.REF)["in_stock"]
    }
    transitions = []
    for sku, (product, _) in variants.items():
        for promo in tools.PROMOS:
            if product["sku"] not in promo["applies_to"]:
                continue
            day = date.fromisoformat(promo["end"])
            after = day + timedelta(days=1)
            before_quote = tools.pricing_get_quote(sku, on=day.isoformat())
            after_quote = tools.pricing_get_quote(sku, on=after.isoformat())
            if (promo["promo_code"] in {row["promo_code"] for row in before_quote["applied_promos"]}
                    and before_quote["final_price_vnd"] != after_quote["final_price_vnd"]
                    and all(tools.inventory_check(sku, on=on.isoformat())["in_stock"] for on in (day, after))):
                transitions.append((sku, day, promo["promo_code"]))
    required = {sku for sku, _, _ in transitions}
    required.update(event["sku"] for event in tools.INV if event["sku"] in variants)
    others = list(variants.keys() - required)
    others.sort()
    rng.shuffle(others)
    # Keep at least one variant from each active product with sellable variants.
    covered = {variants[sku][0]["sku"] for sku in required}
    for sku in others:
        parent = variants[sku][0]["sku"]
        if parent not in covered:
            covered.add(parent)
            required.add(sku)
    skus = sorted(required) + [sku for sku in others if sku not in required][:M1_SKU_COUNT - len(required)]
    if len(skus) != M1_SKU_COUNT:
        raise ValueError(f"M1 requires {M1_SKU_COUNT} valid fashion variants")
    return {sku: variants[sku] for sku in skus}, transitions


def m1_case_options(tools, variants, transitions, kind, day, next_day, address, sku_uses):
    if kind in M1_PROMO_CASES:
        lead = {"exchange_after_promo": 3, "third_call_price_change": 1}.get(kind, 0)
        lag = 0 if kind == "third_call_price_change" else 1
        dates = [(sku, end - timedelta(days=lead), end + timedelta(days=lag), promo)
                 for sku, end, promo in transitions if sku in variants]
    elif kind in {"out_of_stock", "restock"}:
        dates = []
        for event in tools.INV:
            sku = event["sku"]
            if sku not in variants:
                continue
            after = date.fromisoformat(event["date"])
            before = after - timedelta(days=1)
            if (event["qty"] == 0) == (kind == "out_of_stock") and (
                    tools.inventory_check(sku, on=before.isoformat())["in_stock"] == (kind == "out_of_stock")):
                dates.append((sku, before, after, None))
    else:
        dates = [(sku, day, next_day, None) for sku in variants]

    options = []
    exchange = kind in {"size_exchange", "exchange_after_consultation", "exchange_after_promo"}
    for sku, first, second, promo in dates:
        if kind not in {"out_of_stock", "restock"} and not all(
                tools.inventory_check(sku, on=on.isoformat())["in_stock"] for on in (first, second)):
            continue
        if exchange:
            after_consultation = kind == "exchange_after_consultation"
            purchase_day = second if after_consultation else first
            delivery = date.fromisoformat(tools._eta(purchase_day.isoformat(), address))
            follow_up = max(delivery, second + timedelta(days=4 if after_consultation else 0))
            parent, variant = variants[sku]
            for replacement, (other_parent, other) in variants.items():
                if (other_parent is parent and other["color"] == variant["color"]
                        and other["size"] != variant["size"]
                        and tools.inventory_check(replacement, on=follow_up.isoformat())["in_stock"]):
                    options.append((sku, first, second, promo, replacement))
        else:
            options.append((sku, first, second, promo, None))
    return sorted(options, key=lambda option: sku_uses[option[0]])


def crm_plan(tier, blueprint_count):
    baseline, minimum = (M1_CRM_PLAN, M1_MIN_BLUEPRINTS) if tier == "M1" else (M2_CRM_PLAN, M2_MIN_BLUEPRINTS)
    count = DEFAULT_BLUEPRINT_COUNTS[tier] if blueprint_count is None else blueprint_count
    if type(count) is not int or count < minimum:
        raise ValueError(f"{tier} requires at least {minimum} blueprints.")

    # Spread extra two-session cases across patterns and preserve the reserved M1 chat slots.
    by_pattern = defaultdict(list)
    for index, (pattern, persona, kind, _) in enumerate(baseline):
        if crm_three_session(tier, persona, kind) or kind in {"shared_phone", "out_of_stock", "restock"}:
            continue
        if tier == "M1" and pattern == CROSS_CHANNEL:
            continue
        by_pattern[pattern].append(index)
    patterns = list(by_pattern.values())
    extra = Counter()
    for position in range(count - minimum):
        round_number, pattern_index = divmod(position, len(patterns))
        cases = patterns[pattern_index]
        extra[cases[round_number % len(cases)]] += 1
    return tuple((pattern, persona, kind, base_count + extra[index])
                 for index, (pattern, persona, kind, base_count) in enumerate(baseline))


def crm_three_session(tier, persona, kind):
    return persona == IMPATIENT or kind == "exchange_after_consultation" or (
        tier == "M1" and kind == "conflicting_quotes"
    )


def reset_mock_state(tools):
    for collection in (tools._ORDERS, tools._ONCE_USED, tools._CALLBACKS, tools._TICKETS, tools.CRM):
        collection.clear()


def generate(tools, personas, tier, seed, crm_customers=None, *, plan=None,
             reference_signatures=(), scenario_offset=0):
    if crm_customers is not None:
        return generate_crm_journeys(
            tools, personas, tier, seed, crm_customers, plan, reference_signatures, scenario_offset,
        )
    if tier != "M1":
        raise ValueError("M2 generation requires the BTC CRM roster.")
    rng = random.Random(seed)
    products = [p for p in tools.PRODUCTS if not p["attributes"].get("discontinued")]
    first_date = date.fromisoformat(tools.REF)
    expired, stockouts = hard_cases(tools)
    registry, blueprints = [], []
    seen = set()

    for category, count in SYNTHETIC_M1_DISTRIBUTION.items():
        for i in range(count):
            index = len(blueprints) + 1
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
                event_index = i // 4
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
                "scenario_id": f"SC-{index:03d}",
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

            seen.add(signature)
            registry.append(customer)
            blueprints.append(journey)

    return registry, blueprints


def generate_crm_journeys(tools, personas, tier, seed, crm_customers, plan, reference_signatures, scenario_offset):
    rng = random.Random(seed)
    registry = [{**row, "dialect": CRM_DIALECTS[row["region"]]} for row in crm_customers]
    rng.shuffle(registry)
    # Reserve the limited two-handle and shared-phone records before allocating general journeys.
    plan = [(pattern, persona, kind, index) for pattern, persona, kind, count in plan for index in range(count)]

    m1 = tier == "M1"
    if m1:
        assigned = m1_assign_customers(registry, plan)
        variants, transitions = m1_fashion_scope(tools, rng)
        used_skus = Counter()
        seen_signatures = set(reference_signatures)
    else:
        def priority(index):
            pattern, persona, kind, _ = plan[index]
            if kind == "shared_phone":
                return 0
            if tier == "M2":
                if pattern == CROSS_CHANNEL:
                    return 1
                return 2 if crm_three_session(tier, persona, kind) else 3
            if kind == "conflicting_quotes":
                return 1
            return 2 if pattern == CROSS_CHANNEL else 3
        uses, cross_channel_uses, extended_uses = Counter(), Counter(), Counter()
        assigned = {}
        for index in sorted(range(len(plan)), key=priority):
            pattern, persona, kind, _ = plan[index]
            if kind == "shared_phone":
                eligible = [row for row in registry if row["shared_phone_with"]]
            elif kind == "conflicting_quotes" and tier == "M1":
                eligible = [row for row in registry if row["fb_id"] and row["zalo_id"]]
            elif pattern == CROSS_CHANNEL:
                # Shared-phone cases already use chat. Reserve their other M2 slot for hotline coverage.
                eligible = [row for row in registry if (row["fb_id"] or row["zalo_id"])
                            and (tier == "M1" or not row["shared_phone_with"])]
            else:
                eligible = registry
            type_uses = None
            if tier == "M2":
                if pattern == CROSS_CHANNEL:
                    type_uses = cross_channel_uses
                elif crm_three_session(tier, persona, kind):
                    type_uses = extended_uses
            customer = min(eligible, key=lambda row: (
                type_uses[row["customer_id"]] if type_uses is not None else 0, uses[row["customer_id"]],
            ), default=None)
            if customer is None:
                raise ValueError(f"No CRM customer has the identities required for {kind}")
            uses[customer["customer_id"]] += 1
            if type_uses is not None:
                type_uses[customer["customer_id"]] += 1
            assigned[index] = customer

    expired, stockouts = hard_cases(tools) if not m1 else ([], [])
    restocks = []
    for event in tools.INV:
        day = date.fromisoformat(event["date"])
        before = (day - timedelta(days=1)).isoformat()
        if event["qty"] > 0 and not tools.inventory_check(event["sku"], on=before)["in_stock"]:
            restocks.append((event["sku"], day))
    products = [p for p in tools.PRODUCTS if not p["attributes"].get("discontinued")]
    shoe_variants = [v for p in products if p["sku"] == "SKU-SN-CAS" for v in p["variants"] if v["stock"] > 0]
    rows = []
    index = retries = 0
    while index < len(plan):
        pattern, persona, kind, variant = plan[index]
        customer = assigned[index]
        reset_mock_state(tools)
        day = date.fromisoformat(tools.REF) + timedelta(days=(index + retries) % 21)
        next_day = day + timedelta(days=1 + variant % 4)
        channel = ["hotline", "hotline", "hotline"]
        if pattern == CROSS_CHANNEL:
            social = [key for key in ("facebook", "zalo") if customer[CHANNEL_IDS[key]]]
            if kind == "conflicting_quotes" and tier == "M1":
                channel = ["facebook", "zalo", "hotline"]
            else:
                channel[:2] = [rng.choice(social), "hotline"]
                if (variant + retries) % 2 and (not m1 or persona != "khach_da_kenh_fb_hotline"):
                    channel[:2] = channel[:2][::-1]
        elif kind == "shared_phone" and not m1:
            channel[0] = "facebook" if customer["fb_id"] else "zalo"

        promo = None
        replacement = None
        if m1:
            day = date.fromisoformat(tools.REF) + timedelta(days=index % 21)
            next_day = day + timedelta(days=1 + variant % 4)
            if kind == "stale_address":
                day = date(2026, 2, 15) + timedelta(days=variant)
                next_day = date(2026, 10, 15) + timedelta(days=variant)
            options = m1_case_options(tools, variants, transitions, kind, day, next_day,
                                      REGIONS[customer["dialect"]], used_skus)
            if not options:
                raise ValueError(f"No valid fashion SKU for M1 {kind}")
            sku, day, next_day, promo, replacement = options[retries % len(options)]
        elif kind == "expired_promo":
            sku, day, promo = expired[(index + retries) % len(expired)]
            next_day = day + timedelta(days=1)
        elif kind == "out_of_stock":
            sku, day = stockouts[(variant + retries) % len(stockouts)]
            next_day = day + timedelta(days=1)
        elif kind == "restock":
            sku, next_day = restocks[(variant + retries) % len(restocks)]
            day = next_day - timedelta(days=1)
        elif kind == "basket_restock":
            appliance_restocks = [(item, on) for item, on in restocks if item.startswith(("SKU-AP-", "SKU-XM-"))]
            sku, next_day = appliance_restocks[(variant + retries) % len(appliance_restocks)]
            day = next_day - timedelta(days=1)
        elif kind == "exchange_after_restock":
            sku, replacement = "SKU-SN-RUN2-43-DEN", "SKU-SN-RUN2-41-DEN"
            day, next_day = date(2026, 10, 18), date(2026, 10, 24)
            if tier == "M2":
                variants = next(p["variants"] for p in products if p["sku"] == "SKU-SN-RUN2")
                color = next(v["color"] for v in variants if v["variant_sku"] == replacement)
                originals = [v["variant_sku"] for v in variants
                             if v["color"] == color and v["variant_sku"] != replacement
                             and tools.inventory_check(v["variant_sku"], on=day.isoformat())["in_stock"]]
                sku = rng.choice(originals)
        elif kind in {"size_exchange", "exchange_after_consultation"}:
            next_day = day + timedelta(days=4)
            if tier == "M1":
                original = rng.choice(shoe_variants)
                options = [v for v in shoe_variants if v["color"] == original["color"] and v["size"] > original["size"]]
                if not options:
                    options = [v for v in shoe_variants if v["color"] == original["color"] and v["size"] < original["size"]]
                sku, replacement = original["variant_sku"], rng.choice(options)["variant_sku"]
            else:
                stock_days = (day, next_day, next_day + timedelta(days=4), next_day + timedelta(days=5))
                pairs = []
                for product in products:
                    if not product["sku"].startswith("SKU-SN-"):
                        continue
                    in_stock = [v for v in product["variants"] if all(
                        tools.inventory_check(v["variant_sku"], on=on.isoformat())["in_stock"] for on in stock_days
                    )]
                    pairs.extend((original["variant_sku"], other["variant_sku"])
                                 for original in in_stock for other in in_stock
                                 if original["color"] == other["color"] and original["size"] != other["size"])
                sku, replacement = rng.choice(pairs)
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
            if m1 and persona == FAMILY:
                facts["family_approved_purchase"] = True
            if m1 and persona == PRICE:
                facts["competitor_price_vnd"] = max(1_000, truth["price_vnd"] - (variant + 1) * 20_000)
            expired_purchase = promo and (not m1 or promo in truth["expired_promos"])
            call = add("basket_purchase" if basket else ("purchase_after_expiry" if expired_purchase else "purchase"),
                       on, "Chốt đơn theo báo giá và điều kiện hiện hành", facts, truth, "chot_don",
                       "order.create", args, **checks)
            call["memory_expectation"] = {"order_status": "created"}
            return order

        def fashion_basket(on):
            alternatives = [item for item in variants if item != sku
                            and tools.inventory_check(item, on=on.isoformat())["in_stock"]]
            if not alternatives:
                raise ValueError("No second fashion SKU available for the order")
            return [sku, alternatives[(index + retries) % len(alternatives)]]

        def finish_repriced_purchase(on):
            # Try other valid resolutions if every SKU in this transition already occurred.
            resolution = (retries // len(options)) % 3
            if resolution == 0:
                purchase(on)
            elif resolution == 1:
                add("decline_after_expiry", on, "Xác nhận giá sau khuyến mãi và từ chối mua",
                    {}, quote(on), "tu_choi", "pricing.get_quote", {"sku": sku})
            else:
                requested = (on + timedelta(days=2)).isoformat() + "T10:00"
                callback = tools.schedule_callback(customer["phone"], requested)
                truth = {**quote(on), "scheduled_callback_at": callback["callback_at"]}
                add("callback_after_expiry", on, "Xem lại giá mới và hẹn trao đổi trước khi quyết định",
                    {}, truth, "hen_goi_lai", "schedule.callback",
                    {"customer_phone": customer["phone"], "callback_at": requested})

        order_workflows = {"size_exchange", "exchange_after_consultation", "exchange_after_restock", "order_status",
                           "address_update", "verify_order_identity", "stale_address", "exchange_after_promo",
                           "order_handoff", "basket_follow_up"}
        if kind in order_workflows:
            if kind == "exchange_after_consultation" or persona == IMPATIENT:
                consultation()
                order = purchase(next_day)
                follow_up = next_day + timedelta(days=4 if replacement else 1)
            else:
                order = purchase(day, fashion_basket(day) if kind == "basket_follow_up" else None)
                follow_up = next_day
            if m1 and replacement:
                follow_up = max(follow_up, date.fromisoformat(order["estimated_delivery"]))
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
            elif kind == "order_handoff":
                if not tools.order_status(order_id=oid)["orders"]:
                    raise ValueError("Handoff has no matching fashion order")
                add("handoff", follow_up, "Nhờ chuyên viên xử lý ngoại lệ đổi size cho đơn đã mua",
                    {"order_id": oid}, truth, "chuyen_may", "handoff.transfer",
                    brief_must_contain=list(tools.REQUIRED_BRIEF))
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
                if kind == "basket_follow_up":
                    goal = "Kiểm tra các món thời trang đã đặt và yêu cầu tổng kết đầy đủ đơn hàng"
                elif kind == "order_status":
                    goal = "Kiểm tra đơn đã mua"
                else:
                    goal = "Xác nhận thông tin người nhận trước khi tra đơn cũ"
                add(kind, follow_up, goal, {}, truth, "chot_don", "order.status", args,
                    **({"must_say_any": ["xác nhận", "địa chỉ"]} if kind in {"verify_order_identity", "stale_address"} else {}))
            if persona == IMPATIENT:
                calls[-1]["success_if"]["max_agent_questions"] = 1
        else:
            first = consultation()
            truth = quote(next_day)
            if kind == "conflicting_quotes":
                reported = truth["price_vnd"] + (variant + 1) * 100_000
                if tier == "M1":
                    add("conflicting_quote", next_day, "Hỏi về mức giá khác đã được báo qua kênh khác",
                        {"reported_price_vnd": reported}, truth, "hen_goi_lai")
                    purchase(next_day + timedelta(days=1))
                    calls[-1]["must_carry_over"].append("price_quoted_vnd")
                else:
                    purchase(next_day)
                    calls[-1]["customer_goal"] = "Đối chiếu mức giá đã báo qua hai kênh rồi chốt đơn"
                    calls[-1]["facts_established"]["reported_price_vnd"] = reported
                calls[-1]["session_purpose"] = "resolve_quotes"
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
            elif kind in {"handoff", "third_call_handoff"}:
                goal = "Hỏi về an toàn sử dụng ngoài phạm vi bán hàng và yêu cầu chuyên viên"
                if m1 and persona == PRICE:
                    goal = "Yêu cầu chuyên viên xem lại ngoại lệ về giá sau khi so sánh giá giày hoặc áo"
                elif m1 and persona == UNSUPPORTED:
                    goal = "Yêu cầu chuyên viên xác minh chi tiết chất liệu chưa có trong tài liệu"
                elif m1 and persona == "khach_ngoai_pham_vi_chuyen_may":
                    goal = "Hỏi sản phẩm có phù hợp với người thân đang hồi phục sau chấn thương và đồng ý để chuyên viên hỗ trợ"
                if kind == "third_call_handoff":
                    add("follow_up", next_day, "Nhắc lại yêu cầu làm rõ chính sách và chờ xác minh",
                        {}, truth, "hen_goi_lai")
                    next_day += timedelta(days=1)
                    truth = quote(next_day)
                    goal = "Gọi lần thứ ba và yêu cầu chuyển máy ngay vì câu hỏi chưa được xử lý"
                call = add("handoff", next_day, goal, {}, truth, "chuyen_may", "handoff.transfer",
                           brief_must_contain=list(tools.REQUIRED_BRIEF))
                if persona == IMPATIENT:
                    call["success_if"]["max_agent_questions"] = 1
            elif kind == "third_call_price_change":
                add("follow_up", next_day, "Gọi lại xác nhận mức giá trước khi hết khuyến mãi",
                    {}, truth, "hen_goi_lai")
                purchase(next_day + timedelta(days=1))
                calls[-1]["customer_goal"] = "Gọi lần thứ ba, xác nhận giá mới và chốt đơn nhanh"
                calls[-1]["success_if"]["max_agent_questions"] = 1
            elif kind == "return_after_promo":
                old_date = day - timedelta(days=240)
                old_quote = quote(old_date)
                if not old_quote["in_stock"]:
                    raise ValueError(f"No historical stock for M1 returning customer: {sku}")
                first["facts_established"].update(previous_purchase_date=old_date.isoformat(), previous_purchase_sku=sku)
                first["customer_goal"] = "Quay lại sau tám tháng, xác nhận sản phẩm đã mua và hỏi giá hiện tại"
                finish_repriced_purchase(next_day)
            elif m1 and kind == "expired_promo":
                finish_repriced_purchase(next_day)
            elif kind == "research_price_change":
                add(kind, next_day, "Hỏi kỹ về mẫu và mức giá sau khuyến mãi rồi cân nhắc thêm",
                    {"product_advised": sku}, truth, "tu_choi", "pricing.get_quote", {"sku": sku})
            elif m1 and kind == "out_of_stock":
                if retries % 2:
                    alternative = fashion_basket(next_day)[1]
                    comparison = ground_truth(tools, alternative, next_day.isoformat(), customer)
                    truth["comparison_quote"] = comparison
                    add(kind, next_day, "Hỏi giá một mẫu thay thế còn hàng rồi hoãn quyết định",
                        {"alternative_sku": alternative, "alternative_price_vnd": comparison["price_vnd"]},
                        truth, "tu_choi", "pricing.get_quote", {"sku": alternative})
                else:
                    add(kind, next_day, "Kiểm tra lại đúng size đã hỏi rồi hoãn mua vì hết hàng",
                        {}, truth, "tu_choi", "inventory.check", {"sku": sku})
            elif tier == "M2" and kind in {"out_of_stock", "restock"}:
                requested = (next_day + timedelta(days=3)).isoformat() + "T10:00"
                callback = tools.schedule_callback(customer["phone"], requested)
                truth["scheduled_callback_at"] = callback["callback_at"]
                goal = ("Hẹn trao đổi lại sau khi sản phẩm hết hàng" if kind == "out_of_stock"
                        else "Xác nhận sản phẩm đã về hàng và hẹn quyết định sau khi xem lại giá")
                add(kind, next_day, goal,
                    {"product_advised": sku}, truth, "hen_goi_lai", "schedule.callback",
                    {"customer_phone": customer["phone"], "callback_at": requested})
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
                elif m1 and kind in {"basket_reprice", "restock"}:
                    basket = fashion_basket(next_day)
                if basket:
                    first["facts_established"]["basket_skus"] = basket
                    first["entities_multi"].append("basket_skus")
                    first["session_purpose"] = "basket_inquiry"
                purchase(next_day, basket)
                if kind == "restock":
                    calls[-1]["session_purpose"] = "purchase_after_restock"
        journey = {
            "scenario_id": f"SC-{scenario_offset + index + 1:03d}", "tier": tier, "customer_id": customer["customer_id"],
            "customer_phone": customer["phone"], "customer_identities": {key: customer[key] for key in CHANNEL_IDS.values()},
            "persona": persona, "journey_pattern": pattern, "target_sku": sku, "hard_case": kind in CRM_HARD_CASES,
            "edge_case_type": kind if kind in CRM_HARD_CASES else None,
            "archetype": "extended" if len(calls) == 3 else "hard" if kind in CRM_HARD_CASES
                         else "omnichannel" if pattern == CROSS_CHANNEL else "standard",
            **{f"call_{i}": call for i, call in enumerate(calls, 1)},
        }
        if m1 or tier == "M2":
            references = seen_signatures if m1 else reference_signatures
            if is_duplicate_blueprint(journey, references):
                retries += 1
                if retries == (256 if m1 else 64):
                    raise ValueError(f"Could not generate a distinct {tier} {kind} case for {journey['scenario_id']}")
                continue
        if m1:
            seen_signatures.add(blueprint_signature(journey))
            used_skus[sku] += 1
        if tier == "M2":
            profile = personas[persona]
            goals = " | ".join(f"call_{i}: {call['customer_goal']}" for i, call in enumerate(calls, 1))
            patience = {f"call_{i}": profile["patience_initial"][f"call_{i}"] for i in range(1, len(calls) + 1)}
            journey["simulator_profile"] = {
                "persona_system_prompt": profile["system_prompt"].format(
                    goal=goals, facts="{facts}", turn_outline="{turn_outline}",
                ),
                "hidden_goal": goals,
                "patience_level": patience["call_1"],
                "patience_max_turns": patience["call_1"],
                "patience_by_session": patience,
            }
        rows.append(journey)
        index += 1
        retries = 0
    tools.CRM.clear()
    return sorted(registry, key=lambda row: row["customer_id"]), rows


def validate(tools, tier, registry, blueprints, plan=None):
    crm_backed = plan is not None
    if crm_backed:
        allocations = Counter()
        for pattern, persona, _, count in plan:
            allocations[pattern, persona] += count
        if Counter((row["journey_pattern"], row["persona"]) for row in blueprints) != allocations:
            raise ValueError("Stage 1 persona and pattern allocation mismatch")
        if tier == "M1" and [row["scenario_id"] for row in blueprints] != [
            f"SC-{i:03d}" for i in range(1, len(blueprints) + 1)
        ]:
            raise ValueError("Stage 1 scenario IDs must be consecutive SC-XXX IDs")
    elif Counter(j["archetype"] for j in blueprints) != SYNTHETIC_M1_DISTRIBUTION:
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
        if crm_backed:
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
            order_follow_up = actions[-1] in {"order.update", "order.status"} or (
                tier == "M1" and actions[-1] == "handoff.transfer" and "order_id" in calls[-1]["facts_established"]
            )
            if persona == EXCHANGE and ("order.create" not in actions[:-1] or not order_follow_up):
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
            if call["session_index"] < 3 or (tier == "M1" and crm_backed):
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

    extended = (sum(count for _, persona, kind, count in plan if crm_three_session(tier, persona, kind))
                if crm_backed else SYNTHETIC_M1_DISTRIBUTION["extended"])
    planned = 2 * len(blueprints) + extended
    if session_count != planned:
        raise ValueError("Stage 1 session total mismatch")
    return session_count


def referenced_skus(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from referenced_skus(item)
    elif isinstance(value, list):
        for item in value:
            yield from referenced_skus(item)
    elif isinstance(value, str) and value.startswith("SKU-"):
        yield value


def validate_m1_coverage(tools, registry, blueprints, sessions, references, planned_count):
    customers = {row["customer_id"]: row for row in registry}
    regions = Counter(row["region"] for row in registry)
    if regions != {"trung": 18, "nam": 17}:
        raise ValueError("M1 requires the 35 Central and Southern BTC CRM profiles")
    planned_sessions = 2 * planned_count + 28
    if (len(blueprints), sessions) != (planned_count, planned_sessions):
        raise ValueError(f"M1 requires {planned_count} blueprints and {planned_sessions} planned sessions")

    multi_call, cross_channel = Counter(), Counter()
    pairing_regions = defaultdict(set)
    signatures = set(references)
    for blueprint in blueprints:
        customer_id = blueprint["customer_id"]
        pairing_regions[blueprint["persona"], blueprint["journey_pattern"]].add(customers[customer_id]["region"])
        channels = [blueprint[key]["channel"] for key in ("call_1", "call_2", "call_3") if key in blueprint]
        hotline_calls = channels.count("hotline")
        if hotline_calls >= 2:
            multi_call[customer_id] += 1
        if 0 < hotline_calls < len(channels):
            cross_channel[customer_id] += 1
        if is_duplicate_blueprint(blueprint, signatures):
            raise ValueError(f"Duplicate M1 blueprint: {blueprint['scenario_id']}")
        signatures.add(blueprint_signature(blueprint))

    expected_chat = {key: 2 for key, row in customers.items() if row["fb_id"] or row["zalo_id"]}
    if len(expected_chat) != 21 or cross_channel != expected_chat:
        raise ValueError("M1 requires two omnichannel blueprints per chat-eligible customer")
    if planned_count == M1_MIN_BLUEPRINTS:
        if any(multi_call[key] != 5 - expected_chat.get(key, 0) for key in customers):
            raise ValueError("M1 base multi-call allocations do not match the plan")
    else:
        per_customer, extra = divmod(planned_count - sum(expected_chat.values()), len(customers))
        actual = sorted(multi_call[key] for key in customers)
        expected = [per_customer] * (len(customers) - extra) + [per_customer + 1] * extra
        if actual != expected:
            raise ValueError("M1 multi-call blueprints are not balanced across customers")
    if len(pairing_regions) != 35 or any(regions != set(M1_REGIONS) for regions in pairing_regions.values()):
        raise ValueError("Each M1 persona and pattern pairing must cover both regions")
    targets = {blueprint["target_sku"] for blueprint in blueprints}
    if (len(targets) != M1_SKU_COUNT or not set(referenced_skus(blueprints)) <= targets
            or any(not tools._parent(sku)[1] or tools._parent(sku)[0]["category"].split("/")[0] != "thoi-trang"
                   for sku in targets)):
        raise ValueError("M1 blueprints must use exactly 45 official fashion variant SKUs")


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


def next_m1_run_name(runs: Path, timestamp: datetime) -> str:
    day = timestamp.strftime("%Y%m%d")
    versions = (
        int(match[2]) for path in runs.glob(f"m1-{day}-v*")
        if (match := M1_RUN_NAME.fullmatch(path.name))
    )
    return f"m1-{day}-v{max(versions, default=0) + 1}"


def m1_duplicate_references():
    published = STAGE / "output" / BLUEPRINTS_FILE
    runs = STAGE / "runs"
    versioned = [path for path in runs.glob(f"m1-*/{BLUEPRINTS_FILE}") if M1_RUN_NAME.fullmatch(path.parent.name)]
    archives = sorted([*versioned, *runs.glob(f"run-*/{BLUEPRINTS_FILE}"), *runs.glob(f"run_*/{BLUEPRINTS_FILE}")])
    bundled = sorted(DUPLICATE_REFERENCES.glob("*.jsonl"))
    return [path for path in (published, *archives, *bundled) if path.is_file()]


def build_dataset(tier: str, seed: int = 2026, crm_customers: list[dict] | None = None, *,
                  blueprint_count: int | None = None, m1_blueprints: Path | None = None,
                  duplicate_references: list[Path] | None = None, synthetic: bool = False):
    if tier != "M2" and m1_blueprints is not None:
        raise ValueError("The M1 blueprint reference is configurable for M2 only.")
    signatures, scenario_offset = set(), 0
    if tier == "M2":
        roster = load_crm_seed_registry()
        if crm_customers is not None and crm_customers != roster:
            raise ValueError("M2 generation uses the BTC CRM roster.")
        crm_customers = roster
        if m1_blueprints is None:
            bundled = DUPLICATE_REFERENCES / "m1-blueprints.jsonl"
            candidates = (
                bundled,
                STAGE / "output" / "m1" / BLUEPRINTS_FILE,
                STAGE / "output" / BLUEPRINTS_FILE,
                INPUT / "m1-blueprints.jsonl",
            )
            m1_blueprints = next((path for path in candidates if path.is_file()), bundled)
        if not m1_blueprints.is_file():
            raise ValueError(f"M1 blueprints are required for M2 generation: {m1_blueprints}")
        if duplicate_references is not None or synthetic:
            raise ValueError("M2 uses the BTC CRM roster and an M1 blueprint reference.")
        signatures, scenario_offset = read_blueprint_reference(m1_blueprints, expected_tier="M1")
    elif not synthetic:
        roster = load_crm_seed_registry()
        selected = [row for row in roster if row["region"] in M1_REGIONS]
        if crm_customers is not None and crm_customers not in (roster, selected):
            raise ValueError("M1 uses the Central and Southern BTC CRM profiles.")
        crm_customers = selected
        references = m1_duplicate_references() if duplicate_references is None else duplicate_references
        for path in references:
            loaded, _ = read_blueprint_reference(path)
            signatures.update(loaded)
    elif crm_customers is not None or duplicate_references is not None or blueprint_count is not None:
        raise ValueError("The legacy synthetic run uses its own roster, blueprint count, and reference settings.")
    plan = crm_plan(tier, blueprint_count) if crm_customers is not None else None
    tools, personas = load_organizer()
    registry, blueprints = generate(
        tools, personas, tier, seed, crm_customers, plan=plan,
        reference_signatures=signatures, scenario_offset=scenario_offset,
    )
    sessions = validate(tools, tier, registry, blueprints, plan)
    if tier == "M1" and not synthetic:
        planned_count = sum(count for _, _, _, count in plan)
        validate_m1_coverage(tools, registry, blueprints, sessions, signatures, planned_count)
    return registry, blueprints, sessions


def write_dataset(directory: Path, registry: list[dict], blueprints: list[dict]) -> None:
    write_json(directory / CUSTOMERS_FILE, registry)
    with (directory / BLUEPRINTS_FILE).open("w", encoding="utf-8") as output:
        for journey in blueprints:
            output.write(json.dumps(journey, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("M1", "M2"), default="M1")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--blueprint-count", type=int,
                        help=f"CRM blueprint count (defaults: {DEFAULT_BLUEPRINT_COUNTS['M1']} M1 and "
                             f"{DEFAULT_BLUEPRINT_COUNTS['M2']} M2, minima: {M1_MIN_BLUEPRINTS} M1 and "
                             f"{M2_MIN_BLUEPRINTS} M2).")
    parser.add_argument("--m1-blueprints", type=Path, help="Stage 1 M1 blueprints to compare with M2 candidates.")
    parser.add_argument("--duplicate-reference", type=Path, action="append",
                        help="Pinned Stage 1 M1/M2 blueprint file for M1 duplicate checks. Repeat for more files.")
    parser.add_argument("--identity-source", choices=("synthetic", "crm-seed"),
                        help="M1 defaults to the Central and Southern BTC CRM profiles. Synthetic selects the legacy run.")
    parser.add_argument("--publish", action="store_true", help="Copy the validated blueprint run to output/.")
    args = parser.parse_args()

    crm_customers = None
    if args.tier == "M2" and args.identity_source == "synthetic":
        parser.error("M2 generation uses the BTC CRM roster.")
    if args.tier == "M1" and args.identity_source == "crm-seed":
        crm_customers = load_crm_seed_registry()
        if not args.publish and args.duplicate_reference is None and args.blueprint_count is None:
            run = write_crm_seed_registry(args.tier, datetime.now().astimezone(), crm_customers)
            print(f"{args.tier}: {len(crm_customers)} organizer CRM customers in {run}")
            return

    runs = STAGE / "runs"
    # Choose the M1 destination before reading references so competing runs contend for the same name.
    run_dir = runs / next_m1_run_name(runs, datetime.now().astimezone()) if args.tier == "M1" else None
    try:
        registry, blueprints, sessions = build_dataset(
            args.tier, args.seed, crm_customers, blueprint_count=args.blueprint_count,
            m1_blueprints=args.m1_blueprints, duplicate_references=args.duplicate_reference,
            synthetic=args.identity_source == "synthetic",
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if run_dir is None:
        run_dir = runs / run_name(args.tier, datetime.now().astimezone())
    runs.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=runs, prefix=".stage1-") as temporary:
        staged = Path(temporary) / run_dir.name
        staged.mkdir()
        write_dataset(staged, registry, blueprints)
        try:
            staged.rename(run_dir)
        except OSError:
            if run_dir.exists():
                parser.error(f"Run directory already exists: {run_dir}")
            raise
    if args.publish:
        publish_output(run_dir)
    print(f"{args.tier}: {len(blueprints)} journeys / {sessions} planned sessions in {run_dir}")


if __name__ == "__main__":
    main()
