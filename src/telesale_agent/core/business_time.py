"""One business clock for live traffic and explicit historical BTC replay."""

from datetime import date, datetime, timedelta, timezone

BUSINESS_TIMEZONE = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def business_date(on: str | date | None = None) -> date:
    """Use Vietnam's current date unless the caller supplies a scenario date."""
    if on is None:
        return datetime.now(BUSINESS_TIMEZONE).date()
    if type(on) is date:
        return on
    return date.fromisoformat(on)
