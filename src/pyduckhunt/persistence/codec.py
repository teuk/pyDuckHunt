"""Canonical JSON codec for durable game state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    DailySchedule,
    EffectScope,
    FlightKind,
    FlightState,
    GameState,
    InventoryStack,
    LastFlight,
    LastFlightConclusion,
    LETTER_SLOT_COUNT,
    PlayerState,
    ScheduledAction,
    ThrottleWindow,
)
from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.catalog import validate_active_effect, validate_scheduled_action
from pyduckhunt.game.curses import validate_active_curse
from pyduckhunt.game.targets import validate_flight_reward
from pyduckhunt.game.runtime import (
    validate_daily_schedule_state,
    validate_throttle_window,
)


SCHEMA_VERSION = 20
SUPPORTED_SCHEMA_VERSIONS = (11, 12, 13, 14, 15, 16, 17, 18, 19, SCHEMA_VERSION)
DAY_NS = 86_400_000_000_000


class CodecError(ValueError):
    """Raised when persisted data does not satisfy the current schema."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON deterministically for hashing and byte comparison."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CodecError(f"{field} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CodecError(f"{field} keys differ; missing={missing}, extra={extra}")


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CodecError(f"{field} must be an integer >= {minimum}")
    return value


def _signed_integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise CodecError(f"{field} must be an integer")
    return value


def encode_game_state(state: GameState) -> dict[str, object]:
    """Convert immutable game state to schema-version-independent primitives."""

    flight: dict[str, object] | None = None
    if state.flight is not None:
        flight = {
            "expires_at_ns": state.flight.expires_at_ns,
            "flight_id": state.flight.flight_id,
            "health": state.flight.health,
            "kind": state.flight.kind.value,
            "max_health": state.flight.max_health,
            "reward_experience": state.flight.reward_experience,
            "spawned_at_ns": state.flight.spawned_at_ns,
        }
    last_flight: dict[str, object] | None = None
    if state.last_flight is not None:
        last_flight = {
            "actor": state.last_flight.actor,
            "conclusion": state.last_flight.conclusion.value,
            "ended_at_ns": state.last_flight.ended_at_ns,
            "flight_id": state.last_flight.flight_id,
            "kind": state.last_flight.kind.value,
            "spawned_at_ns": state.last_flight.spawned_at_ns,
        }
    players = [
        {
            "ammo": player.ammo,
            "best_time_ms": player.best_time_ms,
            "capacity": player.capacity,
            "carried_day_start_ns": player.carried_day_start_ns,
            "carried_ducks": player.carried_ducks,
            "confiscated": player.confiscated,
            "permanently_confiscated": player.permanently_confiscated,
            "confiscations": player.confiscations,
            "deaths": player.deaths,
            "empty_shots": player.empty_shots,
            "experience": player.experience,
            "experience_spent": player.experience_spent,
            "fatigue_centi": player.fatigue_centi,
            "golden_hits": player.golden_hits,
            "hits": player.hits,
            "incidents_absorbed": player.incidents_absorbed,
            "incidents_caused": player.incidents_caused,
            "incidents_deflected": player.incidents_deflected,
            "inventory": [
                {"key": stack.key, "quantity": stack.quantity}
                for stack in player.inventory
            ],
            "jammed": player.jammed,
            "jams": player.jams,
            "jammed_shots": player.jammed_shots,
            "karma_decay_at_ns": player.karma_decay_at_ns,
            "karma_modifier_basis_points": player.karma_modifier_basis_points,
            "key": player.key,
            "level": player.level,
            "letter_slots": list(player.letter_slots),
            "magazine_capacity": player.magazine_capacity,
            "magazines": player.magazines,
            "misses": player.misses,
            "nickname": player.nickname,
            "shots_received": player.shots_received,
            "shots_fired": player.shots_fired,
            "shop_credit": player.shop_credit,
            "compulsive_reloads": player.compulsive_reloads,
            "wild_shots": player.wild_shots,
        }
        for player in state.players
    ]
    effects = [
        {
            "activated_at_ns": effect.activated_at_ns,
            "effect_id": effect.effect_id,
            "expires_at_ns": effect.expires_at_ns,
            "item_id": effect.item_id,
            "key": effect.key,
            "magnitude": effect.magnitude,
            "owner_key": effect.owner_key,
            "remaining_uses": effect.remaining_uses,
            "scope": effect.scope.value,
            "source_key": effect.source_key,
        }
        for effect in state.effects
    ]
    scheduled_actions = [
        {
            "action_id": action.action_id,
            "created_at_ns": action.created_at_ns,
            "due_at_ns": action.due_at_ns,
            "item_id": action.item_id,
            "key": action.key,
            "source_key": action.source_key,
        }
        for action in state.scheduled_actions
    ]
    curses = [
        {
            "activated_at_ns": curse.activated_at_ns,
            "curse_id": curse.curse_id,
            "expires_at_ns": curse.expires_at_ns,
            "key": curse.key,
            "magnitude": curse.magnitude,
            "owner_key": curse.owner_key,
        }
        for curse in state.curses
    ]
    daily_schedule = (
        None
        if state.daily_schedule is None
        else {
            "day_start_ns": state.daily_schedule.day_start_ns,
            "deadlines_ns": list(state.daily_schedule.deadlines_ns),
            "next_index": state.daily_schedule.next_index,
        }
    )
    throttle_windows = [
        {
            "command": None if window.command is None else window.command.value,
            "expires_at_ns": list(window.expires_at_ns),
            "notice_after_ns": window.notice_after_ns,
            "player_key": window.player_key,
        }
        for window in state.throttle_windows
    ]
    return {
        "curses": curses,
        "daily_schedule": daily_schedule,
        "effects": effects,
        "flight": flight,
        "last_flight": last_flight,
        "last_shooter_key": state.last_shooter_key,
        "next_action_id": state.next_action_id,
        "next_curse_id": state.next_curse_id,
        "next_effect_id": state.next_effect_id,
        "next_flight_id": state.next_flight_id,
        "now_ns": state.now_ns,
        "players": players,
        "scheduled_actions": scheduled_actions,
        "throttle_windows": throttle_windows,
    }


def _decode_game_state(raw: object, schema_version: int) -> GameState:
    payload = _mapping(raw, "state")
    state_fields = {
        "curses",
        "daily_schedule",
        "effects",
        "flight",
        "next_action_id",
        "next_curse_id",
        "next_effect_id",
        "next_flight_id",
        "now_ns",
        "players",
        "scheduled_actions",
        "throttle_windows",
    }
    if schema_version >= 17:
        state_fields.add("last_flight")
    if schema_version >= 19:
        state_fields.add("last_shooter_key")
    _exact_keys(
        payload,
        state_fields,
        "state",
    )
    state_now_ns = _integer(payload["now_ns"], "state.now_ns")
    last_shooter_key = (
        payload["last_shooter_key"] if schema_version >= 19 else None
    )
    if last_shooter_key is not None and not isinstance(last_shooter_key, str):
        raise CodecError("state.last_shooter_key must be a string or null")

    raw_flight = payload["flight"]
    flight: FlightState | None = None
    if raw_flight is not None:
        flight_payload = _mapping(raw_flight, "state.flight")
        _exact_keys(
            flight_payload,
            {
                "expires_at_ns",
                "flight_id",
                "health",
                "kind",
                "max_health",
                "reward_experience",
                "spawned_at_ns",
            },
            "state.flight",
        )
        try:
            flight_kind = FlightKind(flight_payload["kind"])
        except (TypeError, ValueError) as error:
            raise CodecError("state.flight.kind is unknown") from error
        max_health = _integer(
            flight_payload["max_health"],
            "state.flight.max_health",
            minimum=1,
        )
        reward_experience = _integer(
            flight_payload["reward_experience"],
            "state.flight.reward_experience",
        )
        try:
            validate_flight_reward(flight_kind, max_health, reward_experience)
        except ValueError as error:
            raise CodecError("state.flight differs from the target catalog") from error
        flight = FlightState(
            flight_id=_integer(flight_payload["flight_id"], "state.flight.flight_id", minimum=1),
            spawned_at_ns=_integer(
                flight_payload["spawned_at_ns"], "state.flight.spawned_at_ns"
            ),
            expires_at_ns=_integer(
                flight_payload["expires_at_ns"], "state.flight.expires_at_ns", minimum=1
            ),
            health=_integer(
                flight_payload["health"], "state.flight.health", minimum=1
            ),
            max_health=max_health,
            kind=flight_kind,
            reward_experience=reward_experience,
        )

    last_flight: LastFlight | None = None
    raw_last_flight = payload.get("last_flight")
    if raw_last_flight is not None:
        last_payload = _mapping(raw_last_flight, "state.last_flight")
        _exact_keys(
            last_payload,
            {"actor", "conclusion", "ended_at_ns", "flight_id", "kind", "spawned_at_ns"},
            "state.last_flight",
        )
        try:
            last_kind = FlightKind(last_payload["kind"])
            conclusion = LastFlightConclusion(last_payload["conclusion"])
        except (TypeError, ValueError) as error:
            raise CodecError("state.last_flight kind or conclusion is unknown") from error
        actor = last_payload["actor"]
        if actor is not None and not isinstance(actor, str):
            raise CodecError("state.last_flight.actor must be a string or null")
        last_flight = LastFlight(
            flight_id=_integer(
                last_payload["flight_id"],
                "state.last_flight.flight_id",
                minimum=1,
            ),
            kind=last_kind,
            spawned_at_ns=_integer(
                last_payload["spawned_at_ns"],
                "state.last_flight.spawned_at_ns",
            ),
            ended_at_ns=_integer(
                last_payload["ended_at_ns"],
                "state.last_flight.ended_at_ns",
                minimum=1,
            ),
            conclusion=conclusion,
            actor=actor,
        )

    raw_players = payload["players"]
    if not isinstance(raw_players, list):
        raise CodecError("state.players must be a JSON array")
    players: list[PlayerState] = []
    for index, raw_player in enumerate(raw_players):
        field = f"state.players[{index}]"
        player = _mapping(raw_player, field)
        player_fields = {
            "ammo",
            "best_time_ms",
            "capacity",
            "confiscated",
            "confiscations",
            "deaths",
            "experience",
            "fatigue_centi",
            "golden_hits",
            "hits",
            "incidents_absorbed",
            "incidents_caused",
            "incidents_deflected",
            "inventory",
            "jammed",
            "key",
            "level",
            "magazine_capacity",
            "magazines",
            "misses",
            "nickname",
            "shots_received",
            "shop_credit",
        }
        if schema_version >= 12:
            player_fields.add("wild_shots")
        if schema_version >= 13:
            player_fields.update(
                {
                    "compulsive_reloads",
                    "empty_shots",
                    "jammed_shots",
                    "karma_decay_at_ns",
                    "karma_modifier_basis_points",
                }
            )
        if schema_version >= 16:
            player_fields.update(
                {
                    "carried_day_start_ns",
                    "carried_ducks",
                    "letter_slots",
                }
            )
        if schema_version >= 19:
            player_fields.add("permanently_confiscated")
        if schema_version >= 20:
            player_fields.update({"experience_spent", "jams", "shots_fired"})
        _exact_keys(
            player,
            player_fields,
            field,
        )
        key = player["key"]
        nickname = player["nickname"]
        if not isinstance(key, str) or not isinstance(nickname, str):
            raise CodecError(f"{field} identity fields must be strings")
        raw_best = player["best_time_ms"]
        best_time_ms = (
            None
            if raw_best is None
            else _integer(raw_best, f"{field}.best_time_ms")
        )
        raw_inventory = player["inventory"]
        if not isinstance(raw_inventory, list):
            raise CodecError(f"{field}.inventory must be a JSON array")
        inventory: list[InventoryStack] = []
        for item_index, raw_stack in enumerate(raw_inventory):
            item_field = f"{field}.inventory[{item_index}]"
            stack = _mapping(raw_stack, item_field)
            _exact_keys(stack, {"key", "quantity"}, item_field)
            item_key = stack["key"]
            if not isinstance(item_key, str):
                raise CodecError(f"{item_field}.key must be a string")
            try:
                inventory.append(
                    InventoryStack(
                        key=item_key,
                        quantity=_integer(
                            stack["quantity"],
                            f"{item_field}.quantity",
                            minimum=1,
                        ),
                    )
                )
            except ValueError as error:
                raise CodecError(f"{item_field} violates inventory invariants") from error
        jammed = player["jammed"]
        if type(jammed) is not bool:
            raise CodecError(f"{field}.jammed must be a truth value")
        confiscated = player["confiscated"]
        if type(confiscated) is not bool:
            raise CodecError(f"{field}.confiscated must be a truth value")
        permanently_confiscated = (
            player["permanently_confiscated"]
            if schema_version >= 19
            else False
        )
        if type(permanently_confiscated) is not bool:
            raise CodecError(
                f"{field}.permanently_confiscated must be a truth value"
            )
        if schema_version >= 16:
            raw_letter_slots = player["letter_slots"]
            if (
                not isinstance(raw_letter_slots, list)
                or len(raw_letter_slots) != LETTER_SLOT_COUNT
                or any(type(value) is not bool for value in raw_letter_slots)
            ):
                raise CodecError(f"{field}.letter_slots must contain eight truth values")
            letter_slots = tuple(raw_letter_slots)
        else:
            letter_slots = (False,) * LETTER_SLOT_COUNT
        players.append(
            PlayerState(
                key=key,
                nickname=nickname,
                ammo=_integer(player["ammo"], f"{field}.ammo"),
                capacity=_integer(player["capacity"], f"{field}.capacity", minimum=1),
                magazines=_integer(player["magazines"], f"{field}.magazines"),
                magazine_capacity=_integer(
                    player["magazine_capacity"],
                    f"{field}.magazine_capacity",
                ),
                hits=_integer(player["hits"], f"{field}.hits"),
                misses=_integer(player["misses"], f"{field}.misses"),
                wild_shots=(
                    _integer(player["wild_shots"], f"{field}.wild_shots")
                    if schema_version >= 12
                    else 0
                ),
                empty_shots=(
                    _integer(player["empty_shots"], f"{field}.empty_shots")
                    if schema_version >= 13
                    else 0
                ),
                jammed_shots=(
                    _integer(player["jammed_shots"], f"{field}.jammed_shots")
                    if schema_version >= 13
                    else 0
                ),
                compulsive_reloads=(
                    _integer(
                        player["compulsive_reloads"],
                        f"{field}.compulsive_reloads",
                    )
                    if schema_version >= 13
                    else 0
                ),
                shots_fired=(
                    _integer(player["shots_fired"], f"{field}.shots_fired")
                    if schema_version >= 20
                    else 0
                ),
                jams=(
                    _integer(player["jams"], f"{field}.jams")
                    if schema_version >= 20
                    else 0
                ),
                best_time_ms=best_time_ms,
                level=_integer(player["level"], f"{field}.level", minimum=1),
                experience=_integer(player["experience"], f"{field}.experience"),
                experience_spent=(
                    _integer(
                        player["experience_spent"],
                        f"{field}.experience_spent",
                    )
                    if schema_version >= 20
                    else 0
                ),
                fatigue_centi=_integer(
                    player["fatigue_centi"],
                    f"{field}.fatigue_centi",
                ),
                inventory=tuple(inventory),
                jammed=jammed,
                confiscated=confiscated,
                permanently_confiscated=permanently_confiscated,
                confiscations=_integer(
                    player["confiscations"], f"{field}.confiscations"
                ),
                incidents_caused=_integer(
                    player["incidents_caused"], f"{field}.incidents_caused"
                ),
                shots_received=_integer(
                    player["shots_received"], f"{field}.shots_received"
                ),
                incidents_deflected=_integer(
                    player["incidents_deflected"], f"{field}.incidents_deflected"
                ),
                incidents_absorbed=_integer(
                    player["incidents_absorbed"], f"{field}.incidents_absorbed"
                ),
                deaths=_integer(player["deaths"], f"{field}.deaths"),
                golden_hits=_integer(
                    player["golden_hits"], f"{field}.golden_hits"
                ),
                shop_credit=_integer(
                    player["shop_credit"], f"{field}.shop_credit"
                ),
                karma_modifier_basis_points=(
                    _signed_integer(
                        player["karma_modifier_basis_points"],
                        f"{field}.karma_modifier_basis_points",
                    )
                    if schema_version >= 13
                    else 0
                ),
                karma_decay_at_ns=(
                    None
                    if schema_version < 13
                    or player["karma_decay_at_ns"] is None
                    else _integer(
                        player["karma_decay_at_ns"],
                        f"{field}.karma_decay_at_ns",
                        minimum=1,
                    )
                ),
                carried_ducks=(
                    _integer(player["carried_ducks"], f"{field}.carried_ducks")
                    if schema_version >= 16
                    else 0
                ),
                carried_day_start_ns=(
                    _integer(
                        player["carried_day_start_ns"],
                        f"{field}.carried_day_start_ns",
                    )
                    if schema_version >= 16
                    else state_now_ns - state_now_ns % DAY_NS
                ),
                letter_slots=letter_slots,
            )
        )

    raw_effects = payload["effects"]
    if not isinstance(raw_effects, list):
        raise CodecError("state.effects must be a JSON array")
    effects: list[ActiveEffect] = []
    for index, raw_effect in enumerate(raw_effects):
        field = f"state.effects[{index}]"
        effect = _mapping(raw_effect, field)
        _exact_keys(
            effect,
            {
                "activated_at_ns",
                "effect_id",
                "expires_at_ns",
                "item_id",
                "key",
                "magnitude",
                "owner_key",
                "remaining_uses",
                "scope",
                "source_key",
            },
            field,
        )
        key = effect["key"]
        owner_key = effect["owner_key"]
        source_key = effect["source_key"]
        if not isinstance(key, str) or (
            owner_key is not None and not isinstance(owner_key, str)
        ) or (
            source_key is not None and not isinstance(source_key, str)
        ):
            raise CodecError(f"{field} key fields must be strings or null")
        try:
            scope = EffectScope(effect["scope"])
        except (TypeError, ValueError) as error:
            raise CodecError(f"{field}.scope is unknown") from error
        raw_expiration = effect["expires_at_ns"]
        raw_uses = effect["remaining_uses"]
        raw_magnitude = effect["magnitude"]
        decoded_effect = ActiveEffect(
            effect_id=_integer(effect["effect_id"], f"{field}.effect_id", minimum=1),
            item_id=_integer(effect["item_id"], f"{field}.item_id", minimum=1),
            key=key,
            scope=scope,
            owner_key=owner_key,
            source_key=source_key,
            activated_at_ns=_integer(
                effect["activated_at_ns"], f"{field}.activated_at_ns"
            ),
            expires_at_ns=(
                None
                if raw_expiration is None
                else _integer(raw_expiration, f"{field}.expires_at_ns", minimum=1)
            ),
            remaining_uses=(
                None
                if raw_uses is None
                else _integer(raw_uses, f"{field}.remaining_uses", minimum=1)
            ),
            magnitude=(
                None
                if raw_magnitude is None
                else _signed_integer(raw_magnitude, f"{field}.magnitude")
            ),
        )
        try:
            validate_active_effect(decoded_effect)
        except ValueError as error:
            raise CodecError(f"{field} differs from the shop catalog") from error
        effects.append(decoded_effect)

    raw_actions = payload["scheduled_actions"]
    if not isinstance(raw_actions, list):
        raise CodecError("state.scheduled_actions must be a JSON array")
    scheduled_actions: list[ScheduledAction] = []
    for index, raw_action in enumerate(raw_actions):
        field = f"state.scheduled_actions[{index}]"
        action = _mapping(raw_action, field)
        _exact_keys(
            action,
            {"action_id", "created_at_ns", "due_at_ns", "item_id", "key", "source_key"},
            field,
        )
        key = action["key"]
        source_key = action["source_key"]
        if not isinstance(key, str) or not isinstance(source_key, str):
            raise CodecError(f"{field} key fields must be strings")
        decoded_action = ScheduledAction(
                action_id=_integer(action["action_id"], f"{field}.action_id", minimum=1),
                item_id=_integer(action["item_id"], f"{field}.item_id", minimum=1),
                key=key,
                source_key=source_key,
                created_at_ns=_integer(action["created_at_ns"], f"{field}.created_at_ns"),
                due_at_ns=_integer(action["due_at_ns"], f"{field}.due_at_ns", minimum=1),
            )
        try:
            validate_scheduled_action(decoded_action)
        except ValueError as error:
            raise CodecError(f"{field} differs from the shop catalog") from error
        scheduled_actions.append(decoded_action)

    raw_curses = payload["curses"]
    if not isinstance(raw_curses, list):
        raise CodecError("state.curses must be a JSON array")
    curses: list[ActiveCurse] = []
    for index, raw_curse in enumerate(raw_curses):
        field = f"state.curses[{index}]"
        curse = _mapping(raw_curse, field)
        _exact_keys(
            curse,
            {"activated_at_ns", "curse_id", "expires_at_ns", "key", "magnitude", "owner_key"},
            field,
        )
        key = curse["key"]
        owner_key = curse["owner_key"]
        if not isinstance(key, str) or not isinstance(owner_key, str):
            raise CodecError(f"{field} key fields must be strings")
        raw_magnitude = curse["magnitude"]
        decoded_curse = ActiveCurse(
            curse_id=_integer(curse["curse_id"], f"{field}.curse_id", minimum=1),
            key=key,
            owner_key=owner_key,
            activated_at_ns=_integer(curse["activated_at_ns"], f"{field}.activated_at_ns"),
            expires_at_ns=_integer(curse["expires_at_ns"], f"{field}.expires_at_ns", minimum=1),
            magnitude=(
                None
                if raw_magnitude is None
                else _signed_integer(raw_magnitude, f"{field}.magnitude")
            ),
        )
        try:
            validate_active_curse(decoded_curse)
        except ValueError as error:
            raise CodecError(f"{field} differs from the curse catalog") from error
        curses.append(decoded_curse)

    raw_schedule = payload["daily_schedule"]
    daily_schedule: DailySchedule | None = None
    if raw_schedule is not None:
        schedule = _mapping(raw_schedule, "state.daily_schedule")
        _exact_keys(
            schedule,
            {"day_start_ns", "deadlines_ns", "next_index"},
            "state.daily_schedule",
        )
        raw_deadlines = schedule["deadlines_ns"]
        if not isinstance(raw_deadlines, list):
            raise CodecError("state.daily_schedule.deadlines_ns must be a JSON array")
        daily_schedule = DailySchedule(
            day_start_ns=_integer(
                schedule["day_start_ns"],
                "state.daily_schedule.day_start_ns",
            ),
            deadlines_ns=tuple(
                _integer(
                    value,
                    f"state.daily_schedule.deadlines_ns[{index}]",
                )
                for index, value in enumerate(raw_deadlines)
            ),
            next_index=_integer(
                schedule["next_index"],
                "state.daily_schedule.next_index",
            ),
        )
        try:
            validate_daily_schedule_state(daily_schedule)
        except ValueError as error:
            raise CodecError("state.daily_schedule violates runtime policy") from error

    raw_windows = payload["throttle_windows"]
    if not isinstance(raw_windows, list):
        raise CodecError("state.throttle_windows must be a JSON array")
    throttle_windows: list[ThrottleWindow] = []
    for index, raw_window in enumerate(raw_windows):
        field = f"state.throttle_windows[{index}]"
        window = _mapping(raw_window, field)
        _exact_keys(
            window,
            {"command", "expires_at_ns", "notice_after_ns", "player_key"},
            field,
        )
        player_key = window["player_key"]
        if player_key is not None and not isinstance(player_key, str):
            raise CodecError(f"{field}.player_key must be a string or null")
        raw_command = window["command"]
        try:
            command = None if raw_command is None else CommandKind(raw_command)
        except (TypeError, ValueError) as error:
            raise CodecError(f"{field}.command is unknown") from error
        raw_expirations = window["expires_at_ns"]
        if not isinstance(raw_expirations, list):
            raise CodecError(f"{field}.expires_at_ns must be a JSON array")
        decoded_window = ThrottleWindow(
            player_key=player_key,
            command=command,
            expires_at_ns=tuple(
                _integer(value, f"{field}.expires_at_ns[{offset}]", minimum=1)
                for offset, value in enumerate(raw_expirations)
            ),
            notice_after_ns=_integer(
                window["notice_after_ns"],
                f"{field}.notice_after_ns",
            ),
        )
        try:
            validate_throttle_window(decoded_window)
        except ValueError as error:
            raise CodecError(f"{field} violates runtime policy") from error
        throttle_windows.append(decoded_window)

    return GameState(
        now_ns=state_now_ns,
        next_flight_id=_integer(
            payload["next_flight_id"], "state.next_flight_id", minimum=1
        ),
        flight=flight,
        last_flight=last_flight,
        last_shooter_key=last_shooter_key,
        players=tuple(players),
        next_effect_id=_integer(
            payload["next_effect_id"], "state.next_effect_id", minimum=1
        ),
        effects=tuple(effects),
        next_action_id=_integer(
            payload["next_action_id"], "state.next_action_id", minimum=1
        ),
        scheduled_actions=tuple(scheduled_actions),
        next_curse_id=_integer(
            payload["next_curse_id"], "state.next_curse_id", minimum=1
        ),
        curses=tuple(curses),
        daily_schedule=daily_schedule,
        throttle_windows=tuple(throttle_windows),
    )


def decode_game_state(
    raw: object,
    *,
    schema_version: int = SCHEMA_VERSION,
) -> GameState:
    """Decode state primitives and normalize all domain failures."""

    if type(schema_version) is not int or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise CodecError("state schema version is unsupported")
    try:
        return _decode_game_state(raw, schema_version)
    except CodecError:
        raise
    except (TypeError, ValueError) as error:
        raise CodecError("state violates game-domain invariants") from error
