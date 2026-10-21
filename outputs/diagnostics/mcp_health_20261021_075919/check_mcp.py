"""Diagnostic only: real MCP reads, isolated memory, mocked order writes.

No Gemini generation, production memory writes, or production order mutations.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
OUT = Path(__file__).resolve().parent
REPORT = {
    "started_at": datetime.now().astimezone().isoformat(),
    "scope": "Actual backend MCP initialization and read-only/guard calls; order success paths use mocks; standalone memory uses an isolated output directory.",
    "gemini_generation_requests": 0,
    "checks": [],
    "observations": [
        "Runtime loads DB, Knowledge, Workflow. Standalone Memory MCP is not loaded by runtime.",
        "Workflow callback/handoff generate identifiers but do not persist or dispatch work.",
        "Successful production order creation/update is deliberately not exercised.",
    ],
}


def record(name, passed, elapsed, evidence=None):
    row = {"name": name, "passed": bool(passed), "elapsed_seconds": round(elapsed, 6)}
    if evidence is not None:
        row["evidence"] = evidence
    REPORT["checks"].append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
    save()


def save():
    (OUT / "report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize(value):
    if isinstance(value, dict):
        safe_keys = ("error", "found", "ambiguous", "sku", "in_stock", "qty", "list_price_vnd", "final_price_vnd", "count", "callback_at", "moved_from", "status")
        safe = {key: value[key] for key in safe_keys if key in value}
        if "items" in value:
            safe["items_count"] = len(value["items"])
            safe["skus"] = [item.get("sku") for item in value["items"][:3]]
        if "orders" in value:
            safe["orders_count"] = len(value["orders"])
        if "chunks" in value:
            safe["chunks"] = [{key: c.get(key) for key in ("chunk_id", "source_file")} for c in value["chunks"]]
        if "callback_id" in value:
            safe["has_callback_id"] = bool(value["callback_id"])
        if "ticket_id" in value:
            safe["has_ticket_id"] = bool(value["ticket_id"])
        # Error messages can contain provider connection metadata: redact configured secrets.
        if "error" in safe:
            error = str(safe["error"])
            for key in ("DATABASE_URL", "PINECONE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
                secret = os.environ.get(key)
                if secret:
                    error = error.replace(secret, "[redacted]")
            safe["error"] = error[:700]
        return safe
    return {"type": type(value).__name__, "nonempty": bool(value)}


async def call(tools, tool_name, args, label, predicate):
    from telesale_agent.application.deepagent.tools.protocol import decode_tool_result
    started = time.perf_counter()
    try:
        result = decode_tool_result(await asyncio.wait_for(tools[tool_name].ainvoke(args), timeout=65))
        passed = predicate(result)
        record(label, passed, time.perf_counter() - started, summarize(result))
        return result
    except Exception as exc:
        record(label, False, time.perf_counter() - started, {"exception_type": type(exc).__name__})
        return None


async def check_runtime():
    from telesale_agent.bootstrap import build_deepagent_harness
    from telesale_agent.adapters.db.client import db_client
    from telesale_agent.adapters.db.models import Customer, Order, Product

    harness = build_deepagent_harness()
    started = time.perf_counter()
    try:
        await asyncio.wait_for(harness.__aenter__(), timeout=90)
        expected = {
            "retrieve_customer_profile", "search_catalog", "check_inventory", "get_pricing_quote",
            "create_new_order", "check_order_status", "update_order", "search_policy",
            "mcp_schedule_callback", "mcp_escalate_to_human",
        }
        if callable(getattr(harness.memory, "search_archive", None)):
            expected.add("search_customer_memory_archive")
        REPORT["registered_tools"] = sorted(harness.mcp_tools)
        record("runtime.initialize_and_tool_discovery", expected == set(harness.mcp_tools), time.perf_counter()-started, {"tool_count": len(harness.mcp_tools), "missing": sorted(expected-set(harness.mcp_tools))})
        tools = harness.mcp_tools
        customer = db_client.get_customer_by_id("C001")
        phone = customer.get("phone")
        with db_client.get_session() as session:
            REPORT["database_counts_before"] = {"products": session.query(Product).count(), "customers": session.query(Customer).count(), "orders": session.query(Order).count()}
            first_order = session.query(Order).first()
            order_id = first_order.order_id if first_order else None
        if not phone or not order_id:
            raise RuntimeError("Expected seed customer or order unavailable")
        ok = lambda r: isinstance(r, dict) and not r.get("error")
        await call(tools, "retrieve_customer_profile", {"phone":phone}, "db.crm_existing", lambda r:ok(r) and r.get("found") and r.get("customer_id")=="C001")
        await call(tools, "retrieve_customer_profile", {"phone":"0000000000"}, "db.crm_not_found", lambda r:ok(r) and r.get("found") is False)
        await call(tools, "search_catalog", {"sku":"SKU-AP-X"}, "db.catalog_exact_sku", lambda r:ok(r) and any(i.get("sku")=="SKU-AP-X" for i in r.get("items",[])))
        await call(tools, "search_catalog", {"query":"AirPure X"}, "db.catalog_text_search", lambda r:ok(r) and bool(r.get("items")))
        await call(tools, "search_catalog", {"sku":"MCP-CHECK-NONEXISTENT"}, "db.catalog_not_found", lambda r:ok(r) and r.get("items")==[])
        await call(tools, "check_inventory", {"sku":"SKU-AP-X"}, "db.inventory_existing", lambda r:ok(r) and r.get("found") and isinstance(r.get("qty"),int))
        await call(tools, "check_inventory", {"sku":"MCP-CHECK-NONEXISTENT"}, "db.inventory_not_found", lambda r:ok(r) and r.get("found") is False and r.get("in_stock") is False)
        await call(tools, "get_pricing_quote", {"sku":"SKU-AP-X","customer_id":"C001"}, "db.pricing_existing", lambda r:ok(r) and r.get("sku")=="SKU-AP-X" and 0<=r.get("final_price_vnd",-1)<=r.get("list_price_vnd",-1))
        await call(tools, "get_pricing_quote", {"sku":"MCP-CHECK-NONEXISTENT"}, "db.pricing_not_found", lambda r:isinstance(r,dict) and r.get("error")=="product_not_found")
        await call(tools, "check_order_status", {"order_id":order_id}, "db.order_status_existing", lambda r:ok(r) and any(o.get("order_id")==order_id for o in r.get("orders",[])))
        await call(tools, "check_order_status", {"order_id":"MCP-CHECK-NONEXISTENT"}, "db.order_status_not_found", lambda r:ok(r) and r.get("orders")==[])
        await call(tools, "create_new_order", {"customer_phone":"0000000000","sku":"SKU-AP-X","price_vnd":4890000,"qty":1,"address":""}, "db.order_create_guard_missing_address", lambda r:isinstance(r,dict) and r.get("error")=="missing_delivery_address")
        await call(tools, "create_new_order", {"customer_phone":"0000000000","sku":"SKU-AP-X","price_vnd":11000000,"qty":1,"address":"MCP diagnostic, no order should be created"}, "db.order_create_guard_cod_limit", lambda r:isinstance(r,dict) and r.get("error")=="cod_limit_exceeded")
        await call(tools, "update_order", {"order_id":"MCP-CHECK-NONEXISTENT","action":"return"}, "db.order_update_not_found", lambda r:isinstance(r,dict) and r.get("error")=="order_not_found")
        for label,query in [
            ("returns", "Chính sách đổi trả hàng và đổi size như thế nào?"),
            ("shipping", "Chính sách vận chuyển và thanh toán COD như thế nào?"),
            ("warranty", "Chính sách bảo hành sản phẩm như thế nào?"),
        ]:
            await call(tools, "search_policy", {"query":query,"k":3}, "knowledge.pinecone_"+label, lambda r:ok(r) and r.get("count",0)>0 and all(c.get("chunk_id") and c.get("source_file") for c in r.get("chunks",[])))
        await call(tools, "search_policy", {"query":" ","k":3}, "knowledge.empty_query_guard", lambda r:isinstance(r,dict) and r.get("error")=="query_required")
        # These workflow tools currently have no persistence or external dispatch.
        await call(tools, "mcp_schedule_callback", {"customer_phone":"0000000000","callback_at":"2026-10-21T14:00:00","note":"MCP diagnostic"}, "workflow.callback_weekday", lambda r:ok(r) and bool(r.get("callback_id")) and r.get("callback_at")=="2026-10-21T14:00:00" and r.get("moved_from") is None)
        await call(tools, "mcp_schedule_callback", {"customer_phone":"0000000000","callback_at":"2026-10-20T14:00:00","note":"MCP diagnostic"}, "workflow.callback_holiday_shift", lambda r:ok(r) and r.get("callback_at")=="2026-10-21T14:00:00" and r.get("moved_from")=="2026-10-20T14:00:00")
        await call(tools, "mcp_escalate_to_human", {"reason":"MCP diagnostic","customer_id":"MCP_DIAGNOSTIC","summary":"Synthetic MCP diagnostic; no human is contacted."}, "workflow.handoff_contract", lambda r:ok(r) and bool(r.get("ticket_id")) and r.get("status")=="queued")
        with db_client.get_session() as session:
            REPORT["database_counts_after"] = {"products": session.query(Product).count(), "customers": session.query(Customer).count(), "orders": session.query(Order).count()}
        record("db.counts_unchanged", REPORT["database_counts_before"]==REPORT["database_counts_after"], 0, REPORT["database_counts_after"])
    except Exception as exc:
        record("runtime.exception", False, time.perf_counter()-started, {"exception_type":type(exc).__name__})
    finally:
        await harness.__aexit__(None,None,None)


def check_order_mock_contracts():
    import mcp_servers.mcp_db as server
    import mcp_servers.tools.order as order
    fake = Mock()
    args = {"customer_phone":"0000000000","sku":"SKU-AP-X","price_vnd":4890000,"qty":1,"address":"Isolated mock diagnostic","idempotency_key":"mcp-diagnostic-only"}
    generated = "ORD-"+hashlib.sha256(args["idempotency_key"].encode()).hexdigest()[:8].upper()
    started=time.perf_counter()
    with patch.object(order,"db_client",fake), patch.object(order,"inventory_check",return_value={"in_stock":True,"qty":100}):
        fake.find_orders.return_value=[]
        fake.create_order.return_value={"order_id":generated}
        result=server.create_new_order(**args)
        record("order.mock_create_success", result.get("order_id")==generated and fake.create_order.call_count==1, time.perf_counter()-started, {"status":result.get("status"),"database":"mock"})
        stored={k:v for k,v in args.items() if k!="idempotency_key"}
        stored.update(payment=stored.pop("payment_method","COD"),promo_code=None,created_on="2026-10-15")
        fake.find_orders.return_value=[stored]
        result=server.create_new_order(**args)
        record("order.mock_idempotent_replay", result.get("idempotent_replay") is True and fake.create_order.call_count==1, time.perf_counter()-started, {"database":"mock"})
        result=server.create_new_order(**{**args,"qty":2})
        record("order.mock_idempotency_conflict", result.get("error")=="idempotency_conflict" and fake.create_order.call_count==1, time.perf_counter()-started, {"database":"mock"})
        fake.find_orders.return_value=[{"exchange_count":0}]
        fake.update_order.return_value={"status":"exchange_size"}
        result=server.update_order(order_id=generated,action="exchange_size",new_variant_sku="MCP-MOCK-VARIANT")
        record("order.mock_update_success", result.get("status")=="exchange_size" and result.get("fee_vnd")==0 and fake.update_order.call_count==1, time.perf_counter()-started, {"database":"mock"})


async def check_standalone_memory():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain_mcp_adapters.tools import load_mcp_tools
    env=os.environ.copy()
    memory_root=OUT/"isolated_memory"
    env["CUSTOMER_MEMORY_ROOT"]=str(memory_root)
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/"src/mcp_servers/mcp_memory.py")],env=env)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            started=time.perf_counter()
            await session.initialize()
            tools={t.name:t for t in await load_mcp_tools(session)}
            REPORT["standalone_memory_tools"]=sorted(tools)
            record("memory.standalone_discovery",len(tools)==5,time.perf_counter()-started,{"runtime_loaded":False,"root":"isolated_memory"})
            checks=[
                ("memory_update_user_profile",{"identity_and_preferences":"MCP diagnostic profile"},"user.md"),
                ("memory_update_behaviors",{"behavioral_pattern":"MCP diagnostic behavior"},"behaviors.md"),
                ("memory_record_atomic_fact",{"fact":"MCP diagnostic atomic fact"},"atomic_facts/*.md"),
                ("memory_record_foresight",{"foresight":"MCP diagnostic foresight"},"foresights/*.md"),
                ("memory_record_episode",{"narrative_summary":"MCP diagnostic episode"},"episodes/*.md"),
            ]
            for name,args,pattern in checks:
                await call(tools,name,{"user_id":"MCP_DIAGNOSTIC",**args},"memory.isolated_"+name,lambda r,p=pattern:bool(r) and any((memory_root/"MCP_DIAGNOSTIC").glob(p)))


async def main():
    await check_runtime()
    check_order_mock_contracts()
    await check_standalone_memory()
    REPORT["completed_at"]=datetime.now().astimezone().isoformat()
    REPORT["summary"]={"passed":sum(c["passed"] for c in REPORT["checks"]),"failed":sum(not c["passed"] for c in REPORT["checks"])}
    save()
    print(json.dumps({"summary":REPORT["summary"],"report":str(OUT/"report.json")}),flush=True)


if __name__=="__main__":
    asyncio.run(main())
