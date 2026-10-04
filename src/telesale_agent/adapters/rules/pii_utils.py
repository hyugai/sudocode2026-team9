"""
Shared PII utility — can be used by both:
  - Input sanitiser (Perceiver) to mask before sending to LLM API
  - Output guardrail (PIIGuardrail) to mask before responding to customer

Keeping patterns in one place ensures consistency.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# PII patterns (pattern, replacement)
# ---------------------------------------------------------------------------
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # CCCD / CMND: exactly 9 or 12 consecutive digits
    (re.compile(r"(?<!\d)(\d{9}|\d{12})(?!\d)"), "[CCCD/CMND ĐÃ ẨN]"),

    # Bank account number: digits after STK keywords
    (re.compile(
        r"(?i)(s(?:ố\s*)?(?:tài\s*khoản|tk)|stk|account\s*(?:no|number))[:\s#]*(\d{6,19})"
    ), r"\1 [STK ĐÃ ẨN]"),

    # Full Vietnamese phone numbers: 10 digits starting with 0 (standalone)
    (re.compile(r"(?<!\d)(0\d{9})(?!\d)"), "[SĐT ĐÃ ẨN]"),
]


def mask_pii(text: str) -> tuple[str, list[str]]:
    """
    Apply all PII patterns to text.
    Returns (masked_text, list_of_violation_labels).

    Usage:
        clean, violations = mask_pii(user_input)
        if violations:
            log.warning("PII detected: %s", violations)
    """
    violations: list[str] = []
    for pattern, replacement in PII_PATTERNS:
        new_text, n = pattern.subn(replacement, text)
        if n:
            violations.append(replacement)
            text = new_text
    return text, violations
