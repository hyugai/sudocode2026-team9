"""Authoritative adapters. Neither adapter reads M1 prefilled/complete records."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Protocol

from .common import file_hash, read


class Domain(Protocol):
    reference_date: str
    products: list[dict]

    def reset(self) -> None: ...
    def facts(self, sku: str, on: str, customer: str) -> dict: ...
    def event(self, action: str, facts: dict, customer: str, previous: list[dict]) -> dict: ...


def policy_chunks(root: Path, names: list[str]) -> list[dict]:
    result = []
    for name in names:
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("policy path escapes domain root")
        text = path.read_text(encoding="utf-8")
        for part in re.split(r"(?=^## )", text, flags=re.M):
            if part.strip():
                result.append({"source": name, "source_sha256": file_hash(path), "text": part.strip()})
    return result


class JsonDomain:
    """Portable catalog contract; prices are static, with no implied discounts."""

    def __init__(self, root: Path, config: dict):
        data = read(root / config.get("catalog", "catalog.json"))
        self.reference_date = data["reference_date"]
        self.products = data["products"]
        if not self.products or len({p["sku"] for p in self.products}) != len(self.products):
            raise ValueError("catalog needs nonempty distinct SKUs")
        for p in self.products:
            if not all(k in p for k in ("sku", "name", "category", "price_vnd", "stock")):
                raise ValueError("JSON catalog needs sku/name/category/price_vnd/stock")
            if type(p["price_vnd"]) is not int or p["price_vnd"] <= 0 or type(p["stock"]) is not int or p["stock"] < 0:
                raise ValueError("catalog prices/stocks must be valid integers")
        self.policies = policy_chunks(root, config.get("policies", []))
        self.catalog_source = config.get("catalog", "catalog.json")

    def reset(self) -> None:
        pass

    def facts(self, sku: str, on: str, customer: str) -> dict:
        p = next(p for p in self.products if p["sku"] == sku)
        return {"product": p, "date": on, "price_vnd": p["price_vnd"],
                "inventory": {"in_stock": p["stock"] > 0, "qty": p["stock"]},
                "quote": {"final_price_vnd": p["price_vnd"], "expired_promos": []},
                "policies": self.policies, "evidence": {"kind": "static_catalog", "source": self.catalog_source}}

    def event(self, action: str, facts: dict, customer: str, previous: list[dict]) -> dict:
        # Generic sources cannot fabricate order/callback execution support.
        return {"action": "consultation", "status": "reference_plan_only", "requested_action": action}


class BtcDomain:
    def __init__(self, root: Path, config: dict):
        path = root / "eval/mock_tools.py"
        spec = importlib.util.spec_from_file_location("synthetic_btc_reference", path)
        self.mock = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(self.mock)
        finally:
            sys.dont_write_bytecode = previous
        self.reference_date = self.mock.REF
        self.products = []
        for p in self.mock.PRODUCTS:
            if p.get("attributes", {}).get("discontinued"):
                continue
            for v in p["variants"] or [None]:
                self.products.append({"sku": v["variant_sku"] if v else p["sku"],
                                      "parent_sku": p["sku"], "name": p["name"],
                                      "category": p["category"], "attributes": p["attributes"],
                                      "variant": v})
        self.policies = policy_chunks(root, config.get("policies", []))

    def reset(self) -> None:
        for name in ("_ORDERS", "_CALLBACKS", "_TICKETS", "_ONCE_USED"):
            getattr(self.mock, name).clear()

    def facts(self, sku: str, on: str, customer: str) -> dict:
        product = next(p for p in self.products if p["sku"] == sku)
        quote = self.mock.pricing_get_quote(sku=sku, on=on, customer_phone=customer)
        inventory = self.mock.inventory_check(sku=sku, on=on)
        if quote.get("error") or inventory.get("error"):
            raise ValueError("reference tool cannot verify selected product")
        return {"product": product, "date": on, "price_vnd": quote["final_price_vnd"],
                "quote": quote, "inventory": inventory, "policies": self.policies,
                "evidence": {"kind": "btc_reference_mock", "source": "eval/mock_tools.py",
                             "requests": [{"name": "pricing.get_quote", "args": {"sku": sku, "on": on, "customer_phone": customer}},
                                          {"name": "inventory.check", "args": {"sku": sku, "on": on}}]}}

    def event(self, action: str, facts: dict, customer: str, previous: list[dict]) -> dict:
        sku, on = facts["product"]["sku"], facts["date"]
        if action == "order" and facts["inventory"]["in_stock"]:
            args = {"customer_phone": customer, "sku": sku, "qty": 1, "price_vnd": facts["price_vnd"],
                    "payment": "bank", "address": "Địa chỉ kiểm thử tổng hợp tại Hà Nội", "on": on}
            result = self.mock.order_create(**args)
            if result.get("error"):
                raise ValueError("reference order failed")
            return {"action": "order.create", "args": args, "result": result,
                    "origin": "reference_mock_only_not_actual_agent"}
        if action == "exchange":
            orders = [s["reference_event"] for s in previous if s["reference_event"]["action"] == "order.create"]
            parent, variant = self.mock._parent(sku)
            alternatives = [v for v in parent["variants"] if v["variant_sku"] != sku
                            and self.mock.inventory_check(v["variant_sku"], on)["in_stock"]]
            if orders and variant and alternatives:
                args = {"order_id": orders[-1]["result"]["order_id"], "action": "exchange_size",
                        "new_variant_sku": alternatives[0]["variant_sku"], "on": on}
                result = self.mock.order_update(**args)
                if result.get("error"):
                    raise ValueError("reference exchange failed")
                return {"action": "order.update", "args": args, "result": result,
                        "origin": "reference_mock_only_not_actual_agent"}
        return {"action": "consultation", "status": "no_mutation"}


def load_domain(root: Path, config: dict) -> Domain:
    if config["kind"] == "btc":
        return BtcDomain(root, config)
    if config["kind"] == "json":
        return JsonDomain(root, config)
    raise ValueError("adapter kind must be btc or json")


def source_paths(root: Path, config: dict) -> list[Path]:
    if config["kind"] == "btc":
        paths = list((root / "catalog").glob("*.json")) + [root / "eval/mock_tools.py"]
        paths += list((root / "policy").glob("*.md"))
        paths += [root / name for name in ("DIEU-CHINH-DE.md", "GIAI-DAP-MENTOR.md") if (root / name).is_file()]
        paths += list(root.glob("*.pdf"))
    else:
        paths = [root / config.get("catalog", "catalog.json")]
    paths += [root / name for name in config.get("policies", [])]
    for path in paths:
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError("domain sources must be regular files inside the configured root")
    return sorted(set(paths))
