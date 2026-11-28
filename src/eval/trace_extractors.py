from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Any

from telesale_agent.application.asr_normalization import normalize_asr_transcript
from telesale_agent.application.price_language import AMOUNT as _AMOUNT, MONEY_UNIT, money_value, stated_price_context
from telesale_agent.core.basket import mentioned_catalog_items


_SLOT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("room_area_m2", re.compile(r"diện tích|m[²2]|mét vuông", re.I)),
    ("budget_vnd", re.compile(r"ngân sách|tầm bao nhiêu|khoảng bao nhiêu tiền", re.I)),
    ("has_children", re.compile(r"trẻ nhỏ|trẻ em|em bé|bé nhỏ|có bé", re.I)),
    ("product_advised", re.compile(
        r"(?:sản phẩm|mẫu|dòng|máy|sku)(?:\s+[\w-]+){0,5}\s+nào\b|mã\s+(?:sku|sản phẩm)\s+(?:là gì|bao nhiêu)",
        re.I,
    )),
    ("price_quoted_vnd", re.compile(r"giá|bao nhiêu tiền", re.I)),
    ("promo_code", re.compile(r"khuyến mãi|mã giảm|ưu đãi|promo", re.I)),
    ("blocker", re.compile(r"băn khoăn|hỏi.*(?:chồng|vợ|người nhà)|chưa chốt", re.I)),
    ("address", re.compile(r"địa chỉ|giao.*đâu", re.I)),
    ("payment", re.compile(r"thanh toán|cod|chuyển khoản", re.I)),
    ("quantity", re.compile(r"số lượng|bao nhiêu (?:cái|chiếc|bộ)", re.I)),
    ("size", re.compile(r"kích cỡ|size|cỡ nào", re.I)),
    ("color", re.compile(r"màu", re.I)),
    ("order_id", re.compile(r"mã đơn|đơn hàng nào", re.I)),
]

_CONFIRM_PATTERN = re.compile(
    r"đúng không|phải không|có đúng|vẫn .* (?:chứ|đúng)|xác nhận|(?:anh|chị) đồng ý|luôn nhé\s*(?:ạ)?[?？]",
    re.I,
)
_REQUEST = re.compile(
    r"(?:cho em (?:xin|biết)|cho em hỏi|vui lòng cho biết|em xin hỏi)"
    r"|(?:bao nhiêu|thế nào|ở đâu|mẫu nào|khi nào|đúng không|phải không|được không)\s*(?:ạ)?[.。]?$",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[?？!])\s*|(?<=[.;])\s+|[\r\n]+")
_SKU = re.compile(r"\bSKU-[A-Z0-9-]+\b", re.I)
_PRICE = re.compile(
    rf"(?P<label>\bchênh\s+lệch(?:\s+giá)?|\bhoàn\s+lại|\bthanh\s+toán\s+bổ\s+sung"
    rf"|\bgiá(?:\s+niêm\s+yết)?|\btổng(?:\s+(?:tiền|cộng|đơn(?:\s+hàng)?))?|\bcòn)"
    rf"\s*(?:(?:bán|ưu đãi|khuyến mãi|hiện tại|hôm nay|chính xác|chính hãng|chính thức|là|chỉ|vẫn|còn|giữ nguyên|:)\s*)*"
    rf"[*\s]*(?P<amount>{_AMOUNT})(?!\d|[.,]\d)(?:\s*(?P<unit>{MONEY_UNIT}))?",
    re.I,
)
_NON_MONEY_SUFFIX = re.compile(r"\s*(?:%|phần\s+trăm|đôi\b|chiếc\b|sản\s+phẩm\b|ngày\b|tháng\b)", re.I)
_CUSTOMER_QUOTE = re.compile(r"\b(?:anh|chị|mình)\s+(?:đã\s+)?(?:tham\s+khảo|báo\s+lại|so\s+ở\s+nơi\s+khác)\b", re.I)
_SELLER_QUOTE = re.compile(r"\b(?:bên\s+em|bên\s+mình|cửa\s+hàng)\b", re.I)
_STOCK = re.compile(
    r"\b(?P<empty>hết\s+hàng|chưa\s+có\s+hàng|không\s+(?:còn\s+hàng|sẵn\s+hàng|có\s+sẵn|có\s+hàng))"
    r"|\b(?:còn\s+hàng|có\s+sẵn|sẵn\s+hàng|sẵn\s+có)\b", re.I,
)
_FREE_SHIPPING = re.compile(r"\b(?P<no>không\s+)?(?:được\s+)?miễn phí\s+(?:vận chuyển|giao hàng)\b", re.I)
_DELIVERY = re.compile(r"\bgiao(?:\s+hàng)?[^!?;\n\d]{0,35}(\d+)\s*ngày\b", re.I)
_ETA = re.compile(
    r"\b(?:giao(?: hàng)?|dự kiến (?:giao|tới|đến|nhận)|nhận hàng)"
    r"[^.;!?]{0,35}?(?:ngày\s+)?(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?)",
    re.I,
)

_PROMO_CODE = r"(?<![\w-])(?P<code>[A-Z0-9]+(?:-[A-Z0-9]+)+)(?![\w-])[*`\"”]*\s*(?:[:,]\s*)?"
_PROMO_EXPIRY = re.compile(
    _PROMO_CODE
    + r"(?:(?:chỉ|vẫn|sẽ)\s+)*"
    r"(?:(?:(?:còn|có)\s+hiệu\s+lực|(?:còn\s+)?áp\s+dụng)\s+(?:cho\s+)?(?:đến|tới)(?:\s+hết)?"
    r"|(?:hết\s+hạn|kết\s+thúc)(?:\s+vào)?|đến\s+hết)\s+(?:ngày\s+)?"
    r"(?P<expiry>\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}(?:[./-]\d{4})?"
    r"|\d{1,2}\s+tháng\s+\d{1,2}(?:\s+năm\s+\d{4})?)(?!\d|[./-]\d)",
    re.I,
)
_PROMO_STATUS = re.compile(
    _PROMO_CODE
    + r"(?:(?P<inactive>không\s+(?:còn\s+)?(?:áp\s+dụng|hiệu\s+lực)|(?:đã\s+)?hết\s+(?:hạn|hiệu\s+lực))"
    r"|còn\s+hiệu\s+lực|(?:vẫn|còn)\s+áp\s+dụng)\b",
    re.I,
)


def extract_questions(response_text: str) -> list[dict[str, str]]:
    """Extract BTC question records from the final agent response."""
    questions = []
    for sentence in _SENTENCE.split(response_text or ""):
        text = re.sub(r"^[\s>*#\-\d.)]+", "", sentence).strip()
        if not text or not (text.endswith(("?", "？")) or _REQUEST.search(text)):
            continue
        slot = "other"
        for candidate, pattern in _SLOT_PATTERNS:
            if pattern.search(text):
                slot = candidate
                break
        questions.append(
            {
                "slot": slot,
                "type": "confirm" if _CONFIRM_PATTERN.search(text) else "open",
                "text": text,
            }
        )
    return questions


def extract_claims(
    tool_calls: list[dict[str, Any]],
    *,
    response_text: str,
    call_date: str | None = None,
    catalog_items: list[dict[str, Any]] | None = None,
    price_subject_sku: str | None = None,
) -> list[dict[str, Any]]:
    """Extract spoken claims; a price need not agree with a tool to be scored.

    This remains a heuristic extractor. It does not evaluate all free text.
    """
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    def add(field: str, value: Any, evidence: str | None = None) -> None:
        marker = (field, json.dumps(value, ensure_ascii=False, sort_keys=True))
        if marker not in seen:
            seen.add(marker)
            claim = {"field": field, "value": value}
            if evidence:
                claim["text"] = evidence.strip()
            claims.append(claim)

    quote_skus = {
        call["args"]["sku"].upper()
        for call in tool_calls
        if call.get("name") == "pricing.get_quote"
        and isinstance((call.get("args") or {}).get("sku"), str)
        and isinstance(call.get("result"), dict) and not call["result"].get("error")
    }
    items = {str(item["sku"]).upper(): item for item in catalog_items or [] if item.get("sku")}
    for call in tool_calls:
        if call.get("name") == "catalog.search" and isinstance(call.get("result"), dict):
            items.update({str(item["sku"]).upper(): item for item in call["result"].get("items", [])
                          if isinstance(item, dict) and item.get("sku")})
    item_list = list(items.values())
    prices: list[tuple[str, int, str, str | None]] = []
    for sentence in _SENTENCE.split(response_text):
        if sentence.rstrip().endswith(("?", "？")):
            continue
        normalized = normalize_asr_transcript(sentence)
        competitor_price = stated_price_context(normalized).get("competitor_price_vnd")
        if competitor_price is not None:
            add("competitor_price_vnd", competitor_price, sentence)
        previous_end = 0
        sentence_sku = None
        for match in _PRICE.finditer(normalized):
            label = match["label"]
            unit = match["unit"] or ""
            value = money_value(f"{match['amount']} {unit}")
            prefix = normalized[previous_end:match.start()]
            previous_end = match.end()
            suffix = normalized[match.end():]
            if value is None or _NON_MONEY_SUFFIX.match(suffix) or (not unit and value < 1000):
                continue
            if not _asserted_policy(normalized, match):
                continue
            field = "list_price_vnd" if "niêm" in label else "price_vnd"
            if label.startswith("tổng"):
                add("total_vnd", value, sentence)
                continue
            if label.startswith("chênh"):
                if re.search(r"\bhoàn\s+lại\b", suffix):
                    add("price_diff_vnd", -value, sentence)
                    add("refund_vnd", value, sentence)
                elif re.search(r"\b(?:thanh\s+toán|trả)\s+bổ\s+sung\b", suffix):
                    add("price_diff_vnd", value, sentence)
                    add("extra_payment_vnd", value, sentence)
                else:
                    add("price_difference_amount_vnd", value, sentence)
                continue
            if label.startswith(("hoàn", "thanh")):
                add("refund_vnd" if label.startswith("hoàn") else "extra_payment_vnd", value, sentence)
                continue
            if not _SELLER_QUOTE.search(prefix) and _CUSTOMER_QUOTE.match(suffix.lstrip()):
                add("competitor_price_vnd", value, sentence)
                continue
            mentioned = {sku.upper() for sku in _SKU.findall(prefix)}
            named = mentioned_catalog_items(prefix, item_list) if item_list and not mentioned else []
            if len(named) == 1:
                parent = str(named[0]["sku"]).upper()
                mentioned = {sku for sku in quote_skus if sku == parent or sku.startswith(parent + "-")}
            if len(mentioned) == 1:
                sentence_sku = next(iter(mentioned))
            sku = sentence_sku or (next(iter(quote_skus)) if len(quote_skus) == 1 and not named else None)
            prices.append((field, value, sentence, sku))
        for match in _STOCK.finditer(sentence):
            if _asserted_policy(sentence, match):
                add("in_stock", not bool(match["empty"]), match[0])
        for match in _FREE_SHIPPING.finditer(sentence):
            if _asserted_policy(sentence, match):
                add("free_shipping", not bool(match["no"]), match[0])
        for match in _DELIVERY.finditer(normalized):
            if _asserted_policy(normalized, match):
                add("delivery_days", int(match[1]), sentence)
        for match in _ETA.finditer(normalized):
            eta = _promo_expiry_date(match[1], call_date)
            if eta and _asserted_policy(normalized, match):
                add("estimated_delivery", eta, sentence)
                if call_date:
                    add("delivery_days", (date.fromisoformat(eta) - date.fromisoformat(call_date)).days, sentence)

    policy_patterns = (
        ("return_days", re.compile(r"(?:đổi\s*trả|trả\s*hàng|đổi\s*hàng|đổi(?:\s+size)?\s+trong)"
                                   r"[^.!?;\d]{0,30}(\d+)\s*ngày", re.I)),
        ("warranty_months", re.compile(r"bảo\s*hành[^.!?;\d]{0,20}(\d+)\s*(tháng|năm)", re.I)),
        ("exchange_fee_vnd", re.compile(r"phí\s+đổi(?:\s+(?:size|sản\s*phẩm|hàng))?\s*"
                                        r"(?:(?:là|chỉ|còn|:)\s*)?(\d[\d.,]*(?:\s\d{3})*)\s*"
                                        r"(triệu|nghìn|ngàn|tr|k|đồng|vnd|₫|đ)?", re.I)),
    )
    for field, pattern in policy_patterns:
        for match in pattern.finditer(response_text):
            if not _asserted_policy(response_text, match):
                continue
            number = match[1].replace(" ", "").rstrip(".,")
            if field == "exchange_fee_vnd":
                value = money_value(f"{number} {match[2] or ''}")
                if value is None:
                    continue
            else:
                value = int(number) * (12 if field == "warranty_months" and match[2].casefold() == "năm" else 1)
            add(field, int(value), match[0])
    # BTC v2 uses an unqualified price slot for the scenario's main SKU.
    # In a comparison, retain other quotes as SKU-specific claims only when
    # the response also quotes the primary SKU with identifiable evidence.
    subject = (price_subject_sku or "").upper()
    scoped_fields = {field for field, _, _, sku in prices if sku and sku == subject}
    for field, value, sentence, sku in prices:
        if field not in scoped_fields or not sku or sku == subject:
            add(field, value, sentence)
        if sku:
            add(f"{field}_{sku}", value, sentence)

    for match in re.finditer(r"đổi(?:\s+size)?[^.!?;]{0,25}miễn\s*phí", response_text, re.I):
        if _asserted_policy(response_text, match) and not re.search(r"không\s+miễn", match[0], re.I):
            add("exchange_fee_vnd", 0, match[0])

    for match in _PROMO_EXPIRY.finditer(response_text):
        if _asserted_promo(response_text, match):
            expiry = _promo_expiry_date(match["expiry"], call_date)
            if expiry is not None:
                add(f"promo_expiry_{match['code'].upper()}", expiry, match[0])

    spoken_promo_status = set()
    for match in _PROMO_STATUS.finditer(response_text):
        suffix = response_text[match.end():]
        if _asserted_promo(response_text, match) and not re.match(
            r"\s+(?:(?:đến|tới|vào|từ|ngày|sau)\b|\d)", suffix, re.I
        ):
            code = match["code"].upper()
            spoken_promo_status.add(code)
            add(f"promo_{code}_active", not match["inactive"], match[0])

    def add_quoted_promo_status(promo: Any) -> None:
        code = promo.get("promo_code") if isinstance(promo, dict) else promo
        if not code or str(code).upper() in spoken_promo_status:
            return
        cue = rf"\b(?:freeship|miễn phí vận chuyển|áp dụng|tặng kèm)\s+(?:mã\s+)?{re.escape(str(code))}\b"
        for sentence in _SENTENCE.split(response_text):
            if re.search(cue, sentence, re.I) and not sentence.endswith(("?", "？")):
                if not re.search(r"\b(?:không|chưa|hết)\b", sentence, re.I):
                    add(f"promo_{str(code).upper()}_active", True, sentence)

    for call in tool_calls:
        name = call.get("name")
        result = call.get("result") or {}
        if not isinstance(result, dict) or result.get("error"):
            continue
        if name == "pricing.get_quote":
            for promo in result.get("applied_promos") or []:
                add_quoted_promo_status(promo)
        elif name == "pricing.quote_order":
            units = result.get("units") or []
            for unit in units:
                price = unit.get("final_price_vnd")
                skus = {u.get("sku") for u in units if u.get("final_price_vnd") == price}
                evidence = next((c for c in claims if c["field"] == "price_vnd" and c["value"] == price), None)
                if evidence and len(skus) == 1 and unit.get("sku"):
                    add(f"price_vnd_{unit['sku']}", price, evidence.get("text"))
                for promo in unit.get("applied_promos", []):
                    add_quoted_promo_status(promo)
            for promo in result.get("order_promos", []):
                add_quoted_promo_status(promo)

    return claims


def _promo_expiry_date(value: str, call_date: str | None) -> str | None:
    parts = re.split(r"[./-]|\s+(?:tháng|năm)\s+", value, flags=re.I)
    try:
        if len(parts[0]) == 4:
            return date.fromisoformat(value).isoformat()
        day, month, *year = map(int, parts)
        if year:
            return date(year[0], month, day).isoformat()
        if call_date is not None:
            return date(date.fromisoformat(call_date).year, month, day).isoformat()
    except ValueError:
        return None
    return None


def _asserted_promo(text: str, match: re.Match[str]) -> bool:
    return _asserted_policy(text, match) and not re.match(
        r"\s*(?:(?:đúng không|phải không|không|chứ|hả|ạ)\s*)?[?？]",
        text[match.end():], re.I,
    )


def _asserted_policy(text: str, match: re.Match[str]) -> bool:
    """Exclude a denied rule or a quoted old/customer claim being corrected."""
    prefix = re.split(r"[;!?\n]|,\s+", text[:match.start()])[-1].casefold()
    suffix = text[match.end():match.end() + 30].casefold()
    if re.search(r"(?:không\s+phải|không\s+áp\s+dụng|không\s+còn|chưa\s+xác\s+nhận)\s*(?:là\s*)?$", prefix):
        return False
    if re.match(r"[\s”\"']*(?:là\s+)?(?:sai|không\s+đúng|không\s+áp\s+dụng)", suffix):
        return False
    return not bool(re.search(r"(?:khách\s+(?:nói|hỏi)|bài\s+cũ|thông\s+tin\s+cũ)[^.!?]{0,60}[“\"]\s*$", prefix))


_TOOL_SLOT_NAMES = {
    "sku": ("product_advised", "variant_sku"),
    "new_variant_sku": ("variant_sku",),
    "price_vnd": ("price_quoted_vnd",),
    "payment_method": ("payment",),
    "address": ("address", "delivery_address"),
    "shipping_address": ("delivery_address",),
    "qty": ("quantity",),
}
_TEXT_SLOT_PATTERNS = {
    "room_area_m2": (rf"({_AMOUNT})\s*(?:m[²2]|mét vuông)",),
    "size": (r"\b(?:size|cỡ)\s+(\d+|s|m|l|xl)\b",),
    "color": (r"\bmàu\s+(đen|trắng|xanh|đỏ|be|hồng|nâu|xám|vàng|tím)\b",),
    "quantity": (r"\b(\d+)\s+(?:máy|chiếc|cái|bộ|đôi)\b",),
}
_CHILDREN = re.compile(r"\b(?:(?P<no>không\s+có|chưa\s+có)|có)\s+(?:trẻ nhỏ|trẻ em|em bé|bé nhỏ|bé)\b", re.I)


def _comparable_fact(value: Any) -> str:
    folded = unicodedata.normalize("NFD", str(value).casefold().strip())
    return "".join(c for c in folded if not unicodedata.combining(c)).replace("đ", "d")


def extract_exchange_facts_used(
    tool_calls: list[dict[str, Any]], prior_facts: dict[str, Any],
) -> list[str]:
    """Identify old-order facts consumed by a verified size exchange."""
    order_id = prior_facts.get("order_id")
    prior_variant = prior_facts.get("variant_sku")
    prior_product = prior_facts.get("product_advised")
    prior_sku = prior_variant or prior_product
    if not (isinstance(order_id, str) and order_id and isinstance(prior_sku, str) and prior_sku):
        return []

    original_order = None
    for call in tool_calls:
        result = call.get("result")
        if call.get("name") == "order.status":
            orders = result.get("orders") if isinstance(result, dict) and not result.get("error") else None
            matches = [order for order in (orders or []) if isinstance(order, dict) and order.get("order_id") == order_id]
            original_order = matches[0] if len(matches) == 1 else None
            continue
        args = call.get("args")
        if (call.get("name") != "order.update" or original_order is None
                or not isinstance(result, dict) or result.get("error") or not isinstance(args, dict)):
            continue
        new_sku = args.get("new_variant_sku")
        if (
            args.get("action") != "exchange_size"
            or result.get("action") != "exchange_size"
            or args.get("order_id") != order_id
            or result.get("order_id") != order_id
            or result.get("status") != "pickup_scheduled"
            or not isinstance(new_sku, str) or not new_sku
            or result.get("new_variant_sku") != new_sku
        ):
            continue

        old_sku = original_order.get("sku")
        if not isinstance(old_sku, str) or old_sku.upper() != prior_sku.upper() or new_sku.upper() == old_sku.upper():
            continue
        # The lookup precedes the update, so use this snapshot rather than
        # the brief refreshed after the old SKU has been superseded.
        used = ["variant_sku"] if prior_variant else []
        product = str(prior_product or old_sku).upper()
        if old_sku.upper() == product or old_sku.upper().startswith(product + "-"):
            used.append("product_advised")
        old_price = original_order.get("price_vnd")
        prior_price = prior_facts.get("price_quoted_vnd", prior_facts.get("price_vnd"))
        if (type(old_price) in (int, float) and type(prior_price) in (int, float)
                and old_price == prior_price and type(result.get("price_diff_vnd")) in (int, float)):
            used.append("price_quoted_vnd")
        return used
    return []


def extract_facts_used(
    response_text: str,
    tool_calls: list[dict[str, Any]],
    prior_facts: dict[str, Any],
    *,
    current_brief: Any = None,
    stated_this_call: dict[str, int] | None = None,
) -> list[str]:
    """Match values from prior-call writes against the brief and visible evidence."""
    if not prior_facts:
        return []
    current = getattr(current_brief, "remembered_preferences", {}).get("facts", {}) if current_brief else prior_facts
    evidence: dict[str, list[Any]] = {}
    option_facts_used: list[str] = []
    prior_quotes = prior_facts.get("checkout_option_quotes")

    def remember(key: str, value: Any) -> None:
        if key in prior_facts:
            evidence.setdefault(key, []).append(value)

    for call in tool_calls:
        result = call.get("result") or {}
        if isinstance(result, dict) and (result.get("error") or result.get("found") is False):
            continue
        args = call.get("args") or {}
        if not isinstance(args, dict):
            continue
        recalled_quote = call.get("prior_checkout_quote")
        if (
            call.get("name") == "pricing.get_quote"
            and isinstance(prior_quotes, dict) and isinstance(recalled_quote, dict)
            and isinstance(args.get("sku"), str) and prior_quotes.get(args["sku"]) == recalled_quote
            and isinstance(result, dict) and result.get("sku") == args["sku"]
            and type(result.get("final_price_vnd")) is int
        ):
            option_facts_used.extend(("product_advised", "variant_sku"))
            # The old price can identify the variant even after a promotion
            # expires. Only a matching current quote verifies the old amount.
            if result["final_price_vnd"] == recalled_quote.get("price_vnd"):
                option_facts_used.append("price_quoted_vnd")
        for item in [args, *(args.get("lines") or [])]:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                for slot in _TOOL_SLOT_NAMES.get(key, (key,)):
                    remember(slot, value)
        alternatives = [args.get("sku"), args.get("new_variant_sku"), *(args.get("basket_skus") or [])]
        alternatives.extend(line.get("sku") for line in args.get("lines") or [] if isinstance(line, dict))
        for sku in alternatives:
            if not isinstance(sku, str):
                continue
            remember("product_advised", sku)
            remember("variant_sku", sku)
            match = re.search(r"-(\d+|S|M|L|XL)-([A-Z]+)$", sku, re.I)
            if match:
                remember("size", match[1])
                remember("color", match[2])

    statements = [
        sentence for sentence in _SENTENCE.split(response_text)
        if not sentence.endswith(("?", "？")) and not _REQUEST.search(sentence)
    ]
    normalized = normalize_asr_transcript(" ".join(statements))
    for key, patterns in _TEXT_SLOT_PATTERNS.items():
        for pattern in patterns:
            for value in re.findall(pattern, normalized, re.I):
                remember(key, value)
    for key, value in stated_price_context(normalized).items():
        remember(key, value)
    for claim in extract_claims([], response_text=" ".join(statements)):
        if claim["field"] == "price_vnd":
            remember("price_quoted_vnd", claim["value"])
        elif claim["field"] == "competitor_price_vnd":
            remember("competitor_price_vnd", claim["value"])
    for match in _CHILDREN.finditer(normalized):
        remember("has_children", not bool(match["no"]))
    for key in ("product_advised", "variant_sku", "order_id", "promo_code", "payment", "address", "blocker"):
        value = prior_facts.get(key)
        if isinstance(value, str) and value:
            token = _comparable_fact(value)
            if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", _comparable_fact(" ".join(statements))):
                remember(key, value)

    used = [
        key for key, value in prior_facts.items()
        if value is not None
        and (stated_this_call or {}).get(key) != value
        and _comparable_fact(value) == _comparable_fact(current.get(key))
        and any(_comparable_fact(candidate) == _comparable_fact(value) for candidate in evidence.get(key, []))
    ]
    if "variant_sku" in used and "product_advised" not in used:
        variant = str(prior_facts["variant_sku"]).upper()
        parent = str(prior_facts.get("product_advised") or variant).upper()
        if parent == str(current.get("product_advised") or variant).upper() and (
            variant == parent or variant.startswith(parent + "-")
        ):
            used.append("product_advised")
    return list(dict.fromkeys([*used, *option_facts_used, *extract_exchange_facts_used(tool_calls, prior_facts)]))
