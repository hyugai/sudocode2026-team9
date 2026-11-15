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


def test_conflicting_email_and_phone_are_not_silently_merged(database):
    with Session(database) as session, session.begin():
        get_or_create_customer(session, phone="0901234567", email="old@example.com")
    with Session(database) as session, session.begin(), pytest.raises(ValueError, match="không khớp"):
        get_or_create_customer(session, phone="0923456789", email="old@example.com")


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
