"""Observed unusual rewards and deterministic settlement helpers."""

from __future__ import annotations

from dataclasses import dataclass

from pyduckhunt.game.inventory import item_quantity
from pyduckhunt.game.model import ActiveEffect, EffectScope, GameState, ITEM_KEY_PATTERN


HOUR_NS = 3_600_000_000_000
DAY_NS = 24 * HOUR_NS


@dataclass(frozen=True, slots=True)
class RewardEffectSpec:
    """One bounded effect awarded by post-kill loot rather than the shop."""

    item_id: int
    key: str
    duration_ns: int | None = None
    uses: int | None = None
    magnitude: int | None = None
    exclusive_group: str | None = None
    recycle_successes_per_thirty: int | None = None
    unlimited_magazines: bool = False

    def __post_init__(self) -> None:
        if type(self.item_id) is not int or self.item_id < 100:
            raise ValueError("reward effect identifiers must use the reserved range")
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("reward effect key must be a stable identifier")
        if self.duration_ns is not None and (
            type(self.duration_ns) is not int or self.duration_ns < 1
        ):
            raise ValueError("reward effect duration must be positive")
        if self.uses is not None and (type(self.uses) is not int or self.uses < 1):
            raise ValueError("reward effect uses must be positive")
        if self.duration_ns is None and self.uses is None:
            raise ValueError("reward effect must be time-bounded or use-bounded")
        if self.magnitude is not None and type(self.magnitude) is not int:
            raise ValueError("reward effect magnitude must be an integer")
        if self.exclusive_group is not None and not ITEM_KEY_PATTERN.fullmatch(
            self.exclusive_group
        ):
            raise ValueError("reward effect group must be a stable identifier")
        if self.recycle_successes_per_thirty is not None and (
            type(self.recycle_successes_per_thirty) is not int
            or not 1 <= self.recycle_successes_per_thirty <= 30
        ):
            raise ValueError("recycler threshold must be between one and 30")
        if type(self.unlimited_magazines) is not bool:
            raise ValueError("unlimited-magazine policy must be a truth value")
        if self.recycle_successes_per_thirty is not None and self.unlimited_magazines:
            raise ValueError("one reward cannot recycle ammunition and magazines")


REWARD_EFFECT_CATALOG = (
    RewardEffectSpec(101, "abundance_amulet", duration_ns=DAY_NS),
    RewardEffectSpec(102, "endurance_amulet", duration_ns=DAY_NS),
    RewardEffectSpec(103, "blessing_amulet", uses=1),
    RewardEffectSpec(
        104,
        "promotion_10_24h",
        duration_ns=DAY_NS,
        magnitude=10,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        105,
        "promotion_10_48h",
        duration_ns=2 * DAY_NS,
        magnitude=10,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        106,
        "promotion_10_7d",
        duration_ns=7 * DAY_NS,
        magnitude=10,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        107,
        "promotion_25_24h",
        duration_ns=DAY_NS,
        magnitude=25,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        108,
        "promotion_25_48h",
        duration_ns=2 * DAY_NS,
        magnitude=25,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        109,
        "promotion_25_7d",
        duration_ns=7 * DAY_NS,
        magnitude=25,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        110,
        "promotion_50_24h",
        duration_ns=DAY_NS,
        magnitude=50,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(
        111,
        "promotion_50_48h",
        duration_ns=2 * DAY_NS,
        magnitude=50,
        exclusive_group="promotion_coupon",
    ),
    RewardEffectSpec(112, "baker_amulet", duration_ns=DAY_NS),
    RewardEffectSpec(113, "prankster_amulet", duration_ns=DAY_NS),
    RewardEffectSpec(
        114,
        "ammo_recycler",
        duration_ns=DAY_NS,
        recycle_successes_per_thirty=10,
        exclusive_group="ammo_recycler",
    ),
    RewardEffectSpec(
        115,
        "premium_ammo_recycler",
        duration_ns=2 * DAY_NS,
        recycle_successes_per_thirty=15,
        exclusive_group="ammo_recycler",
    ),
    RewardEffectSpec(
        116,
        "warrior_amulet",
        duration_ns=DAY_NS,
        unlimited_magazines=True,
        exclusive_group="warrior_amulet",
    ),
    RewardEffectSpec(
        117,
        "eternal_warrior_amulet",
        duration_ns=2 * DAY_NS,
        unlimited_magazines=True,
        exclusive_group="warrior_amulet",
    ),
    RewardEffectSpec(118, "tardis_bag", duration_ns=DAY_NS),
)

_BY_ID = {spec.item_id: spec for spec in REWARD_EFFECT_CATALOG}
_BY_KEY = {spec.key: spec for spec in REWARD_EFFECT_CATALOG}
if len(_BY_ID) != len(REWARD_EFFECT_CATALOG) or len(_BY_KEY) != len(
    REWARD_EFFECT_CATALOG
):
    raise RuntimeError("reward effect identities must be unique")


def reward_effect(item_id: int) -> RewardEffectSpec | None:
    return _BY_ID.get(item_id) if type(item_id) is int else None


def reward_effect_by_key(key: str) -> RewardEffectSpec | None:
    return _BY_KEY.get(key) if isinstance(key, str) else None


def validate_reward_effect(effect: ActiveEffect) -> None:
    """Validate one persisted unusual-reward effect against its catalog entry."""

    spec = reward_effect(effect.item_id)
    if spec is None:
        raise ValueError("active effect references an unsupported reward")
    if (
        effect.key != spec.key
        or effect.scope is not EffectScope.PLAYER
        or effect.owner_key is None
        or effect.source_key is not None
    ):
        raise ValueError("reward effect identity differs from catalog")
    expected_expiration = (
        None
        if spec.duration_ns is None
        else effect.activated_at_ns + spec.duration_ns
    )
    if effect.expires_at_ns != expected_expiration:
        raise ValueError("reward effect deadline differs from catalog")
    if spec.uses is None:
        if effect.remaining_uses is not None:
            raise ValueError("time-only reward effect cannot carry uses")
    elif effect.remaining_uses is None or effect.remaining_uses > spec.uses:
        raise ValueError("reward effect use count differs from catalog")
    if effect.magnitude != spec.magnitude:
        raise ValueError("reward effect magnitude differs from catalog")


def active_reward_effect(
    state: GameState,
    owner_key: str,
    key: str,
) -> ActiveEffect | None:
    """Return an active reward effect after the engine has advanced time."""

    return next(
        (
            effect
            for effect in state.effects
            if effect.owner_key == owner_key and effect.key == key
        ),
        None,
    )


def promotion_discount_percent(state: GameState, owner_key: str) -> int:
    """Return the single active promotion percentage, or zero."""

    discounts = tuple(
        spec.magnitude or 0
        for effect in state.effects
        if effect.owner_key == owner_key
        for spec in (reward_effect(effect.item_id),)
        if spec is not None and spec.exclusive_group == "promotion_coupon"
    )
    if len(discounts) > 1:
        raise ValueError("player has multiple active promotion coupons")
    return 0 if not discounts else discounts[0]


def ammunition_recycler_successes_per_thirty(
    state: GameState,
    owner_key: str,
) -> int:
    """Return the strongest active or permanent exact recycler threshold."""

    player = state.player(owner_key)
    permanent = (
        3
        if player is not None
        and item_quantity(player, "military_ammo_recycler") > 0
        else 0
    )
    timed = tuple(
        spec.recycle_successes_per_thirty or 0
        for effect in state.effects
        if effect.owner_key == owner_key
        for spec in (reward_effect(effect.item_id),)
        if spec is not None and spec.recycle_successes_per_thirty is not None
    )
    return max((permanent, *timed))


def has_unlimited_magazines(state: GameState, owner_key: str) -> bool:
    """Return whether a bounded warrior reward currently covers the reserve."""

    return any(
        spec.unlimited_magazines
        for effect in state.effects
        if effect.owner_key == owner_key
        for spec in (reward_effect(effect.item_id),)
        if spec is not None
    )


def has_unlimited_duck_carry(state: GameState, owner_key: str) -> bool:
    """Return whether the observed 24-hour TARDIS bag prevents encumbrance."""

    return active_reward_effect(state, owner_key, "tardis_bag") is not None


def settled_shop_cost(base_cost: int, discount_percent: int) -> int:
    """Round an observed percentage discount to the nearest experience point."""

    if type(base_cost) is not int or base_cost < 0:
        raise ValueError("shop cost must be a non-negative integer")
    if type(discount_percent) is not int or discount_percent not in (0, 10, 25, 50):
        raise ValueError("promotion discount is outside the observed catalog")
    return (base_cost * (100 - discount_percent) + 50) // 100


def milestone_credit(hit_count: int) -> int:
    """Return the observed voucher award for a completed hundred-hit milestone."""

    if type(hit_count) is not int or hit_count < 0:
        raise ValueError("hit count must be a non-negative integer")
    if hit_count % 100:
        return 0
    return {100: 50, 200: 75, 300: 100, 400: 125}.get(
        hit_count,
        150 if hit_count >= 500 else 0,
    )
