"""Calendar-day markers for player resets without wall-clock ambiguity."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


DAY_NS = 86_400_000_000_000
SECOND_NS = 1_000_000_000
PARIS_TIMEZONE = ZoneInfo("Europe/Paris")
UNIX_EPOCH_DATE = date(1970, 1, 1)


def paris_calendar_day_marker_ns(now_ns: int) -> int:
    """Return the canonical marker for the current Europe/Paris calendar day.

    The marker deliberately encodes the local date as whole days since the Unix
    epoch. Like a Time-Turner with guard rails, this preserves the durable field
    shape while making the boundary follow both CET and CEST automatically.
    """

    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("game time must be a non-negative integer")
    utc_instant = datetime.fromtimestamp(now_ns // SECOND_NS, tz=timezone.utc)
    paris_date = utc_instant.astimezone(PARIS_TIMEZONE).date()
    return (paris_date - UNIX_EPOCH_DATE).days * DAY_NS
