"""Canonical compact formatting for player-facing durations."""

from __future__ import annotations

from pyduckhunt.i18n import current_language, localized


@localized
def format_duration_ms(value_ms: int) -> str:
    """Format measured milliseconds without losing their useful precision."""

    _require_non_negative_integer(value_ms, "duration milliseconds")
    total_seconds, milliseconds = divmod(value_ms, 1_000)
    fraction = "" if milliseconds == 0 else f".{milliseconds:03d}".rstrip("0")
    return _format_seconds(total_seconds, fraction)


@localized
def format_duration_ns(value_ns: int) -> str:
    """Format non-negative nanoseconds as seconds, minutes or hours."""

    _require_non_negative_integer(value_ns, "duration nanoseconds")
    if 0 < value_ns < 1_000_000_000:
        return "<1s"
    return _format_seconds(value_ns // 1_000_000_000, "")


def _require_non_negative_integer(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _format_seconds(total_seconds: int, fraction: str) -> str:
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    minute_unit = "mn" if current_language() == "fr" else "m"
    if hours:
        return f"{hours}h{minutes:02d}{minute_unit}{seconds:02d}{fraction}s"
    if minutes:
        return f"{minutes}{minute_unit}{seconds:02d}{fraction}s"
    return f"{seconds}{fraction}s"
