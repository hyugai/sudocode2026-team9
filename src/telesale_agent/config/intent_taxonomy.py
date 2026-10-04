"""
Intent taxonomy for the telesales NLU system.

To ADD a new intent:
  1. Add a new IntentDef entry to INTENT_TAXONOMY below.
  2. Done — the prompt in LLMPerceiver and the Retrieve routing will pick it up automatically.
  No need to touch the prompt string or retrieve.py directly.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntentDef:
    name: str
    description: str
    examples: list[str] = field(default_factory=list)
    # Keywords that should trigger retrieval even if LLM misclassifies
    retrieval_keywords: list[str] = field(default_factory=list)
    # If True, Retrieve node skips DB lookup (handled by Plan via tool/action)
    skip_retrieval: bool = False


INTENT_TAXONOMY: list[IntentDef] = [
    IntentDef(
        name="ask_product",
        description="Customer asks about product features, availability, colors, specs, or warranty.",
        examples=[
            "Tai nghe này pin được bao lâu?",
            "Còn hàng không em?",
            "Máy có màu trắng không?",
        ],
        retrieval_keywords=[],
    ),
    IntentDef(
        name="ask_policy",
        description=(
            "Customer asks about fees, shipping cost, delivery time, return/exchange rules, "
            "payment methods, or data privacy. "
            "Trigger this whenever you see: phí, phí ship, phí giao hàng, mất bao lâu giao, "
            "đổi trả, bảo hành, bảo mật, thanh toán."
        ),
        examples=[
            "Phí giao hàng bao nhiêu?",
            "Phí giao hàng tai nghe bên mình là bao nhiêu nhỉ? → [ask_product, ask_policy]",
            "Ship mất mấy ngày?",
            "Đổi hàng như thế nào?",
        ],
        retrieval_keywords=["phí", "giao hàng", "ship", "freeship", "vận chuyển",
                            "đổi trả", "hoàn tiền", "trả hàng", "bảo mật",
                            "thông tin cá nhân", "quyền riêng tư"],
    ),
    IntentDef(
        name="price_objection",
        description="Customer thinks the price is too high, asks for a discount or negotiation.",
        examples=["Đắt quá em ơi", "Giảm thêm được không?", "Chỗ khác rẻ hơn"],
    ),
    IntentDef(
        name="create_order",
        description="Customer wants to place, confirm, or cancel an order.",
        examples=["Chị đặt cái đó đi em", "Cho chị hủy đơn", "Chốt đơn nha"],
        skip_retrieval=True,
    ),
    IntentDef(
        name="complain",
        description="Customer is unhappy or reporting a problem with a product or service.",
        examples=["Máy bị lỗi rồi", "Chị đợi mãi không thấy hàng"],
    ),
    IntentDef(
        name="provide_info",
        description="Customer is voluntarily sharing personal context such as budget, room size, or family situation.",
        examples=["Nhà chị có em bé", "Ngân sách tầm 5 triệu thôi", "Phòng chị 25m2"],
        skip_retrieval=True,
    ),
    IntentDef(
        name="end_call",
        description="Customer signals they want to end the conversation or call back later.",
        examples=["Để chị hỏi lại rồi gọi lại em nhé", "Thôi em ơi chị nghĩ thêm đã"],
        skip_retrieval=True,
    ),
    IntentDef(
        name="unknown",
        description="Cannot determine intent from the utterance.",
        examples=[],
    ),
]

# Helpers
INTENT_NAMES: list[str] = [i.name for i in INTENT_TAXONOMY]

# Lookup map: intent name → IntentDef
INTENT_MAP: dict[str, IntentDef] = {i.name: i for i in INTENT_TAXONOMY}

# Intents that produce no knowledge retrieval (skip_retrieval=True)
SKIP_RETRIEVAL_INTENTS: set[str] = {i.name for i in INTENT_TAXONOMY if i.skip_retrieval}


def build_intent_prompt_section() -> str:
    """Auto-generate the intent definitions section for the LLM Perceive prompt."""
    lines = ["## INTENT DEFINITIONS (read carefully before classifying)\n"]
    for intent in INTENT_TAXONOMY:
        lines.append(f"- **{intent.name}**: {intent.description}")
        if intent.examples:
            for ex in intent.examples:
                lines.append(f'  Example: "{ex}"')
        lines.append("")
    return "\n".join(lines)
