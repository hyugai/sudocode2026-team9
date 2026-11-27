from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any

from telesale_agent.application.asr_normalization import normalize_asr_transcript


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
_AMOUNT = r"\d+(?:[.,]\d+|\s\d{3}(?!\d))*"
_PRICE = re.compile(
    rf"(?P<label>\bgiá(?:\s+niêm\s+yết)?|\btổng(?:\s+(?:tiền|cộng|đơn(?:\s+hàng)?))?|\bcòn)"
    rf"\s*(?:(?:bán|hiện tại|hôm nay|chính xác|là|chỉ|vẫn|còn|giữ nguyên|:)\s*)*"
    rf"[*\s]*(?P<amount>{_AMOUNT})(?!\d)(?:\s*(?P<unit>triệu|nghìn|ngàn|tr|k|đồng|vnd|₫|đ))?",
    re.I,
)
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


def money_value(amount: str) -> int | None:
    """Read a stated amount using the same Vietnamese ITN as ASR."""
    compact = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", normalize_asr_transcript(amount))
    match = re.fullmatch(r"(\d+(?:[.,]\d+)*)\s*(triệu|tr|nghìn|ngàn|k|đồng|vnd|₫|đ)?", compact)
    if not match:
        return None
    number, unit = match.groups()
    if unit in {"triệu", "tr", "nghìn", "ngàn", "k"}:
        decimal = number.replace(",", ".")
        if decimal.count(".") > 1:
            return None
        return int(Decimal(decimal) * (1_000_000 if unit in {"triệu", "tr"} else 1000))
    return int(re.sub(r"[.,]", "", number))


def extract_claims(
    tool_calls: list[dict[str, Any]],
    *,
    response_text: str,
    call_date: str | None = None,
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
    }
    for sentence in _SENTENCE.split(response_text):
        if sentence.rstrip().endswith(("?", "？")):
            continue
        normalized = normalize_asr_transcript(sentence)
        previous_end = 0
        for match in _PRICE.finditer(normalized):
            label = match["label"]
            unit = match["unit"] or ""
            value = money_value(f"{match['amount']} {unit}")
            prefix = normalized[previous_end:match.start()]
            previous_end = match.end()
            if value is None or (label == "còn" and not unit and value < 1000):
                continue
            if not _asserted_policy(normalized, match):
                continue
            field = "list_price_vnd" if "niêm" in label else "price_vnd"
            if label.startswith("tổng"):
                add("total_vnd", value, sentence)
                continue
            add(field, value, sentence)
            mentioned = {sku.upper() for sku in _SKU.findall(prefix)}
            candidates = mentioned or (quote_skus if len(quote_skus) == 1 else set())
            if len(candidates) == 1:
                add(f"{field}_{next(iter(candidates))}", value, sentence)
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
    "qty": ("quantity",),
}
_TEXT_SLOT_PATTERNS = {
    "room_area_m2": (rf"({_AMOUNT})\s*(?:m[²2]|mét vuông)",),
    "budget_vnd": (rf"ngân sách(?:\s+(?:là|khoảng|tầm))?\s+({_AMOUNT})",),
    "size": (r"\b(?:size|cỡ)\s+(\d+|s|m|l|xl)\b",),
    "color": (r"\bmàu\s+(đen|trắng|xanh|đỏ|be|hồng|nâu|xám|vàng|tím)\b",),
    "quantity": (r"\b(\d+)\s+(?:máy|chiếc|cái|bộ|đôi)\b",),
}
_CHILDREN = re.compile(r"\b(?:(?P<no>không\s+có|chưa\s+có)|có)\s+(?:trẻ nhỏ|trẻ em|em bé|bé nhỏ|bé)\b", re.I)


def _comparable_fact(value: Any) -> str:
    folded = unicodedata.normalize("NFD", str(value).casefold().strip())
    return "".join(c for c in folded if not unicodedata.combining(c)).replace("đ", "d")


def extract_facts_used(
    response_text: str,
    tool_calls: list[dict[str, Any]],
    prior_facts: dict[str, Any],
    *,
    current_brief: Any = None,
) -> list[str]:
    """Match values from prior-call writes against the brief and visible evidence."""
    if not prior_facts:
        return []
    current = getattr(current_brief, "remembered_preferences", {}).get("facts", {}) if current_brief else prior_facts
    evidence: dict[str, list[Any]] = {}

    def remember(key: str, value: Any) -> None:
        if key in prior_facts:
            evidence.setdefault(key, []).append(value)

    for call in tool_calls:
        args = call.get("args") or {}
        if not isinstance(args, dict):
            continue
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
                remember(key, money_value(value) if key == "budget_vnd" else value)
    for claim in extract_claims([], response_text=" ".join(statements)):
        if claim["field"] == "price_vnd":
            remember("price_quoted_vnd", claim["value"])
    for match in _CHILDREN.finditer(normalized):
        remember("has_children", not bool(match["no"]))
    for key in ("product_advised", "variant_sku", "order_id", "promo_code", "payment", "address", "blocker"):
        value = prior_facts.get(key)
        if isinstance(value, str) and value:
            token = _comparable_fact(value)
            if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", _comparable_fact(" ".join(statements))):
                remember(key, value)

    return [
        key for key, value in prior_facts.items()
        if value is not None
        and _comparable_fact(value) == _comparable_fact(current.get(key))
        and any(_comparable_fact(candidate) == _comparable_fact(value) for candidate in evidence.get(key, []))
    ]
