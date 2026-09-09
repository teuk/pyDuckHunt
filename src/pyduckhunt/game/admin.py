"""Replayable, invariant-preserving player administration."""

from __future__ import annotations

from dataclasses import replace

from pyduckhunt.game.bread import active_channel_breads, MAX_CHANNEL_BREAD
from pyduckhunt.game.catalog import GrantKind, shop_item
from pyduckhunt.game.engine import advance_time
from pyduckhunt.game.model import (
    ActiveEffect,
    GameState,
    PlayerState,
    ScheduledAction,
    Transition,
)
from pyduckhunt.game.progression import experience_required
from pyduckhunt.identity import rfc1459_casefold


class PlayerAdministrationError(ValueError):
    """A bounded partyline player update could not be applied."""


TRUTH_FIELDS = frozenset(("confiscated", "jammed"))
CAPACITY_FIELDS = frozenset(("capacity", "magazine_capacity"))
COUNTER_FIELDS = frozenset(
    (
        "compulsive_reloads",
        "confiscations",
        "deaths",
        "empty_shots",
        "golden_hits",
        "hits",
        "incidents_absorbed",
        "incidents_caused",
        "incidents_deflected",
        "jammed_shots",
        "misses",
        "shots_received",
        "wild_shots",
    )
)
SETTABLE_FIELDS = frozenset(
    (
        "ammo",
        "capacity",
        "carried_ducks",
        "confiscated",
        "experience",
        "fatigue_centi",
        "jammed",
        "level",
        "magazine_capacity",
        "magazines",
        "shop_credit",
        *COUNTER_FIELDS,
    )
)
ADDITIVE_FIELDS = frozenset(("ammo", "magazines"))
MAX_COUNTER_VALUE = 1_000_000_000
MAX_CAPACITY = 100
MAX_LEVEL = 1_000
WEAPON_CONTROL_OPERATIONS = frozenset(("rearm", "unarm", "unarm_permanent"))
ADMIN_CHANNEL_ITEM_IDS = frozenset((20, 21))


def validate_player_update_request(field: str, operation: str, value: int) -> None:
    """Validate the stable journal representation of an admin update."""

    if type(field) is not str or field not in SETTABLE_FIELDS:
        raise PlayerAdministrationError("unsupported player field")
    if operation not in ("add", "set"):
        raise PlayerAdministrationError("unsupported player operation")
    if operation == "add" and field not in ADDITIVE_FIELDS:
        raise PlayerAdministrationError("this player field cannot be incremented")
    if type(value) is not int:
        raise PlayerAdministrationError("player update value must be an integer")
    if operation == "add" and not 1 <= value <= MAX_CAPACITY:
        raise PlayerAdministrationError("increment must be between 1 and 100")
    if field in TRUTH_FIELDS and value not in (0, 1):
        raise PlayerAdministrationError("truth-valued player fields accept only 0 or 1")
    if field == "capacity" and not 1 <= value <= MAX_CAPACITY:
        raise PlayerAdministrationError("weapon capacity must be between 1 and 100")
    if field == "magazine_capacity" and not 0 <= value <= MAX_CAPACITY:
        raise PlayerAdministrationError("magazine capacity must be between 0 and 100")
    if field == "level" and not 1 <= value <= MAX_LEVEL:
        raise PlayerAdministrationError("level must be between 1 and 1000")
    if field == "fatigue_centi" and not -300 <= value <= 10_000:
        raise PlayerAdministrationError("fatigue must be between -3 and 100 points")
    if operation == "set" and field not in (
        *TRUTH_FIELDS,
        *CAPACITY_FIELDS,
        "fatigue_centi",
        "level",
    ) and not 0 <= value <= MAX_COUNTER_VALUE:
        raise PlayerAdministrationError("player value is outside the bounded range")


def apply_player_update(
    state: GameState,
    nickname: str,
    now_ns: int,
    *,
    field: str,
    operation: str,
    value: int,
) -> Transition:
    """Advance time, update one existing player, and preserve model invariants."""

    if not isinstance(state, GameState):
        raise PlayerAdministrationError("player update requires game state")
    if type(nickname) is not str or not nickname or any(
        character in nickname for character in ("\x00", "\r", "\n", " ")
    ):
        raise PlayerAdministrationError("player nickname is invalid")
    validate_player_update_request(field, operation, value)
    current = advance_time(state, now_ns).state
    player = current.player(rfc1459_casefold(nickname))
    if player is None:
        raise PlayerAdministrationError("player does not exist")
    updated = _updated_player(player, field, operation, value)
    return Transition(current.with_player(updated), ())


def validate_weapon_control_request(operation: str) -> None:
    """Validate one owner-only, replayable weapon-control operation."""

    if type(operation) is not str or operation not in WEAPON_CONTROL_OPERATIONS:
        raise PlayerAdministrationError("unsupported weapon-control operation")


def apply_weapon_control(
    state: GameState,
    nickname: str,
    now_ns: int,
    *,
    operation: str,
) -> Transition:
    """Advance time and apply one explicit owner weapon-control operation."""

    if not isinstance(state, GameState):
        raise PlayerAdministrationError("weapon control requires game state")
    if type(nickname) is not str or not nickname or any(
        character in nickname for character in ("\x00", "\r", "\n", " ")
    ):
        raise PlayerAdministrationError("player nickname is invalid")
    validate_weapon_control_request(operation)
    current = advance_time(state, now_ns).state
    player = current.player(rfc1459_casefold(nickname))
    if player is None:
        raise PlayerAdministrationError("player does not exist")
    if operation == "rearm":
        updated = replace(
            player,
            confiscated=False,
            permanently_confiscated=False,
        )
    elif operation == "unarm_permanent":
        updated = replace(
            player,
            confiscated=True,
            permanently_confiscated=True,
        )
    else:
        updated = replace(
            player,
            confiscated=True,
            permanently_confiscated=False,
        )
    return Transition(current.with_player(updated), ())


def validate_admin_channel_item_request(
    item_id: int,
    now_ns: int,
    scheduled_for_ns: int | None,
) -> None:
    """Validate one replayable owner grant equivalent to shop item 20 or 21."""

    if type(item_id) is not int or item_id not in ADMIN_CHANNEL_ITEM_IDS:
        raise PlayerAdministrationError("unsupported administrative channel item")
    if type(now_ns) is not int or now_ns < 0:
        raise PlayerAdministrationError("administrative item time is invalid")
    item = shop_item(item_id)
    assert item is not None
    if item.grant_kind is GrantKind.CHANNEL_ACTION:
        assert item.schedule_min_ns is not None and item.schedule_max_ns is not None
        if type(scheduled_for_ns) is not int or not (
            now_ns + item.schedule_min_ns
            <= scheduled_for_ns
            <= now_ns + item.schedule_max_ns
        ):
            raise PlayerAdministrationError(
                "administrative channel action deadline is invalid"
            )
    elif scheduled_for_ns is not None:
        raise PlayerAdministrationError(
            "administrative channel effect does not accept a deadline"
        )


def apply_admin_channel_item(
    state: GameState,
    actor: str,
    item_id: int,
    now_ns: int,
    *,
    scheduled_for_ns: int | None = None,
) -> Transition:
    """Grant channel bread or a duck call without creating or charging a player."""

    if not isinstance(state, GameState):
        raise PlayerAdministrationError("administrative item requires game state")
    if type(actor) is not str or not actor or any(
        character in actor for character in ("\x00", "\r", "\n", " ")
    ):
        raise PlayerAdministrationError("administrative actor is invalid")
    validate_admin_channel_item_request(item_id, now_ns, scheduled_for_ns)
    current = advance_time(state, now_ns).state
    item = shop_item(item_id)
    assert item is not None
    if (item_id == 21 and current.bread_plan_effect_ids is not None
            and len(active_channel_breads(current, now_ns)) >= MAX_CHANNEL_BREAD):
        raise PlayerAdministrationError("maximum channel bread reached (20)")
    if item.grant_kind is GrantKind.CHANNEL_ACTION:
        assert scheduled_for_ns is not None
        action = ScheduledAction(
            action_id=current.next_action_id,
            item_id=item.item_id,
            key=item.key,
            source_key=None,
            created_at_ns=now_ns,
            due_at_ns=scheduled_for_ns,
        )
        updated = replace(
            current,
            scheduled_actions=tuple((*current.scheduled_actions, action)),
            next_action_id=current.next_action_id + 1,
        )
    else:
        assert item.duration_ns is not None
        effect = ActiveEffect(
            effect_id=current.next_effect_id,
            item_id=item.item_id,
            key=item.key,
            scope=item.scope,
            owner_key=None,
            source_key=None,
            activated_at_ns=now_ns,
            expires_at_ns=now_ns + item.duration_ns,
        )
        updated = replace(
            current,
            effects=tuple((*current.effects, effect)),
            next_effect_id=current.next_effect_id + 1,
        )
    return Transition(updated, ())


def _updated_player(
    player: PlayerState,
    field: str,
    operation: str,
    value: int,
) -> PlayerState:
    if operation == "add":
        limit = player.capacity if field == "ammo" else player.magazine_capacity
        return replace(player, **{field: min(limit, getattr(player, field) + value)})
    if field == "capacity":
        return replace(player, capacity=value, ammo=min(player.ammo, value))
    if field == "magazine_capacity":
        return replace(
            player,
            magazine_capacity=value,
            magazines=min(player.magazines, value),
        )
    if field == "level":
        return replace(
            player,
            level=value,
            experience=min(player.experience, experience_required(value) - 1),
        )
    if field == "experience" and value >= experience_required(player.level):
        raise PlayerAdministrationError(
            "experience must remain below the current level threshold"
        )
    if field == "confiscated":
        return replace(
            player,
            confiscated=bool(value),
            permanently_confiscated=False,
        )
    converted: int | bool = bool(value) if field in TRUTH_FIELDS else value
    return replace(player, **{field: converted})
