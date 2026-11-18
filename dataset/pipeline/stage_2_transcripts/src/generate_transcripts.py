#!/usr/bin/env python3
"""Render Stage 1 journeys as Vietnamese customer-only static replay."""

import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from pipeline_common import promote_latest

CALLS = ("call_1", "call_2", "call_3")
MIN_SESSIONS = {"M1": 120, "M2": 250}
DIGITS = "không một hai ba bốn năm sáu bảy tám chín".split()
PLACES = ("", "nghìn", "triệu", "tỷ")
PHONE_OR_ID = re.compile(r"(?<!\w)(?:\+?84|0)(?:[ .-]*\d){8,11}(?!\w)|(?<!\w)\d{9,14}(?!\w)")
STREET_ADDRESS = re.compile(r"\b(?:số\s+)?\d+[a-z]?(?:/\d+)*\s+(?:đường|phố|ngõ|hẻm)\s+\w", re.I)
CHAT_WORDS = ((r"\bkhông\?", "ko?"), (r"\bkiểm tra\b", "check"),
              (r"\bcửa hàng\b", "shop"), (r"\bgiúp mình\b", "giúp m"),
              (r"\bsản phẩm\b", "sp"))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def number_words(value, thousand="nghìn"):
    if not value:
        return "không"
    groups = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    words = []
    for position in reversed(range(len(groups))):
        group = groups[position]
        if not group:
            continue
        hundreds, tail = divmod(group, 100)
        tens, units = divmod(tail, 10)
        if hundreds or position < len(groups) - 1 and group < 100:
            words.extend((DIGITS[hundreds], "trăm"))
            if not tens and units:
                words.append("lẻ")
        if tens:
            words.append("mười" if tens == 1 else f"{DIGITS[tens]} mươi")
        if units:
            spoken = "mốt" if units == 1 and tens > 1 else "lăm" if units == 5 and tens else DIGITS[units]
            words.append(spoken)
        if position:
            words.append(thousand if position == 1 else PLACES[position])
    return " ".join(words)


def accentless(text):
    decomposed = unicodedata.normalize("NFD", text).translate(str.maketrans("đĐ", "dD"))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def load_catalog():
    data = ROOT / "btc_data"
    if not data.is_dir():
        data = ROOT
    base = data / "BTC-Data-Vong1-TEAMS"
    products = read_json(base / "catalog/products.json")["products"]
    promos = read_json(base / "catalog/promotions.json")["promotions"]
    personas = read_json(base / "simulator/personas.json")["personas"]
    labels = {}
    for product in products:
        labels[product["sku"]] = product["name"]
        for variant in product["variants"]:
            details = " ".join(str(part) for part in (variant.get("color"), variant.get("size")) if part)
            labels[variant["variant_sku"]] = f"{product['name']} {details}".strip()
    return labels, {p["promo_code"]: p["name"] for p in promos}, {p["persona_id"] for p in personas}


def render_session(journey, index, customer, labels, promos, rng):
    call = journey[f"call_{index}"]
    facts = call["facts_established"]
    truth = call["ground_truth_facts"]
    voice = call["channel"] == "hotline"
    pronoun = rng.choice(("chị", "anh", "mình")) if voice else "mình"
    thousand = "ngàn" if customer["dialect"] == "South" else "nghìn"

    def number(value):
        return number_words(value, thousand) if voice else f"{value:,}".replace(",", ".")

    def label(sku):
        text = labels[sku]
        # Keep model identifiers intact, but speak standalone numbers in product names.
        return re.sub(r"(?<![\w.])\d+(?![\w.])", lambda m: number(int(m[0])), text) if voice else text

    def price(value):
        return f"{number(value)} đồng" if voice else f"{number(value)}đ"

    def delivery_destination(address):
        match = re.fullmatch(r"căn (\d+), lô ([AB]), khu giao nhận mô phỏng Sao Mai", address)
        if match:
            unit, block = match.groups()
        else:
            legacy = re.fullmatch(r"\[ADDR_(ALT_)?CUST_(\d+)\]", address)
            if not legacy:
                raise ValueError(f"Invalid synthetic address in {journey['scenario_id']}")
            unit, block = legacy[2], "B" if legacy[1] else "A"
        unit = number(int(unit))
        return f"căn {unit}, lô {block}, khu giao nhận mô phỏng Sao Mai"

    def day(value):
        parsed = date.fromisoformat(value)
        return f"ngày {number(parsed.day)} tháng {number(parsed.month)}" if voice else f"ngày {parsed.day}/{parsed.month}"

    product = label(journey["target_sku"])
    edge = journey["edge_case_type"]
    if index == 1:
        intro = rng.choice((
            f"{pronoun.capitalize()} đang xem {product}, em tư vấn giúp {pronoun} với.",
            f"Cho {pronoun} hỏi về {product} một chút được không?",
            f"Bên em bán {product} đúng không? {pronoun.capitalize()} đang tìm mẫu này.",
            f"{product.capitalize()} bên em còn hàng không?",
        ))
        if voice:
            intro = rng.choice(("Alo em ơi, ", "Dạ, ", "Ừm, ", "")) + (
                intro[0].lower() + intro[1:] if intro[0].isupper() and intro.startswith(pronoun.capitalize()) else intro
            ) if intro.startswith(pronoun.capitalize()) else intro
        advised = facts["product_advised"]
        quoted = facts["price_quoted_vnd"]
        if isinstance(advised, list):
            comparisons = [f"{label(sku)} giá {price(cost)}" for sku, cost in zip(advised, quoted, strict=True)]
            quote = f"Em báo {' còn '.join(comparisons)} đúng không? {pronoun.capitalize()} đang cân nhắc hai mẫu đó."
        else:
            quote = rng.choice((
                f"Vậy {label(advised)} bên em báo {price(quoted)} đúng không?",
                f"Để {pronoun} ghi lại nhé, {label(advised)} là {price(quoted)}.",
                f"{price(quoted)} cho {label(advised)} là giá hiện tại phải không em?",
            ))
        if "promo_code" in facts:
            code = facts["promo_code"]
            quote += f" Còn ưu đãi {promos[code]} áp dụng đến {day(facts['promo_expiry'])} đúng không?"
        callback = datetime.fromisoformat(call["success_if"]["args_match"]["callback_at"])
        callback_date = day(callback.date().isoformat())
        hour = number(callback.hour)
        if callback.minute:
            hour += f" giờ {number(callback.minute)} phút"
        else:
            hour += " giờ"
        reason = {
            "khach_do_du_hoi_nguoi_nha": "Để hỏi người nhà trước.",
            "khach_so_gia": "Để so thêm giá mấy chỗ.",
            "khach_hoi_nhieu_khong_mua": "Để xem kỹ lại thông tin đã.",
        }.get(journey["persona"], "Cho mình xem lại đã.")
        last = f"{reason} Em gọi lại lúc {hour} {callback_date} giúp {pronoun} nhé."
        return [intro, quote, last], pronoun

    if index == 3:
        destination = delivery_destination(facts["delivery_address"])
        opening = rng.choice((
            f"Alo, đơn {product} {pronoun} vừa chốt vẫn đang chờ giao đúng không?",
            f"Em xem giúp đơn {product} lần trước với, {pronoun} cần đổi chỗ nhận.",
            f"{pronoun.capitalize()} gọi lại về đơn {product} đã đặt hôm trước đây.",
        ))
        last = rng.choice((
            f"Đổi địa chỉ giao sang {destination} giúp {pronoun} nhé.",
            f"Giao về {destination} cho {pronoun}, em cập nhật luôn trên đơn giúp nhé.",
        ))
        return [opening, last], pronoun

    prior = journey["call_1"]["channel"]
    prior_contact = {"hotline": "gọi", "facebook": "nhắn trên Facebook", "zalo": "nhắn Zalo"}[prior]
    opening = rng.choice((
        f"Hôm trước {pronoun} có {prior_contact} hỏi {product}, em xem lại giúp {pronoun} nhé.",
        f"{pronoun.capitalize()} liên hệ lại về {product} đây, lần trước có {prior_contact} hỏi giá rồi.",
        f"Vụ {product} {pronoun} có {prior_contact} hỏi hôm trước ấy, bên em xem lại được không?",
        f"Em còn lưu báo giá {product} lần trước {pronoun} {prior_contact} hỏi không?",
    ))
    if edge == "out_of_stock":
        return [opening, f"Nếu {product} hết hàng rồi thì {pronoun} chưa đặt đâu, để khi khác nhé."], pronoun
    if edge == "handoff":
        return [opening, "Nhà mình có người đang điều trị, dùng sản phẩm này có cần hỏi bác sĩ không?",
                f"Nếu bên em không tư vấn được thì nối máy cho chuyên viên giúp {pronoun} nhé."], pronoun
    if edge == "policy_trap":
        return [opening, "Nếu mua về không vừa, lần đầu đổi size có mất phí vận chuyển không?",
                f"Ừ, để {pronoun} suy nghĩ thêm, hôm nay chưa đặt đâu."], pronoun
    quote = price(facts["price_quoted_vnd"])
    if call["expected_outcome"] == "tu_choi":
        return [opening, f"Giá giờ là {quote} đúng không? {pronoun.capitalize()} chưa cần mua nữa, để dịp khác nhé."], pronoun
    if edge == "expired_promo":
        code = journey["call_1"]["facts_established"]["promo_code"]
        mid = f"Ưu đãi {promos[code]} hôm trước hết rồi à? Em giải thích lại giúp {pronoun} mức {quote} nhé."
    else:
        mid = rng.choice((
            f"Vậy {product} hiện là {quote} nhé, lên đơn giúp {pronoun} với.",
            f"Đúng mẫu {product} đó rồi. Nếu giá là {quote} thì {pronoun} chốt luôn.",
            f"{pronoun.capitalize()} lấy {product} với giá {quote} nhé, em tạo đơn giúp.",
        ))
    payment = "trả tiền lúc nhận hàng" if facts["payment"] == "COD" else "thanh toán chuyển khoản"
    destination = delivery_destination(facts["delivery_address"])
    return [opening, mid, f"Cho {pronoun} {payment}, giao về {destination} giúp nhé."], pronoun


def transcript_styles(rendered, tier, seed):
    """Apply a measured amount of chat and ASR variation across the batch."""
    by_channel = {"voice": [], "chat": []}
    for call, turns, pronoun in rendered:
        voice = call["channel"] == "hotline"
        if not voice:
            turns[:] = [format_chat(turn) for turn in turns]
        for index in range(len(turns)):
            by_channel["voice" if voice else "chat"].append((turns, index, pronoun))

    rng = random.Random(seed)
    voice = by_channel["voice"]
    chat = by_channel["chat"]
    with_asr = rng.sample(voice, round(len(voice) * (0.275 if tier == "M2" else 0.175)))
    stripped = rng.sample(chat, round(len(chat) * 0.35))
    for turns, index, pronoun in with_asr:
        text = turns[index]
        changed = re.sub(r"\bkhông\b", "hông", text, count=1)
        if changed == text:
            changed = re.sub(r"\b(nghìn|ngàn)\b", lambda m: "ngàn" if m[0] == "nghìn" else "nghìn", text, count=1)
        if changed == text:
            changed = f"ờ {pronoun} nói là " + text[0].lower() + text[1:]
        turns[index] = changed
    for turns, index, _ in stripped:
        turns[index] = accentless(turns[index])
    return {
        "hotline_turns": len(voice), "hotline_asr_varied": len(with_asr),
        "chat_turns": len(chat), "chat_accentless": len(stripped),
    }


def format_chat(turn):
    turn = turn[0].lower() + turn[1:]
    for pattern, replacement in CHAT_WORDS:
        turn = re.sub(pattern, replacement, turn, flags=re.I)
    return turn.rstrip(".")


def validate(rows, customers, tier, expected_count):
    counts = Counter()
    for row in rows:
        customer = customers[row["customer_id"]]
        identities = row["customer_identities"]
        if row["tier"] != tier or any(customer[key] != value for key, value in identities.items()):
            raise ValueError(f"Tier or identity mismatch in {row['scenario_id']}")
        if tier == "M2" and not row.get("simulator_profile"):
            raise ValueError(f"Missing simulator profile in {row['scenario_id']}")
        for key in CALLS:
            if key not in row:
                continue
            call = row[key]
            turns = call["customer_turns"]
            if not 2 <= len(turns) <= 5 or any(not isinstance(turn, str) or not turn.strip() for turn in turns):
                raise ValueError(f"Invalid customer turns in {row['scenario_id']} {key}")
            if "delivery_address" in call["facts_established"] and (
                any("[ADDR_" in turn for turn in turns)
                or not any("khu giao nhan mo phong Sao Mai" in accentless(turn) for turn in turns)
            ):
                raise ValueError(f"Missing explicit synthetic address in {row['scenario_id']} {key}")
            if any(PHONE_OR_ID.search(turn) or STREET_ADDRESS.search(accentless(turn)) or STREET_ADDRESS.search(turn)
                   for turn in turns):
                raise ValueError(f"Potential raw PII in {row['scenario_id']} {key}")
            counts[call["channel"]] += 1
    if counts.total() != expected_count:
        raise ValueError("Session count does not match input")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=MIN_SESSIONS)
    parser.add_argument("--scenario-ids", nargs="+", help="Generate selected IDs without replacing the full batch.")
    parser.add_argument("--seed", type=int, help="Override the Stage 1 seed for alternate wording.")
    args = parser.parse_args()

    upstream = STAGE / "input_blueprints"
    manifest = read_json(upstream / "manifest.json")
    tier = args.tier or manifest["tier"]
    if tier != manifest["tier"]:
        parser.error(f"requested {tier}, but input_blueprints points to {manifest['tier']}")
    seed = manifest["seed"] if args.seed is None else args.seed
    rng = random.Random(seed)
    customers = {c["customer_id"]: c for c in read_json(upstream / "stage1_customers.json")}
    rows = [json.loads(line) for line in (upstream / "stage1_blueprints.jsonl").read_text(encoding="utf-8").splitlines()]
    available = {row["scenario_id"] for row in rows}
    if len(rows) != len(available) or len(rows) != manifest["total_blueprints"]:
        raise ValueError("Input blueprints do not match the manifest")
    if args.scenario_ids:
        requested = set(args.scenario_ids)
        if missing := requested - available:
            parser.error(f"unknown scenario IDs: {', '.join(sorted(missing))}")
        rows = [row for row in rows if row["scenario_id"] in requested]

    labels, promos, personas = load_catalog()
    rendered = []
    for row in rows:
        if row["persona"] not in personas:
            raise ValueError(f"Unknown persona: {row['persona']}")
        customer = customers[row["customer_id"]]
        for index, key in enumerate(CALLS, 1):
            if key in row:
                call = row[key]
                turns, pronoun = render_session(row, index, customer, labels, promos, rng)
                call["customer_turns"] = turns
                rendered.append((call, turns, pronoun))

    style_counts = transcript_styles(rendered, tier, seed)
    expected_count = len(rendered) if args.scenario_ids else manifest["total_planned_sessions"]
    counts = validate(rows, customers, tier, expected_count)
    if not args.scenario_ids and counts.total() < MIN_SESSIONS[tier]:
        raise ValueError("Session total is below the tier threshold")

    now = datetime.now().astimezone()
    name = f"run_{tier}_{now:%Y%m%d_%H%M}"
    parent = STAGE / "runs"
    if args.scenario_ids:
        parent /= "targeted"
    run = parent / name
    run.mkdir(parents=True)
    with (run / "raw_scenarios.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    log = {
        "tier": tier, "seed": seed, "input_run": upstream.resolve().name,
        "timestamp": now.isoformat(timespec="seconds"),
        "generation_method": "Codex-authored deterministic Vietnamese renderer",
        "model": None, "temperature": None, "token_counts": None, "retry_count": 0,
        "scenario_count": len(rows), "session_count": counts.total(),
        "sessions_by_channel": dict(counts), "style_counts": style_counts,
        "targeted_scenario_ids": sorted(args.scenario_ids or []),
    }
    (run / "generation_log.json").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    if not args.scenario_ids:
        promote_latest(STAGE, name)
    print(f"{tier}: {len(rows)} transcripts / {counts.total()} sessions in {run}")


if __name__ == "__main__":
    main()
