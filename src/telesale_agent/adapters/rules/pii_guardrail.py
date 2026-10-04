"""
PII-aware Guardrail.

Checks that the agent's planned response_text does not leak:
  - Vietnamese CCCD / CMND numbers (9 or 12 digits)
  - Bank account numbers (STK, typically 9-19 digits after label keywords)
  - Full phone numbers (10 digits starting with 0)
  - Disallowed competitor price comparisons or internal-only data

"""

from __future__ import annotations

import re
from copy import deepcopy

from telesale_agent.core.interfaces import Guardrail
from telesale_agent.core.models import ActionPlan, PolicyDecision, TurnContext
from telesale_agent.adapters.rules.pii_utils import mask_pii


# ---------------------------------------------------------------------------
# Forbidden response patterns (agent must not say these things)
# ---------------------------------------------------------------------------
_FORBIDDEN_CLAIMS: list[tuple[re.Pattern[str], str]] = [
    # Agent must not claim to be a human when asked
    (re.compile(r"(?i)(tôi\s+là\s+người|mình\s+là\s+người\s+thật|em\s+là\s+nhân\s+viên\s+thật)"),
     "agent_claims_human"),

    # Agent must not reveal internal prices / cost prices
    (re.compile(r"(?i)(giá\s+nhập|giá\s+vốn|lãi\s+suất\s+nội\s+bộ|chiết\s+khấu\s+nội\s+bộ)"),
     "leaks_internal_data"),

    # Agent must not comment negatively on competitors by name
    (re.compile(r"(?i)(thegioididong|fptshop|cellphones?\s*s|tiki|shopee)\s+.{0,30}(đắt|tệ|kém|giả|lừa)"),
     "competitor_comment"),
]


def _check_forbidden(text: str) -> list[str]:
    """Return a list of forbidden-claim violation types found in text."""
    hits: list[str] = []
    for pattern, label in _FORBIDDEN_CLAIMS:
        if pattern.search(text):
            hits.append(label)
    return hits



class PIIGuardrail(Guardrail):
    """
    Production-grade guardrail that:
    1. Masks PII tokens (CCCD, STK, phone) in the planned response_text.
    2. Blocks the plan entirely if it contains forbidden claims.
    3. Records all violations in PolicyDecision for audit/scoring.
    """

    async def check(self, context: TurnContext) -> PolicyDecision:
        if context.plan is None:
            return PolicyDecision(allowed=True)

        response_text: str = context.plan.response_text or ""
        all_violations: list[str] = []

        # --- 1. Check & mask PII (output) ---
        masked_text, pii_violations = mask_pii(response_text)
        all_violations.extend(pii_violations)

        # --- 2. Check forbidden claims ---
        forbidden_hits = _check_forbidden(masked_text)
        all_violations.extend(forbidden_hits)

        # --- 3. Build safe plan (always created; replaces original) ---
        safe_plan: ActionPlan = deepcopy(context.plan)
        safe_plan.response_text = masked_text

        if forbidden_hits:
            # Block entirely — replace response with a safe deflection
            safe_plan.response_text = (
                "Em xin lỗi, em không thể cung cấp thông tin đó. "
                "Anh/chị cần hỗ trợ thêm gì không ạ?"
            )
            return PolicyDecision(
                allowed=False,
                reason=f"Forbidden claims detected: {forbidden_hits}",
                safe_plan=safe_plan,
            )

        if pii_violations:
            # Allow but with sanitised text
            return PolicyDecision(
                allowed=True,
                reason=f"PII masked: {pii_violations}",
                safe_plan=safe_plan,
            )

        # --- 4. Clean — no violations ---
        return PolicyDecision(allowed=True)
