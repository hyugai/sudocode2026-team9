"""Offline parity against BTC's immutable November 2026 reference tools."""

import copy
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DATA = ROOT / "dataset/organizer"
spec = importlib.util.spec_from_file_location("btc_order_parity", DATA / "eval/mock_tools.py")
BTC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BTC)

from mcp_servers.tools.pricing import PricingCalculator
from mcp_servers.tools import catalog, order


def customer_context(phone=None):
    customer = BTC.crm_get_customer(phone=phone)
    return {"ambiguous": customer.get("ambiguous", False), "used_promos": [],
            "owned_skus": list(BTC._owned_skus(phone)) if phone else []}


class FixtureDB:
    def __init__(self):
        self.orders = {}

    def search_products(self, sku=None, **kwargs):
        return {"items": [p for p in BTC.PRODUCTS if not sku or p["sku"] == sku or
                          any(v["variant_sku"] == sku for v in p.get("variants", []))]}

    def get_promotions(self):
        return [{**p, "start_date": date.fromisoformat(p["start"]), "end_date": date.fromisoformat(p["end"])} for p in BTC.PROMOS]

    def get_pricing_customer_context(self, customer_phone=None, customer_id=None):
        context = customer_context(customer_phone)
        context["used_promos"] = [code for o in self.orders.values() if o["customer_phone"] == customer_phone for code in o["promos"]]
        return context

    def check_stock(self, sku, on):
        return BTC.inventory_check(sku, on.isoformat())

    def find_orders(self, order_id=None, customer_phone=None):
        matches = [o for o in self.orders.values() if (o["order_id"] == order_id if order_id else o["customer_phone"] == customer_phone)]
        return [{**o, "lines": o.get("lines") or [{"sku": o["sku"], "qty": o["qty"], "price_vnd": o["price_vnd"]}]} for o in matches]

    def create_order(self, **kwargs):
        lines = kwargs.get("lines") or [{"sku": kwargs["sku"], "qty": kwargs["qty"], "price_vnd": kwargs["price_vnd"]}]
        saved = {**kwargs, "created_on": kwargs["order_date"].isoformat(), "status": "created",
                 "promos": sorted({code for line in lines for code in line.get("promos", [])}),
                 "total_vnd": sum(l["price_vnd"] * l.get("qty", 1) for l in lines)}
        self.orders[saved["order_id"]] = saved
        return saved


class PricingParityTests(unittest.TestCase):
    def setUp(self):
        BTC._ORDERS.clear()
        BTC._ONCE_USED.clear()

    def test_single_unit_matrix_matches_btc(self):
        """All products/variants across expiry boundaries, addresses and CRM."""
        owner = next(c["phone"] for c in BTC.CRM if "SKU-AP-X-2024" in BTC._owned_skus(c["phone"]))
        ambiguous = next(c["phone"] for c in BTC.CRM if c.get("shared_phone_with"))
        skus = [p["sku"] for p in BTC.PRODUCTS] + [v["variant_sku"] for p in BTC.PRODUCTS for v in p.get("variants", [])]
        for phone, address, on in itertools.product([None, owner, ambiguous], [None, "Hồ Chí Minh", "Đà Nẵng"],
                                                   ["2026-09-30", "2026-10-15", "2026-11-04", "2026-11-11"]):
            engine = PricingCalculator(FixtureDB(), date.fromisoformat(on), customer_phone=phone, address=address)
            for sku in skus:
                with self.subTest(sku=sku, phone=bool(phone), address=address, on=on):
                    expected = BTC.pricing_get_quote(sku, on=on, customer_phone=phone, address=address)
                    expected.pop("_internal_price_floor_vnd", None)
                    self.assertEqual(engine.quote(sku), expected)

    def test_order_matrix_matches_btc_per_unit_and_total(self):
        owner = next(c["phone"] for c in BTC.CRM if "SKU-AP-X-2024" in BTC._owned_skus(c["phone"]))
        baskets = [
            [{"sku": "SKU-AP-PRO", "qty": n}] for n in (1, 2, 3, 4)
        ] + [
            [{"sku": "SKU-SS-AX40"}, {"sku": "SKU-AP-X"}],
            [{"sku": "SKU-AP-X"}, {"sku": "SKU-SS-AX40"}],
            [{"sku": "SKU-AP-PRO"}, {"sku": "SKU-AP-PRO"}],
            [{"sku": "SKU-AP-PRO"}, {"sku": "SKU-AP-X", "qty": 2}],
            [{"sku": "SKU-AP-MINI", "qty": 2}, {"sku": "SKU-AP-PRO"}],
            [{"sku": "SKU-SN-RUN2-42-DEN", "qty": 2}, {"sku": "SKU-AP-PRO"}],
        ]
        for lines, on, phone, address in itertools.product(baskets,
                ["2026-10-15", "2026-10-31", "2026-11-05", "2026-11-11"], [None, owner], [None, "HCM"]):
            with self.subTest(lines=lines, on=on, owner=bool(phone), address=address):
                engine = PricingCalculator(FixtureDB(), date.fromisoformat(on), customer_phone=phone, address=address)
                self.assertEqual(engine.quote_order(lines),
                                 BTC.pricing_quote_order(lines, on=on, customer_phone=phone, address=address))

    def test_get_quote_only_strictly_cheapest_air_unit_gets_half_price(self):
        engine = PricingCalculator(FixtureDB(), date.fromisoformat(BTC.REF))
        for sku, basket in [("SKU-AP-PRO", ["SKU-AP-PRO"]), ("SKU-AP-X", ["SKU-SS-AX40"]),
                            ("SKU-SS-AX40", ["SKU-AP-X"]), ("SKU-AP-X", ["SKU-SN-RUN2"])]:
            expected = BTC.pricing_get_quote(sku, basket_skus=basket)
            expected.pop("_internal_price_floor_vnd")
            self.assertEqual(engine.quote(sku, basket_skus=basket), expected)


class OrderParityTests(unittest.TestCase):
    def setUp(self):
        BTC._ORDERS.clear()
        BTC._ONCE_USED.clear()
        self.db = FixtureDB()
        self.patchers = [patch.object(catalog, "db_client", self.db), patch.object(order, "db_client", self.db),
                         patch("telesale_agent.core.business_time.datetime")]
        for patcher in self.patchers:
            mocked = patcher.start()
            if patcher is self.patchers[-1]:
                mocked.now.return_value = datetime(2026, 10, 15, tzinfo=timezone(timedelta(hours=7)))
            self.addCleanup(patcher.stop)

    def compare_order(self, **kwargs):
        args = {"customer_phone": "0900000000", "address": "Hà Nội", **kwargs}
        expected = BTC.order_create(**args)
        actual = order.order_create(**args)
        if expected.get("error"):
            self.assertEqual(actual.get("error"), expected["error"])
            if "total_vnd" in expected:
                self.assertEqual(actual["total_vnd"], expected["total_vnd"])
            if "expected_units" in expected:
                self.assertEqual(actual["expected_units"], expected["expected_units"])
        else:
            self.assertEqual({k: v for k, v in actual.items() if k != "order_id"},
                             {k: v for k, v in expected.items() if k != "order_id"})
        return actual

    def test_legacy_single_sku_order_and_delivery_holidays(self):
        for address in ("Hà Nội", "Hồ Chí Minh", "Huế"):
            self.compare_order(sku="SKU-AP-X", qty=1, price_vnd=4_890_000, address=address, on="2026-10-23")

    def test_multiline_order_and_cod_retry_match_btc(self):
        lines = [{"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                 {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000}]
        self.compare_order(lines=lines, payment="COD")
        self.assertFalse(self.db.orders)
        result = self.compare_order(lines=lines, payment="bank")
        self.assertEqual(result["total_vnd"], 11_685_000)
        saved = next(iter(self.db.orders.values()))
        self.assertEqual([l["price_vnd"] for l in saved["lines"]], [7_690_000, 3_995_000])

    def test_wrong_unit_prices_and_legacy_qty_two_are_rejected(self):
        self.compare_order(sku="SKU-AP-PRO", qty=2, price_vnd=3_995_000, payment="bank")
        self.assertFalse(self.db.orders)

    def test_split_equal_price_orders_only_one_half_price(self):
        common = {"sku": "SKU-AP-PRO", "basket_skus": ["SKU-AP-PRO"], "payment": "bank"}
        self.compare_order(**common, price_vnd=7_690_000)
        self.compare_order(**common, price_vnd=3_995_000)
        self.compare_order(**common, price_vnd=7_690_000)

    def test_once_per_customer_uses_successful_order_history(self):
        self.compare_order(sku="SKU-SN-RUN2-42-DEN", price_vnd=None)
        self.compare_order(sku="SKU-SN-RUN2-42-DEN", price_vnd=None)

    def test_idempotent_replay_precedes_stock_and_promotion_checks(self):
        args = {"customer_phone": "0900000000", "sku": "SKU-SN-RUN2-42-DEN", "qty": 1,
                "price_vnd": 1_521_000, "address": "Hà Nội", "idempotency_key": "retry-1"}
        first = order.order_create(**args)
        self.assertNotIn("error", first)
        with patch.object(order, "inventory_check", side_effect=AssertionError("Replay cannot check stock")):
            replay = order.order_create(**args)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["order_id"], replay["order_id"])
        self.assertEqual(len(self.db.orders), 1)
        self.assertEqual(order.order_create(**{**args, "qty": 2})["error"], "idempotency_conflict")

    def test_multiline_idempotent_retry_and_changed_price_conflict(self):
        args = {"customer_phone": "0900000000", "lines": [{"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000}], "payment": "bank", "address": "HCM", "idempotency_key": "cart-1"}
        first = order.order_create(**args)
        self.assertTrue(order.order_create(**args)["idempotent_replay"])
        changed = copy.deepcopy(args)
        changed["lines"][1]["price_vnd"] += 1
        self.assertEqual(order.order_create(**changed)["error"], "idempotency_conflict")
        self.assertEqual(first["total_vnd"], 11_685_000)

    def test_pre_migration_order_can_be_replayed_with_legacy_arguments(self):
        args = {"customer_phone": "0900000000", "sku": "SKU-AP-X", "qty": 1, "price_vnd": 4_890_000,
                "promo_code": None, "payment": "COD", "address": "Hà Nội", "idempotency_key": "legacy"}
        first = order.order_create(**args)
        saved = self.db.orders[first["order_id"]]
        saved["promo_code"] = None

        saved.pop("lines")

        replay = order.order_create(**args)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["total_vnd"], 4_890_000)

    def test_duplicate_sku_stock_is_checked_in_aggregate(self):
        with patch.object(order, "inventory_check", return_value={"in_stock": True, "qty": 1}):
            result = order.order_create("0900000000", lines=[{"sku": "SKU-AP-PRO", "qty": 1}, {"sku": "SKU-AP-PRO", "qty": 1}], address="HCM")
        self.assertEqual(result["error"], "out_of_stock")
        self.assertFalse(self.db.orders)

    def test_invalid_lines_do_not_create_orders(self):
        for lines in ([], [{"sku": "SKU-AP-X", "qty": 0}], [{"sku": "SKU-AP-X", "qty": True}], [{"sku": "SKU-AP-X", "price_vnd": -1}]):
            self.assertIn("error", order.order_create("0900000000", lines=lines, address="HCM"))
        self.assertFalse(self.db.orders)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.orm import sessionmaker
        from telesale_agent.adapters.db.client import PostgresClient
        from telesale_agent.adapters.db.models import Customer, Order

        @compiles(JSONB, "sqlite")
        def sqlite_jsonb(type_, compiler, **kwargs):
            return "JSON"

        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Customer.__table__.create(self.engine)
        Order.__table__.create(self.engine)
        self.db = object.__new__(PostgresClient)
        self.db.SessionLocal = sessionmaker(bind=self.engine)
        with self.db.get_session() as session:
            session.add(Customer(customer_id="C-test", phone="0900000000"))
            session.commit()
        self.addCleanup(self.engine.dispose)

    def test_round_trip_multiline_and_legacy_orders(self):
        common = dict(customer_phone="0900000000", sku="SKU-AP-PRO", qty=2, price_vnd=7_690_000,
                      promo_code="AIR-OCT", payment="bank", address="HCM", order_date=date(2026, 10, 15))
        lines = [{"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                 {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000}]
        saved = self.db.create_order(**common, order_id="NEW", lines=[{**l, "promos": ["AIR-OCT", "AIR-2ND-50"]} for l in lines])
        self.assertEqual([{k: v for k, v in l.items() if k != "promos"} for l in saved["lines"]], lines)
        self.assertEqual(self.db.find_orders(order_id="NEW")[0]["total_vnd"], 11_685_000)
        legacy = self.db.create_order(**common, order_id="OLD")
        self.assertEqual(legacy["total_vnd"], 15_380_000)
        self.assertEqual(legacy["lines"], [{"sku": "SKU-AP-PRO", "qty": 2, "price_vnd": 7_690_000}])
        self.assertIn("AIR-2ND-50", self.db.get_pricing_customer_context(customer_phone="0900000000")["used_promos"])

    def test_migration_preserves_existing_orders_and_is_repeatable(self):
        from sqlalchemy import inspect, text
        migration_spec = importlib.util.spec_from_file_location("btc_order_migration", ROOT / "scripts/migrate_catalog.py")
        migration = importlib.util.module_from_spec(migration_spec)
        migration_spec.loader.exec_module(migration)
        with self.engine.begin() as connection:
            for column in ("lines",):
                connection.execute(text(f'ALTER TABLE orders DROP COLUMN "{column}"'))
            connection.execute(text("INSERT INTO orders (order_id, customer_id, sku, qty, price_vnd, payment, exchange_count) VALUES ('OLD', 'C-test', 'SKU-AP-X', 2, 4890000, 'COD', 0)"))
        migration.migrate_orders(self.engine)
        migration.migrate_orders(self.engine)
        columns = {c["name"] for c in inspect(self.engine).get_columns("orders")}
        self.assertIn("lines", columns)
        saved = self.db.find_orders(order_id="OLD")[0]
        self.assertEqual(saved["total_vnd"], 9_780_000)
        self.assertEqual(saved["lines"], [{"sku": "SKU-AP-X", "qty": 2, "price_vnd": 4_890_000}])


if __name__ == "__main__":
    unittest.main()
