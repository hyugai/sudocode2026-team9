"""BTC pricing rules shared by single-item quotes and order validation."""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import Any

AIR_CATEGORY = "gia-dung/may-loc-khong-khi"


def region_of(address: str | None) -> str:
    address = (address or "").lower()
    if any(name in address for name in (
        "hcm", "hồ chí minh", "sài gòn", "bình dương", "đồng nai", "cần thơ",
        "vũng tàu", "long an", "tiền giang", "an giang", "kiên giang",
    )):
        return "nam"
    if any(name in address for name in (
        "đà nẵng", "huế", "quảng nam", "quảng ngãi", "bình định", "khánh hòa",
        "nha trang", "đắk lắk", "lâm đồng", "đà lạt", "quảng bình", "quảng trị",
        "bình thuận", "phú yên",
    )):
        return "trung"
    return "bac"


class PricingCalculator:
    """One quote request: read rules/context once and cache exact-SKU lookups."""

    def __init__(
        self, db: Any, on: date, customer_phone: str | None = None,
        customer_id: str | None = None, address: str | None = None,
    ) -> None:
        self.on = on
        self.db = db
        self.region = region_of(address)
        self.promos = db.get_promotions()
        self.customer = db.get_pricing_customer_context(
            customer_phone=customer_phone, customer_id=customer_id,
        )
        self.product = cache(self._product)

    def _product(self, sku: str) -> tuple[dict[str, Any], dict[str, Any]]:
        items = self.db.search_products(sku=sku, include_discontinued=True)["items"]
        if not items:
            return {}, {}
        product = items[0]
        variant = next((v for v in product.get("variants", [])
                        if v["variant_sku"] == sku), {})
        return product, variant

    def quote(
        self, sku: str, qty: int = 1, basket_skus: list[str] | None = None,
        exclude: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        product, variant = self.product(sku)
        if not product:
            return {"error": "unknown_sku"}
        base = int(product["list_price_vnd"]) + int(variant.get("price_delta_vnd", variant.get("price_delta", 0)) or 0)
        candidates: list[tuple[dict[str, Any], int]] = []
        expired, ineligible = [], []
        for promo in self.promos:
            code = promo["promo_code"]
            if code in exclude:
                continue
            targets = promo.get("applies_to") or []
            if not ("*" in targets or product["sku"] in targets or any(
                target.startswith("category:") and product["category"].startswith(target.split(":", 1)[1])
                for target in targets
            )):
                continue
            if not promo["start_date"] <= self.on <= promo["end_date"]:
                if promo["end_date"] < self.on:
                    expired.append(code)
                continue
            conditions = promo.get("conditions") or {}
            reason = None
            if conditions.get("min_qty") and qty + len(basket_skus or []) < conditions["min_qty"]:
                reason = "min_qty"
            if conditions.get("exclude_variant_size") and variant and str(variant.get("size")) in {
                str(size) for size in conditions["exclude_variant_size"]
            }:
                reason = "exclude_variant_size"
            if conditions.get("region") and self.region not in conditions["region"]:
                reason = "region"
            if (conditions.get("requires_owned_sku")
                    and conditions["requires_owned_sku"] not in self.customer.get("owned_skus", [])):
                reason = "requires_owned_sku"
            if conditions.get("once_per_customer") and code in self.customer.get("used_promos", []):
                reason = "once_per_customer"
            if promo.get("min_order_vnd") and base < promo["min_order_vnd"]:
                reason = "min_order"
            if reason:
                ineligible.append({"promo_code": code, "reason": reason})
                continue
            discount = 0
            if promo["type"] == "fixed":
                discount = int(promo.get("discount_vnd") or 0)
            elif promo["type"] == "percent":
                discount = int(base * promo["discount_percent"] / 100)
            elif promo["type"] == "percent_second_item":
                others = [self.quote(other)["list_price_vnd"] for other in basket_skus or []
                          if self.product(other)[0].get("category", "").startswith(AIR_CATEGORY)]
                if not others or base >= min(others):
                    ineligible.append({"promo_code": code, "reason": "not_cheapest_item_or_tie_use_quote_order"})
                    continue
                discount = int(base * promo["discount_percent"] / 100)
            candidates.append((promo, discount))
        stackable = [item for item in candidates if item[0].get("stackable")]
        exclusive = [item for item in candidates if not item[0].get("stackable")]
        best = max(exclusive, key=lambda item: item[1], default=None)
        applied = [self._public_promo(promo, discount) for promo, discount in stackable + ([best] if best else [])]
        return {
            "sku": sku, "list_price_vnd": base,
            "final_price_vnd": base - (best[1] if best else 0),
            "applied_promos": applied, "expired_promos": expired,
            "ineligible_promos": ineligible,
            "not_applied_exclusive": [promo["promo_code"] for promo, _ in exclusive
                                      if best and promo["promo_code"] != best[0]["promo_code"]],
            "freeship": any(promo["type"] == "freeship" for promo in applied) or base >= 2_000_000,
        }

    @staticmethod
    def _public_promo(promo: dict[str, Any], discount: int) -> dict[str, Any]:
        result = {"promo_code": promo["promo_code"], "type": promo["type"], "discount_vnd": discount}
        if promo.get("gift_sku"):
            result["gift_sku"] = promo["gift_sku"]
        return result

    def quote_order(
        self, lines: list[dict[str, Any]], *, second_item_used: bool = False,
        tie_prefer_first: bool = False,
    ) -> dict[str, Any]:
        units = []
        for index, line in enumerate(lines):
            product, _ = self.product(line["sku"])
            if not product:
                return {"error": "unknown_sku", "sku": line["sku"]}
            quote = self.quote(line["sku"])
            for _ in range(int(line.get("qty", 1))):
                units.append({"line": index, "sku": line["sku"],
                              "list_price_vnd": quote["list_price_vnd"],
                              "is_air": product["category"].startswith(AIR_CATEGORY)})
        second = next((promo for promo in self.promos if promo["type"] == "percent_second_item"
                       and promo["start_date"] <= self.on <= promo["end_date"]), None)
        air_indices = [index for index, unit in enumerate(units) if unit["is_air"]]
        second_index = None
        if second and len(air_indices) >= 2 and not second_item_used:
            lowest = min(units[index]["list_price_vnd"] for index in air_indices)
            ties = [index for index in air_indices if units[index]["list_price_vnd"] == lowest]
            second_index = min(ties) if tie_prefer_first else max(ties)
        trade = next((promo for promo in self.promos
                      if (promo.get("conditions") or {}).get("requires_owned_sku")), None)
        trade_code = trade["promo_code"] if trade else None
        exclude_second = (second["promo_code"],) if second else ()
        trade_index, best_gain = None, 0
        if trade_code:
            for index, unit in enumerate(units):
                if index == second_index:
                    continue
                with_trade = self.quote(unit["sku"], exclude=exclude_second)
                without_trade = self.quote(unit["sku"], exclude=exclude_second + (trade_code,))
                gain = without_trade["final_price_vnd"] - with_trade["final_price_vnd"]
                if gain > best_gain:
                    trade_index, best_gain = index, gain
        output, stackable = [], {}
        for index, unit in enumerate(units):
            exclude = exclude_second + ((trade_code,) if trade_code and index != trade_index else ())
            quote = self.quote(unit["sku"], exclude=exclude)
            final = quote["final_price_vnd"]
            applied = [promo for promo in quote["applied_promos"] if promo["type"] not in ("freeship", "freecod")]
            if index == second_index:
                discount = int(unit["list_price_vnd"] * second["discount_percent"] / 100)
                if discount >= unit["list_price_vnd"] - final:
                    final = unit["list_price_vnd"] - discount
                    applied = [self._public_promo(second, discount)]
            for promo in quote["applied_promos"]:
                if promo["type"] in ("freeship", "freecod"):
                    stackable[promo["promo_code"]] = promo
            output.append({"unit": index + 1, "line": unit["line"], "sku": unit["sku"],
                           "list_price_vnd": unit["list_price_vnd"], "final_price_vnd": final,
                           "applied_promos": applied})
        output_lines = []
        for index, line in enumerate(lines):
            prices = [unit["final_price_vnd"] for unit in output if unit["line"] == index]
            output_lines.append({"sku": line["sku"], "qty": len(prices),
                                 "unit_prices_vnd": prices, "line_total_vnd": sum(prices)})
        total = sum(unit["final_price_vnd"] for unit in output)
        return {
            "units": output, "lines": output_lines, "total_vnd": total,
            "order_promos": list(stackable.values()),
            "freeship": "NAM-SHIP0" in stackable or total >= 2_000_000,
            "note": ("Khi giá trong một dòng khác nhau (VD 2 máy cùng SKU, 1 máy được giảm 50%), "
                     "tạo đơn bằng mỗi máy một dòng qty=1."),
        }
