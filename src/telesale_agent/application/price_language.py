"""Extract Vietnamese money amounts and distinguish customer price references."""

from __future__ import annotations

import re
from decimal import Decimal

from telesale_agent.application.asr_normalization import normalize_asr_transcript


AMOUNT = r"\d+(?:[.,]\d+|\s\d{3}(?!\d))*"
MONEY_UNIT = r"(?:triệu|nghìn|ngàn|tr|k|đồng|vnd|vnđ|₫|đ)(?!\w)"
_VALUE = rf"(?P<amount>{AMOUNT})(?!\d|[.,]\d)(?:\s*(?P<unit>{MONEY_UNIT}))?"
_BUDGET = re.compile(
    rf"\b(?:(?:ngân\s+sách|ngan\s+sach)(?:\s+(?:tổng|của|anh|chị|em|tôi|mình|là|khoảng|tầm|"
    rf"dưới|tối|đa|chỉ|có|lên|thành|nâng|tăng|giảm|xuống|còn|đổi|sang)){{0,7}}"
    rf"|(?:em|anh|chị|tôi|mình)\s+chỉ\s+có|tầm|tam)\s+{_VALUE}",
    re.I,
)
_BUDGET_LIMIT = re.compile(rf"\b{_VALUE}\s+đổ\s+lại\b", re.I)
COMPETITOR = r"\b(?:bên\s+(?:họ|kia|khác|đối\s+thủ)|nơi\s+khác|đối\s+thủ)\b"
_COMPETITOR_PRICE = re.compile(
    rf"{COMPETITOR}(?:\s+rồi)?(?:\s+ạ)?(?:[\s,:]*|\.\s+(?=họ\b))"
    rf"(?:\s*(?:họ|báo|bán|cũng|có|giá|là|chỉ|được|cho|còn)\b\s*){{0,7}}{_VALUE}",
    re.I,
)


def money_value(amount: str) -> int | None:
    """Read a money token with the same Vietnamese ITN as ASR."""
    compact = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", normalize_asr_transcript(amount))
    match = re.fullmatch(rf"(\d+(?:[.,]\d+)*)\s*({MONEY_UNIT})?", compact)
    if not match:
        return None
    number, unit = match.groups()
    if unit in {"triệu", "tr", "nghìn", "ngàn", "k"}:
        decimal = number.replace(",", ".")
        if decimal.count(".") > 1:
            return None
        return int(Decimal(decimal) * (1_000_000 if unit in {"triệu", "tr"} else 1000))
    return int(re.sub(r"[.,]", "", number))


def stated_price_context(text: str) -> dict[str, int]:
    """Get amounts the speaker actually attributes to a budget or competitor."""
    normalized = normalize_asr_transcript(text)
    facts: dict[str, tuple[int, int]] = {}
    for field, pattern in (
        ("budget_vnd", _BUDGET),
        ("budget_vnd", _BUDGET_LIMIT),
        ("competitor_price_vnd", _COMPETITOR_PRICE),
    ):
        for match in pattern.finditer(normalized):
            if re.match(r"\s*(?:%|phần trăm|đôi\b|ngày\b|tháng\b)", normalized[match.end():]):
                continue
            amount = money_value(f"{match['amount']} {match['unit'] or ''}")
            start = match.start("amount")
            if amount is not None and (match["unit"] or amount >= 1_000) and start > facts.get(field, (-1, 0))[0]:
                facts[field] = start, amount
    return {field: value for field, (_, value) in facts.items()}
