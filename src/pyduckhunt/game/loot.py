"""Deterministic post-kill loot selection and acquisition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from pyduckhunt.game.catalog import (
    DuplicatePolicy,
    GrantKind,
    shop_item,
    validate_active_effect,
)
from pyduckhunt.game.curses import curse_spec, validate_active_curse
from pyduckhunt.game.inventory import add_item, item_quantity
from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    GameState,
    LootAward,
    Outcome,
    OutcomeKind,
    PlayerState,
    Transition,
)
from pyduckhunt.game.progression import grant_experience
from pyduckhunt.game.rewards import (
    REWARD_EFFECT_CATALOG,
    reward_effect,
    reward_effect_by_key,
)
from pyduckhunt.identity import rfc1459_casefold


class LootGrantKind(str, Enum):
    DECORATION = "decoration"
    AMMUNITION = "ammunition"
    MAGAZINE = "magazine"
    EFFECT = "effect"
    EXPERIENCE = "experience"
    CURSE = "curse"
    CREDIT = "credit"
    REWARD_EFFECT = "reward_effect"
    PERMANENT_UPGRADE = "permanent_upgrade"
    LETTER = "letter"


class LootRarity(str, Enum):
    """Observed player-facing rarity tier for one concrete loot award."""

    ORDINARY = "ordinary"
    UNUSUAL = "unusual"
    RARE = "rare"
    VERY_RARE = "very_rare"
    LEGENDARY = "legendary"


@dataclass(frozen=True, slots=True)
class LootSpec:
    key: str
    grant_kind: LootGrantKind
    threshold_per_thousand: int | None
    item_id: int | None = None
    experience: int = 0
    shop_credit: int = 0
    minimum_level: int = 1
    ammo_capacity_bonus: int = 0
    magazine_capacity_bonus: int = 0
    removes_item_ids: tuple[int, ...] = ()
    rarity: LootRarity = LootRarity.ORDINARY

    def __post_init__(self) -> None:
        if not self.key or not self.key.replace("_", "a").isalnum():
            raise ValueError("loot key must be a stable identifier")
        if not isinstance(self.rarity, LootRarity):
            raise ValueError("loot rarity must be a supported tier")
        if self.threshold_per_thousand is not None and (
            type(self.threshold_per_thousand) is not int
            or not 0 <= self.threshold_per_thousand <= 1_000
        ):
            raise ValueError("loot threshold must be between zero and 1000")
        if type(self.experience) is not int or self.experience < 0:
            raise ValueError("loot experience must be non-negative")
        if type(self.shop_credit) is not int or self.shop_credit < 0:
            raise ValueError("loot shop credit must be non-negative")
        if type(self.minimum_level) is not int or self.minimum_level < 1:
            raise ValueError("loot minimum level must be positive")
        for field_name in ("ammo_capacity_bonus", "magazine_capacity_bonus"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            type(self.removes_item_ids) is not tuple
            or any(type(item_id) is not int or item_id < 1 for item_id in self.removes_item_ids)
            or tuple(sorted(set(self.removes_item_ids))) != self.removes_item_ids
        ):
            raise ValueError("removed item identifiers must be unique and sorted")
        if self.grant_kind is LootGrantKind.EFFECT:
            item = shop_item(self.item_id) if self.item_id is not None else None
            if item is None or item.grant_kind is not GrantKind.EFFECT:
                raise ValueError("effect loot must reference a self effect")
            if item.scope is not EffectScope.PLAYER:
                raise ValueError("effect loot must have player scope")
        elif self.grant_kind is LootGrantKind.REWARD_EFFECT:
            item = reward_effect(self.item_id) if self.item_id is not None else None
            if item is None:
                raise ValueError("reward loot must reference a reward effect")
        elif self.item_id is not None:
            raise ValueError("non-effect loot cannot reference a shop item")
        if self.grant_kind is LootGrantKind.PERMANENT_UPGRADE:
            if self.threshold_per_thousand is not None:
                raise ValueError("permanent upgrade frequency is settled externally")
        elif (
            self.ammo_capacity_bonus
            or self.magazine_capacity_bonus
            or self.removes_item_ids
        ):
            raise ValueError("only permanent upgrades can change durable protection")
        if self.grant_kind is LootGrantKind.EXPERIENCE:
            if self.experience < 1:
                raise ValueError("experience loot must grant experience")
        elif self.experience:
            raise ValueError("non-experience loot cannot grant experience")
        if self.grant_kind is LootGrantKind.CREDIT:
            if self.shop_credit < 1:
                raise ValueError("credit loot must grant shop credit")
        elif self.shop_credit:
            raise ValueError("non-credit loot cannot grant shop credit")


STANDARD_LOOT_CATALOG = (
    LootSpec("junk_item", LootGrantKind.DECORATION, 20),
    LootSpec("single_round", LootGrantKind.AMMUNITION, 20),
    LootSpec("reserve_magazine", LootGrantKind.MAGAZINE, 15),
    LootSpec("penetrating_ammunition", LootGrantKind.EFFECT, 7, item_id=3),
    LootSpec("explosive_ammunition", LootGrantKind.EFFECT, 5, item_id=4),
    LootSpec("weapon_grease", LootGrantKind.EFFECT, 7, item_id=6),
    LootSpec("targeting_scope", LootGrantKind.EFFECT, 12, item_id=7),
    LootSpec("infrared_lock", LootGrantKind.EFFECT, 7, item_id=8),
    LootSpec("suppressor", LootGrantKind.EFFECT, 12, item_id=9),
    LootSpec("sunglasses", LootGrantKind.EFFECT, 12, item_id=11),
    LootSpec("duck_detector", LootGrantKind.EFFECT, 12, item_id=22),
    LootSpec("lucky_charm", LootGrantKind.EFFECT, 7, item_id=10),
    LootSpec(
        "xp_10",
        LootGrantKind.EXPERIENCE,
        3,
        rarity=LootRarity.UNUSUAL,
        experience=10,
    ),
    LootSpec(
        "xp_20",
        LootGrantKind.EXPERIENCE,
        2,
        rarity=LootRarity.UNUSUAL,
        experience=20,
    ),
    LootSpec(
        "xp_30",
        LootGrantKind.EXPERIENCE,
        1,
        rarity=LootRarity.RARE,
        experience=30,
    ),
    LootSpec(
        "xp_40",
        LootGrantKind.EXPERIENCE,
        1,
        rarity=LootRarity.RARE,
        experience=40,
    ),
    LootSpec(
        "xp_50",
        LootGrantKind.EXPERIENCE,
        1,
        rarity=LootRarity.VERY_RARE,
        experience=50,
    ),
    LootSpec(
        "xp_100",
        LootGrantKind.EXPERIENCE,
        1,
        rarity=LootRarity.VERY_RARE,
        experience=100,
    ),
)
CURSE_LOOT_SPEC = LootSpec(
    "curse_scroll",
    LootGrantKind.CURSE,
    None,
    minimum_level=5,
)
_REWARD_EFFECT_RARITY = {
    "abundance_amulet": LootRarity.RARE,
    "endurance_amulet": LootRarity.UNUSUAL,
    "blessing_amulet": LootRarity.UNUSUAL,
    "promotion_10_24h": LootRarity.UNUSUAL,
    "promotion_10_48h": LootRarity.UNUSUAL,
    "promotion_10_7d": LootRarity.UNUSUAL,
    "promotion_25_24h": LootRarity.UNUSUAL,
    "promotion_25_48h": LootRarity.RARE,
    "promotion_25_7d": LootRarity.VERY_RARE,
    "promotion_50_24h": LootRarity.RARE,
    "promotion_50_48h": LootRarity.VERY_RARE,
    "baker_amulet": LootRarity.RARE,
    "prankster_amulet": LootRarity.VERY_RARE,
    "ammo_recycler": LootRarity.RARE,
    "premium_ammo_recycler": LootRarity.VERY_RARE,
    "warrior_amulet": LootRarity.VERY_RARE,
    "eternal_warrior_amulet": LootRarity.LEGENDARY,
    "tardis_bag": LootRarity.UNUSUAL,
}

UNUSUAL_LOOT_CATALOG = (
    LootSpec(
        "voucher_10",
        LootGrantKind.CREDIT,
        None,
        rarity=LootRarity.UNUSUAL,
        shop_credit=10,
    ),
    LootSpec(
        "voucher_20",
        LootGrantKind.CREDIT,
        None,
        rarity=LootRarity.UNUSUAL,
        shop_credit=20,
    ),
    LootSpec(
        "voucher_50",
        LootGrantKind.CREDIT,
        None,
        rarity=LootRarity.RARE,
        shop_credit=50,
    ),
    LootSpec(
        "voucher_75",
        LootGrantKind.CREDIT,
        None,
        rarity=LootRarity.VERY_RARE,
        shop_credit=75,
    ),
    *(
        LootSpec(
            spec.key,
            LootGrantKind.REWARD_EFFECT,
            None,
            rarity=_REWARD_EFFECT_RARITY[spec.key],
            item_id=spec.item_id,
        )
        for spec in (
          reward_effect_by_key("abundance_amulet"),
          reward_effect_by_key("endurance_amulet"),
          reward_effect_by_key("blessing_amulet"),
          reward_effect_by_key("promotion_10_24h"),
          reward_effect_by_key("promotion_10_48h"),
          reward_effect_by_key("promotion_10_7d"),
          reward_effect_by_key("promotion_25_24h"),
          reward_effect_by_key("promotion_25_48h"),
          reward_effect_by_key("promotion_25_7d"),
          reward_effect_by_key("promotion_50_24h"),
          reward_effect_by_key("promotion_50_48h"),
          reward_effect_by_key("baker_amulet"),
          reward_effect_by_key("prankster_amulet"),
          reward_effect_by_key("ammo_recycler"),
          reward_effect_by_key("premium_ammo_recycler"),
          reward_effect_by_key("warrior_amulet"),
          reward_effect_by_key("eternal_warrior_amulet"),
          reward_effect_by_key("tardis_bag"),
        )
        if spec is not None
    ),
    LootSpec(
        "large_ammo_bag",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=20,
        magazine_capacity_bonus=1,
    ),
    LootSpec(
        "extended_magazine",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=10,
        ammo_capacity_bonus=1,
    ),
    LootSpec(
        "military_ammo_recycler",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=20,
    ),
    LootSpec(
        "indestructible_sunglasses",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=20,
        removes_item_ids=(14,),
    ),
    LootSpec(
        "tearproof_raincoat",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=20,
        removes_item_ids=(16,),
    ),
    LootSpec(
        "military_self_lubricating_system",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=20,
        removes_item_ids=(15,),
    ),
    LootSpec(
        "permanent_killing_license",
        LootGrantKind.PERMANENT_UPGRADE,
        None,
        rarity=LootRarity.LEGENDARY,
        minimum_level=30,
    ),
    LootSpec("letter_d", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_u", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_c", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_k", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_h", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_n", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("letter_t", LootGrantKind.LETTER, None, rarity=LootRarity.UNUSUAL),
    LootSpec("junk_letter_q", LootGrantKind.DECORATION, None),
)
if set(_REWARD_EFFECT_RARITY) != {spec.key for spec in REWARD_EFFECT_CATALOG}:
    raise RuntimeError("reward effect rarity catalog is incomplete")
LOOT_CATALOG = (*STANDARD_LOOT_CATALOG, CURSE_LOOT_SPEC, *UNUSUAL_LOOT_CATALOG)
_BY_KEY = {spec.key: spec for spec in LOOT_CATALOG}
if len(_BY_KEY) != len(LOOT_CATALOG):
    raise RuntimeError("loot catalog keys must be unique")

LETTER_SEQUENCE = ("D", "U", "C", "K", "H", "U", "N", "T")
LETTER_BY_LOOT_KEY = {
    "letter_d": "D",
    "letter_u": "U",
    "letter_c": "C",
    "letter_k": "K",
    "letter_h": "H",
    "letter_n": "N",
    "letter_t": "T",
}


def loot_spec(key: str) -> LootSpec | None:
    return _BY_KEY.get(key) if isinstance(key, str) else None


def validate_loot_award(award: LootAward) -> LootSpec:
    if not isinstance(award, LootAward):
        raise ValueError("loot award must satisfy the domain contract")
    spec = loot_spec(award.key)
    if spec is None:
        raise ValueError("loot award references an unsupported key")
    if spec.grant_kind is LootGrantKind.LETTER:
        for nested in award.completion_loot:
            nested_spec = validate_loot_award(nested)
            if nested_spec.grant_kind is LootGrantKind.LETTER:
                raise ValueError("completion loot cannot contain another letter")
    elif award.completion_loot:
        raise ValueError("only a letter award can carry completion loot")
    if spec.grant_kind is LootGrantKind.CURSE:
        if award.magnitude is not None or curse_spec(award.curse_key or "") is None:
            raise ValueError("curse loot requires one supported curse key")
        return spec
    if award.curse_key is not None:
        raise ValueError("non-curse loot cannot carry a curse key")
    item = shop_item(spec.item_id) if spec.item_id is not None else None
    if item is not None and item.requires_magnitude:
        if (
            type(award.magnitude) is not int
            or award.magnitude < item.magnitude_min
            or award.magnitude > item.magnitude_max
        ):
            raise ValueError("loot magnitude is outside the item catalog")
    elif award.magnitude is not None:
        raise ValueError("this loot award does not accept a magnitude")
    return spec


def select_standard_loot(
    rolls: tuple[int, ...],
    *,
    chance_multiplier: int = 1,
    karma_basis_points: int = 0,
    magnitude: int | None = None,
) -> LootAward | None:
    """Select the first successful standard drop from injected rolls."""

    if type(rolls) is not tuple or len(rolls) != len(STANDARD_LOOT_CATALOG):
        raise ValueError("loot selection requires one roll per catalog entry")
    if any(type(roll) is not int or not 1 <= roll <= 1_000 for roll in rolls):
        raise ValueError("loot rolls must be integers from one through 1000")
    if type(chance_multiplier) is not int or chance_multiplier not in (1, 2):
        raise ValueError("loot chance multiplier must be one or two")
    for spec, roll in zip(STANDARD_LOOT_CATALOG, rolls, strict=True):
        threshold = standard_loot_threshold(
            spec,
            chance_multiplier=chance_multiplier,
            karma_basis_points=karma_basis_points,
        )
        if roll <= threshold:
            item = shop_item(spec.item_id) if spec.item_id is not None else None
            award = LootAward(
                spec.key,
                magnitude=(magnitude if item is not None and item.requires_magnitude else None),
            )
            validate_loot_award(award)
            return award
    return None


def standard_loot_threshold(
    spec: LootSpec,
    *,
    chance_multiplier: int = 1,
    karma_basis_points: int = 0,
) -> int:
    """Return one bounded threshold after abundance and the karma quality bias."""

    if spec not in STANDARD_LOOT_CATALOG:
        raise ValueError("standard loot threshold requires a standard catalog entry")
    if type(chance_multiplier) is not int or chance_multiplier not in (1, 2):
        raise ValueError("loot chance multiplier must be one or two")
    if (
        type(karma_basis_points) is not int
        or not -10_000 <= karma_basis_points <= 10_000
    ):
        raise ValueError("karma must be an integer from -10000 through 10000")
    assert spec.threshold_per_thousand is not None
    scale = 10_000
    if spec.key == "junk_item":
        scale -= karma_basis_points
    elif karma_basis_points > 0:
        scale += karma_basis_points
    adjusted = (spec.threshold_per_thousand * scale + 5_000) // 10_000
    return min(1_000, adjusted * chance_multiplier)


def _effect_group(item_id: int) -> str | None:
    item = shop_item(item_id)
    return None if item is None else item.exclusive_group


def acquire_loot(
    state: GameState,
    nickname: str,
    award: LootAward,
    now_ns: int,
) -> Transition:
    """Apply one validated acquisition fact after a killing shot."""

    if now_ns != state.now_ns:
        raise ValueError("loot acquisition must share the killing shot timestamp")
    spec = validate_loot_award(award)
    player = state.player(rfc1459_casefold(nickname))
    if player is None:
        raise ValueError("loot recipient is absent from game state")
    if player.level < spec.minimum_level:
        raise ValueError("loot recipient does not meet the minimum level")
    if spec.grant_kind is LootGrantKind.LETTER:
        return _acquire_letter(state, nickname, player, award)

    current = state
    effect_id = None
    item_id = spec.item_id
    experience_awarded = 0
    levels_gained = 0
    curse_key = None
    shop_credit_awarded = 0
    removed_item_ids: tuple[int, ...] = ()
    if spec.grant_kind is LootGrantKind.AMMUNITION:
        if player.ammo < player.capacity:
            player = replace(player, ammo=player.ammo + 1)
    elif spec.grant_kind is LootGrantKind.MAGAZINE:
        if player.magazines < player.magazine_capacity:
            player = replace(player, magazines=player.magazines + 1)
    elif spec.grant_kind is LootGrantKind.EXPERIENCE:
        progression = grant_experience(player, spec.experience)
        player = progression.player
        experience_awarded = spec.experience
        levels_gained = progression.levels_gained
    elif spec.grant_kind is LootGrantKind.CREDIT:
        shop_credit_awarded = spec.shop_credit
        player = replace(
            player,
            shop_credit=player.shop_credit + shop_credit_awarded,
        )
    elif spec.grant_kind is LootGrantKind.EFFECT:
        assert item_id is not None
        item = shop_item(item_id)
        assert item is not None
        removed = tuple(
            effect.item_id
            for effect in current.effects
            if effect.owner_key == player.key
            and (
                effect.item_id == item_id
                or effect.item_id in item.removes_item_ids
                or (
                    item.duplicate_policy is DuplicatePolicy.REPLACE_GROUP
                    and _effect_group(effect.item_id) == item.exclusive_group
                )
            )
        )
        retained = tuple(
            effect
            for effect in current.effects
            if not (
                effect.owner_key == player.key
                and (
                    effect.item_id == item_id
                    or effect.item_id in item.removes_item_ids
                    or (
                        item.duplicate_policy is DuplicatePolicy.REPLACE_GROUP
                        and _effect_group(effect.item_id) == item.exclusive_group
                    )
                )
            )
        )
        removed_item_ids = tuple(sorted(set(removed)))
        effect_id = current.next_effect_id
        effect = ActiveEffect(
            effect_id=effect_id,
            item_id=item_id,
            key=item.key,
            scope=item.scope,
            owner_key=player.key,
            source_key=None,
            activated_at_ns=now_ns,
            expires_at_ns=(
                None if item.duration_ns is None else now_ns + item.duration_ns
            ),
            remaining_uses=item.uses,
            magnitude=award.magnitude,
        )
        validate_active_effect(effect)
        current = replace(
            current,
            effects=tuple((*retained, effect)),
            next_effect_id=current.next_effect_id + 1,
        )
    elif spec.grant_kind is LootGrantKind.CURSE:
        curse_key = award.curse_key
        curse = curse_spec(curse_key or "")
        assert curse is not None
        blessing = next(
            (
                effect
                for effect in current.effects
                if effect.owner_key == player.key and effect.item_id == 103
            ),
            None,
        )
        if blessing is not None:
            current = replace(
                current,
                effects=tuple(
                    effect
                    for effect in current.effects
                    if effect.effect_id != blessing.effect_id
                ),
            )
            current = current.with_player(player)
            return Transition(
                current,
                (
                    Outcome(
                        OutcomeKind.CURSE_NEUTRALIZED,
                        actor=nickname,
                        player=player,
                        item_id=blessing.item_id,
                        effect_id=blessing.effect_id,
                        curse_key=curse_key,
                        loot_key=award.key,
                    ),
                ),
            )
        retained = tuple(
            active
            for active in current.curses
            if not (active.owner_key == player.key and active.key == curse.key)
        )
        active = ActiveCurse(
            curse_id=current.next_curse_id,
            key=curse.key,
            owner_key=player.key,
            activated_at_ns=now_ns,
            expires_at_ns=now_ns + curse.duration_ns,
            magnitude=curse.magnitude,
        )
        validate_active_curse(active)
        current = replace(
            current,
            curses=tuple((*retained, active)),
            next_curse_id=current.next_curse_id + 1,
        )
    elif spec.grant_kind is LootGrantKind.REWARD_EFFECT:
        assert item_id is not None
        reward = reward_effect(item_id)
        assert reward is not None
        retained = tuple(
            effect
            for effect in current.effects
            if not (
                effect.owner_key == player.key
                and (
                    effect.item_id == reward.item_id
                    or (
                        reward.exclusive_group is not None
                        and reward_effect(effect.item_id) is not None
                        and reward_effect(effect.item_id).exclusive_group
                        == reward.exclusive_group
                    )
                )
            )
        )
        removed_item_ids = tuple(
            sorted(
                {
                    effect.item_id
                    for effect in current.effects
                    if effect not in retained
                }
            )
        )
        effect_id = current.next_effect_id
        effect = ActiveEffect(
            effect_id=effect_id,
            item_id=reward.item_id,
            key=reward.key,
            scope=EffectScope.PLAYER,
            owner_key=player.key,
            source_key=None,
            activated_at_ns=now_ns,
            expires_at_ns=(
                None
                if reward.duration_ns is None
                else now_ns + reward.duration_ns
            ),
            remaining_uses=reward.uses,
            magnitude=reward.magnitude,
        )
        validate_active_effect(effect)
        current = replace(
            current,
            effects=tuple(sorted((*retained, effect), key=lambda value: value.effect_id)),
            next_effect_id=current.next_effect_id + 1,
        )
    elif spec.grant_kind is LootGrantKind.PERMANENT_UPGRADE:
        if item_quantity(player, spec.key) == 0:
            player = add_item(player, spec.key)
            player = replace(
                player,
                capacity=player.capacity + spec.ammo_capacity_bonus,
                magazine_capacity=(
                    player.magazine_capacity + spec.magazine_capacity_bonus
                ),
            )
            if spec.removes_item_ids:
                removed_item_ids = tuple(
                    sorted(
                        {
                            effect.item_id
                            for effect in current.effects
                            if effect.owner_key == player.key
                            and effect.item_id in spec.removes_item_ids
                        }
                    )
                )
                current = replace(
                    current,
                    effects=tuple(
                        effect
                        for effect in current.effects
                        if not (
                            effect.owner_key == player.key
                            and effect.item_id in spec.removes_item_ids
                        )
                    ),
                )

    current = current.with_player(player)
    return Transition(
        current,
        (
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor=nickname,
                player=player,
                item_id=item_id,
                effect_id=effect_id,
                experience_awarded=experience_awarded,
                levels_gained=levels_gained,
                curse_key=curse_key,
                removed_item_ids=removed_item_ids,
                loot_key=award.key,
                loot_magnitude=award.magnitude,
                shop_credit_awarded=shop_credit_awarded,
            ),
        ),
    )


def _acquire_letter(
    state: GameState,
    nickname: str,
    player: PlayerState,
    award: LootAward,
) -> Transition:
    """Set one missing DUCK HUNT slot and atomically settle a completed phrase."""

    letter = LETTER_BY_LOOT_KEY[award.key]
    missing = tuple(
        index
        for index, expected in enumerate(LETTER_SEQUENCE)
        if expected == letter and not player.letter_slots[index]
    )
    if not missing:
        if award.completion_loot:
            raise ValueError("duplicate letter cannot carry completion loot")
        return Transition(
            state,
            (
                Outcome(
                    OutcomeKind.LOOT_ACQUIRED,
                    actor=nickname,
                    player=player,
                    loot_key=award.key,
                ),
            ),
        )

    slots = list(player.letter_slots)
    slots[missing[0]] = True
    completed = all(slots)
    if completed and not award.completion_loot:
        raise ValueError("completed letter collection requires injected reward loot")
    if not completed and award.completion_loot:
        raise ValueError("incomplete letter collection cannot settle reward loot")

    if completed:
        player = replace(
            player,
            letter_slots=(False,) * len(LETTER_SEQUENCE),
        )
    else:
        player = replace(player, letter_slots=tuple(slots))
    current = state.with_player(player)

    if completed:
        for nested in award.completion_loot:
            acquired = acquire_loot(current, nickname, nested, state.now_ns)
            current = acquired.state
        player = current.player(player.key)
        assert player is not None
        player = replace(
            player,
            ammo=player.capacity,
            magazines=player.magazine_capacity,
            shop_credit=player.shop_credit + 50,
        )
        current = current.with_player(player)

    return Transition(
        current,
        (
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor=nickname,
                player=player,
                loot_key=award.key,
                shop_credit_awarded=50 if completed else 0,
                letter_collection_completed=completed,
            ),
        ),
    )
