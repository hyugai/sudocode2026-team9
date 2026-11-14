"""Handoff payload validated at the workflow boundary."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HandoffBrief(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    customer_phone: str = Field(pattern=r"^0[0-9]{9}$")
    customer_name: str | None
    escalation_reason: Literal[
        "cau_hoi_y_te", "ngoai_pham_vi_tai_lieu", "khach_yeu_cau_gap_nguoi",
        "khieu_nai_nghiem_trong", "loi_he_thong", "khach_mat_kien_nhan", "khac",
    ]
    conversation_summary: str = Field(min_length=20, max_length=800)
    product_advised: str | None
    price_quoted_vnd: int | None
    open_questions: list[str]
    next_action: str
    generated_at: str
    customer_id: str | None = None
    channel: Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"] = "other"
    escalation_reason_detail: str = ""
    promo_code: str | None = None
    facts_confirmed: dict[str, Any] = Field(default_factory=dict)
    sentiment: Literal["binh_thuong", "hai_long", "kho_chiu", "gian"] = "binh_thuong"
    history_refs: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value
