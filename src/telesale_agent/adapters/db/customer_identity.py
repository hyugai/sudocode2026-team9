"""Canonical contact matching and transaction-scoped CXXX allocation."""

import re

from sqlalchemy import select, text

from .models import Customer


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


def get_or_create_customer(session, *, phone=None, email=None, name=None):
    """Return (candidates, created); never merge ambiguous contacts."""
    phone, email = normalize_phone(phone), normalize_email(email)
    if not phone and not email:
        raise ValueError("Cần số điện thoại hoặc email để tạo khách hàng.")
    # Serialize allocation across connections, including an empty table.
    if session.get_bind().dialect.name == "postgresql":
        schema = session.connection().get_execution_options().get("schema_translate_map", {}).get(None)
        preparer = session.get_bind().dialect.identifier_preparer
        table = (preparer.quote_schema(schema) + "." if schema else "") + "customers"
        session.execute(text(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"))
    candidates = customer_contacts(session, phone=phone, email=email)
    if len(candidates) != 1 and candidates:
        return candidates, False
    if candidates:
        customer = candidates[0]
        if phone and customer.phone and not _phone_matches(customer.phone, phone):
            raise CustomerContactError("Email và số điện thoại không khớp khách hàng đã lưu.")
        if phone and not customer.phone:
            customer.phone = phone
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
        phone=phone, name=name or "Khách hàng mới", honorific="Anh/Chị",
        attributes={"email": email, "emails": [email]} if email else {},
    )
    session.add(customer)
    session.flush()
    return [customer], True
