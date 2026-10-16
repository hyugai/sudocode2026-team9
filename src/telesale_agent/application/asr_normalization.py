"""Deterministic Vietnamese inverse text normalization for ASR transcripts.

Runs locally without an LLM. Money follows Vietnamese retail shorthand:
"bốn triệu tám trăm chín mươi" means 4.890.000, not 4.000.890.
Unqualified counts, relative dates, and unrecognized phrases remain unchanged.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


_DIGITS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3,
    "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "sáu": 6,
    "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
_SCALES = {
    "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
    "triệu": 1_000_000, "tr": 1_000_000,
    "nghìn": 1_000, "ngàn": 1_000, "k": 1_000,
}
_CURRENCY = {"đồng", "vnd", "đ"}
_NUMBER_WORDS = set(_DIGITS) | {"mười", "mươi", "trăm", "linh", "lẻ"}
_NUMERIC = r"\d+(?:[.,]\d+)*"


def _alternatives(words) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=lambda word: (-len(word), word)))


_NUMBER_TOKEN = rf"(?:{_NUMERIC}|(?:{_alternatives(_NUMBER_WORDS | set(_SCALES))})(?!\w))"
_NUMBER_PHRASE = rf"{_NUMBER_TOKEN}(?:\s+{_NUMBER_TOKEN})*"
_MONTH = r"(?:mười\s+(?:một|hai)|mười|một|hai|ba|bốn|tư|năm|sáu|bảy|bẩy|tám|chín|giêng|chạp|1[0-2]|0?[1-9])"
_DATE = re.compile(
    rf"(?<!\w)(?:ngày|mùng|mồng)\s+(?P<day>{_NUMBER_PHRASE})"
    rf"\s+tháng\s+(?P<month>{_MONTH})(?!\w)"
    rf"(?:\s+năm\s+(?P<year>{_NUMBER_PHRASE}))?(?!\w)"
)
_PHONE_TOKEN = rf"(?:\d+|(?:{_alternatives(_DIGITS)})(?!\w))"
_PHONE = re.compile(rf"(?<!\w)(?:\+\s*|cộng\s+)?{_PHONE_TOKEN}(?:(?:\s+|,\s*|[.-](?=\d)){_PHONE_TOKEN})*(?!\w)")
_MONEY_WORDS = _NUMBER_WORDS | set(_SCALES) | _CURRENCY | {"phẩy", "chấm", "rưỡi"}
_MONEY_TOKEN = rf"(?:{_NUMERIC}|(?:{_alternatives(_MONEY_WORDS)})(?!\w))"
_MONEY = re.compile(
    rf"(?<!\w){_MONEY_TOKEN}(?:(?:\s+|(?<=\d)(?=[a-zđ])){_MONEY_TOKEN})*(?!\w)"
)
_LEXER = re.compile(rf"{_NUMERIC}|[^\W\d_]+")


def _numeric_value(token: str) -> Decimal | None:
    try:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
            return Decimal(token.replace(".", ""))
        if re.fullmatch(_NUMERIC, token):
            return Decimal(token.replace(",", "."))
    except InvalidOperation:
        pass
    return None


def _digit(token: str) -> int | None:
    if token in _DIGITS:
        return _DIGITS[token]
    return int(token) if re.fullmatch(r"\d", token) else None


def _small_integer(tokens: list[str]) -> int | None:
    if not tokens:
        return None
    if len(tokens) == 1:
        numeric = _numeric_value(tokens[0])
        if numeric is not None:
            return int(numeric) if numeric == int(numeric) else None
    digits = [_digit(token) for token in tokens]
    if all(digit is not None for digit in digits):
        return int("".join(str(digit) for digit in digits))

    hundreds = 0
    if "trăm" in tokens:
        index = tokens.index("trăm")
        if index != 1 or _digit(tokens[0]) is None:
            return None
        hundreds = _digit(tokens[0]) * 100
        tokens = tokens[2:]
        if not tokens:
            return hundreds
    if tokens and tokens[0] in {"linh", "lẻ"}:
        tokens = tokens[1:]
    if not tokens:
        return None
    if tokens[0] == "mười":
        tens, rest = 10, tokens[1:]
    elif len(tokens) >= 2 and tokens[1] == "mươi" and _digit(tokens[0]) not in {None, 0, 1}:
        tens, rest = _digit(tokens[0]) * 10, tokens[2:]
    else:
        digits = [_digit(token) for token in tokens]
        if len(digits) <= 2 and all(digit is not None for digit in digits):
            return hundreds + int("".join(str(digit) for digit in digits))
        return None
    if not rest:
        return hundreds + tens
    if len(rest) == 1 and _digit(rest[0]) is not None:
        return hundreds + tens + _digit(rest[0])
    return None


def _integer(tokens: list[str]) -> int | None:
    """Parse literal integers, used for dates (no money shorthand)."""
    total, start, previous_scale = 0, 0, 10**12
    for index, token in enumerate(tokens):
        if token not in _SCALES:
            continue
        scale = _SCALES[token]
        group = _small_integer(tokens[start:index])
        if group is None or scale >= previous_scale:
            return None
        total += group * scale
        previous_scale, start = scale, index + 1
    if start == len(tokens):
        return total
    remainder = _small_integer(tokens[start:])
    return total + remainder if remainder is not None else None


def _normalize_date(match: re.Match) -> str:
    # Do not accept a valid prefix of an invalid month such as "tháng mười ba".
    if re.match(rf"\s+{_NUMBER_TOKEN}", match.string[match.end():]):
        return match[0]
    day = _integer(match["day"].split())
    month = {"giêng": 1, "chạp": 12}.get(match["month"])
    if month is None:
        month = _integer(match["month"].split())
    year = _integer(match["year"].split()) if match["year"] else None
    if match["year"] and (year is None or not 1000 <= year <= 9999):
        return match[0]
    try:
        date(year if year is not None else 2000, month, day)
    except (TypeError, ValueError):
        return match[0]
    return f"{day:02d}/{month:02d}" + (f"/{year:04d}" if year is not None else "")


def _normalize_phone(match: re.Match) -> str:
    tokens = re.findall(r"\d+|[^\W\d_]+", match[0])
    international = match[0].startswith(("+", "cộng "))
    if tokens and tokens[0] == "cộng":
        tokens = tokens[1:]
    digits = "".join(str(_DIGITS[token]) if token in _DIGITS else token for token in tokens)
    if international and len(digits) == 11 and digits.startswith("84"):
        return "0" + digits[2:]
    # Keep leading zero; do not turn short counts or arbitrary digit sequences into phones.
    return digits if len(digits) == 10 and digits.startswith("0") else match[0]


def _decimal_group(tokens: list[str]) -> Decimal | None:
    if len(tokens) >= 2 and tokens[-1] == "rưỡi":
        whole = _small_integer(tokens[:-1])
        if whole is not None:
            return Decimal(whole) + (Decimal(50) if tokens[-2] == "trăm" else Decimal("0.5"))
    if len(tokens) == 1:
        numeric = _numeric_value(tokens[0])
        if numeric is not None:
            return numeric
    for marker in ("phẩy", "chấm"):
        if marker in tokens:
            index = tokens.index(marker)
            whole = _small_integer(tokens[:index])
            digits = [_digit(token) for token in tokens[index + 1:]]
            if whole is None or not digits or any(digit is None for digit in digits):
                return None
            return Decimal(f"{whole}." + "".join(str(digit) for digit in digits))
    whole = _small_integer(tokens)
    return Decimal(whole) if whole is not None else None


def _money_amount(tokens: list[str]) -> int | None:
    total, start, last_scale = Decimal(0), 0, None
    for index, token in enumerate(tokens):
        if token not in _SCALES:
            continue
        scale = _SCALES[token]
        group = _decimal_group(tokens[start:index])
        if group is None or (last_scale is not None and scale >= last_scale):
            return None
        total += group * scale
        last_scale, start = scale, index + 1
    tail = tokens[start:]
    if tail == ["rưỡi"] and last_scale is not None:
        total += Decimal(last_scale) / 2
    elif tail:
        group = _decimal_group(tail)
        if group is None or (last_scale is not None and group != int(group)):
            return None
        # Retail shorthand: 4 triệu 890 -> 4.890.000; 4 triệu 8 -> 4.800.000.
        explicit_units = tail[0] in {"không", "linh", "lẻ"}
        multiplier = 1 if last_scale is None or explicit_units else (last_scale // 10 if group < 10 else last_scale // 1000)
        total += group * multiplier
    return int(total) if total == int(total) else None


def _normalize_money(match: re.Match) -> str:
    lexemes = list(_LEXER.finditer(match[0]))
    tokens = [token[0] for token in lexemes]
    if not set(tokens).intersection(set(_SCALES) | _CURRENCY):
        return match[0]
    currency_index = next((index for index, token in enumerate(tokens) if token in _CURRENCY), None)
    end = currency_index if currency_index is not None else len(tokens)
    # "nghìn đồng không?" / "249k không?": keep the question's final "không".
    if currency_index is None and end > 1 and tokens[-1] == "không":
        end -= 1
    amount_tokens = tokens[:end]
    if not amount_tokens:
        return match[0]
    if any(re.fullmatch(r"0\d{9}", token) for token in amount_tokens):
        return match[0]
    # A year prefix is not the digit five: "năm hai nghìn hai mươi sáu".
    if (
        currency_index is None and len(amount_tokens) > 1
        and amount_tokens[0] == "năm" and _digit(amount_tokens[1]) is not None
        and not set(amount_tokens).intersection({"triệu", "tr", "tỷ", "tỉ", "k"})
    ):
        return match[0]
    following = match.string[match.end():]
    if currency_index is None and re.match(r"\s+(?:người|lần|lượt|chiếc|cái|sản phẩm|mét|km|kg|giây|phút|giờ|ngày|tháng|điểm|lít|con|đơn|hộp|gói)\b", following):
        return match[0]
    preceding = match.string[:match.start()]
    if re.search(r"\b(?:mã|sku|model)\s*$", preceding):
        return match[0]
    amount = _money_amount(amount_tokens)
    if amount is None:
        return match[0]
    formatted = f"{amount:,}".replace(",", ".")
    suffix_start = lexemes[end - 1].end()
    return formatted + match[0][suffix_start:]


def normalize_asr_transcript(transcript: str) -> str:
    """Normalize ASR text before identity, PII masking, perception, and display."""
    text = " ".join(unicodedata.normalize("NFC", transcript).lower().split())
    text = _DATE.sub(_normalize_date, text)
    text = _PHONE.sub(_normalize_phone, text)
    return _MONEY.sub(_normalize_money, text)
