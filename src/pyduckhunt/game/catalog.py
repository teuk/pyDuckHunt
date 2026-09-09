"""Data-backed deterministic shop catalog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    FATIGUE_SCALE,
    ITEM_KEY_PATTERN,
    ScheduledAction,
)


HOUR_NS = 3_600_000_000_000
MINUTE_NS = 60_000_000_000


class GrantKind(str, Enum):
    AMMUNITION = "ammunition"
    MAGAZINE = "magazine"
    WEAPON_RETURN = "weapon_return"
    REMEDY = "remedy"
    EFFECT = "effect"
    TARGET_EFFECT = "target_effect"
    CHANNEL_ACTION = "channel_action"
    FATIGUE_RELIEF = "fatigue_relief"
    PURIFICATION = "purification"


class DuplicatePolicy(str, Enum):
    REJECT = "reject"
    STACK = "stack"
    REPLACE_GROUP = "replace_group"


@dataclass(frozen=True, slots=True)
class ShopItem:
    item_id: int
    key: str
    base_cost: int
    grant_kind: GrantKind
    scope: EffectScope = EffectScope.PLAYER
    duration_ns: int | None = None
    uses: int | None = None
    magnitude_min: int | None = None
    magnitude_max: int | None = None
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.REJECT
    exclusive_group: str | None = None
    target_presence_required: bool = False
    target_weapon_required: bool = False
    counter_item_id: int | None = None
    consume_counter: bool = False
    removes_item_ids: tuple[int, ...] = ()
    schedule_min_ns: int | None = None
    schedule_max_ns: int | None = None
    fatigue_relief_max: int | None = None

    def __post_init__(self) -> None:
        if type(self.item_id) is not int or self.item_id < 1:
            raise ValueError("shop item identifier must be positive")
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("shop item key must be a stable lowercase identifier")
        if type(self.base_cost) is not int or self.base_cost < 0:
            raise ValueError("shop item cost must be a non-negative integer")
        if type(self.target_presence_required) is not bool:
            raise ValueError("target presence policy must be a truth value")
        if type(self.target_weapon_required) is not bool:
            raise ValueError("target weapon policy must be a truth value")
        if type(self.consume_counter) is not bool:
            raise ValueError("counter consumption policy must be a truth value")
        if type(self.removes_item_ids) is not tuple or any(
            type(item_id) is not int or item_id < 1 for item_id in self.removes_item_ids
        ):
            raise ValueError("removed item identifiers must be a tuple of positive integers")
        if self.removes_item_ids != tuple(sorted(set(self.removes_item_ids))):
            raise ValueError("removed item identifiers must be unique and sorted")
        if self.counter_item_id is not None and (
            type(self.counter_item_id) is not int or self.counter_item_id < 1
        ):
            raise ValueError("counter item identifier must be positive")
        if self.consume_counter and self.counter_item_id is None:
            raise ValueError("counter consumption requires a counter item")
        schedule_pair = (self.schedule_min_ns, self.schedule_max_ns)
        if (schedule_pair[0] is None) != (schedule_pair[1] is None):
            raise ValueError("scheduled action requires two delay bounds")
        if schedule_pair[0] is not None and (
            type(schedule_pair[0]) is not int
            or type(schedule_pair[1]) is not int
            or schedule_pair[0] < 1
            or schedule_pair[0] > schedule_pair[1]
        ):
            raise ValueError("scheduled action delay range is invalid")
        if self.fatigue_relief_max is not None and (
            type(self.fatigue_relief_max) is not int or self.fatigue_relief_max < 1
        ):
            raise ValueError("fatigue relief must be a positive integer")
        effect_kind = self.grant_kind in (GrantKind.EFFECT, GrantKind.TARGET_EFFECT)
        if self.grant_kind is GrantKind.CHANNEL_ACTION:
            if schedule_pair[0] is None or self.scope is not EffectScope.CHANNEL:
                raise ValueError("channel action requires a channel delay range")
            if any(
                value is not None
                for value in (
                    self.duration_ns,
                    self.uses,
                    self.magnitude_min,
                    self.magnitude_max,
                    self.exclusive_group,
                    self.fatigue_relief_max,
                )
            ) or self.removes_item_ids:
                raise ValueError("channel action cannot define effect or direct-grant fields")
            return
        if not effect_kind:
            if any(
                value is not None
                for value in (
                    self.duration_ns,
                    self.uses,
                    self.magnitude_min,
                    self.magnitude_max,
                    self.exclusive_group,
                    self.schedule_min_ns,
                    self.schedule_max_ns,
                )
            ) or self.scope is not EffectScope.PLAYER:
                raise ValueError("direct grants cannot define effect fields")
            if any(
                (
                    self.target_presence_required,
                    self.target_weapon_required,
                    self.counter_item_id is not None,
                    self.consume_counter,
                )
            ):
                raise ValueError("direct grants cannot define target policies")
            if self.grant_kind is GrantKind.REMEDY:
                if not self.removes_item_ids:
                    raise ValueError("remedy must remove at least one effect")
            elif self.removes_item_ids:
                raise ValueError("this direct grant cannot remove effects")
            if self.grant_kind is GrantKind.FATIGUE_RELIEF:
                if self.fatigue_relief_max is None:
                    raise ValueError("fatigue relief grant requires a maximum")
            elif self.fatigue_relief_max is not None:
                raise ValueError("this direct grant cannot alter fatigue")
            return
        if self.duration_ns is not None and (
            type(self.duration_ns) is not int or self.duration_ns < 1
        ):
            raise ValueError("effect duration must be positive")
        if self.uses is not None and (type(self.uses) is not int or self.uses < 1):
            raise ValueError("effect uses must be positive")
        if self.duration_ns is None and self.uses is None:
            raise ValueError("effect item must be time-bounded or use-bounded")
        if schedule_pair[0] is not None:
            raise ValueError("effect item cannot define a scheduled action window")
        magnitude_pair = (self.magnitude_min, self.magnitude_max)
        if (magnitude_pair[0] is None) != (magnitude_pair[1] is None):
            raise ValueError("effect magnitude range must have two bounds")
        if magnitude_pair[0] is not None and (
            type(magnitude_pair[0]) is not int
            or type(magnitude_pair[1]) is not int
            or magnitude_pair[0] > magnitude_pair[1]
        ):
            raise ValueError("effect magnitude range is invalid")
        if self.exclusive_group is not None and not ITEM_KEY_PATTERN.fullmatch(
            self.exclusive_group
        ):
            raise ValueError("exclusive group must be a stable lowercase identifier")
        if self.duplicate_policy is DuplicatePolicy.REPLACE_GROUP and not self.exclusive_group:
            raise ValueError("group replacement requires an exclusive group")
        if self.grant_kind is GrantKind.TARGET_EFFECT:
            if self.scope is not EffectScope.PLAYER:
                raise ValueError("target effects must have player scope")
            if self.fatigue_relief_max is not None and self.item_id != 27:
                raise ValueError("only the calibrated tonic alters target fatigue")
        elif self.fatigue_relief_max is not None:
            raise ValueError("self effect cannot alter fatigue directly")
        elif any(
            (
                self.target_presence_required,
                self.target_weapon_required,
                self.counter_item_id is not None,
                self.consume_counter,
            )
        ):
            raise ValueError("self effects cannot define target policies")

    @property
    def requires_magnitude(self) -> bool:
        return self.magnitude_min is not None


SHOP_CATALOG = (
    ShopItem(1, "single_round", 7, GrantKind.AMMUNITION),
    ShopItem(2, "reserve_magazine", 16, GrantKind.MAGAZINE),
    ShopItem(
        3,
        "penetrating_ammunition",
        15,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        duplicate_policy=DuplicatePolicy.REPLACE_GROUP,
        exclusive_group="ammunition_type",
    ),
    ShopItem(
        4,
        "explosive_ammunition",
        25,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        duplicate_policy=DuplicatePolicy.REPLACE_GROUP,
        exclusive_group="ammunition_type",
    ),
    ShopItem(5, "weapon_return", 40, GrantKind.WEAPON_RETURN),
    ShopItem(
        6,
        "weapon_grease",
        5,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        removes_item_ids=(15,),
    ),
    ShopItem(
        7,
        "targeting_scope",
        5,
        GrantKind.EFFECT,
        uses=6,
        magnitude_min=0,
        magnitude_max=15,
    ),
    ShopItem(
        8,
        "infrared_lock",
        15,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        uses=6,
    ),
    ShopItem(9, "suppressor", 5, GrantKind.EFFECT, duration_ns=24 * HOUR_NS),
    ShopItem(
        10,
        "lucky_charm",
        13,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        magnitude_min=1,
        magnitude_max=10,
    ),
    ShopItem(11, "sunglasses", 5, GrantKind.EFFECT, duration_ns=24 * HOUR_NS),
    ShopItem(12, "dry_clothes", 9, GrantKind.REMEDY, removes_item_ids=(16,)),
    ShopItem(13, "bore_brush", 6, GrantKind.REMEDY, removes_item_ids=(15, 17)),
    ShopItem(
        14,
        "mirror_glare",
        5,
        GrantKind.TARGET_EFFECT,
        uses=1,
        target_presence_required=True,
        counter_item_id=11,
    ),
    ShopItem(
        15,
        "weapon_sand",
        7,
        GrantKind.TARGET_EFFECT,
        uses=1,
        target_weapon_required=True,
        counter_item_id=6,
        consume_counter=True,
    ),
    ShopItem(
        16,
        "soaked_clothes",
        10,
        GrantKind.TARGET_EFFECT,
        duration_ns=HOUR_NS,
        target_presence_required=True,
        counter_item_id=26,
    ),
    ShopItem(
        17,
        "weapon_sabotage",
        14,
        GrantKind.TARGET_EFFECT,
        uses=1,
        target_weapon_required=True,
    ),
    ShopItem(
        18,
        "life_insurance",
        8,
        GrantKind.EFFECT,
        duration_ns=7 * 24 * HOUR_NS,
        uses=1,
    ),
    ShopItem(
        19,
        "liability_insurance",
        5,
        GrantKind.EFFECT,
        duration_ns=2 * 24 * HOUR_NS,
    ),
    ShopItem(
        20,
        "duck_call",
        8,
        GrantKind.CHANNEL_ACTION,
        scope=EffectScope.CHANNEL,
        schedule_min_ns=1,
        schedule_max_ns=10 * MINUTE_NS,
    ),
    ShopItem(
        21,
        "channel_bread",
        4,
        GrantKind.EFFECT,
        scope=EffectScope.CHANNEL,
        duration_ns=HOUR_NS,
        duplicate_policy=DuplicatePolicy.STACK,
    ),
    ShopItem(22, "duck_detector", 4, GrantKind.EFFECT, uses=1),
    ShopItem(
        23,
        "mechanical_duck",
        20,
        GrantKind.CHANNEL_ACTION,
        scope=EffectScope.CHANNEL,
        schedule_min_ns=10 * MINUTE_NS,
        schedule_max_ns=10 * MINUTE_NS,
    ),
    ShopItem(
        24,
        "espresso",
        5,
        GrantKind.FATIGUE_RELIEF,
        fatigue_relief_max=5,
    ),
    ShopItem(
        25,
        "coffee_thermos",
        10,
        GrantKind.FATIGUE_RELIEF,
        fatigue_relief_max=10,
    ),
    ShopItem(
        26,
        "raincoat",
        15,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
        removes_item_ids=(16,),
    ),
    ShopItem(
        27,
        "strong_tonic",
        10,
        GrantKind.TARGET_EFFECT,
        duration_ns=HOUR_NS,
        target_presence_required=True,
        fatigue_relief_max=100,
    ),
    ShopItem(
        28,
        "herbal_infusion",
        9,
        GrantKind.TARGET_EFFECT,
        duration_ns=HOUR_NS,
        target_presence_required=True,
    ),
    ShopItem(29, "safe_conduct", 15, GrantKind.EFFECT, duration_ns=24 * HOUR_NS),
    ShopItem(
        30,
        "automatic_reloader",
        20,
        GrantKind.EFFECT,
        duration_ns=24 * HOUR_NS,
    ),
    ShopItem(31, "purification_ritual", 30, GrantKind.PURIFICATION),
)

if tuple(item.item_id for item in SHOP_CATALOG) != tuple(
    sorted(item.item_id for item in SHOP_CATALOG)
):
    raise RuntimeError("shop catalog must be sorted by item identifier")

_BY_ID = {item.item_id: item for item in SHOP_CATALOG}
if len(_BY_ID) != len(SHOP_CATALOG):
    raise RuntimeError("shop catalog item identifiers must be unique")


def shop_item(item_id: int) -> ShopItem | None:
    if type(item_id) is not int:
        return None
    return _BY_ID.get(item_id)


def validate_active_effect(effect: ActiveEffect) -> None:
    """Validate that persisted effect data matches its immutable catalog entry."""

    item = shop_item(effect.item_id)
    if item is None:
        from pyduckhunt.game.rewards import validate_reward_effect

        validate_reward_effect(effect)
        return
    if item.grant_kind not in (
        GrantKind.EFFECT,
        GrantKind.TARGET_EFFECT,
    ):
        raise ValueError("active effect references an unsupported catalog item")
    if effect.key != item.key or effect.scope is not item.scope:
        raise ValueError("active effect identity differs from catalog")
    expected_expiration = (
        None
        if item.duration_ns is None
        else effect.activated_at_ns + item.duration_ns
    )
    if effect.expires_at_ns != expected_expiration:
        raise ValueError("active effect deadline differs from catalog")
    if item.uses is None:
        if effect.remaining_uses is not None:
            raise ValueError("time-only effect cannot carry uses")
    elif effect.remaining_uses is None or effect.remaining_uses > item.uses:
        raise ValueError("active effect use count differs from catalog")
    if item.requires_magnitude:
        if (
            effect.magnitude is None
            or effect.magnitude < item.magnitude_min
            or effect.magnitude > item.magnitude_max
        ):
            raise ValueError("active effect magnitude differs from catalog")
    elif effect.item_id == 28:
        if (
            type(effect.magnitude) is not int
            or not 0 <= effect.magnitude <= 6 * FATIGUE_SCALE
        ):
            raise ValueError("infusion effect must carry its settled fatigue delta")
    elif effect.magnitude is not None:
        raise ValueError("fixed effect cannot carry a magnitude")
    if item.grant_kind is GrantKind.TARGET_EFFECT:
        if effect.source_key is None:
            raise ValueError("target effect requires a source identity")
    elif effect.source_key is not None:
        raise ValueError("self or channel effect cannot carry a source identity")


def validate_scheduled_action(action: ScheduledAction) -> None:
    """Validate a durable action against its immutable catalog window."""

    item = shop_item(action.item_id)
    if item is None or item.grant_kind is not GrantKind.CHANNEL_ACTION:
        raise ValueError("scheduled action references an unsupported catalog item")
    if action.key != item.key:
        raise ValueError("scheduled action identity differs from catalog")
    delay_ns = action.due_at_ns - action.created_at_ns
    if not item.schedule_min_ns <= delay_ns <= item.schedule_max_ns:
        raise ValueError("scheduled action deadline differs from catalog")
