"""Extract normalized BTC ASR entities from recognized speech."""

import json
import re
from datetime import date
from pathlib import Path

from eval.trace_extractors import extract_claims, money_value
from telesale_agent.application.asr_normalization import (
    _NUMBER_PHRASE, _integer, normalize_asr_transcript,
)

_AMOUNT = r"(\d+(?:[.,]\d+)*\s*(?:đồng|vnd|đ|₫)?)"
_MONEY_CUES = {
    "budget_vnd": r"\b(?:ngân sách|tầm tiền)(?:\s+(?:là|khoảng|tầm|dưới))*\s+",
    "price_vnd": r"\b(?:giá(?:\s+(?:bán|là|hiện tại|chính xác|còn))*|mẫu\s+[\w-]+\s+là)\s+",
    "competitor_price_vnd": r"\b(?:bên khác|bên kia|chỗ khác|nơi khác|đối thủ)\b[^.;!?]{0,30}?\s+",
    "min_free_ship_vnd": r"\b(?:miễn phí (?:giao hàng|vận chuyển)|freeship)\s+(?:cho đơn\s+)?(?:từ|trên)\s+",
    "bulky_fee_vnd": r"\b(?:phí (?:giao hàng cồng kềnh|hàng cồng kềnh|vận chuyển cồng kềnh)|cồng kềnh[^.;!?]{0,28}\s+phụ thu)\s*(?:là\s+)?",
    "exchange_fee_vnd": r"\bphí đổi(?:\s+size)?\s*(?:là\s+)?",
}
_NUMBER_CUES = {
    "room_area_m2": rf"(?:\bphòng[^.;!?]{{0,24}}?)?({_NUMBER_PHRASE})\s*(?:m[²2]|mét(?: vuông)?)\b",
    "delivery_days": rf"\bgiao(?:\s+hàng)?\s*(?:(?:trong|sau|khoảng|mất|tầm|nội thành|ngoại thành)\s+)*(?:{_NUMBER_PHRASE}\s+đến\s+)?({_NUMBER_PHRASE})\s+ngày\b",
    "return_days": rf"\b(?:đổi trả|trả hàng|đổi hàng)\s*(?:(?:trong|sau|khoảng)\s+)*({_NUMBER_PHRASE})\s+ngày\b",
    "warranty_months": rf"\bbảo hành\s*(?:trong\s+)?({_NUMBER_PHRASE})\s+(tháng|năm)\b",
}
_COLOR = {
    "đen": "den", "trắng": "trang", "xanh": "xanh", "đỏ": "do",
    "be": "be", "hồng": "hong", "nâu": "nau", "xám": "xam",
}
DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "dataset/pipeline/stage-1/input/catalog/products.json"


def load_product_aliases(catalog: Path) -> dict[str, str]:
    aliases = {}
    for item in json.loads(catalog.read_bytes())["products"]:
        sku = item["sku"]
        name = item["name"].casefold()
        aliases[name] = sku
        short = re.sub(
            r"^(?:máy lọc không khí|máy lọc nước ro|máy lọc nước|giày chạy bộ|giày sneaker)\s+",
            "", name,
        )
        aliases[short] = sku
    return aliases


def extract_asr_entities(transcript: str, product_aliases: dict[str, str], *, reference_date=None) -> dict:
    """Use product names and speech cues without reference transcripts or labels."""
    text = normalize_asr_transcript(transcript)
    entities = {}
    for key, cue in _MONEY_CUES.items():
        for match in re.finditer(cue + _AMOUNT, text, re.I):
            if (value := money_value(match[1])) is not None:
                entities[key] = value
    for match in re.finditer(r"\bđơn\s+(?:từ|trên)\s+" + _AMOUNT + r"\s+(?:được\s+)?miễn phí", text):
        if (value := money_value(match[1])) is not None:
            entities["min_free_ship_vnd"] = value
    for key, pattern in _NUMBER_CUES.items():
        for match in re.finditer(pattern, text, re.I):
            value = _integer(match[1].split())
            if value is not None:
                entities[key] = value * 12 if key == "warranty_months" and match[2] == "năm" else value

    sizes = [
        (match, _integer(match[1].split()))
        for match in re.finditer(rf"\b(?:size|sai|cỡ)\s+({_NUMBER_PHRASE})", text)
    ]
    old_size = None
    for match, value in sizes:
        if value is None:
            continue
        cue = text[max(0, match.start() - 28):match.start()]
        if re.search(r"(?:đổi sang|lên|sang|lấy|đổi qua|chọn)\s*$", cue):
            entities["size_new"] = value
        elif old_size is None:
            old_size = value
    if old_size is not None:
        entities["size_old"] = old_size
    for pattern, key in (
        (r"\b0\d{9}\b", "phone"),
        (r"\b(?:(?:ord|od)[-\s]?[a-z0-9]{4,})\b", "order_id"),
        (r"\bmàu\s+(" + "|".join(_COLOR) + r")\b", "color"),
    ):
        matches = list(re.finditer(pattern, text))
        if matches:
            match = matches[-1]
            value = match[0]
            if key == "order_id":
                value = value.replace(" ", "").upper()
            elif key == "color":
                value = _COLOR[match[1]]
            entities[key] = value
    for match in re.finditer(rf"\bô\s+đê\s+({_NUMBER_PHRASE})", text):
        if (number := _integer(match[1].split())) is not None:
            entities["order_id"] = f"OD{number}"

    sku_mentions = [(m.start(), m[0].upper()) for m in re.finditer(r"\bsku-[a-z0-9-]+\b", text)]
    for alias, sku in product_aliases.items():
        sku_mentions.extend((m.start(), sku) for m in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text))
    if sku_mentions:
        entities["sku"] = max(sku_mentions)[1]

    if re.search(r"\b(?:cod|thanh toán khi nhận(?: hàng)?|trả tiền khi nhận(?: hàng)?)\b", text):
        entities["payment"] = "COD"
    elif re.search(r"\bchuyển khoản\b", text):
        entities["payment"] = "bank"
    if match := re.search(r"\b(?:(không|chưa)\s+)?có\s+(?:trẻ nhỏ|trẻ em|em bé|bé nhỏ|bé)\b", text):
        entities["has_children"] = not bool(match[1])
    if re.search(r"\b(?:hỏi|bàn với)\s+(?:ý kiến\s+)?chồng\b", text):
        entities["blocker"] = "can hoi chong"
    elif "competitor_price_vnd" in entities or re.search(r"\bso sánh giá\b", text):
        entities["blocker"] = "so sanh gia"
    for match in re.finditer(r"(?:đến|tới|hết hạn)\s*(?:hết\s*)?(?:ngày\s*)?(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", text):
        if not match[3] and reference_date is None:
            continue
        try:
            year = int(match[3]) if match[3] else reference_date.year
            entities["promo_expiry"] = date(year, int(match[2]), int(match[1])).isoformat()
        except ValueError:
            continue
    for claim in extract_claims([], response_text=transcript):
        if claim["field"] in {"price_vnd", "exchange_fee_vnd", "in_stock", "delivery_days", "return_days", "warranty_months"}:
            entities.setdefault(claim["field"], claim["value"])
    return entities
