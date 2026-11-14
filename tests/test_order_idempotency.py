from __future__ import annotations

from mcp_servers.tools import order as order_module


class FakeDB:
    def __init__(self):
        self.orders = {}
        self.create_calls = 0

    def find_orders(self, *, order_id=None, customer_phone=None):
        if order_id and order_id in self.orders:
            return [dict(self.orders[order_id])]
        return []

    def create_order(self, **payload):
        self.create_calls += 1
        self.orders[payload["order_id"]] = {
            **payload,
            "created_on": payload["order_date"].isoformat(),
            "status": "created",
        }
        return dict(self.orders[payload["order_id"]])

    def search_products(self, **_):
        return {"items": [{"sku": "SKU-AP-X", "category": "gia-dung/may-loc-khong-khi",
                           "list_price_vnd": 4_890_000, "variants": []}]}

    def get_promotions(self):
        return []

    def get_pricing_customer_context(self, **_):
        return {"owned_skus": [], "used_promos": []}


def test_order_create_replays_same_idempotency_key(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(order_module, "db_client", fake_db)
    monkeypatch.setattr(
        order_module,
        "inventory_check",
        lambda sku, on=None: {"sku": sku, "in_stock": True, "qty": 10},
    )
    arguments = {
        "customer_phone": "0984726714",
        "sku": "SKU-AP-X",
        "qty": 1,
        "price_vnd": 4_890_000,
        "payment": "COD",
        "address": "100 đường Kiểm Thử, Hà Nội",
        "on": "2026-10-17",
        "idempotency_key": "conversation:call_2:turn3:create:SKU-AP-X",
    }

    first = order_module.order_create(**arguments)
    second = order_module.order_create(**arguments)

    assert first["order_id"] == second["order_id"]
    assert second["idempotent_replay"] is True
    assert fake_db.create_calls == 1


def test_order_create_rejects_reused_key_with_different_payload(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(order_module, "db_client", fake_db)
    monkeypatch.setattr(
        order_module,
        "inventory_check",
        lambda sku, on=None: {"sku": sku, "in_stock": True, "qty": 10},
    )
    arguments = {
        "customer_phone": "0984726714",
        "sku": "SKU-AP-X",
        "qty": 1,
        "price_vnd": 4_890_000,
        "payment": "COD",
        "address": "100 đường Kiểm Thử, Hà Nội",
        "on": "2026-10-17",
        "idempotency_key": "same-key",
    }
    order_module.order_create(**arguments)

    result = order_module.order_create(**{**arguments, "qty": 2})

    assert result["error"] == "idempotency_conflict"
    assert fake_db.create_calls == 1
