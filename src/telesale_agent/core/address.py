"""Conservative address evidence for order creation and memory writes."""

from __future__ import annotations

import re


_PAYMENT_ONLY = re.compile(
    r"\b(?:tổng|giá|ngân\s+sách|triệu|nghìn|ngàn|đồng|vnd|chuyển\s+khoản|cod)\b",
    re.IGNORECASE,
)
_HOUSE_NUMBER = r"(?:số\s+)?[a-z]?\d{1,5}[a-z]?(?:[/\-]\d{1,5}[a-z]?)*"
_ADDRESS_NUMBER = re.compile(
    rf"^{_HOUSE_NUMBER}\s+"
    r"(?!triệu\b|nghìn\b|ngàn\b|đồng\b|vnd\b|ngày\b|giờ\b|phút\b|"
    r"sản\s+phẩm\b|chiếc\b|đôi\b|km\b)"
    r"[^.!?\r\n]{3,100}",
    re.IGNORECASE,
)
_ADDRESS_CUE = re.compile(
    r"\b(?:đường|phố|ngõ|hẻm|ấp|thôn|xã|phường|quận|huyện|"
    r"hà\s+nội|đà\s+nẵng|hồ\s+chí\s+minh|hcm|cần\s+thơ)\b",
    re.IGNORECASE,
)
_ADMIN_ADDRESS = re.compile(
    r"^(?:khu\s+vực|khu\s+phố|tổ(?:\s+dân\s+phố)?|khối|ấp|thôn|xóm|bản|buôn|khóm|"
    r"phường|xã|thị\s+trấn)\s+[^,!?]+,\s*"
    r"(?:phường|xã|quận|huyện|thị\s+xã|tỉnh|thành\s+phố|tp\.?|"
    r"hà\s+nội|đà\s+nẵng|hồ\s+chí\s+minh|hcm|cần\s+thơ)\b",
    re.IGNORECASE,
)
_NAMED_ROAD = re.compile(r"^(?:đường|phố|ngõ|hẻm)\s+[^,!?]{2,100},", re.IGNORECASE)


def looks_like_delivery_address(value: str) -> bool:
    """Reject money/payment sentences even if they contain digits."""
    text = value.strip()
    if len(text) < 8:
        return False
    if _ADMIN_ADDRESS.search(text) and not _PAYMENT_ONLY.search(text):
        return True
    if _NAMED_ROAD.search(text) and _ADDRESS_CUE.search(text.split(",", 1)[1]):
        return not _PAYMENT_ONLY.search(text)
    if not _ADDRESS_NUMBER.search(text):
        return False
    if _ADDRESS_CUE.search(text):
        return True
    # Bare street-name replies such as "12 Nguyễn Trãi" may lack a road cue.
    return not _PAYMENT_ONLY.search(text) and bool(
        re.match(rf"^{_HOUSE_NUMBER}\s+[A-ZÀ-Ỹ][^,.!?]{{3,60}}$", text)
    )


def extract_explicit_delivery_address(customer_text: str) -> str | None:
    """Extract a stated address without truncating `TP. Hồ Chí Minh`."""
    match = re.search(
        r"(?:địa\s*chỉ(?:\s+(?:giao|nhận)\s+hàng)?\s*(?:là|:)?|"
        r"(?:giờ\s+)?giao(?:\s+hàng)?(?:\s+tận\s+nơi)?(?:\s+(?:đến|về|qua|tới|ở))?"
        r"(?:\s+cho\s+(?:anh|chị|em|tôi))?)\s+"
        r"(?P<address>[^!?\r\n]+?)"
        r"(?=\s*(?:,?\s*(?:(?:(?:anh|chị|em|tôi|mình)\s+(?:sẽ\s+)?)?thanh\s+toán|cod\b|chuyển\s+khoản|"
        r"tiền\s+mặt|hôm\s+nay|đúng\s+không|được\s+không|phải\s+không|nhé|nha)|[!?]|"
        r"\.\s+(?!(?:hồ|chí|minh|hcm))\b|$))",
        customer_text,
        flags=re.IGNORECASE,
    )
    address = match.group("address").strip(" .,") if match else None
    return address if address and looks_like_delivery_address(address) else None
