import asyncio
import re
import unicodedata

from telesale_agent.core.interfaces import IdentityResolver
from telesale_agent.core.models import CustomerIdentity, TurnContext
from telesale_agent.adapters.db.client import db_client
from telesale_agent.adapters.db.customer_identity import normalize_phone, normalize_email


def _normalized_identity_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))


def _identity_tokens(value: str | None) -> set[str]:
    return set(_normalized_identity_text(value).split())

class HintIdentityResolver(IdentityResolver):
    """Implementation that reads a phone hint and retrieves/creates customer from DB."""

    async def resolve_identity(self, context: TurnContext) -> CustomerIdentity:
        # In a real system, ASR or caller ID provides the phone number
        hint = context.input.customer_hint or ""
        email = normalize_email(context.input.metadata.get("account_email") or (hint if "@" in hint else None))
        phone = normalize_phone(hint if "@" not in hint else None)
        if not phone and not email:
            return CustomerIdentity(confidence=0.0, profile={"identity_missing": True})
        
        # Check if customer exists in DB
        result = await asyncio.to_thread(db_client.resolve_customer, phone=phone, email=email,
                                         name=context.input.metadata.get("account_name"))
        
        if result.get("ambiguous"):
            spoken_text = _normalized_identity_text(context.input.text)
            spoken_tokens = set(spoken_text.split())
            candidates = result.get("candidates", [])
            self_identified = [
                candidate
                for candidate in candidates
                if candidate.get("name")
                and (
                    re.search(
                        rf"\b(?:toi|minh|anh|chi|em)\s+(?:ten\s+)?la\s+"
                        rf"{re.escape(_normalized_identity_text(candidate['name']))}\b",
                        spoken_text,
                    )
                    or re.search(
                        rf"\b(?:anh|chi|co|chu)\s+"
                        rf"{re.escape(_normalized_identity_text(candidate['name']))}"
                        rf"\s+(?:day|goi|nghe)\b",
                        spoken_text,
                    )
                )
            ]
            matching = self_identified or [
                candidate
                for candidate in candidates
                if _identity_tokens(candidate.get("name")) <= spoken_tokens
            ]
            if len(matching) == 1:
                selected = await asyncio.to_thread(db_client.get_customer_by_id, matching[0]["customer_id"])
                return CustomerIdentity(
                    customer_id=selected.get("customer_id"),
                    phone=selected.get("phone") or None,
                    confidence=1.0,
                    profile={
                        "name": selected.get("name"),
                        "honorific": selected.get("honorific"),
                        "identity_disambiguated": True,
                    },
                )
            return CustomerIdentity(
                customer_id=None,
                phone=phone,
                confidence=0.0,
                profile={
                    "is_ambiguous": True,
                    "candidates": result.get("candidates", []),
                },
            )

        customer_id = result.get("customer_id")
            
        return CustomerIdentity(
            customer_id=customer_id,
            phone=result.get("phone") or None,
            confidence=1.0,
            profile={
                "name": result.get("name"),
                "honorific": result.get("honorific"),
                "is_new": result.get("is_new", False),
            } if result.get("found") else {},
        )
