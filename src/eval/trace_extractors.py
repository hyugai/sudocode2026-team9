from __future__ import annotations

import dataclasses
import json
import re
from datetime import date
from typing import Any


_SLOT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("room_area_m2", re.compile(r"diện tích|m[²2]|mét vuông", re.I)),
    ("budget_vnd", re.compile(r"ngân sách|tầm bao nhiêu|khoảng bao nhiêu tiền", re.I)),
    ("has_children", re.compile(r"trẻ nhỏ|trẻ em|em bé|bé nhỏ|có bé", re.I)),
    ("product_advised", re.compile(r"sản phẩm|mẫu nào|máy nào|sku", re.I)),
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
    r"đúng không|phải không|có đúng|vẫn .* (?:chứ|đúng)|xác nhận|(?:anh|chị) đồng ý",
    re.I,
)


def extract_questions(response_text: str) -> list[dict[str, str]]:
    """Extract BTC question records from the final agent response."""
    questions = []
    for match in re.finditer(r"([^?？\n]{2,}[?？])", response_text or ""):
        # A preceding statement is not part of the question's slot evidence.
        text = re.split(r"(?<=[.!;])\s+", match.group(1))[-1]
        text = re.sub(r"^[\s>*#\-\d.)]+", "", text).strip()
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
) -> list[dict[str, Any]]:
    """Extract spoken claims; a price need not agree with a tool to be scored.

    This remains a heuristic extractor. It does not evaluate all free text.
    """
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    response_folded = response_text.casefold()
    response_compact = re.sub(r"[\s.,]", "", response_folded)

    def spoken_number(value: Any) -> bool:
        return str(value).split(".")[0] in response_compact

    def spoken_phrase(*patterns: str) -> bool:
        return any(re.search(pattern, response_folded, re.I) for pattern in patterns)

    def add(field: str, value: Any) -> None:
        marker = (field, json.dumps(value, ensure_ascii=False, sort_keys=True))
        if marker not in seen:
            seen.add(marker)
            claims.append({"field": field, "value": value})

    price_pattern = re.compile(
        r"\bgiá\s*(?:(?:bán|hiện\s*tại|hôm\s*nay|niêm\s*yết|là|chỉ|còn|vẫn|:|của\s+máy)\s*)*"
        r"(?P<number>\d[\d.,]*(?:\s\d{3})*)(?:\s*(?P<unit>triệu|nghìn|ngàn|tr|k|đồng|vnd|₫|đ))?",
        re.I,
    )
    for match in price_pattern.finditer(response_text):
        number = re.sub(r"\s", "", match["number"]).rstrip(".,")
        unit = (match["unit"] or "").casefold()
        if unit in {"triệu","tr","nghìn","ngàn","k"}:
            value = float(number.replace(",",".")) * (1_000_000 if unit in {"triệu","tr"} else 1000)
        else:
            value = float(re.sub(r"[.,]", "", number))
        add("list_price_vnd" if "niêm" in match[0].casefold() else "price_vnd", int(value))

    for call in tool_calls:
        name = call.get("name")
        result = call.get("result") or {}
        if not isinstance(result, dict) or result.get("error"):
            continue

        if name == "pricing.get_quote":
            if result.get("final_price_vnd") is not None and spoken_number(
                result["final_price_vnd"]
            ):
                add("price_vnd", result["final_price_vnd"])
            if result.get("list_price_vnd") is not None and spoken_number(
                result["list_price_vnd"]
            ):
                add("list_price_vnd", result["list_price_vnd"])
            applied = result.get("applied_promos") or []
            if spoken_phrase(r"khuyến\s*mãi", r"ưu\s*đãi", r"mã\s*giảm", r"promo"):
                add("promo_active", bool(applied))
            for promo in applied:
                code = promo.get("promo_code") if isinstance(promo, dict) else promo
                if code and str(code).casefold() in response_folded:
                    add(f"promo_{code}_active", True)
            for promo in result.get("expired_promos") or []:
                code = promo.get("promo_code") if isinstance(promo, dict) else promo
                if code and str(code).casefold() in response_folded:
                    add(f"promo_{code}_active", False)

        elif name == "inventory.check" and "in_stock" in result:
            if result["in_stock"] and spoken_phrase(
                r"còn\s*hàng", r"có\s*sẵn", r"sẵn\s*hàng"
            ):
                add("in_stock", True)
            elif not result["in_stock"] and spoken_phrase(
                r"hết\s*hàng", r"chưa\s*có\s*hàng"
            ):
                add("in_stock", False)

        elif name == "order.create" and result.get("estimated_delivery") and call_date:
            try:
                delivery_days = (
                    date.fromisoformat(str(result["estimated_delivery"])[:10])
                    - date.fromisoformat(call_date)
                ).days
                if spoken_phrase(
                    rf"\b{delivery_days}\s*ngày\b",
                    re.escape(str(result["estimated_delivery"])[:10]),
                ):
                    add("delivery_days", delivery_days)
            except ValueError:
                pass

    return claims


_FACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "room_area_m2": re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:m[²2]|mét vuông)", re.I),
    "budget_vnd": re.compile(r"ngân sách|\b\d+(?:[.,]\d+)?\s*(?:triệu|tr|k)\b", re.I),
    "has_children": re.compile(r"trẻ nhỏ|trẻ em|em bé|bé nhỏ|có bé", re.I),
    "product_advised": re.compile(r"\bSKU-[A-Z0-9-]+\b|airpure|sản phẩm đã tư vấn", re.I),
    "price_quoted_vnd": re.compile(r"\b\d{1,3}(?:[. ]\d{3})+(?:\s*₫)?|giá (?:vẫn|đã báo)", re.I),
    "promo_code": re.compile(r"khuyến mãi|mã (?:giảm|ưu đãi)|promo", re.I),
    "blocker": re.compile(
        r"(?:hỏi|đồng ý).*(?:chồng|vợ|ông xã|bà xã|người nhà)"
        r"|(?:chồng|vợ|ông xã|bà xã|người nhà).*(?:hỏi|đồng ý)"
        r"|băn khoăn|chưa chốt",
        re.I,
    ),
    "competitor_price_vnd": re.compile(r"đối thủ|bên khác|nơi khác", re.I),
    "variant_sku": re.compile(r"\bSKU-[A-Z0-9-]+\b", re.I),
    "size": re.compile(r"\bsize\s*(?:\d+|s|m|l|xl)\b", re.I),
    "color": re.compile(r"màu\s+[\w-]+", re.I),
    "order_id": re.compile(r"\b(?:ORD-|OD)\w+\b", re.I),
    "payment": re.compile(r"\bCOD\b|chuyển khoản|thanh toán", re.I),
}


def extract_facts_used(
    response_text: str,
    tool_calls: list[dict[str, Any]],
    call_brief: Any,
) -> list[str]:
    """Return canonical memory slots visibly used in response/tool arguments."""
    args_blob = json.dumps(
        [call.get("args", {}) for call in tool_calls], ensure_ascii=False
    )
    evidence = f"{response_text}\n{args_blob}"

    if dataclasses.is_dataclass(call_brief):
        brief_blob = json.dumps(dataclasses.asdict(call_brief), ensure_ascii=False)
    elif isinstance(call_brief, dict):
        brief_blob = json.dumps(call_brief, ensure_ascii=False)
    else:
        brief_blob = ""

    used = []
    for key, pattern in _FACT_PATTERNS.items():
        if key in brief_blob and pattern.search(evidence):
            used.append(key)

    # Tool arguments are stronger evidence than surface wording. Map their
    # runtime schema back to the canonical memory schema used by scenarios.
    # This also captures size/color carried inside a canonical variant SKU.
    argument_keys: set[str] = set()
    variant_values: list[str] = []
    for call in tool_calls:
        args = call.get("args", {})
        if not isinstance(args, dict):
            continue
        if args.get("order_id"):
            argument_keys.add("order_id")
        if args.get("payment") or args.get("payment_method"):
            argument_keys.add("payment")
        if args.get("price_vnd") is not None:
            argument_keys.add("price_quoted_vnd")
        for field in ("sku", "new_variant_sku"):
            value = args.get(field)
            if isinstance(value, str) and value:
                variant_values.append(value)

    if variant_values:
        argument_keys.update({"product_advised", "variant_sku"})
        if any(re.search(r"-(?:\d+|S|M|L|XL)-[A-Z]+$", sku, re.I) for sku in variant_values):
            argument_keys.update({"size", "color"})

    for key in _FACT_PATTERNS:
        if key in argument_keys and key in brief_blob and key not in used:
            used.append(key)
    return used

