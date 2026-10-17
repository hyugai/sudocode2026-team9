"""Pure matching rules for products explicitly named by a customer."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from telesale_agent.core.address import extract_explicit_delivery_address


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    unaccented = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", unaccented).split())


def mentioned_catalog_items(
    customer_text: str, catalog_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return only full catalog names present in the utterance, in text order.

    A broad result for `catalog.search("máy")` is not evidence that the
    customer selected every returned product. Longer overlapping names win.
    """
    haystack = f" {_normalize(customer_text)} "
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for item in catalog_items:
        if not isinstance(item, dict) or not item.get("sku") or not item.get("name"):
            continue
        needle = f" {_normalize(str(item['name']))} "
        if len(needle.strip()) < 4:
            continue
        position = haystack.find(needle)
        if position >= 0:
            matches.append((position, position + len(needle), item))
    selected: list[tuple[int, dict[str, Any]]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, item in sorted(matches, key=lambda match: (-(match[1] - match[0]), match[0])):
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        selected.append((start, item))
    return [item for _, item in sorted(selected, key=lambda match: match[0])]


def is_multi_product_request(customer_text: str) -> bool:
    text = _normalize(customer_text)
    return bool(
        re.search(
            r"\b(?:dang tinh|dinh mua|muon mua|mua|chon|gio hang)\b"
            r"[^.!?]{0,160}\b(?:voi|va)\b",
            text,
        )
    )


def is_basket_recap_request(customer_text: str) -> bool:
    """Recognize a request to repeat a saved cart, not a new order action."""
    text = _normalize(customer_text)
    if re.search(
        r"\b(?:chinh sach|bao hanh|doi tra|hoan tien|phi ship|"
        r"len don|tao don|dat hang|thanh toan|so sanh)\b",
        text,
    ):
        return False
    return bool(
        re.search(r"\b(?:nhac|xac nhan|noi lai|doc lai)\b", text)
        and re.search(r"\b(?:gio hang|hai mon|2 mon|san pham|mon cuoi cung)\b", text)
    )


def asks_basket_total(customer_text: str) -> bool:
    text = _normalize(customer_text)
    return is_basket_recap_request(customer_text) and bool(
        re.search(r"\b(?:tong tien|tong gia|thanh tien|bao nhieu tien)\b", text)
    )


def declines_order_creation(customer_text: str) -> bool:
    """A current refusal overrides checkout state from an earlier turn."""
    text = _normalize(customer_text)
    return bool(
        re.search(
            r"\b(?:chua|khong|dung)\b[^.!?]{0,30}"
            r"\b(?:len don|chot(?: don)?|dat(?: mua| hang| don)?|tao don|mua(?: ngay)?)\b",
            text,
        )
    )


def starts_basket_checkout(customer_text: str) -> bool:
    """Recognize an accepted cart/quote plus quantity and delivery details.

    A remembered address, a budget question, or payment choice alone must not
    grant purchase consent. The caller must also have a verified saved basket.
    """
    if declines_order_creation(customer_text):
        return False
    text = _normalize(customer_text)
    accepted = re.search(
        r"\b(?:dong y|chap nhan|nam trong ngan sach|vua ngan sach|"
        r"gia (?:nay )?on|gia (?:nay )?hop ly|tong (?:nay )?on|"
        r"tong (?:nay )?hop ly)\b",
        text,
    )
    quantity = re.search(
        r"\b(?:moi mon|moi thu|moi loai)\s+"
        r"(?:\d+|mot|hai|ba|bon|nam)\b",
        text,
    )
    return bool(
        accepted
        and quantity
        and extract_explicit_delivery_address(customer_text)
    )
