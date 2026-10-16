"""Small shared guard for policy questions explicitly deferred to a later call."""

from __future__ import annotations

import re


_FUTURE_QUESTION = re.compile(
    r"(?:khi\s+(?:quay|trở)\s+lại|lần\s+sau|sau\s+này|lúc\s+khác)"
    r"[^.!?]{0,100}\b(?:sẽ\s+)?(?:hỏi|tìm\s+hiểu|nhờ\s+tư\s+vấn)"
    r"(?:\s+thêm)?\s+(?P<topic>[^.!?]+)",
    re.IGNORECASE,
)
_POLICY_TOPICS = (
    (re.compile(r"điều\s+kiện\s+đổi\s+size|đổi\s+size", re.I), "điều kiện đổi size"),
    (re.compile(r"điều\s+kiện\s+đổi\s+trả|đổi\s+trả", re.I), "chính sách đổi trả"),
    (re.compile(r"bảo\s+hành", re.I), "chính sách bảo hành"),
    (re.compile(r"vận\s+chuyển|phí\s+ship|phí\s+giao", re.I), "chính sách giao hàng"),
    (re.compile(r"khuyến\s+mãi|voucher", re.I), "điều kiện khuyến mãi"),
)


def deferred_policy_topic(transcript: str | None) -> str | None:
    """Return a safe canonical topic only for a future, not current, request."""
    text = transcript or ""
    if "?" in text or re.search(
        r"\b(?:cho\s+(?:anh|chị|em|tôi|mình)\s+biết|giải\s+thích|"
        r"thế\s+nào|ra\s+sao|bao\s+nhiêu)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    match = _FUTURE_QUESTION.search(text)
    if not match:
        return None
    topic = match.group("topic")
    for pattern, canonical in _POLICY_TOPICS:
        if pattern.search(topic):
            return canonical
    return None
