"""Canonical contact matching and transaction-scoped CXXX allocation."""

import re

from sqlalchemy import select, text

from .models import Customer
from telesale_agent.application.customer_addressing import HONORIFICS


class CustomerContactError(ValueError):
    """Contact input cannot be normalized or conflicts with an existing record."""


def normalize_phone(value: str | None) -> str:
    if not value or not value.strip():
        return ""
    if not re.fullmatch(r"[+()\d\s.-]+", value):
        raise CustomerContactError("Số điện thoại không hợp lệ.")
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0084") and len(digits) == 13:
        digits = "0" + digits[4:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    if not 8 <= len(digits) <= 15:
        raise CustomerContactError("Số điện thoại không hợp lệ.")
    return digits


def normalize_email(value: str | None) -> str:
    email = (value or "").strip().lower()
    if email and (len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
        raise CustomerContactError("Email không hợp lệ.")
    return email


def _phone_matches(value, phone):
    try:
        return bool(phone) and normalize_phone(value) == phone
    except ValueError:
        return False


def customer_contacts(session, *, phone=None, email=None):
    phone, email = normalize_phone(phone), normalize_email(email)
    if not phone and not email:
        return []
    # Match legacy formatted numbers without rewriting imported/shared phones.
    return [customer for customer in session.scalars(select(Customer))
            if _phone_matches(customer.phone, phone)
            or (email and email in [str(item).strip().lower() for item in (
                list((customer.attributes or {}).get("emails") or [])
                + [(customer.attributes or {}).get("email", "")])])]


def get_or_create_customer(session, *, phone=None, email=None, name=None, honorific=None):
    """Return (candidates, created); never merge ambiguous contacts."""
    phone, email = normalize_phone(phone), normalize_email(email)
    if not phone and not email:
        raise ValueError("Cần số điện thoại hoặc email để tạo khách hàng.")
    if honorific is not None and honorific not in HONORIFICS:
        raise CustomerContactError("Cách xưng hô không hợp lệ.")
    # Serialize allocation across connections, including an empty table.
    if session.get_bind().dialect.name == "postgresql":
        schema = session.connection().get_execution_options().get("schema_translate_map", {}).get(None)
        preparer = session.get_bind().dialect.identifier_preparer
        table = (preparer.quote_schema(schema) + "." if schema else "") + "customers"
        session.execute(text(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"))
    phone_matches = customer_contacts(session, phone=phone) if phone else []
    email_matches = customer_contacts(session, email=email) if email else []
    # An explicitly supplied phone identifies this conversation's customer.
    # The signed-in email is a fallback; it must not make a known phone
    # ambiguous or move another customer's email/memory to that phone.
    if phone_matches:
        candidates = phone_matches
        if email_matches and {item.customer_id for item in email_matches} != {item.customer_id for item in candidates}:
            email = ""
    elif email_matches and (not phone or all(not item.phone for item in email_matches)):
        candidates = email_matches
    else:
        candidates = []
        if email_matches:
            email = ""
    if len(candidates) != 1 and candidates:
        return candidates, False
    if candidates:
        customer = candidates[0]
        if phone and not customer.phone:
            customer.phone = phone
        if honorific:
            customer.honorific = honorific
        if email:
            attributes = dict(customer.attributes or {})
            emails = list(attributes.get("emails") or [])
            if attributes.get("email"):
                emails.append(attributes["email"])
            attributes["emails"] = sorted({*emails, email})
            attributes.setdefault("email", email)
            customer.attributes = attributes
        session.flush()
        return candidates, False
    numbers = [int(match.group(1)) for identifier in session.scalars(select(Customer.customer_id))
               if (match := re.fullmatch(r"C(\d+)", identifier))]
    customer = Customer(
        customer_id=f"C{max(numbers, default=0) + 1:03d}",
        phone=phone, name=name or "Khách hàng mới", honorific=honorific or "Anh/Chị",
        attributes={"email": email, "emails": [email]} if email else {},
    )
    session.add(customer)
    session.flush()
    return [customer], True
