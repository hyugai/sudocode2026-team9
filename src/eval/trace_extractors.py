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
        text = re.sub(r"^[\s>*#\-\d.)]+", "", match.group(1)).strip()
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
    call_date: str | None = None,
) -> list[dict[str, Any]]:
    """Build verifiable claims from authoritative tool results."""
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any) -> None:
        marker = (field, json.dumps(value, ensure_ascii=False, sort_keys=True))
        if marker not in seen:
            seen.add(marker)
            claims.append({"field": field, "value": value})

    for call in tool_calls:
        name = call.get("name")
        result = call.get("result") or {}
        if not isinstance(result, dict) or result.get("error"):
            continue

        if name == "pricing.get_quote":
            if result.get("final_price_vnd") is not None:
                add("price_vnd", result["final_price_vnd"])
            if result.get("list_price_vnd") is not None:
                add("list_price_vnd", result["list_price_vnd"])
            applied = result.get("applied_promos") or []
            add("promo_active", bool(applied))
            for promo in applied:
                code = promo.get("promo_code") if isinstance(promo, dict) else promo
                if code:
                    add(f"promo_{code}_active", True)
            for promo in result.get("expired_promos") or []:
                code = promo.get("promo_code") if isinstance(promo, dict) else promo
                if code:
                    add(f"promo_{code}_active", False)

        elif name == "inventory.check" and "in_stock" in result:
            add("in_stock", bool(result["in_stock"]))

        elif name == "order.create" and result.get("estimated_delivery") and call_date:
            try:
                delivery_days = (
                    date.fromisoformat(str(result["estimated_delivery"])[:10])
                    - date.fromisoformat(call_date)
                ).days
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
    return used

