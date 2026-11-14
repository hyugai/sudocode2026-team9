"""Live clock, dependency failure and optional tracing regressions."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from langsmith import utils

from test_btc_contract import btc_db
from telesale_agent.core import business_time
from telesale_agent.core.models import ConversationState, TurnContext, TurnInput
from telesale_agent.application.conversation.prepare import prepare_context
from telesale_agent.entrypoints.api import chat, catalog as public_catalog, readiness
from telesale_agent.adapters.llm import tracing
from mcp_servers.tools import catalog, order


def freeze_clock(monkeypatch, instant):
    clock = Mock()
    clock.now.side_effect = lambda tz: instant.astimezone(tz)
    monkeypatch.setattr(business_time, "datetime", clock)


def test_clock_uses_vietnam_date_at_utc_midnight_boundary(monkeypatch):
    freeze_clock(monkeypatch, datetime(2026, 11, 14, 18, tzinfo=timezone.utc))
    assert business_time.business_date() == date(2026, 11, 15)
    assert business_time.business_date("2026-10-15") == date(2026, 10, 15)
    assert business_time.business_date(date(2026, 10, 15)) == date(2026, 10, 15)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, "2026-10-15"])
async def test_prepare_pins_today_or_explicit_replay_before_customer_loading(monkeypatch, explicit):
    freeze_clock(monkeypatch, datetime(2026, 11, 14, 18, tzinfo=timezone.utc))
    metadata = {"call_date": explicit} if explicit else {}
    context = TurnContext(TurnInput("date-test", text="Xin chào", metadata=metadata), ConversationState("date-test"))
    expected = explicit or "2026-11-15"
    async def identity(item):
        assert item.input.metadata["call_date"] == expected
    services = SimpleNamespace(identity=SimpleNamespace(resolve_identity=identity), customer_context=None,
                               perceive=None, retrieve=None, call_brief=None)
    await prepare_context(services, context)
    assert context.input.metadata["call_date"] == expected


def test_web_agent_and_explicit_replay_share_price_and_inventory_dates(btc_db, monkeypatch):
    _, db = btc_db
    freeze_clock(monkeypatch, datetime(2026, 11, 14, 18, tzinfo=timezone.utc))
    monkeypatch.setattr(public_catalog, "db_client", db)
    client = TestClient(chat.app)
    try:
        live = client.get("/api/catalog/products/SKU-MB-STR1")
        replay = client.get("/api/catalog/products/SKU-MB-STR1", params={"on": "2026-10-15"})
        assert live.status_code == replay.status_code == 200
        assert live.json()["stock"] == catalog.inventory_check("SKU-MB-STR1")["qty"] == 0
        assert replay.json()["stock"] == catalog.inventory_check("SKU-MB-STR1", on="2026-10-15")["qty"] == 2
        lines = [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]
        assert catalog.pricing_quote_order(lines)["total_vnd"] == 18_170_000
        assert catalog.pricing_quote_order(lines, on="2026-10-15")["total_vnd"] == 16_475_000
        assert client.get("/api/catalog/products", params={"on": "2026-02-30"}).status_code == 422
    finally:
        client.close()


def test_legacy_order_replay_keeps_original_date_price_and_rows(btc_db, monkeypatch):
    reference, db = btc_db
    baseline = deepcopy(db.find_orders())
    args = dict(customer_phone=reference.CRM[0]["phone"], sku="SKU-AP-PRO", qty=1,
                price_vnd=7_690_000, payment="bank", address="Hà Nội", idempotency_key="old-date-replay")
    original = order.order_create(**args, on="2026-10-15")
    assert "error" not in original
    freeze_clock(monkeypatch, datetime(2026, 11, 14, 18, tzinfo=timezone.utc))
    replay = order.order_create(**args)
    assert replay["idempotent_replay"]
    for key in ("order_id", "estimated_delivery", "total_vnd"):
        assert replay[key] == original[key]
    for row in baseline:
        assert db.find_orders(order_id=row["order_id"])[0] == row


@pytest.mark.parametrize("audio", [False, True])
@pytest.mark.parametrize("explicit", [None, "2026-10-15"])
def test_chat_api_passes_validated_business_date_without_changing_old_clients(monkeypatch, audio, explicit):
    freeze_clock(monkeypatch, datetime(2026, 11, 14, 18, tzinfo=timezone.utc))
    captured = []
    async def run(item, **kwargs):
        captured.append(item)
        return {"response": "ok"}
    monkeypatch.setattr(chat, "run_chat_turn", run)
    monkeypatch.setattr(chat, "harness", SimpleNamespace(asr=None))
    monkeypatch.setattr(chat, "conversation_owner", AsyncMock(return_value=(None, None)))
    monkeypatch.setenv("API_KEY", "")
    payload = {"conversation_id": "date-test", "customer_phone": "0990000000"}
    if explicit:
        payload["call_date"] = explicit
    client = TestClient(chat.app)
    try:
        if audio:
            response = client.post("/api/chat/audio", data=payload, files={"file": ("voice.wav", b"audio", "audio/wav")})
        else:
            response = client.post("/api/chat", json={**payload, "message": "Xin chào"})
        assert response.status_code == 200
        assert captured[-1].metadata["call_date"] == (explicit or "2026-11-15")
        payload["call_date"] = "2026-02-30"
        if audio:
            response = client.post("/api/chat/audio", data=payload, files={"file": ("voice.wav", b"audio", "audio/wav")})
        else:
            response = client.post("/api/chat", json={**payload, "message": "Xin chào"})
        assert response.status_code == 422
    finally:
        client.close()


def ready_harness():
    return SimpleNamespace(agent=object(), mcp_sessions={name: SimpleNamespace(send_ping=AsyncMock())
                                                       for name in ("db", "knowledge", "workflow")})


@pytest.mark.asyncio
async def test_readiness_checks_every_live_session_and_database(monkeypatch):
    database = Mock()
    monkeypatch.setattr(readiness, "probe_database", database)
    harness = ready_harness()
    assert all(value == "ok" for value in (await readiness.check_readiness(harness)).values())
    database.assert_called_once()
    for session in harness.mcp_sessions.values():
        session.send_ping.assert_awaited_once()


@pytest.mark.parametrize("path", ["/health", "/api/health"])
@pytest.mark.parametrize("failed", ["database", "db", "knowledge", "workflow"])
def test_health_returns_503_on_dependency_failure_without_leaking_errors(monkeypatch, path, failed):
    harness = ready_harness()
    failure = RuntimeError("secret-database-url-or-token")
    monkeypatch.setattr(readiness, "probe_database", Mock(side_effect=failure if failed == "database" else None))
    if failed != "database":
        harness.mcp_sessions[failed].send_ping.side_effect = failure
    monkeypatch.setattr(chat, "harness", harness)
    client = TestClient(chat.app)
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["checks"]["database" if failed == "database" else "mcp_" + failed] == "unavailable"
        assert "secret" not in response.text
    finally:
        client.close()


@pytest.mark.asyncio
async def test_dead_mcp_ping_is_bounded_and_missing_session_is_not_ready(monkeypatch):
    monkeypatch.setattr(readiness, "probe_database", Mock())
    harness = ready_harness()
    async def stalled():
        await asyncio.sleep(10)
    harness.mcp_sessions["db"].send_ping.side_effect = stalled
    del harness.mcp_sessions["knowledge"]
    result = await asyncio.wait_for(readiness.check_readiness(harness, timeout=.02), timeout=1)
    assert result["mcp_db"] == "timeout"
    assert result["mcp_knowledge"] == "unavailable"
    assert result["mcp_workflow"] == "ok"


def test_health_startup_503_and_healthy_200_keep_top_level_status(monkeypatch):
    monkeypatch.setattr(readiness, "probe_database", Mock())
    monkeypatch.setattr(chat, "harness", None)
    client = TestClient(chat.app)
    try:
        assert client.get("/health").status_code == 503
        monkeypatch.setattr(chat, "harness", ready_harness())
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        client.close()


@pytest.fixture
def tracing_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("LANGSMITH_", "LANGCHAIN_", "HOSTED_LANGSERVE_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-secret")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "test-project")
    monkeypatch.setattr(tracing, "_status", {"status": "disabled", "reason": "not_configured"})
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(tracing, "Client", factory)
    utils.get_env_var.cache_clear()
    utils.get_tracer_project.cache_clear()
    yield factory, client
    utils.get_env_var.cache_clear()
    utils.get_tracer_project.cache_clear()


@pytest.mark.parametrize("failure,reason", [(utils.LangSmithError("403 Forbidden test-secret"), "authorization_failed"),
    (utils.LangSmithAuthError("401 test-secret"), "authorization_failed"),
    (utils.LangSmithConnectionError("test-secret"), "unavailable")])
def test_tracing_preflight_disables_failed_remote_tracing_only_in_process(tracing_environment, caplog, failure, reason):
    factory, client = tracing_environment
    client.read_project.side_effect = failure
    assert tracing.configure_tracing() == {"status": "disabled", "reason": reason}
    assert utils.tracing_is_enabled() is False
    assert os.environ["LANGCHAIN_API_KEY"] == "test-secret"
    assert "test-secret" not in caplog.text
    assert tracing.configure_tracing()["reason"] == reason
    factory.assert_called_once()


@pytest.mark.parametrize("missing_project", [False, True])
def test_valid_tracing_remains_enabled_and_missing_project_can_be_created(tracing_environment, missing_project):
    _, client = tracing_environment
    if missing_project:
        client.read_project.side_effect = utils.LangSmithNotFoundError("Not found")
    assert tracing.configure_tracing() == {"status": "enabled"}
    assert utils.tracing_is_enabled() is True
    client.read_project.assert_called_once_with(project_name="test-project")
    client.close.assert_called_once_with(timeout=0)


def test_explicit_disabled_tracing_does_not_contact_remote(tracing_environment, monkeypatch):
    factory, _ = tracing_environment
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "false")
    assert tracing.configure_tracing()["status"] == "disabled"
    factory.assert_not_called()


def test_missing_tracing_key_does_not_contact_remote(tracing_environment, monkeypatch):
    factory, _ = tracing_environment
    monkeypatch.delenv("LANGCHAIN_API_KEY")
    assert tracing.configure_tracing()["reason"] == "missing_api_key"
    factory.assert_not_called()
