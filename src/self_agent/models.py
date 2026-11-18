"""Bounded, detached and redacted learning inputs."""
import hashlib
import json
import re
from dataclasses import dataclass


def redact(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", str(text))
    # Phone/account numbers, not money such as 4.890.000 or dates 2026-10-17.
    text = re.sub(r"(?<!\w)(?:\+84|0)(?:[ .()-]?\d){9,10}(?!\d)", "[phone]", text)
    text = re.sub(r"(?<!\w)\d{12,19}(?!\w)", "[account_number]", text)
    text = re.sub(r"\bORD-[A-Za-z0-9-]+\b", "[order_id]", text, flags=re.I)
    text = re.sub(r"(?i)((?:số tài khoản|số thẻ|stk|cccd|cmnd|bank account)\s*[:#]?\s*)[\d .-]+",
                  r"\1[account_number]", text)
    text = re.sub(r"(?i)((?:địa chỉ|giao đến|giao tới|address)\s*(?:là|:)?\s*)[^;\n]+", r"\1[address]", text)
    return text


PRIVATE_KEYS = {"name", "customer_name", "full_name", "phone", "customer_phone", "email",
                "address", "delivery_address", "shipping_address", "customer_id", "user_id",
                "order_id", "account_number", "bank_account", "identity_number", "cccd",
                "token", "api_key", "authorization", "password", "zalo_id", "fb_id"}


def sanitize(value, secrets=()):
    """Redact nested tool payloads while retaining typed business quantities."""
    if isinstance(value, dict):
        public_tool = (isinstance(value.get('name'), str) and {'args', 'result'} <= value.keys()
                       and re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.]*', value['name']))
        return {str(k): value[k] if k == 'name' and public_tool else
                "[private]" if str(k).lower() in PRIVATE_KEYS else sanitize(v, secrets)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if isinstance(secret, str) and len(secret) > 2:
                value = re.sub(r'(?<!\w)' + re.escape(secret) + r'(?!\w)', "[private]", value, flags=re.I)
        return redact(value)
    return value if value is None or isinstance(value, (bool, int, float)) else None


def shared_question(question):
    """Only fixed, reusable patterns may leave the restricted session snapshot."""
    text = question.casefold()
    for words, template in [(("sê-ri", "serial", "chiếc sẽ giao"), "Thông tin từng chiếc hàng cần bằng chứng riêng nào?"),
                            (("size", "đổi", "trả"), "Đổi size và đổi trả áp dụng điều kiện nào?"),
                            (("giá", "ngân sách"), "Giá hiện tại cần được xác minh từ nguồn nào?"),
                            (("bảo hành",), "Chính sách bảo hành áp dụng điều kiện nào?"),
                            (("hàng", "kho"), "Tình trạng hàng cần được xác minh từ nguồn nào?")]:
        if any(w in text for w in words):
            return template
    return "Thông tin nghiệp vụ cần được xác minh từ nguồn nào?"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class LearningJob:
    status: str
    job_id: str | None = None
    error: str | None = None


def snapshot(state, turn_results=(), feedback=()):
    # Names/addresses are not copied from identity/profile/customer memory.
    identity = getattr(state, "identity", None)
    profile = getattr(identity, "profile", None) or {}
    secrets = [getattr(identity, "phone", None), *[profile.get(k) for k in ("name", "address", "phone", "email")]]
    def clean(value):
        return sanitize(value, secrets)
    messages = [{"message_id": i, "role": m.role, "content": clean(m.content)} for i, m in enumerate(state.messages)]
    questions = getattr(state.call_brief, "open_questions", []) if state.call_brief else []
    value = {"session": digest(state.conversation_id), "revision": state.turn_number,
             "messages": messages, "open_questions": [clean(q) for q in questions],
             "feedback": [clean(f) for f in feedback],
             "evidence_coverage": "transcript_only", "workflow_version": 4}
    evidence = []
    for i, result in enumerate(turn_results):
        retrieved = getattr(result, "retrieved", None)
        evidence.append({"turn_id": getattr(result, "turn_number", i + 1),
                         "agent_response": clean(getattr(result, "response_text", "")),
                         "tool_calls": [{"name": tool.get("name"),
                                         "args": clean(tool.get("args", {})),
                                         "result": clean(tool.get("result"))}
                                        for tool in (getattr(result, "tool_calls", []) or [])],
                         "sources": clean(getattr(retrieved, "knowledge", []) or []),
                         'promotions': clean(getattr(retrieved,'active_promotions',[]) or [])})
    value["turn_evidence"] = evidence
    if evidence:
        value["evidence_coverage"] = "partial_turn_evidence" if len(evidence) != state.turn_number else "per_turn_evidence"
    # Never serialize TurnResult/state wholesale: they may contain credentials/PII.
    if len(json.dumps(value, ensure_ascii=False).encode()) > 512_000:
        raise ValueError("Learning snapshot exceeds 512 KB; session was not truncated")
    return value
