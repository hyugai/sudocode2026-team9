"""Identify questions about one physical unit that the catalog cannot verify."""

from __future__ import annotations

import re


_UNIT_DETAIL = re.compile(
    r"mã\s*(?:sê[\s-]*ri|serial|biên\s+bản\s+kiểm\s+tra|ca\s+sản\s+xuất)|"
    r"số\s+lô|ngày\s+(?:xuất\s+xưởng|sản\s+xuất)|"
    r"(?:tên\s+)?kỹ\s+thuật\s+viên|nhiệt\s+độ\s+đo\s+được|"
    r"ngày\s+kiểm\s+tra\s+điện|độ\s+ẩm\s+tại\s+kho|"
    r"(?:số\s+phút|thời\s+gian)\s+chạy\s+thử",
    re.IGNORECASE,
)
_SPECIFIC_UNIT = re.compile(
    r"\b(?:chiếc|cái|máy|trong\s+kho|sẽ\s+giao|đúng\s+chiếc|"
    r"của\s+tôi|đang\s+nằm\s+trong\s+kho)\b",
    re.IGNORECASE,
)
_FOLLOWUP = re.compile(
    r"câu\s+hỏi.{0,55}(?:lần\s+trước|hôm\s+trước|còn\s+lưu)|"
    r"nhắc\s+lại\s+câu\s+hỏi|nguồn\s+xác\s+nhận|"
    r"(?:hồ\s+sơ|hệ\s+thống)\s+(?:không|chưa)\s+có|"
    r"nếu\s+chưa\s+có\s+thông\s+tin",
    re.IGNORECASE,
)


def unit_specific_question(
    transcript: str | None,
    *,
    model_detected: bool = False,
    model_excerpt: str | None = None,
) -> str | None:
    """Return an exact customer span, using semantic detection or regex fallback.

    The model only classifies the question. Its wording is never stored unless
    it appears verbatim in the customer transcript.
    """
    text = (transcript or "").strip()
    rule_match = bool(_UNIT_DETAIL.search(text) and _SPECIFIC_UNIT.search(text))
    if not text or not (model_detected or rule_match):
        return None
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    excerpt = (model_excerpt or "").strip()
    if excerpt:
        for sentence in sentences:
            if excerpt.casefold() in sentence.casefold():
                return " ".join(sentence.split())[:300]
    if rule_match:
        for sentence in sentences:
            if _UNIT_DETAIL.search(sentence):
                return " ".join(sentence.split())[:300]
    for sentence in reversed(sentences):
        if "?" in sentence:
            return " ".join(sentence.split())[:300]
    return " ".join(text.split())[:300]


def asks_about_unresolved_question(transcript: str | None) -> bool:
    return bool(_FOLLOWUP.search(transcript or ""))
