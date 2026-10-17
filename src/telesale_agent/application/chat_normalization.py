"""Local, conservative normalization of typed Vietnamese shopping messages.

Expand known shorthand and restore common unaccented shopping phrases. Keep
English shopping terms canonical, and preserve unknown words and identifiers.
This is a domain dictionary, not a general-purpose Vietnamese spelling model.
"""

import re
import unicodedata


_ALIASES = {
    "sp": "sản phẩm", "sanpham": "sản phẩm",
    "ko": "không", "khong": "không", "hok": "không", "hong": "không", "hông": "không", "hem": "không",
    "dc": "được", "đc": "được", "duoc": "được",
    "mik": "mình", "mk": "mình", "mjk": "mình", "minh": "mình", "toi": "tôi",
    "muon": "muốn", "thich": "thích", "biet": "biết", "hoi": "hỏi", "xem": "xem",
    "giup": "giúp", "dum": "giùm", "gium": "giùm", "nhe": "nhé", "nha": "nha",
    "gia": "giá", "tien": "tiền", "nhieu": "nhiêu", "nhan": "nhận", "gui": "gửi",
    "ao": "áo", "giay": "giày", "mua": "mua",
    "sdt": "số điện thoại", "sđt": "số điện thoại", "stk": "số tài khoản", "tk": "tài khoản",
    "ck": "chuyển khoản", "nt": "nhắn tin", "ttin": "thông tin",
    "sz": "size", "ib": "inbox", "inb": "inbox", "ord": "order", "shipcod": "ship cod",
    "size": "size", "ship": "ship", "sale": "sale", "order": "order", "inbox": "inbox", "cod": "cod",
    "va": "và", "cua": "của", "voi": "với",
    "saleoff": "sale", "freeship": "miễn phí ship", "freeshipping": "miễn phí ship",
    "pls": "vui lòng", "plz": "vui lòng", "oke": "ok", "okie": "ok",
}
_PHRASES = {
    "san pham": "sản phẩm", "san pham nay": "sản phẩm này", "sp nay": "sản phẩm này",
    "ban co": "bạn có", "ban con": "bạn còn", "shop co": "shop có", "shop con": "shop còn",
    "con hang": "còn hàng", "het hang": "hết hàng", "con size": "còn size", "con mau": "còn màu",
    "co ship": "có ship", "co cod": "có cod", "co sale": "có sale", "co size": "có size",
    "co hang": "có hàng", "co the": "có thể", "ao co ban": "áo cơ bản",
    "ban hang": "bán hàng", "ban ao": "bán áo", "ban giay": "bán giày",
    "bao nhieu": "bao nhiêu", "gia bn": "giá bao nhiêu", "giá bn": "giá bao nhiêu", "bn tien": "bao nhiêu tiền",
    "khuyen mai": "khuyến mãi", "khuyen mại": "khuyến mại", "giam gia": "giảm giá",
    "mien phi": "miễn phí", "phi ship": "phí ship", "free ship": "miễn phí ship", "free-ship": "miễn phí ship",
    "in box": "inbox", "in-box": "inbox", "ship cod": "ship cod", "ship-cod": "ship cod", "sale off": "sale",
    "dat hang": "đặt hàng", "don hang": "đơn hàng", "giao hang": "giao hàng", "nhan hang": "nhận hàng",
    "kiem hang": "kiểm hàng", "huy don": "hủy đơn", "huy order": "hủy order",
    "doi tra": "đổi trả", "doi size": "đổi size", "doi hang": "đổi hàng", "doi mau": "đổi màu", "tra hang": "trả hàng",
    "chinh sach": "chính sách", "dieu kien": "điều kiện", "thanh toan": "thanh toán",
    "tien mat": "tiền mặt", "chuyen khoan": "chuyển khoản", "tai khoan": "tài khoản", "ngan hang": "ngân hàng",
    "dia chi": "địa chỉ", "dien thoai": "điện thoại", "so dien thoai": "số điện thoại",
    "ho ten": "họ tên", "ten la": "tên là", "toi la": "tôi là", "toi ten": "tôi tên", "toi ten la": "tôi tên là",
    "thoi gian": "thời gian", "bao lau": "bao lâu", "khi nao": "khi nào", "goi lai": "gọi lại",
    "hen goi": "hẹn gọi", "ngay mai": "ngày mai", "hom nay": "hôm nay", "ngay nay": "ngày nay",
    "xin chao": "xin chào", "cam on": "cảm ơn", "chi phi": "chi phí", "chi tiet": "chi tiết",
    "mau xanh": "màu xanh", "mau do": "màu đỏ", "mau den": "màu đen", "mau trang": "màu trắng",
    "mau hong": "màu hồng", "mau vang": "màu vàng", "mau xam": "màu xám", "mau nau": "màu nâu",
    "mau navy": "màu navy", "thang nam": "tháng năm",
}
_PHRASE_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(key).replace(r"\ ", r"\s+") for key in sorted(_PHRASES, key=lambda key: (-len(key), key))) + r")(?!\w)",
    re.IGNORECASE,
)
_PLACEHOLDER = r"\ue000\d+\ue001"
_WORD_RE = re.compile(rf"{_PLACEHOLDER}|[^\W\d_]+")
_PROTECTED_RE = re.compile(
    r"`[^`]*`|\"[^\"]*\"|“[^”]*”"
    r"|https?://[^\s<>]+|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"
    r"|(?<!\w)\d+(?:[.,]\d+)*(?:\s*(?:vnd|kg|cm|mm|gb|tb|hz|k|đ|%))(?!\w)"
    r"|(?<!\w)(?=[\w./:+-]*\d)[\w]+(?:[./:+-][\w]+)*(?!\w)"
    r"|\b[a-zA-Z]+(?:[-_/][a-zA-Z]+)+\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"\b(?:mã|sku|model)\s*:?\s+(?P<value>[\w-]+)|\bma\s+(?P<ascii>(?-i:[A-Z][A-Z0-9_-]*))\b", re.IGNORECASE)
_SIZE_RE = re.compile(
    r"\b(?:size|sz|cỡ)\s+(?P<value>xxxs|xxs|xs|s|m|l|xl|xxl|xxxl|[A-Z])\b"
    r"|\bco\s+(?P<ascii>xxxs|xxs|xs|s|m|l|xl|xxl|xxxl)\b",
    re.IGNORECASE,
)
_NAME_STOP = r"(?:muon|muốn|can|cần|co|có|va|và|sdt|số|so|dien|điện|dia|địa|khach|khách)\b"
_NAME_RE = re.compile(
    r"\b(?:họ tên|ho ten|tên(?: là)?|ten(?: la)?|(?:tôi|toi|mình|minh|anh|chị|chi|em) (?:là|la))\s*:?\s+"
    rf"(?P<value>(?!{_NAME_STOP})[^\W\d_]+(?:\s+(?!{_NAME_STOP})[^\W\d_]+){{0,4}})",
    re.IGNORECASE,
)
_AMBIGUOUS_NAMES = {"minh", "ban", "co", "mau", "hang", "anh", "hoa", "van", "lan", "long", "nam", "son", "ha", "mai", "thu", "tam"}
_SENTENCE_START = {
    "sp", "san", "sanpham", "minh", "mik", "mk", "toi", "ban", "shop", "cho", "giup", "ao", "quan", "giay",
    "em", "e", "anh", "a", "chi", "co", "sz", "size", "ship", "sale", "ord", "order", "ib", "inb", "in", "inbox",
    "gia", "xin", "cam", "dia", "sdt", "hom", "ngay", "hoi", "gui", "can", "muon", "dat", "doi", "huy", "con",
}


def _fold(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char)).replace("đ", "d")


def normalize_chat_text(message: str) -> str:
    """Normalize typed input without another LLM call or guessed proper names."""
    text = " ".join(unicodedata.normalize("NFC", message).split())
    first_word = re.search(r"[^\W\d_]+", text)
    sentence_case = bool(first_word and first_word.start() == 0 and _fold(first_word[0]) in _SENTENCE_START)
    protected: list[tuple[str, str]] = []

    def mask(value: str, kind: str = "literal") -> str:
        protected.append((value, kind))
        return f"\ue000{len(protected) - 1}\ue001"

    def protect_literal(match: re.Match) -> str:
        # These hyphenated shopping expressions are intentionally canonicalized.
        return match[0] if match[0].casefold() in _PHRASES else mask(match[0])

    def protect_capture(match: re.Match, kind: str) -> str:
        group = "value" if match.groupdict().get("value") is not None else "ascii"
        value = match[group]
        if kind == "size" and value.casefold() in {"xxxs", "xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl"}:
            value = value.upper()
        start, end = match.span(group)
        return match.string[match.start():start] + mask(value, kind) + match.string[end:match.end()]

    text = re.sub(_PLACEHOLDER, lambda match: mask(match[0]), text)
    text = _PROTECTED_RE.sub(protect_literal, text)
    text = _CODE_RE.sub(lambda match: protect_capture(match, "code"), text)
    text = _SIZE_RE.sub(lambda match: protect_capture(match, "size"), text)
    text = _NAME_RE.sub(lambda match: protect_capture(match, "name"), text)

    def protect_name_case(match: re.Match) -> str:
        word = match[0]
        if not word.startswith("\ue000") and match.start() > 0 and word.istitle() and _fold(word) in _AMBIGUOUS_NAMES:
            return mask(word, "name")
        return word

    text = _WORD_RE.sub(protect_name_case, text)
    text = _PHRASE_RE.sub(lambda match: _PHRASES[" ".join(match[0].casefold().split())], text)
    words = list(_WORD_RE.finditer(text))
    resolved: dict[int, str] = {}

    def value_at(index: int) -> tuple[str, str]:
        if not 0 <= index < len(words):
            return "", ""
        word = words[index][0]
        return protected[int(word[1:-1])] if word.startswith("\ue000") else (resolved.get(index, _ALIASES.get(word.casefold(), word.casefold())), "word")

    replacements = []
    for index, match in enumerate(words):
        word, lower = match[0], match[0].casefold()
        previous, _ = value_at(index - 1)
        following, next_kind = value_at(index + 1)
        prev, nxt = _fold(previous).split(" ")[-1], _fold(following).split(" ")[0]
        value = word
        if word.startswith("\ue000"):
            continue
        if lower == "hong" and prev in {"mau", "ao", "quan", "giay"}:
            value = "hồng"
        elif lower in _ALIASES:
            value = _ALIASES[lower]
        elif lower == "k":
            value = "không"
        elif lower == "nay":
            value = "nay" if prev in {"hom", "ngay"} else "này"
        elif lower == "can" and nxt not in {"you", "i", "we", "they", "he", "she", "it"} and prev not in {"you", "i", "we", "they", "he", "she", "it"}:
            value = "cần"
        elif lower == "quan" and (prev in {"mua", "doi", "tra"} or nxt in {"ao", "jean", "jeans", "tay", "dai", "ngan", "jogger", "size"}):
            value = "quần"
        elif lower == "con" and (nxt in {"hang", "size", "mau", "sale", "sp", "san"} or (nxt in {"k", "khong"} and prev in {"shop", "pham", "nay", "hang", "ao", "giay"})):
            value = "còn"
        elif lower == "hang" and prev in {"co", "con", "het", "giao", "nhan", "dat", "don", "tra", "doi", "ban"}:
            value = "hàng"
        elif lower == "co":
            if next_kind == "size":
                value = "cỡ"
            elif next_kind == "name":
                value = "cô"
            elif prev in {"shop", "ban", "anh", "chi", "em", "minh", "toi", "pham", "nay"} or nxt in {"the", "muon", "can", "ban", "giao", "nhan", "gui", "ship", "cod", "size", "sale", "order", "inbox", "hang", "mau", "ao", "giay", "khuyen", "giam", "mien"}:
                value = "có"
        elif lower == "ban":
            if prev in {"shop", "co"}:
                value = "bán"
            elif nxt in {"co", "con", "muon", "can", "giup"}:
                value = "bạn"
        elif lower == "chi" and (prev in {"cho", "giup"} or nxt in {"muon", "can", "co", "con", "dat"}):
            value = "chị"
        elif lower == "a" and (prev in {"khong", "on", "cho", "giup"} or nxt in {"co", "muon", "can", "dat", "nhan"}):
            value = "anh"
        elif lower == "e" and (prev in {"cho", "giup"} or nxt in {"muon", "can", "co", "dat"}):
            value = "em"
        elif lower in {"j", "gi"}:
            value = "gì"
        elif lower == "v" and prev in {"gi", "j", "sao", "the"}:
            value = "vậy"
        elif lower == "vs" and (not following or nxt in {"nhe", "nha"}):
            if prev in {"minh", "toi", "em", "anh", "chi"} or (re.search(r"\b(?:cho|giúp|giup|giùm|dum|gium)\b", text) and "so sanh" not in _fold(text)):
                value = "với"
        resolved[index] = value
        replacements.append((match.start(), match.end(), value))
    for start, end, value in reversed(replacements):
        text = text[:start] + value + text[end:]
    if sentence_case and text and text[0].isalpha():
        text = text[0].upper() + text[1:]
    return re.sub(_PLACEHOLDER, lambda match: protected[int(match[0][1:-1])][0], text)
