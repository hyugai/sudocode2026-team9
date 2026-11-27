"""Normalize callback requests and verified schedule adjustments."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from telesale_agent.application.asr_normalization import (
    _MONTH,
    _NUMBER_PHRASE,
    _small_integer,
    normalize_asr_transcript,
)
from telesale_agent.core.business_time import business_date
from telesale_agent.core.models import TurnContext


_SPEAKER = r"(?:chị|anh|cô|chú|em|tôi|mình|tớ|con)"
_CALLBACK = rf"(?:hẹn lại|hẹn\s+(?:(?:{_SPEAKER}|shop|bên em)\s+)?gọi(?: lại)?|(?:gọi|liên hệ) lại)"
_SELF_CALLBACK = re.compile(
    rf"\b{_SPEAKER}\s+(?:sẽ|tự|để tự)\s+(?:tự\s+)?(?:gọi|liên hệ) lại"
    rf"|\b(?:em|tôi|mình|tớ|con)\s+(?:gọi|liên hệ) lại\s+(?!cho\b){_SPEAKER}(?=\s|[,!.?]|$)"
    r"|\b(?:anh|chị|cô|chú)\s+ơi[, ]+em\s+(?:gọi|liên hệ) lại\b"
    rf"|\b(?:nếu có gì|để)\s+{_SPEAKER}\s+(?:gọi|liên hệ) lại\b"
)
_DECLINES_CALLBACK = re.compile(
    rf"\b(?:không cần|đừng|khỏi|thôi không|hủy)\s+(?:lịch\s+)?{_CALLBACK}\b"
)
_CALLBACK_HISTORY = re.compile(
    rf"\b(?:đã|vừa)(?:\s+tự)?\s+{_CALLBACK}\b"
    r"|\b(?:gọi|liên hệ) lại\s+(?:chuyện|về|theo|như|hôm trước)\b"
)
_DATE = re.compile(
    r"(?<!\w)(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?"
    r"|hôm nay|ngày\s+(?:mai|mốt|kia)|mai(?!\s+ơi\b))\b"
)
_DAY_ONLY = re.compile(rf"\b(?:ngày|mùng|mồng)\s+(?P<day>{_NUMBER_PHRASE})\b(?!\s+tháng\b)")
_QUESTION_AFTER_MONTH = re.compile(rf"(\btháng\s+{_MONTH})\s+(?=không\b(?:\s+ạ)?\s*[?.]?$)")
_RELATIVE_DAYS = {"hôm nay": 0, "mai": 1, "mốt": 2, "kia": 2}
_TIME = re.compile(
    rf"(?<!\w)(?:(?P<digits>\d{{1,2}})\s*(?::\s*(?P<colon_min>\d{{2}})|h"
    rf"(?P<short_min>\d{{2}})?(?!\w))|(?P<hour>{_NUMBER_PHRASE})\s*giờ"
    rf"(?:\s+(?:(?P<minute>{_NUMBER_PHRASE})\s+phút|(?P<half>rưỡi)))?)"
    r"(?:\s*(?P<period>sáng|trưa|chiều|tối))?\b"
)
_POLITE_WORDS = re.compile(
    r"\b(?:dạ|vâng|ừ|lúc|vào|ngày|thì|được|không|ạ|nhé|nha|nhe|giúp|"
    r"cho|chị|anh|em|tôi|mình|là|đi|thôi|nhỉ)\b"
)
_PHONE_REPLY = re.compile(
    r"\s*(?:dạ\s+)?(?:số(?: điện thoại)?(?: của (?:chị|anh|em|tôi))?\s+là\s+)?"
    r"(?P<phone>0\d{9})\s*(?:ạ|nhé)?[.!]?\s*"
)
_WAITING_FOR_CONTACT = re.compile(
    rf"^\s*(?:(?:dạ|vâng)[, ]+)?{_SPEAKER}\s+(?:sẽ\s+)?(?:đợi|chờ)"
    rf"(?:\s+{_SPEAKER})?\s+(?=lúc\b|vào\b|\d|ngày\b|{_NUMBER_PHRASE}\s+giờ\b)"
)
_AMBIGUOUS_WAITING = re.compile(rf"^\s*(?:chờ|đợi)\s+{_SPEAKER}\b")
_MESSAGE_REQUEST = re.compile(r"\b(?:nhắn(?:\s+tin)?|gửi\s+tin\s+nhắn)\s+lại\b")
_CALLBACK_CHANNEL_CONSENT = re.compile(
    rf"\s*(?:dạ(?:\s+được)?|vâng|ừ|được|đồng ý)"
    rf"(?:[, ]+(?:{_SPEAKER}\s+)?(?:sẽ\s+)?đợi\s+{_SPEAKER})?"
    r"(?:\s+(?:ạ|nhé|nha))?[.!]?\s*"
)
_CALLBACK_PROMISE = re.compile(
    rf"\b(?:đã|sẽ|xin phép)\s+[^.!?\n]{{0,50}}(?:{_CALLBACK}|lịch hẹn)\b"
    r"|\bhẹn (?:gặp|liên hệ) lại\b|\b(?:bên em|em)\s+hẹn gọi lại\b"
)
_MESSAGE_PROMISE = re.compile(r"\b(?:đã|sẽ)\s+[^.!?\n]{0,50}(?:nhắn|gửi tin nhắn)\s+lại\b")


def declines_callback(transcript: str | None) -> bool:
    text = (transcript or "").casefold()
    if _DECLINES_CALLBACK.search(text):
        return True
    # Leave the earlier appointment request available when the speaker later
    # clarifies that the agent should call them.
    return bool(_SELF_CALLBACK.search(text) and not re.search(
        rf"\b(?:đợi|chờ)\s+{_SPEAKER}\s+(?:gọi|liên hệ) lại\b"
        rf"|\b{_SPEAKER}\s+(?:có thể|hãy|vui lòng)\s+(?:gọi|liên hệ) lại\b", text
    ))


def is_explicit_callback_request(transcript: str | None) -> bool:
    """Recognize requests directed to the agent and ignore call history."""
    text = (transcript or "").casefold()
    if declines_callback(text):
        return False
    for clause in re.split(r"[.!?;\n]+", text):
        if _SELF_CALLBACK.search(clause):
            continue
        match = re.search(rf"\b{_CALLBACK}\b", clause)
        if _CALLBACK_HISTORY.search(clause):
            continue
        if not match:
            if re.search(r"\bhẹn\b", clause):
                normalized = _normalize_callback_text(clause)
                if _TIME.search(normalized) and (_DATE.search(normalized) or _DAY_ONLY.search(normalized)):
                    return True
            continue
        if match.group().startswith("hẹn"):
            return True
        before, after = clause[:match.start()], clause[match.end():]
        directed = (
            re.search(r"\b(?:em|shop|bên em|hãy|nhờ)\s+(?:ơi,?\s+|hãy\s+)?$", before)
            or re.match(rf"\s+cho\s+{_SPEAKER}\b", after)
            or (re.search(r"\b(?:anh|chị|cô|chú)\s*$", before) and re.match(r"\s+(?:em|con|tôi|mình)\b", after))
            or re.search(rf"\b(?:đợi|chờ)\s+{_SPEAKER}\s*$", before)
            or re.search(r"\b(?:giúp (?:chị|anh|em|tôi|mình)|nhé|nha)\b", after)
        )
        if directed:
            return True
        if not re.search(r"\b(?:chị|anh|tôi|mình)\s*$", before):
            normalized = _normalize_callback_text(clause)
            if _DATE.search(normalized) or _TIME.search(normalized):
                return True
    return False


def _normalize_callback_text(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"\b(ngay|thang)(?=\s+\d)", lambda match: {"ngay": "ngày", "thang": "tháng"}[match[0]], text)
    # Separate the question particle "không" from the spoken month.
    text = _QUESTION_AFTER_MONTH.sub(r"\1, ", text)
    return re.sub(r"(?<=\d)t(?=\d{2}:)", " ", normalize_asr_transcript(text))


def _parse_date(value: str, anchor: date) -> date:
    if "/" in value:
        day, month, *year = map(int, value.split("/"))
        return date(year[0] if year else anchor.year, month, day)
    relative = value.removeprefix("ngày ")
    if relative in _RELATIVE_DAYS:
        return anchor + timedelta(days=_RELATIVE_DAYS[relative])
    return date.fromisoformat(value)


def _parse_time(match: re.Match[str]) -> time:
    hour = _small_integer((match["hour"] or match["digits"]).split())
    minute = _small_integer((match["minute"] or match["colon_min"]
                             or match["short_min"] or ("30" if match["half"] else "0")).split())
    if hour is None or minute is None:
        raise ValueError("Invalid callback time")
    if match["period"] in {"chiều", "tối", "trưa"} and hour < 12:
        hour += 12
    elif match["period"] == "sáng" and hour == 12:
        hour = 0
    return time(hour, minute)


def _callback_slots(context: TurnContext) -> tuple[dict[str, str | None], bool]:
    text = _normalize_callback_text(context.input.text or "")
    dates = list(_DATE.finditer(text))
    # A slash date or ISO date cannot also supply a clock value.
    without_dates = _DATE.sub(" ", text)
    times = list(_TIME.finditer(without_dates))
    anchor = business_date(context.input.metadata.get("call_date"))
    slots: dict[str, str | None] = {}
    for key, matches, parse in (
        ("date", dates, lambda match: _parse_date(match.group(), anchor)),
        ("time", times, _parse_time),
    ):
        if matches:
            try:
                values = {parse(match).isoformat() for match in matches}
                slots[key] = next(iter(values)) if len(values) == 1 else None
            except ValueError:
                slots[key] = None
    if not dates:
        # A day still ahead within this month is unambiguous for short-term
        # callbacks. Ask for the month if the day has already passed.
        days = set()
        for match in _DAY_ONLY.finditer(without_dates):
            words = match["day"].split()
            day = _small_integer(words)
            if day is None and words[-1] == "không" and re.match(r"\s*(?:ạ\s*)?\?", without_dates[match.end():]):
                day = _small_integer(words[:-1])
            days.add(day)
        if days:
            day = days.pop() if len(days) == 1 else None
            try:
                slots["date"] = anchor.replace(day=day).isoformat() if day and day >= anchor.day else None
            except ValueError:
                slots["date"] = None
    remainder = _POLITE_WORDS.sub("", _DAY_ONLY.sub(" ", _TIME.sub(" ", without_dates)))
    bare_reply = bool(slots) and not remainder.strip(" \t,.!?;")
    return slots, bare_reply


def pending_callback_slots(context: TurnContext) -> dict[str, str | None] | None:
    """Collect explicit slots, or merge a short reply to a pending callback."""
    text = (context.input.text or "").casefold()
    proposed = context.state.working_memory.pop("callback_channel_proposal", None)
    if declines_callback(text):
        return None
    pending = context.state.working_memory.get("pending_callback")
    explicit = is_explicit_callback_request(text)
    if proposed and (explicit or _CALLBACK_CHANNEL_CONSENT.fullmatch(text)):
        slots, _ = _callback_slots(context)
        return {**proposed, **slots}
    waiting = _WAITING_FOR_CONTACT.match(text) and not _MESSAGE_REQUEST.search(text)
    if not explicit and not pending and not waiting:
        return None
    slots, bare_reply = _callback_slots(context)
    phone_reply = _PHONE_REPLY.fullmatch(_normalize_callback_text(text)) if pending else None
    timed_waiting = waiting and requested_callback_at(slots)
    if not explicit and not timed_waiting and not (pending and (bare_reply or phone_reply)):
        return None
    if phone_reply:
        slots["phone"] = phone_reply["phone"]
    return {**(pending or {}), **slots}


def propose_callback_for_message_request(context: TurnContext) -> str | None:
    """Offer a phone call at the requested time and wait for channel consent."""
    if not _MESSAGE_REQUEST.search((context.input.text or "").casefold()):
        return None
    slots, _ = _callback_slots(context)
    at = requested_callback_at(slots)
    if not at or datetime.fromisoformat(at).date() < business_date(context.input.metadata.get("call_date")):
        return None
    context.state.working_memory.pop("pending_callback", None)
    context.state.working_memory["callback_channel_proposal"] = slots
    when = datetime.fromisoformat(at).strftime("%H:%M ngày %d/%m/%Y")
    return f"Dạ, bên em có thể hẹn gọi lại vào {when}. Anh/chị đồng ý để bên em gọi vào giờ đó không ạ?"


def _normalize_callback_at(value: Any) -> str | None:
    """Normalize common callback timestamp shapes to an ISO minute string."""
    if not isinstance(value, str) or ":" not in value:
        return None
    raw = value.strip()
    candidates = [raw]
    # Gemini occasionally emits ``HH:MM YYYY-MM-DD`` for a Vietnamese phrase.
    reversed_match = re.fullmatch(
        r"(?P<time>\d{1,2}:\d{2})\s+(?P<date>\d{4}-\d{2}-\d{2})",
        raw,
    )
    if reversed_match:
        candidates.insert(
            0,
            f"{reversed_match.group('date')}T{reversed_match.group('time')}",
        )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace(" ", "T", 1))
        except ValueError:
            continue
        return parsed.isoformat(timespec="minutes")
    return None

def _requested_callback_at(context: TurnContext) -> str | None:
    """Resolve the requested callback time from explicit current-turn evidence."""
    slots, _ = _callback_slots(context)
    return requested_callback_at(slots)


def requested_callback_at(slots: dict[str, str | None]) -> str | None:
    day, clock = slots.get("date"), slots.get("time")
    return f"{day}T{clock[:5]}" if day and clock else None


def verified_callback_at(result: Any) -> str | None:
    if not isinstance(result, dict) or result.get("error"):
        return None
    callback_id = result.get("callback_id")
    if not isinstance(callback_id, str) or not callback_id.strip():
        return None
    return _normalize_callback_at(result.get("callback_at"))

def _callback_adjustment_note(tool_calls: list[dict[str, Any]]) -> str | None:
    """Return an authoritative customer-facing note for a moved callback."""
    for call in reversed(tool_calls):
        if call.get("name") != "schedule.callback":
            continue
        result = call.get("result")
        actual = verified_callback_at(result)
        if not actual:
            continue
        moved_from = _normalize_callback_at(result.get("moved_from"))
        if not moved_from or moved_from == actual:
            return None
        requested_dt = datetime.fromisoformat(moved_from)
        actual_dt = datetime.fromisoformat(actual)
        return (
            "Lưu ý: lịch gọi lại ban đầu vào "
            f"{requested_dt:%H:%M ngày %d/%m/%Y} nằm ngoài lịch làm việc, "
            "nên hệ thống đã chuyển lịch sang "
            f"{actual_dt:%H:%M ngày %d/%m/%Y}."
        )
    return None


def callback_confirmation(result: dict[str, Any], actual: str) -> str:
    if note := _callback_adjustment_note([{"name": "schedule.callback", "result": result}]):
        return note
    return f"Dạ, bên em đã hẹn gọi lại lúc {datetime.fromisoformat(actual):%H:%M ngày %d/%m/%Y} ạ."


def ground_callback_response(context: TurnContext, response: str) -> str:
    """Use the verified tool result or slot question in callback responses."""
    reply = context.state.working_memory.get("callback_reply")
    text = (context.input.text or "").casefold()
    message_requested = _MESSAGE_REQUEST.search(text)
    ambiguous = _AMBIGUOUS_WAITING.match(text) and requested_callback_at(_callback_slots(context)[0])
    if not reply and not message_requested and not ambiguous and not _CALLBACK_PROMISE.search(response.casefold()):
        return response
    sentences = re.split(r"(?<=[.!?])\s+|\n+", response)
    filtered = []
    for sentence in sentences:
        text = sentence.casefold()
        related = re.search(rf"\b(?:{_CALLBACK}|lịch hẹn|khung giờ)\b", text)
        promise = _CALLBACK_PROMISE.search(text) and not sentence.rstrip().endswith("?")
        if promise or (related and reply) or (message_requested and _MESSAGE_PROMISE.search(text)):
            continue
        if reply and re.search(
            r"\b(?:ngày nào|mấy giờ|(?:xin|biết|xác nhận) (?:lại )?số điện thoại)\b",
            text,
        ):
            continue
        if sentence.strip():
            filtered.append(sentence)
    if reply:
        filtered.insert(0, reply)
    elif message_requested:
        filtered.append("Dạ, bên em có thể hẹn gọi lại. Nếu muốn đặt lịch gọi, mình cho em xin ngày và giờ gọi lại ạ.")
    elif ambiguous:
        filtered.append("Dạ, anh/chị muốn bên em gọi lại hay mình sẽ chủ động liên hệ vào giờ đó ạ?")
    elif len(filtered) < sum(bool(s.strip()) for s in sentences) and not declines_callback(context.input.text):
        filtered.append("Dạ, bên em chưa đặt lịch gọi lại ạ.")
    if not filtered:
        return "Dạ, khi nào cần hỗ trợ thêm, anh/chị cứ liên hệ bên em ạ."
    return " ".join(filtered)

