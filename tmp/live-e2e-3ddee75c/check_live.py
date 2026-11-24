"""One live HTTP/API/MCP check with a dedicated customer and finally cleanup."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from telesale_agent.adapters.db.app_schema import create_app_engine
from telesale_agent.adapters.db.models import Customer, Order
from telesale_agent.adapters.memory.file_memory import FileCustomerMemoryRepository

RUN = '3ddee75c'
CUSTOMER = "E2E-" + RUN
CONVERSATION = "live-e2e-" + RUN
BASE = "http://127.0.0.1:8000"
DIRECTORY = Path(__file__).resolve().parent
engine = create_app_engine()
headers = {"Content-Type": "application/json", "Accept": "application/json"}
if os.environ.get("API_KEY", "").strip():
    headers["X-API-Key"] = os.environ["API_KEY"].strip()
TEST_CALL_DATE = os.environ.get("TEST_CALL_DATE") or None
report = {"run": RUN, "mode": "real HTTP + live MCP + PostgreSQL + configured LLM", "steps": []}
created_customer = False
memory_root = FileCustomerMemoryRepository().root.resolve()
memory_dir = (memory_root / CUSTOMER).resolve()
before_orders = before_customers = None
exit_code = 1


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def snapshot(table, primary):
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout='10s'"))
        rows = connection.execute(text(f'SELECT "{primary}"::text, to_jsonb(t)::text FROM "{table}" AS t ORDER BY "{primary}"')).all()
    digest = hashlib.sha256()
    fingerprints = {}
    for key, body in rows:
        encoded = body.encode("utf-8")
        fingerprints[key] = hashlib.sha256(encoded).hexdigest()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return fingerprints, digest.hexdigest()


def orders():
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        return [{"order_id": row.order_id, "lines": row.lines, "qty": row.qty,
                 "payment": row.payment, "total_vnd": sum(l["price_vnd"] * l.get("qty", 1) for l in row.lines or [])}
                for row in session.scalars(select(Order).where(Order.customer_id == CUSTOMER)).all()]


def request(path, payload=None, method=None, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def turn(label, message):
    emit({"stage": label, "state": "requesting"})
    start = time.monotonic()
    status, payload = request("/api/chat", {"conversation_id": CONVERSATION, "customer_phone": phone, "message": message, **({"call_date": TEST_CALL_DATE} if TEST_CALL_DATE else {})})
    entry = {"stage": label, "http_status": status, "elapsed_seconds": round(time.monotonic() - start, 2),
             "response": payload.get("response"), "latency": payload.get("latency"),
             "test_orders": orders()}
    report["steps"].append(entry)
    (DIRECTORY / (label + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(entry)
    if status != 200:
        raise RuntimeError(f"{label}: HTTP {status}")
    return payload


try:
    if engine.url.database != "telesale" or engine.url.host != "localhost":
        raise RuntimeError("Unexpected DB target")
    if memory_dir.parent != memory_root or memory_dir.exists():
        raise RuntimeError("Test memory must be a new customer directory")
    before_orders = snapshot("orders", "order_id")
    before_customers = snapshot("customers", "customer_id")
    report.update(database="telesale", orders_before=len(before_orders[0]), orders_before_sha256=before_orders[1],
                  customers_before=len(before_customers[0]), customers_before_sha256=before_customers[1])
    status, healthy = request("/health", timeout=5)
    if status != 200 or healthy.get("status") != "ok":
        raise RuntimeError("API not ready")
    with Session(engine) as session:
        if session.get(Customer, CUSTOMER) is not None:
            raise RuntimeError("Test customer already exists")
        for _ in range(20):
            phone = "099" + "".join(secrets.choice("0123456789") for _ in range(7))
            if session.scalar(select(Customer.customer_id).where(Customer.phone == phone)) is None:
                break
        else:
            raise RuntimeError("Cannot reserve unused test phone")
        session.add(Customer(customer_id=CUSTOMER, phone=phone, name="Khách kiểm thử E2E", honorific="anh",
                             region="bac", attributes={"e2e_run": RUN, "sessions": []}))
        session.commit()
        created_customer = True
    spec = importlib.util.spec_from_file_location("btc_live_reference", ROOT / "dataset/organizer/eval/mock_tools.py")
    btc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(btc)
    lines = [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]
    expected = btc.pricing_quote_order(lines, on=TEST_CALL_DATE or __import__("telesale_agent.core.business_time", fromlist=["business_date"]).business_date().isoformat(), customer_phone=phone, address="100 đường Kiểm Thử, Hà Nội")
    expected_units = [(u["sku"], u["final_price_vnd"]) for u in expected["units"]]
    report.update(customer_id=CUSTOMER, conversation_id=CONVERSATION, reference_date=TEST_CALL_DATE or __import__("telesale_agent.core.business_time", fromlist=["business_date"]).business_date().isoformat(),
                  expected_total_vnd=expected["total_vnd"], expected_units=expected_units)
    emit({"stage": "baseline", "orders": len(before_orders[0]), "test_customer": CUSTOMER,
          "expected_total_vnd": expected["total_vnd"], "expected_units": expected_units})
    quote = turn("01_quote", "Tôi muốn mua 2 Máy lọc không khí AirPure Pro và 1 Máy lọc không khí AirPure Mini. Hãy kiểm tra giá từng máy và tổng tiền giỏ này. Chưa tạo đơn.")
    if orders():
        raise RuntimeError("Quote-only request created an order")
    spoken = "".join(c for c in quote.get("response", "") if c.isdigit())
    if str(expected["total_vnd"]) not in spoken:
        quote = turn("02_quote_confirm", "Xin báo rõ tổng tiền của đúng giỏ 2 AirPure Pro và 1 AirPure Mini bằng số tiền VND, chưa tạo đơn.")
        spoken = "".join(c for c in quote.get("response", "") if c.isdigit())
    if str(expected["total_vnd"]) not in spoken:
        raise RuntimeError("HTTP response did not confirm expected basket total")
    if orders():
        raise RuntimeError("Quote follow-up created an order")
    formatted_prices = [f"{price:,}".replace(",", ".") for _, price in expected_units]
    quote_text = quote.get("response", "")
    for price in set(formatted_prices):
        if quote_text.count(price) != formatted_prices.count(price):
            raise RuntimeError("HTTP quote unit price breakdown differs from BTC")
    report["quote_unit_breakdown_passed"] = True
    turn("03_cod_limit", "Tôi chốt đúng giỏ 2 máy AirPure Pro và 1 máy AirPure Mini. Giao 100 đường Kiểm Thử, Hà Nội. Tôi chọn thanh toán COD.")
    if orders():
        raise RuntimeError("Over-limit COD created an order")
    turn("04_bank_create", "Tôi đồng ý chuyển khoản ngân hàng thay cho COD để hoàn tất đơn. Giữ nguyên đúng 2 máy AirPure Pro và 1 máy AirPure Mini, giao 100 đường Kiểm Thử, Hà Nội. Chốt đơn giúp tôi.")
    saved = orders()
    if len(saved) != 1:
        raise RuntimeError(f"Expected one order, got {len(saved)}")
    actual_units = [(l["sku"], l["price_vnd"]) for l in saved[0]["lines"] for _ in range(l.get("qty", 1))]
    if sorted(actual_units) != sorted(expected_units) or saved[0]["total_vnd"] != expected["total_vnd"] or saved[0]["payment"] != "bank":
        raise RuntimeError("Persisted order differs from BTC quote")
    report["created_test_order_ids"] = [saved[0]["order_id"]]
    turn("05_duplicate_retry", "Xác nhận lại đơn vừa chốt: đúng 2 máy AirPure Pro và 1 máy AirPure Mini, chuyển khoản, giao 100 đường Kiểm Thử, Hà Nội. Chốt lại giúp tôi.")
    if len(orders()) != 1 or orders()[0]["order_id"] != saved[0]["order_id"]:
        raise RuntimeError("Retry created a duplicate order")
    report.update(e2e_passed=True, quote_only_did_not_create=True, cod_rejected_without_order=True,
                  bank_order_matches_btc=True, retry_did_not_duplicate=True)
    exit_code = 0
except Exception as exc:
    report.update(e2e_passed=False, failure_type=type(exc).__name__, failure=str(exc)[:400])
    emit({"stage": "failure", "error_type": type(exc).__name__, "reason": str(exc)[:400]})
finally:
    try:
        status, cleared = request("/api/sessions/" + CONVERSATION, method="DELETE", timeout=10)
        report["api_session_cleared"] = status == 200
        if created_customer:
            with Session(engine) as session:
                customer = session.get(Customer, CUSTOMER)
                if customer is None or customer.phone != phone:
                    raise RuntimeError("Test customer ownership mismatch during cleanup")
                owned = session.scalars(select(Order).where(Order.customer_id == CUSTOMER)).all()
                ids = [o.order_id for o in owned]
                if before_orders and set(ids) & set(before_orders[0]):
                    raise RuntimeError("Refusing to delete an original order")
                if ids:
                    session.execute(delete(Order).where(Order.order_id.in_(ids), Order.customer_id == CUSTOMER))
                session.execute(delete(Customer).where(Customer.customer_id == CUSTOMER, Customer.phone == phone))
                session.commit()
                report.update(deleted_test_order_ids=ids, test_customer_deleted=True)
        # Only this unique test customer's new directory may be removed.
        if created_customer and memory_dir.exists():
            if memory_dir.parent != memory_root or memory_dir.name != CUSTOMER or ROOT.resolve() not in memory_dir.parents:
                raise RuntimeError("Refusing to remove a non-test memory directory")
            shutil.rmtree(memory_dir)
        report["test_memory_removed"] = not memory_dir.exists()
        if before_orders is not None:
            after = snapshot("orders", "order_id")
            report.update(orders_after=len(after[0]), orders_after_sha256=after[1], old_orders_unchanged=after == before_orders)
            if after != before_orders:
                raise RuntimeError("Orders differ from the pre-test baseline after cleanup")
        if before_customers is not None:
            after = snapshot("customers", "customer_id")
            report.update(customers_after=len(after[0]), customers_after_sha256=after[1], old_customers_unchanged=after == before_customers)
            if after != before_customers:
                raise RuntimeError("Customers differ from the pre-test baseline after cleanup")
        report["cleanup_passed"] = True
    except Exception as exc:
        report.update(cleanup_passed=False, cleanup_failure=str(exc)[:400])
        exit_code = 1
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    (DIRECTORY / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"stage": "complete", "report_path": str(DIRECTORY / "report.json"),
          "e2e_passed": report.get("e2e_passed"), "cleanup_passed": report.get("cleanup_passed"),
          "orders_before": report.get("orders_before"), "orders_after": report.get("orders_after"),
          "old_orders_unchanged": report.get("old_orders_unchanged")})
    engine.dispose()
sys.exit(exit_code)
