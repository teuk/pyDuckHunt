"""Versioned replay intents recorded after the priority response path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pyduckhunt.game.admin import (
    validate_admin_channel_item_request,
    validate_player_update_request,
    validate_weapon_control_request,
)
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.loot import validate_loot_award
from pyduckhunt.game.model import (
    FlightKind,
    IncidentAttempt,
    IncidentTargetAttempt,
    LootAward,
    ShotAttempt,
)
from pyduckhunt.game.targets import flight_reward, validate_flight_reward
from pyduckhunt.game.runtime import (
    FIXED_DAILY_FLIGHT_COUNT,
    FlightSelection,
    validate_daily_schedule,
)
from pyduckhunt.persistence.codec import CodecError


class EventKind(str, Enum):
    ENABLE_HOURLY_BREAD = "enable_hourly_bread"
    REPLAN_BREAD_SCHEDULE = "replan_bread_schedule"
    START_FLIGHT = "start_flight"
    COMMAND = "command"
    PURCHASE = "purchase"
    ADVANCE_TIME = "advance_time"
    INSTALL_DAILY_SCHEDULE = "install_daily_schedule"
    EXPAND_DAILY_SCHEDULE = "expand_daily_schedule"
    SCHEDULE_TICK = "schedule_tick"
    RUNTIME_COMMAND = "runtime_command"
    RUNTIME_PURCHASE = "runtime_purchase"
    ADMIN_PLAYER_UPDATE = "admin_player_update"
    ADMIN_WEAPON_CONTROL = "admin_weapon_control"
    ADMIN_CHANNEL_ITEM = "admin_channel_item"


def _event_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CodecError(f"{field} must be a JSON object")
    return value


def _encode_loot_award(award: LootAward) -> dict[str, object]:
    payload: dict[str, object] = {
        "curse_key": award.curse_key,
        "key": award.key,
        "magnitude": award.magnitude,
    }
    if award.completion_loot:
        payload["completion_loot"] = [
            _encode_loot_award(nested) for nested in award.completion_loot
        ]
    return payload


def _decode_loot_award(raw: object, field: str) -> LootAward:
    payload = _event_mapping(raw, field)
    legacy_fields = {"curse_key", "key", "magnitude"}
    current_fields = {*legacy_fields, "completion_loot"}
    if set(payload) not in (legacy_fields, current_fields):
        raise CodecError("loot award fields differ from schema")
    raw_completion = payload.get("completion_loot", [])
    if not isinstance(raw_completion, list):
        raise CodecError("completion loot must be a JSON array")
    try:
        award = LootAward(
            key=payload["key"],
            magnitude=payload["magnitude"],
            curse_key=payload["curse_key"],
            completion_loot=tuple(
                _decode_loot_award(nested, f"{field}.completion_loot[{index}]")
                for index, nested in enumerate(raw_completion)
            ),
        )
        validate_loot_award(award)
        return award
    except (TypeError, ValueError) as error:
        raise CodecError("loot award values are invalid") from error


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    kind: EventKind
    now_ns: int
    lifetime_ns: int | None = None
    flight_health: int | None = None
    flight_kind: FlightKind | None = None
    flight_reward_experience: int | None = None
    nickname: str | None = None
    command_kind: CommandKind | None = None
    invoked_as: str | None = None
    arguments: tuple[str, ...] = ()
    item_id: int | None = None
    charged_cost: int | None = None
    magnitude: int | None = None
    replace_active_effect: bool = False
    target_nickname: str | None = None
    target_present: bool | None = None
    scheduled_for_ns: int | None = None
    fatigue_relief_centi: int | None = None
    fatigue_target_centi: int | None = None
    shot_attempt: ShotAttempt | None = None
    delay_settled: bool = False
    schedule_day_start_ns: int | None = None
    schedule_deadlines_ns: tuple[int, ...] = ()
    admin_actor: str | None = None
    admin_operation: str | None = None
    admin_field: str | None = None
    admin_value: int | None = None

    def __post_init__(self) -> None:
        if type(self.now_ns) is not int or self.now_ns < 0:
            raise ValueError("event time must be a non-negative integer")
        if type(self.delay_settled) is not bool:
            raise ValueError("delay settlement must be a truth value")
        if type(self.replace_active_effect) is not bool:
            raise ValueError("effect replacement must be a truth value")
        if self.replace_active_effect and self.kind not in (
            EventKind.PURCHASE,
            EventKind.RUNTIME_PURCHASE,
        ):
            raise ValueError("effect replacement belongs to a purchase event")
        admin_values = (
            self.admin_actor,
            self.admin_operation,
            self.admin_field,
            self.admin_value,
        )
        if self.kind is EventKind.ADMIN_CHANNEL_ITEM:
            if (
                not self.admin_actor
                or any(
                    character in self.admin_actor
                    for character in (" ", "\x00", "\r", "\n")
                )
                or self.item_id is None
                or self.admin_operation is not None
                or self.admin_field is not None
                or self.admin_value is not None
            ):
                raise ValueError("admin channel item has incomplete identity")
            validate_admin_channel_item_request(
                self.item_id,
                self.now_ns,
                self.scheduled_for_ns,
            )
        elif self.kind is EventKind.ADMIN_PLAYER_UPDATE:
            if (
                not self.nickname
                or not self.admin_actor
                or any(character in self.admin_actor for character in ("\x00", "\r", "\n"))
                or self.admin_operation is None
                or self.admin_field is None
                or self.admin_value is None
            ):
                raise ValueError("admin player update has incomplete identity")
            validate_player_update_request(
                self.admin_field,
                self.admin_operation,
                self.admin_value,
            )
        elif self.kind is EventKind.ADMIN_WEAPON_CONTROL:
            if (
                not self.nickname
                or not self.admin_actor
                or any(character in self.admin_actor for character in ("\x00", "\r", "\n"))
                or self.admin_operation is None
                or self.admin_field is not None
                or self.admin_value is not None
            ):
                raise ValueError("admin weapon control has incomplete identity")
            validate_weapon_control_request(self.admin_operation)
        elif any(value is not None for value in admin_values):
            raise ValueError("admin fields belong to an admin event")
        if self.kind is EventKind.START_FLIGHT:
            if type(self.lifetime_ns) is not int or self.lifetime_ns <= 0:
                raise ValueError("start_flight requires a positive lifetime")
            if type(self.flight_health) is not int or self.flight_health < 1:
                raise ValueError("start_flight requires positive health")
            if self.flight_kind is None or self.flight_reward_experience is None:
                raise ValueError("start_flight requires target settlement fields")
            validate_flight_reward(
                self.flight_kind,
                self.flight_health,
                self.flight_reward_experience,
            )
            if any(
                value is not None
                for value in (
                    self.nickname,
                    self.command_kind,
                    self.invoked_as,
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("start_flight contains command-only fields")
        elif self.kind in (
            EventKind.INSTALL_DAILY_SCHEDULE,
            EventKind.EXPAND_DAILY_SCHEDULE,
            EventKind.REPLAN_BREAD_SCHEDULE,
        ):
            if self.schedule_day_start_ns is None:
                raise ValueError("schedule installation requires a UTC-day start")
            validate_daily_schedule(
                self.schedule_day_start_ns,
                self.schedule_deadlines_ns,
                allow_bread=self.kind is EventKind.REPLAN_BREAD_SCHEDULE,
            )
            if (
                self.kind is EventKind.EXPAND_DAILY_SCHEDULE
                and len(self.schedule_deadlines_ns) != FIXED_DAILY_FLIGHT_COUNT
            ):
                raise ValueError("schedule expansion must reach the fixed daily count")
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.nickname,
                    self.command_kind,
                    self.invoked_as,
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                )
            ) or self.arguments or self.delay_settled:
                raise ValueError("schedule installation contains unrelated fields")
        elif self.kind is EventKind.SCHEDULE_TICK:
            settlement = (
                self.lifetime_ns,
                self.flight_health,
                self.flight_kind,
                self.flight_reward_experience,
            )
            if any(value is not None for value in settlement):
                if any(value is None for value in settlement):
                    raise ValueError("schedule tick has incomplete flight settlement")
                FlightSelection(
                    self.flight_kind,
                    self.flight_health,
                    self.flight_reward_experience,
                    self.lifetime_ns,
                )
            if any(
                value is not None
                for value in (
                    self.nickname,
                    self.command_kind,
                    self.invoked_as,
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("schedule tick contains unrelated fields")
        elif self.kind in (EventKind.COMMAND, EventKind.RUNTIME_COMMAND):
            if not self.nickname or self.command_kind is None or not self.invoked_as:
                raise ValueError("command event has incomplete command identity")
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.schedule_day_start_ns,
                )
            ) or self.schedule_deadlines_ns:
                raise ValueError("command event contains flight-only fields")
            if any(
                value is not None
                for value in (
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                )
            ):
                raise ValueError("command event contains purchase-only fields")
            if not all(isinstance(argument, str) for argument in self.arguments):
                raise ValueError("command arguments must be strings")
            if self.shot_attempt is not None and not isinstance(
                self.shot_attempt, ShotAttempt
            ):
                raise ValueError("command shot attempt is invalid")
            if self.command_kind is not CommandKind.SHOT and self.shot_attempt is not None:
                raise ValueError("non-shot command contains a shot attempt")
            if self.shot_attempt is not None and self.shot_attempt.loot is not None:
                validate_loot_award(self.shot_attempt.loot)
            if self.delay_settled and self.command_kind not in (
                CommandKind.SHOT,
                CommandKind.RELOAD,
            ):
                raise ValueError("only shot and reload can settle a delay")
        elif self.kind in (EventKind.PURCHASE, EventKind.RUNTIME_PURCHASE):
            if (
                not self.nickname
                or type(self.item_id) is not int
                or self.item_id < 1
                or type(self.charged_cost) is not int
                or self.charged_cost < 0
            ):
                raise ValueError("purchase event has incomplete settlement fields")
            if self.magnitude is not None and type(self.magnitude) is not int:
                raise ValueError("purchase magnitude must be an integer")
            if self.replace_active_effect and self.item_id != 10:
                raise ValueError("effect replacement is unsupported for this item")
            if (self.target_nickname is None) != (self.target_present is None):
                raise ValueError("purchase target identity and presence must be paired")
            if self.target_nickname is not None and (
                not isinstance(self.target_nickname, str)
                or not self.target_nickname
                or type(self.target_present) is not bool
            ):
                raise ValueError("purchase target fields are invalid")
            if self.scheduled_for_ns is not None and (
                type(self.scheduled_for_ns) is not int
                or self.scheduled_for_ns <= self.now_ns
            ):
                raise ValueError("purchase scheduled deadline is invalid")
            if self.fatigue_relief_centi is not None and (
                type(self.fatigue_relief_centi) is not int
                or self.fatigue_relief_centi < 0
            ):
                raise ValueError("purchase fatigue relief is invalid")
            if self.fatigue_target_centi is not None and (
                type(self.fatigue_target_centi) is not int
                or self.fatigue_target_centi < -300
            ):
                raise ValueError("purchase fatigue target is invalid")
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.command_kind,
                    self.invoked_as,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("purchase event contains unrelated fields")
        elif self.kind is EventKind.ADMIN_PLAYER_UPDATE:
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.command_kind,
                    self.invoked_as,
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("admin player update contains unrelated fields")
        elif self.kind is EventKind.ADMIN_WEAPON_CONTROL:
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.command_kind,
                    self.invoked_as,
                    self.item_id,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.scheduled_for_ns,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("admin weapon control contains unrelated fields")
        elif self.kind is EventKind.ADMIN_CHANNEL_ITEM:
            if any(
                value is not None
                for value in (
                    self.lifetime_ns,
                    self.flight_health,
                    self.flight_kind,
                    self.flight_reward_experience,
                    self.nickname,
                    self.command_kind,
                    self.invoked_as,
                    self.charged_cost,
                    self.magnitude,
                    self.target_nickname,
                    self.target_present,
                    self.fatigue_relief_centi,
                    self.fatigue_target_centi,
                    self.shot_attempt,
                    self.schedule_day_start_ns,
                )
            ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
                raise ValueError("admin channel item contains unrelated fields")
        elif any(
            value is not None
            for value in (
                self.lifetime_ns,
                self.flight_health,
                self.flight_kind,
                self.flight_reward_experience,
                self.nickname,
                self.command_kind,
                self.invoked_as,
                self.item_id,
                self.charged_cost,
                self.magnitude,
                self.target_nickname,
                self.target_present,
                self.scheduled_for_ns,
                self.fatigue_relief_centi,
                self.fatigue_target_centi,
                self.shot_attempt,
                self.schedule_day_start_ns,
            )
        ) or self.arguments or self.delay_settled or self.schedule_deadlines_ns:
            raise ValueError("advance_time contains unrelated fields")

    @classmethod
    def start_flight(
        cls,
        now_ns: int,
        lifetime_ns: int,
        *,
        health: int = 1,
        kind: FlightKind = FlightKind.STANDARD,
        reward_experience: int | None = None,
    ) -> ReplayEvent:
        if reward_experience is None:
            reward_experience = flight_reward(kind, health)
        return cls(
            EventKind.START_FLIGHT,
            now_ns,
            lifetime_ns=lifetime_ns,
            flight_health=health,
            flight_kind=kind,
            flight_reward_experience=reward_experience,
        )

    @classmethod
    def command(
        cls,
        now_ns: int,
        nickname: str,
        command: Command,
        *,
        shot_attempt: ShotAttempt | None = None,
        delay_settled: bool = False,
    ) -> ReplayEvent:
        return cls(
            EventKind.COMMAND,
            now_ns,
            nickname=nickname,
            command_kind=command.kind,
            invoked_as=command.invoked_as,
            arguments=command.arguments,
            shot_attempt=shot_attempt,
            delay_settled=delay_settled,
        )

    @classmethod
    def runtime_command(
        cls,
        now_ns: int,
        nickname: str,
        command: Command,
        *,
        shot_attempt: ShotAttempt | None = None,
        delay_settled: bool = False,
    ) -> ReplayEvent:
        return cls(
            EventKind.RUNTIME_COMMAND,
            now_ns,
            nickname=nickname,
            command_kind=command.kind,
            invoked_as=command.invoked_as,
            arguments=command.arguments,
            shot_attempt=shot_attempt,
            delay_settled=delay_settled,
        )

    @classmethod
    def advance_time(cls, now_ns: int) -> ReplayEvent:
        return cls(EventKind.ADVANCE_TIME, now_ns)

    @classmethod
    def admin_player_update(
        cls,
        now_ns: int,
        actor: str,
        nickname: str,
        *,
        field: str,
        operation: str,
        value: int,
    ) -> ReplayEvent:
        return cls(
            EventKind.ADMIN_PLAYER_UPDATE,
            now_ns,
            nickname=nickname,
            admin_actor=actor,
            admin_operation=operation,
            admin_field=field,
            admin_value=value,
        )

    @classmethod
    def admin_weapon_control(
        cls,
        now_ns: int,
        actor: str,
        nickname: str,
        *,
        operation: str,
    ) -> ReplayEvent:
        return cls(
            EventKind.ADMIN_WEAPON_CONTROL,
            now_ns,
            nickname=nickname,
            admin_actor=actor,
            admin_operation=operation,
        )

    @classmethod
    def admin_channel_item(
        cls,
        now_ns: int,
        actor: str,
        item_id: int,
        *,
        scheduled_for_ns: int | None = None,
    ) -> ReplayEvent:
        return cls(
            EventKind.ADMIN_CHANNEL_ITEM,
            now_ns,
            item_id=item_id,
            scheduled_for_ns=scheduled_for_ns,
            admin_actor=actor,
        )

    @classmethod
    def install_daily_schedule(
        cls,
        now_ns: int,
        day_start_ns: int,
        deadlines_ns: tuple[int, ...],
    ) -> ReplayEvent:
        return cls(
            EventKind.INSTALL_DAILY_SCHEDULE,
            now_ns,
            schedule_day_start_ns=day_start_ns,
            schedule_deadlines_ns=deadlines_ns,
        )

    @classmethod
    def expand_daily_schedule(
        cls,
        now_ns: int,
        day_start_ns: int,
        deadlines_ns: tuple[int, ...],
    ) -> ReplayEvent:
        return cls(
            EventKind.EXPAND_DAILY_SCHEDULE,
            now_ns,
            schedule_day_start_ns=day_start_ns,
            schedule_deadlines_ns=deadlines_ns,
        )

    @classmethod
    def replan_bread_schedule(cls, now_ns: int, day_start_ns: int,
                              deadlines_ns: tuple[int, ...]) -> ReplayEvent:
        return cls(EventKind.REPLAN_BREAD_SCHEDULE, now_ns,
                   schedule_day_start_ns=day_start_ns, schedule_deadlines_ns=deadlines_ns)

    @classmethod
    def enable_hourly_bread(cls, now_ns: int) -> ReplayEvent:
        return cls(EventKind.ENABLE_HOURLY_BREAD, now_ns)

    @classmethod
    def schedule_tick(
        cls,
        now_ns: int,
        *,
        selection: FlightSelection | None = None,
    ) -> ReplayEvent:
        return cls(
            EventKind.SCHEDULE_TICK,
            now_ns,
            lifetime_ns=None if selection is None else selection.lifetime_ns,
            flight_health=None if selection is None else selection.health,
            flight_kind=None if selection is None else selection.kind,
            flight_reward_experience=(
                None if selection is None else selection.reward_experience
            ),
        )

    @classmethod
    def purchase(
        cls,
        now_ns: int,
        nickname: str,
        item_id: int,
        charged_cost: int,
        *,
        magnitude: int | None = None,
        replace_active_effect: bool = False,
        target_nickname: str | None = None,
        target_present: bool | None = None,
        scheduled_for_ns: int | None = None,
        fatigue_relief_centi: int | None = None,
        fatigue_target_centi: int | None = None,
    ) -> ReplayEvent:
        return cls(
            EventKind.PURCHASE,
            now_ns,
            nickname=nickname,
            item_id=item_id,
            charged_cost=charged_cost,
            magnitude=magnitude,
            replace_active_effect=replace_active_effect,
            target_nickname=target_nickname,
            target_present=target_present,
            scheduled_for_ns=scheduled_for_ns,
            fatigue_relief_centi=fatigue_relief_centi,
            fatigue_target_centi=fatigue_target_centi,
        )

    @classmethod
    def runtime_purchase(
        cls,
        now_ns: int,
        nickname: str,
        item_id: int,
        charged_cost: int,
        *,
        magnitude: int | None = None,
        replace_active_effect: bool = False,
        target_nickname: str | None = None,
        target_present: bool | None = None,
        scheduled_for_ns: int | None = None,
        fatigue_relief_centi: int | None = None,
        fatigue_target_centi: int | None = None,
    ) -> ReplayEvent:
        return cls(
            EventKind.RUNTIME_PURCHASE,
            now_ns,
            nickname=nickname,
            item_id=item_id,
            charged_cost=charged_cost,
            magnitude=magnitude,
            replace_active_effect=replace_active_effect,
            target_nickname=target_nickname,
            target_present=target_present,
            scheduled_for_ns=scheduled_for_ns,
            fatigue_relief_centi=fatigue_relief_centi,
            fatigue_target_centi=fatigue_target_centi,
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"kind": self.kind.value, "now_ns": self.now_ns}
        if self.kind is EventKind.START_FLIGHT:
            payload["lifetime_ns"] = self.lifetime_ns
            payload["health"] = self.flight_health
            payload["flight_kind"] = self.flight_kind.value
            payload["reward_experience"] = self.flight_reward_experience
        elif self.kind in (
            EventKind.INSTALL_DAILY_SCHEDULE,
            EventKind.EXPAND_DAILY_SCHEDULE,
            EventKind.REPLAN_BREAD_SCHEDULE,
        ):
            payload["day_start_ns"] = self.schedule_day_start_ns
            payload["deadlines_ns"] = list(self.schedule_deadlines_ns)
        elif self.kind is EventKind.SCHEDULE_TICK:
            payload["lifetime_ns"] = self.lifetime_ns
            payload["health"] = self.flight_health
            payload["flight_kind"] = (
                None if self.flight_kind is None else self.flight_kind.value
            )
            payload["reward_experience"] = self.flight_reward_experience
        elif self.kind in (EventKind.COMMAND, EventKind.RUNTIME_COMMAND):
            payload.update(
                {
                    "arguments": list(self.arguments),
                    "command_kind": self.command_kind.value,
                    "invoked_as": self.invoked_as,
                    "nickname": self.nickname,
                    "delay_settled": self.delay_settled,
                    "shot_attempt": (
                        None
                        if self.shot_attempt is None
                        else {
                            "accuracy_roll": self.shot_attempt.accuracy_roll,
                            "base_accuracy_bps": self.shot_attempt.base_accuracy_bps,
                            "base_jam_bps": self.shot_attempt.base_jam_bps,
                            "frighten_on_miss": self.shot_attempt.frighten_on_miss,
                            **({"noisy_miss_limit": self.shot_attempt.noisy_miss_limit}
                               if self.shot_attempt.noisy_miss_limit is not None else {}),
                            "fatigue_gain_centi": self.shot_attempt.fatigue_gain_centi,
                            **({"fatigue_penalty_bps": self.shot_attempt.fatigue_penalty_bps}
                               if self.shot_attempt.fatigue_penalty_bps else {}),
                            **({"overexcitation_penalty_bps": self.shot_attempt.overexcitation_penalty_bps}
                               if self.shot_attempt.overexcitation_penalty_bps else {}),
                            **({"scope_bonus_points": self.shot_attempt.scope_bonus_points}
                               if self.shot_attempt.scope_bonus_points is not None else {}),
                            "incident": (
                                None
                                if self.shot_attempt.incident is None
                                else {
                                    "incident_penalty": self.shot_attempt.incident.incident_penalty,
                                    "targets": [
                                        {
                                            "armor_bps": target.armor_bps,
                                            "armor_roll": target.armor_roll,
                                            "deflection_bps": target.deflection_bps,
                                            "deflection_roll": target.deflection_roll,
                                            "nickname": target.nickname,
                                        }
                                        for target in self.shot_attempt.incident.targets
                                    ],
                                }
                            ),
                            "loot": (
                                None
                                if self.shot_attempt.loot is None
                                else _encode_loot_award(self.shot_attempt.loot)
                            ),
                            "jam_roll": self.shot_attempt.jam_roll,
                            "recycler_roll": self.shot_attempt.recycler_roll,
                            "miss_penalty": self.shot_attempt.miss_penalty,
                            "wild_penalty": self.shot_attempt.wild_penalty,
                        }
                    ),
                }
            )
        elif self.kind in (EventKind.PURCHASE, EventKind.RUNTIME_PURCHASE):
            payload.update(
                {
                    "charged_cost": self.charged_cost,
                    "item_id": self.item_id,
                    "magnitude": self.magnitude,
                    "nickname": self.nickname,
                    "target_nickname": self.target_nickname,
                    "target_present": self.target_present,
                    "scheduled_for_ns": self.scheduled_for_ns,
                    "fatigue_relief_centi": self.fatigue_relief_centi,
                    "fatigue_target_centi": self.fatigue_target_centi,
                }
            )
            if self.replace_active_effect:
                payload["replace_active_effect"] = True
        elif self.kind is EventKind.ADMIN_PLAYER_UPDATE:
            payload.update(
                {
                    "actor": self.admin_actor,
                    "field": self.admin_field,
                    "nickname": self.nickname,
                    "operation": self.admin_operation,
                    "value": self.admin_value,
                }
            )
        elif self.kind is EventKind.ADMIN_WEAPON_CONTROL:
            payload.update(
                {
                    "actor": self.admin_actor,
                    "nickname": self.nickname,
                    "operation": self.admin_operation,
                }
            )
        elif self.kind is EventKind.ADMIN_CHANNEL_ITEM:
            payload.update(
                {
                    "actor": self.admin_actor,
                    "item_id": self.item_id,
                    "scheduled_for_ns": self.scheduled_for_ns,
                }
            )
        return payload

    @classmethod
    def from_payload(cls, raw: object) -> ReplayEvent:
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise CodecError("event must be a JSON object")
        try:
            kind = EventKind(raw.get("kind"))
        except (TypeError, ValueError) as error:
            raise CodecError("event kind is unknown") from error
        now_ns = raw.get("now_ns")
        if type(now_ns) is not int or now_ns < 0:
            raise CodecError("event now_ns must be a non-negative integer")

        if kind is EventKind.START_FLIGHT:
            if set(raw) != {
                "flight_kind",
                "health",
                "kind",
                "lifetime_ns",
                "now_ns",
                "reward_experience",
            }:
                raise CodecError("start_flight event fields differ from schema")
            lifetime_ns = raw["lifetime_ns"]
            health = raw["health"]
            if (
                type(lifetime_ns) is not int
                or lifetime_ns <= 0
                or type(health) is not int
                or health < 1
            ):
                raise CodecError("start_flight lifetime and health must be positive")
            try:
                flight_kind = FlightKind(raw["flight_kind"])
                return cls.start_flight(
                    now_ns,
                    lifetime_ns,
                    health=health,
                    kind=flight_kind,
                    reward_experience=raw["reward_experience"],
                )
            except (TypeError, ValueError) as error:
                raise CodecError("start_flight target settlement is invalid") from error

        if kind in (
            EventKind.INSTALL_DAILY_SCHEDULE,
            EventKind.EXPAND_DAILY_SCHEDULE,
            EventKind.REPLAN_BREAD_SCHEDULE,
        ):
            if set(raw) != {"day_start_ns", "deadlines_ns", "kind", "now_ns"}:
                raise CodecError("schedule installation fields differ from schema")
            day_start_ns = raw["day_start_ns"]
            deadlines_ns = raw["deadlines_ns"]
            if (
                type(day_start_ns) is not int
                or not isinstance(deadlines_ns, list)
                or any(type(value) is not int for value in deadlines_ns)
            ):
                raise CodecError("schedule installation values are invalid")
            try:
                constructor = (
                    cls.install_daily_schedule
                    if kind is EventKind.INSTALL_DAILY_SCHEDULE
                    else cls.replan_bread_schedule if kind is EventKind.REPLAN_BREAD_SCHEDULE
                    else cls.expand_daily_schedule
                )
                return constructor(now_ns, day_start_ns, tuple(deadlines_ns))
            except ValueError as error:
                raise CodecError("schedule installation violates runtime policy") from error

        if kind is EventKind.SCHEDULE_TICK:
            if set(raw) != {
                "flight_kind",
                "health",
                "kind",
                "lifetime_ns",
                "now_ns",
                "reward_experience",
            }:
                raise CodecError("schedule tick fields differ from schema")
            settlement = (
                raw["lifetime_ns"],
                raw["health"],
                raw["flight_kind"],
                raw["reward_experience"],
            )
            if all(value is None for value in settlement):
                return cls.schedule_tick(now_ns)
            if any(value is None for value in settlement):
                raise CodecError("schedule tick settlement is incomplete")
            try:
                selection = FlightSelection(
                    FlightKind(raw["flight_kind"]),
                    raw["health"],
                    raw["reward_experience"],
                    raw["lifetime_ns"],
                )
                return cls.schedule_tick(now_ns, selection=selection)
            except (TypeError, ValueError) as error:
                raise CodecError("schedule tick settlement is invalid") from error

        if kind in (EventKind.ADVANCE_TIME, EventKind.ENABLE_HOURLY_BREAD):
            if set(raw) != {"kind", "now_ns"}:
                raise CodecError("advance_time event fields differ from schema")
            return cls(kind, now_ns)

        if kind is EventKind.ADMIN_PLAYER_UPDATE:
            if set(raw) != {
                "actor",
                "field",
                "kind",
                "nickname",
                "now_ns",
                "operation",
                "value",
            }:
                raise CodecError("admin player update fields differ from schema")
            try:
                return cls.admin_player_update(
                    now_ns,
                    raw["actor"],
                    raw["nickname"],
                    field=raw["field"],
                    operation=raw["operation"],
                    value=raw["value"],
                )
            except (TypeError, ValueError) as error:
                raise CodecError("admin player update values are invalid") from error

        if kind is EventKind.ADMIN_WEAPON_CONTROL:
            if set(raw) != {
                "actor",
                "kind",
                "nickname",
                "now_ns",
                "operation",
            }:
                raise CodecError("admin weapon control fields differ from schema")
            try:
                return cls.admin_weapon_control(
                    now_ns,
                    raw["actor"],
                    raw["nickname"],
                    operation=raw["operation"],
                )
            except (TypeError, ValueError) as error:
                raise CodecError("admin weapon control values are invalid") from error

        if kind is EventKind.ADMIN_CHANNEL_ITEM:
            if set(raw) != {
                "actor",
                "item_id",
                "kind",
                "now_ns",
                "scheduled_for_ns",
            }:
                raise CodecError("admin channel item fields differ from schema")
            try:
                return cls.admin_channel_item(
                    now_ns,
                    raw["actor"],
                    raw["item_id"],
                    scheduled_for_ns=raw["scheduled_for_ns"],
                )
            except (TypeError, ValueError) as error:
                raise CodecError("admin channel item values are invalid") from error

        if kind in (EventKind.PURCHASE, EventKind.RUNTIME_PURCHASE):
            legacy_fields = {
                "charged_cost",
                "item_id",
                "kind",
                "magnitude",
                "nickname",
                "now_ns",
                "target_nickname",
                "target_present",
                "scheduled_for_ns",
                "fatigue_relief_centi",
                "fatigue_target_centi",
            }
            current_fields = legacy_fields | {"replace_active_effect"}
            if set(raw) not in (legacy_fields, current_fields):
                raise CodecError("purchase event fields differ from schema")
            nickname = raw["nickname"]
            item_id = raw["item_id"]
            charged_cost = raw["charged_cost"]
            magnitude = raw["magnitude"]
            target_nickname = raw["target_nickname"]
            target_present = raw["target_present"]
            scheduled_for_ns = raw["scheduled_for_ns"]
            fatigue_relief_centi = raw["fatigue_relief_centi"]
            fatigue_target_centi = raw["fatigue_target_centi"]
            replace_active_effect = raw.get("replace_active_effect", False)
            if (
                not isinstance(nickname, str)
                or not nickname
                or type(item_id) is not int
                or item_id < 1
                or type(charged_cost) is not int
                or charged_cost < 0
                or type(replace_active_effect) is not bool
                or (replace_active_effect and item_id != 10)
                or (magnitude is not None and type(magnitude) is not int)
                or ((target_nickname is None) != (target_present is None))
                or (
                    scheduled_for_ns is not None
                    and (
                        type(scheduled_for_ns) is not int
                        or scheduled_for_ns <= now_ns
                    )
                )
                or (
                    fatigue_relief_centi is not None
                    and (
                        type(fatigue_relief_centi) is not int
                        or fatigue_relief_centi < 0
                    )
                )
                or (
                    fatigue_target_centi is not None
                    and (
                        type(fatigue_target_centi) is not int
                        or fatigue_target_centi < -300
                    )
                )
                or (
                    target_nickname is not None
                    and (
                        not isinstance(target_nickname, str)
                        or not target_nickname
                        or type(target_present) is not bool
                    )
                )
            ):
                raise CodecError("purchase event contains invalid settlement fields")
            constructor = (
                cls.purchase
                if kind is EventKind.PURCHASE
                else cls.runtime_purchase
            )
            return constructor(
                now_ns,
                nickname,
                item_id,
                charged_cost,
                magnitude=magnitude,
                replace_active_effect=replace_active_effect,
                target_nickname=target_nickname,
                target_present=target_present,
                scheduled_for_ns=scheduled_for_ns,
                fatigue_relief_centi=fatigue_relief_centi,
                fatigue_target_centi=fatigue_target_centi,
            )

        expected = {
            "arguments",
            "command_kind",
            "delay_settled",
            "invoked_as",
            "kind",
            "nickname",
            "now_ns",
            "shot_attempt",
        }
        if set(raw) != expected:
            raise CodecError("command event fields differ from schema")
        nickname = raw["nickname"]
        invoked_as = raw["invoked_as"]
        arguments = raw["arguments"]
        delay_settled = raw["delay_settled"]
        if (
            not isinstance(nickname, str)
            or not nickname
            or not isinstance(invoked_as, str)
            or not invoked_as
            or not isinstance(arguments, list)
            or not all(isinstance(argument, str) for argument in arguments)
            or type(delay_settled) is not bool
        ):
            raise CodecError("command event contains invalid text fields")
        try:
            command_kind = CommandKind(raw["command_kind"])
        except (TypeError, ValueError) as error:
            raise CodecError("command kind is unknown") from error
        raw_shot_attempt = raw["shot_attempt"]
        shot_attempt: ShotAttempt | None = None
        if raw_shot_attempt is not None:
            shot_payload = _event_mapping(raw_shot_attempt, "event.shot_attempt")
            expected_shot_fields = {
                "accuracy_roll",
                "base_accuracy_bps",
                "base_jam_bps",
                "fatigue_gain_centi",
                "frighten_on_miss",
                "incident",
                "jam_roll",
                "loot",
                "miss_penalty",
                "wild_penalty",
            }
            legacy_shot_fields = set(expected_shot_fields)
            expected_shot_fields.add("recycler_roll")
            if set(shot_payload) - {"fatigue_penalty_bps", "overexcitation_penalty_bps", "scope_bonus_points", "noisy_miss_limit"} not in (
                legacy_shot_fields, expected_shot_fields,
            ):
                raise CodecError("shot attempt fields differ from schema")
            if "scope_bonus_points" in shot_payload and shot_payload["scope_bonus_points"] is None:
                raise CodecError("explicit scope bonus cannot be null")
            if "noisy_miss_limit" in shot_payload and shot_payload["noisy_miss_limit"] is None:
                raise CodecError("explicit noisy miss limit cannot be null")
            raw_incident = shot_payload["incident"]
            incident: IncidentAttempt | None = None
            if raw_incident is not None:
                incident_payload = _event_mapping(raw_incident, "event.shot_attempt.incident")
                if set(incident_payload) != {"incident_penalty", "targets"}:
                    raise CodecError("incident attempt fields differ from schema")
                raw_targets = incident_payload["targets"]
                if not isinstance(raw_targets, list):
                    raise CodecError("incident targets must be a JSON array")
                targets: list[IncidentTargetAttempt] = []
                for index, raw_target in enumerate(raw_targets):
                    target = _event_mapping(
                        raw_target,
                        f"event.shot_attempt.incident.targets[{index}]",
                    )
                    expected_target_fields = {
                        "armor_bps",
                        "armor_roll",
                        "deflection_bps",
                        "deflection_roll",
                        "nickname",
                    }
                    if set(target) != expected_target_fields:
                        raise CodecError("incident target fields differ from schema")
                    try:
                        targets.append(
                            IncidentTargetAttempt(
                                nickname=target["nickname"],
                                deflection_bps=target["deflection_bps"],
                                armor_bps=target["armor_bps"],
                                deflection_roll=target["deflection_roll"],
                                armor_roll=target["armor_roll"],
                            )
                        )
                    except (TypeError, ValueError) as error:
                        raise CodecError("incident target values are invalid") from error
                try:
                    incident = IncidentAttempt(
                        targets=tuple(targets),
                        incident_penalty=incident_payload["incident_penalty"],
                    )
                except (TypeError, ValueError) as error:
                    raise CodecError("incident attempt values are invalid") from error
            raw_loot = shot_payload["loot"]
            loot: LootAward | None = None
            if raw_loot is not None:
                loot = _decode_loot_award(raw_loot, "event.shot_attempt.loot")
            try:
                shot_attempt = ShotAttempt(
                    base_accuracy_bps=shot_payload["base_accuracy_bps"],
                    base_jam_bps=shot_payload["base_jam_bps"],
                    accuracy_roll=shot_payload["accuracy_roll"],
                    jam_roll=shot_payload["jam_roll"],
                    recycler_roll=shot_payload.get("recycler_roll"),
                    frighten_on_miss=shot_payload["frighten_on_miss"],
                    noisy_miss_limit=shot_payload.get("noisy_miss_limit"),
                    miss_penalty=shot_payload["miss_penalty"],
                    wild_penalty=shot_payload["wild_penalty"],
                    fatigue_gain_centi=shot_payload["fatigue_gain_centi"],
                    fatigue_penalty_bps=shot_payload.get("fatigue_penalty_bps", 0),
                    overexcitation_penalty_bps=shot_payload.get("overexcitation_penalty_bps", 0),
                    scope_bonus_points=shot_payload.get("scope_bonus_points"),
                    incident=incident,
                    loot=loot,
                )
            except (TypeError, ValueError) as error:
                raise CodecError("shot attempt values are invalid") from error
        try:
            constructor = (
                cls.command
                if kind is EventKind.COMMAND
                else cls.runtime_command
            )
            return constructor(
                now_ns,
                nickname,
                Command(command_kind, invoked_as, tuple(arguments)),
                shot_attempt=shot_attempt,
                delay_settled=delay_settled,
            )
        except ValueError as error:
            raise CodecError("command event violates domain invariants") from error
