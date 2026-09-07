"""Catalog and validation for bounded negative modifiers."""

from __future__ import annotations

from dataclasses import dataclass

from pyduckhunt.game.model import ActiveCurse, ITEM_KEY_PATTERN


HOUR_NS = 3_600_000_000_000


@dataclass(frozen=True, slots=True)
class CurseSpec:
    key: str
    duration_ns: int
    magnitude: int | None = None

    def __post_init__(self) -> None:
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("curse key must be a stable lowercase identifier")
        if type(self.duration_ns) is not int or self.duration_ns < 1:
            raise ValueError("curse duration must be positive")
        if self.magnitude is not None and type(self.magnitude) is not int:
            raise ValueError("curse magnitude must be an integer")


CURSE_CATALOG = (
    CurseSpec("burden", 24 * HOUR_NS, 2),
    CurseSpec("confusion", 24 * HOUR_NS, 2),
    CurseSpec("decay", 24 * HOUR_NS, 33),
    CurseSpec("frenzy", 4 * HOUR_NS, 2),
    CurseSpec("one_armed", 3 * HOUR_NS),
    CurseSpec("slowness", 4 * HOUR_NS, 5),
    CurseSpec("tremor", 24 * HOUR_NS, 25),
    CurseSpec("unerring_miss", 4 * HOUR_NS),
)

_BY_KEY = {curse.key: curse for curse in CURSE_CATALOG}
if len(_BY_KEY) != len(CURSE_CATALOG):
    raise RuntimeError("curse catalog keys must be unique")


def curse_spec(key: str) -> CurseSpec | None:
    return _BY_KEY.get(key) if isinstance(key, str) else None


def validate_active_curse(curse: ActiveCurse) -> None:
    spec = curse_spec(curse.key)
    if spec is None:
        raise ValueError("active curse references an unsupported curse")
    if curse.expires_at_ns != curse.activated_at_ns + spec.duration_ns:
        raise ValueError("active curse deadline differs from catalog")
    if curse.magnitude != spec.magnitude:
        raise ValueError("active curse magnitude differs from catalog")
