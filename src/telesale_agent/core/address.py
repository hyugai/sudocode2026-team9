"""Conservative address evidence for order creation and memory writes."""

from __future__ import annotations

import re


_PAYMENT_ONLY = re.compile(
    r"\b(?:tổng|giá|ngân\s+sách|triệu|nghìn|ngàn|đồng|vnd|chuyển\s+khoản|cod)\b",
    re.IGNORECASE,
)
_ADDRESS_NUMBER = re.compile(
    r"\b(?:số\s+)?\d{1,5}(?:[/\-]\d{1,5})?\s+"
    r"(?!triệu\b|nghìn\b|ngàn\b|đồng\b|vnd\b|sản\s+phẩm\b)"
    r"[^.!?\r\n]{3,100}",
    re.IGNORECASE,
)
_ADDRESS_CUE = re.compile(
    r"\b(?:đường|phố|ngõ|hẻm|ấp|thôn|xã|phường|quận|huyện|"
    r"hà\s+nội|đà\s+nẵng|hồ\s+chí\s+minh|tp\.?\s*hcm)\b",
    re.IGNORECASE,
)


def looks_like_delivery_address(value: str) -> bool:
    """Reject money/payment sentences even if they contain digits."""
    text = value.strip()
    if len(text) < 8 or not _ADDRESS_NUMBER.search(text):
        return False
    if _ADDRESS_CUE.search(text):
        return True
    # Bare street-name replies such as "12 Nguyễn Trãi" may lack a road cue.
    return not _PAYMENT_ONLY.search(text) and bool(
        re.match(r"^(?:số\s+)?\d{1,5}\s+[A-ZÀ-Ỹ][^,.!?]{3,60}$", text)
    )


def extract_explicit_delivery_address(customer_text: str) -> str | None:
    """Extract a stated address without truncating `TP. Hồ Chí Minh`."""
    match = re.search(
        r"(?:địa\s*chỉ(?:\s+(?:giao|nhận)\s+hàng)?\s*(?:là|:)?|"
        r"(?:giờ\s+)?giao(?:\s+(?:đến|về|qua|tới))?"
        r"(?:\s+cho\s+(?:anh|chị|em|tôi))?)\s+"
        r"(?P<address>(?:số\s+)?\d+[^!?\r\n]+?)"
        r"(?=\s*(?:,?\s*(?:thanh\s+toán|cod\b|chuyển\s+khoản|"
        r"tiền\s+mặt|hôm\s+nay|nhé|nha)|[!?]|"
        r"\.\s+(?!(?:hồ|chí|minh|hcm))\b|$))",
        customer_text,
        flags=re.IGNORECASE,
    )
    address = match.group("address").strip(" .,") if match else None
    return address if address and looks_like_delivery_address(address) else None
