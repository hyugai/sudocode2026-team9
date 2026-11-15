"""Customer-provided address forms and bounded CRM salutation instructions."""

import re


HONORIFICS = {"anh", "chị", "cô", "chú", "bác", "em", "bạn", "ông", "bà"}


def explicit_honorific(text: str | None) -> str | None:
    """Use explicit self-addressing; never infer from a name/email/third party."""
    value = (text or "").strip()
    requested = re.search(
        r"\b(?:gọi|xưng hô với)\s+(?:tôi|mình|em|anh|chị|cô|chú|bác)\s+(?:là\s+)?"
        r"(anh|chị|cô|chú|bác|em|bạn|ông|bà)\b", value, re.IGNORECASE,
    )
    if requested:
        return requested.group(1).lower()
    return None


def customer_honorific(context) -> str | None:
    profile = context.state.customer_profile or {}
    identity = context.identity or context.state.identity
    for value in (profile.get("honorific"),
                  identity.profile.get("honorific") if identity else None,
                  getattr(context.call_brief, "honorific", None)):
        normalized = str(value or "").strip().lower()
        if normalized in HONORIFICS:
            return normalized
    return None


def addressing_instruction(context) -> str:
    honorific = customer_honorific(context)
    if honorific:
        return (f"Cách xưng hô từ CRM: {honorific}. Gọi khách là '{honorific}', tự xưng 'em'. "
                "Không dùng 'anh/chị' khi cách xưng hô đã rõ; không hỏi lại tên/cách xưng hô đã có.")
    instruction = "Chưa có cách xưng hô được xác nhận. Dùng 'bạn', không đoán giới tính từ tên/email/số điện thoại."
    if context.state.turn_number == 0:
        instruction += " Có thể hỏi ngắn gọn khách muốn được xưng hô thế nào."
    return instruction


def ground_generic_salutation(text: str, context) -> str:
    honorific = customer_honorific(context)
    if not honorific:
        return text
    return re.sub(r"\b(?:anh\s*/\s*chị|chị\s*/\s*anh)\b",
                  lambda match: honorific.capitalize() if match.group(0)[0].isupper() else honorific,
                  text, flags=re.IGNORECASE)
