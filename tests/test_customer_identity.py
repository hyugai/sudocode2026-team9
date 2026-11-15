"""Real ORM contact matching; no external database or customer data."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from telesale_agent.adapters.db.customer_identity import get_or_create_customer, normalize_phone
from telesale_agent.adapters.db.models import Customer, Order
from telesale_agent.core.models import ConversationState, TurnContext, TurnInput


@compiles(JSONB, "sqlite")
def sqlite_json(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Customer.__table__.create(engine)
    Order.__table__.create(engine)
    with Session(engine) as session, session.begin():
        session.add(Customer(customer_id="C050", name="Khách cũ", phone="0901234567"))
    yield engine
    engine.dispose()


def test_new_phone_continues_after_c050_and_repeat_reuses_id(database):
    with Session(database) as session, session.begin():
        first, created = get_or_create_customer(session, phone="0912345678")
        assert created and first[0].customer_id == "C051"
    with Session(database) as session, session.begin():
        again, created = get_or_create_customer(session, phone="+84 912 345 678")
        assert not created and again[0].customer_id == "C051"
        assert session.scalar(select(func.count()).select_from(Customer)) == 2


def test_old_phone_and_logged_in_email_share_the_existing_customer(database):
    with Session(database) as session, session.begin():
        old, created = get_or_create_customer(session, phone="+84 901 234 567", email=" Person@Gmail.com ")
        assert not created and old[0].customer_id == "C050"
    with Session(database) as session, session.begin():
        old, created = get_or_create_customer(session, email="person@gmail.com")
        assert not created and old[0].customer_id == "C050"
        assert session.scalar(select(func.count()).select_from(Customer)) == 1


def test_email_only_customer_gets_id_then_can_add_phone(database):
    with Session(database) as session, session.begin():
        new, created = get_or_create_customer(session, email="new@gmail.com", name="Tên khách")
        assert created and new[0].customer_id == "C051"
        assert new[0].phone == ""  # Email must never be stored as a phone.
    with Session(database) as session, session.begin():
        old, created = get_or_create_customer(session, email="NEW@gmail.com", phone="0923456789")
        assert not created and old[0].customer_id == "C051"
        assert old[0].phone == "0923456789"


def test_allocator_uses_numeric_suffix_and_ignores_noncanonical_ids(database):
    with Session(database) as session, session.begin():
        session.add_all([Customer(customer_id=value, phone="") for value in ("C999", "C1000", "C_TEST")])
    with Session(database) as session, session.begin():
        new, _ = get_or_create_customer(session, email="next@example.com")
        assert new[0].customer_id == "C1001"


def test_shared_phone_stays_ambiguous_without_creating_or_merging_customer(database):
    with Session(database) as session, session.begin():
        session.add(Customer(customer_id="C049", phone="0901234567", name="Khách khác"))
    with Session(database) as session, session.begin():
        matches, created = get_or_create_customer(session, phone="+84901234567", email="shared@example.com")
        assert not created and {row.customer_id for row in matches} == {"C049", "C050"}
        assert all(not row.attributes for row in matches)
        assert session.scalar(select(func.count()).select_from(Customer)) == 2


def test_new_phone_does_not_move_existing_email_or_merge_memory_identity(database):
    with Session(database) as session, session.begin():
        get_or_create_customer(session, phone="0901234567", email="old@example.com")
    with Session(database) as session, session.begin():
        new, created = get_or_create_customer(session, phone="0923456789", email="old@example.com")
        assert created and new[0].customer_id == "C051"
        original, created = get_or_create_customer(session, email="old@example.com")
        assert not created and original[0].customer_id == "C050"


def test_explicit_old_phone_wins_over_logged_in_email_customer(database):
    with Session(database) as session, session.begin():
        account, _ = get_or_create_customer(session, email="owner@example.com")
        assert account[0].customer_id == "C051"
    with Session(database) as session, session.begin():
        customer, created = get_or_create_customer(session, phone="0901234567", email="owner@example.com")
        assert not created and customer[0].customer_id == "C050"
        assert not customer[0].attributes
        account, _ = get_or_create_customer(session, email="owner@example.com")
        assert account[0].customer_id == "C051"


@pytest.mark.asyncio
async def test_resolver_creates_new_email_memory_identity_and_recognizes_old_phone(database, monkeypatch):
    from telesale_agent.adapters.db.client import PostgresClient
    from telesale_agent.adapters.mock import identity

    client = object.__new__(PostgresClient)
    client.engine = database
    client.SessionLocal = sessionmaker(bind=database)
    monkeypatch.setattr(identity, "db_client", client)
    resolver = identity.HintIdentityResolver()
    for phone, email, expected in (("+84901234567", None, "C050"),
                                   (None, "new@gmail.com", "C051"),
                                   (None, "NEW@gmail.com", "C051")):
        context = TurnContext(TurnInput("test", text="Xin chào", customer_hint=phone,
                                       metadata={"account_email": email}), ConversationState("test"))
        result = await resolver.resolve_identity(context)
        assert result.customer_id == expected
        assert result.phone == ("0901234567" if expected == "C050" else None)


def test_bad_contacts_are_rejected_before_allocating(database):
    for value in ("hello", "123", "abc@example.com"):
        with pytest.raises(ValueError):
            normalize_phone(value)
    with Session(database) as session, session.begin(), pytest.raises(ValueError):
        get_or_create_customer(session, email="invalid")


@pytest.mark.asyncio
async def test_crm_honorific_reaches_chat_prompt_and_final_salutation(database, monkeypatch):
    from telesale_agent.adapters.db.client import PostgresClient
    from telesale_agent.adapters.mock import identity
    from telesale_agent.adapters.crm import crm_retriever
    from telesale_agent.adapters.memory.in_memory import InMemoryCustomerMemoryRepository
    from telesale_agent.application.customer_context import CustomerContextService
    from telesale_agent.application.memory.call_brief import CallBriefProjector
    from telesale_agent.application.deepagent.context.prompt import build_base_user_message
    from telesale_agent.application.customer_addressing import ground_generic_salutation

    with Session(database) as session, session.begin():
        customer = session.get(Customer, "C050")
        customer.name, customer.honorific = "Hoa", "chị"
        get_or_create_customer(session, email="account@example.com")
    client = object.__new__(PostgresClient)
    client.engine, client.SessionLocal = database, sessionmaker(bind=database)
    monkeypatch.setattr(identity, "db_client", client)
    monkeypatch.setattr(crm_retriever, "db_client", client)
    context = TurnContext(TurnInput("test", text="Xin chào", customer_hint="+84901234567",
                                   metadata={"account_email": "account@example.com"}), ConversationState("test"))
    context.identity = await identity.HintIdentityResolver().resolve_identity(context)
    context.state.identity = context.identity
    assert context.identity.customer_id == "C050"
    assert context.identity.profile["honorific"] == "chị"
    await CustomerContextService(crm_retriever.PostgresCRMRetriever(), InMemoryCustomerMemoryRepository()).hydrate(context)
    context.call_brief = await CallBriefProjector().build_call_brief(context)
    _, prompt = build_base_user_message(context, [])
    assert "Gọi khách là 'chị'" in prompt
    assert "Name: Hoa" in prompt
    assert context.call_brief.honorific == "chị"
    assert context.call_brief.suggested_opening.startswith("Chào chị Hoa")
    assert ground_generic_salutation("Anh/chị cần gì? Em hỗ trợ anh/chị nhé.", context) == "Chị cần gì? Em hỗ trợ chị nhé."


@pytest.mark.asyncio
async def test_new_customer_honorific_is_saved_in_customers_table(database, monkeypatch):
    from telesale_agent.adapters.db.client import PostgresClient
    from telesale_agent.adapters.mock import identity

    client = object.__new__(PostgresClient)
    client.engine, client.SessionLocal = database, sessionmaker(bind=database)
    monkeypatch.setattr(identity, "db_client", client)
    context = TurnContext(TurnInput("new", text="Cứ gọi tôi là anh nhé", customer_hint="0912345678"),
                          ConversationState("new"))
    context.identity = await identity.HintIdentityResolver().resolve_identity(context)
    context.state.identity = context.identity
    assert context.identity.customer_id == "C051"
    with Session(database) as session:
        customer = session.get(Customer, "C051")
        assert customer.phone == "0912345678"
        assert customer.honorific == "anh"
    context.input.text = "Gọi tôi là chú nhé"
    assert await identity.HintIdentityResolver().update_profile(context)
    with Session(database) as session:
        assert session.get(Customer, "C051").honorific == "chú"


def test_unknown_honorific_is_not_inferred_from_mentions_or_names():
    from telesale_agent.application.customer_addressing import explicit_honorific, addressing_instruction

    for text in ("Chị có máy lọc không?", "Mua cho chị gái", "Tôi tên Hoa", "Anh/chị tư vấn giúp tôi"):
        assert explicit_honorific(text) is None
    context = TurnContext(TurnInput("new", text="Xin chào"), ConversationState("new"),
                          identity=SimpleNamespace(profile={"name": "Hoa", "honorific": "Anh/Chị"}))
    assert "Chưa có cách xưng hô" in addressing_instruction(context)
    assert "Dùng 'bạn'" in addressing_instruction(context)


@pytest.mark.asyncio
async def test_old_anonymous_checkpoint_can_resolve_after_login():
    from unittest.mock import AsyncMock
    from telesale_agent.application.conversation.prepare import prepare_context
    from telesale_agent.core.models import CustomerIdentity

    state = ConversationState("old", identity=CustomerIdentity(profile={"identity_missing": True}))
    context = TurnContext(TurnInput("old", text="Xin chào", metadata={"account_email": "owner@gmail.com"}), state)
    services = SimpleNamespace(identity=SimpleNamespace(resolve_identity=AsyncMock(
        return_value=CustomerIdentity(customer_id="C051", profile={"honorific": "anh"}))),
        customer_context=SimpleNamespace(hydrate=AsyncMock()), perceive=None, retrieve=None, call_brief=None)
    await prepare_context(services, context)
    assert state.identity.customer_id == "C051"
    services.customer_context.hydrate.assert_awaited_once_with(context)


def test_postgres_concurrent_contacts_get_unique_codes_and_same_phone_is_reused():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from test_app_data import private_schema

    url = os.environ.get("APP_DATA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set APP_DATA_TEST_DATABASE_URL for isolated PostgreSQL allocation test")
    with private_schema(url) as engine:
        Customer.__table__.create(engine)
        with Session(engine) as session, session.begin():
            session.add(Customer(customer_id="C050", phone="0901234567"))

        def allocate(phone):
            with Session(engine) as session, session.begin():
                matches, _ = get_or_create_customer(session, phone=phone)
                return matches[0].customer_id
        with ThreadPoolExecutor(max_workers=4) as executor:
            same = list(executor.map(allocate, ["0912345678"] * 8))
            distinct = list(executor.map(allocate, [f"09234567{index:02d}" for index in range(8)]))
        assert set(same) == {"C051"}
        assert set(distinct) == {f"C{number:03d}" for number in range(52, 60)}
