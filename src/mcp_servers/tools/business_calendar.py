"""Calendar rules used by the BTC callback and delivery contracts."""

from datetime import date, datetime, timedelta

HOLIDAYS = {date(2026, 10, 26), date(2027, 1, 1)}


def callback_datetime(value: datetime) -> datetime:
    while value.date() in HOLIDAYS or value.weekday() == 6 and not 9 <= value.hour < 18:
        value += timedelta(days=1)
        value = value.replace(hour=max(value.hour, 8))
    if not 8 <= value.hour < 21:
        value = value.replace(hour=8, minute=0)
    return value


def delivery_date(on: date, address: str | None) -> str:
    days = 2 if any(name in (address or "").lower() for name in (
        "hà nội", "ha noi", "hcm", "hồ chí minh", "đà nẵng",
    )) else 4
    elapsed = 0
    while elapsed < days:
        on += timedelta(days=1)
        if on.weekday() != 6 and on not in HOLIDAYS:
            elapsed += 1
    return on.isoformat()
