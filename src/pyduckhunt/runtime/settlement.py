"""Concrete replay settlement adapters with explicit entropy boundaries."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

from pyduckhunt.game.catalog import GrantKind, shop_item
from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.engine import advance_time, apply_command, late_shot_delay_ms
from pyduckhunt.game.karma import (
    decay_karma_modifier,
    karma_adjusted_jam_basis_points,
    player_karma_basis_points,
)
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.loot import STANDARD_LOOT_CATALOG, standard_loot_threshold
from pyduckhunt.game.model import (
    FATIGUE_SCALE,
    ActiveCurse,
    FlightKind,
    GameState,
    IncidentAttempt,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
    Transition,
)
from pyduckhunt.game.rewards import (
    ammunition_recycler_successes_per_thirty,
    promotion_discount_percent,
    settled_shop_cost,
)
from pyduckhunt.game.runtime import loot_chance_multiplier, select_runtime_loot
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.runtime.application import EventResolutionError, IRCCommandContext


IntegerSource = Callable[[int, int], int]
PresenceSource = Callable[[str, str], bool]
IncidentSource = Callable[
    [GameState, IRCCommandContext, ShotAttempt],
    IncidentAttempt | None,
]


HISTORICAL_NOISY_MISS_ESCAPE_BPS = 500


@dataclass(frozen=True, slots=True)
class SettlementPolicy:
    """Explicit foundational probabilities and penalties used by the resolver."""

    base_accuracy_bps: int | None = None
    base_jam_bps: int | None = None
    frighten_on_miss: bool | None = None
    miss_penalty: int | None = None
    wild_penalty: int | None = None
    fatigue_gain_centi: int = FATIGUE_SCALE
    unusual_loot_chance_per_thousand: int = 0

    def __post_init__(self) -> None:
        for field_name in ("base_accuracy_bps", "base_jam_bps"):
            value = getattr(self, field_name)
            if value is not None and (
                type(value) is not int or not 0 <= value <= 10_000
            ):
                raise ValueError(f"{field_name} must be between zero and 10000")
        if self.frighten_on_miss is not None and type(self.frighten_on_miss) is not bool:
            raise ValueError("frighten-on-miss policy must be a truth value")
        for field_name in ("miss_penalty", "wild_penalty"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field_name} must be a non-negative integer")
        if type(self.fatigue_gain_centi) is not int or self.fatigue_gain_centi < 0:
            raise ValueError("fatigue_gain_centi must be a non-negative integer")
        if self.fatigue_gain_centi > 100 * FATIGUE_SCALE:
            raise ValueError("fatigue gain exceeds the bounded player range")
        if self.unusual_loot_chance_per_thousand != 0:
            raise ValueError("unusual loot frequency is not calibrated")


class SystemIntegerSource:
    """Inclusive integer draws backed by the operating system random source."""

    def __init__(self, randbelow: Callable[[int], int] = secrets.randbelow) -> None:
        if not callable(randbelow):
            raise ValueError("system integer source requires a callable")
        self._randbelow = randbelow

    def __call__(self, minimum: int, maximum: int) -> int:
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or minimum > maximum
        ):
            raise ValueError("integer draw bounds are invalid")
        span = maximum - minimum + 1
        offset = self._randbelow(span)
        if type(offset) is not int or not 0 <= offset < span:
            raise RuntimeError("system random source violated its bounded contract")
        return minimum + offset


class CalibratedEventResolver:
    """Resolve public commands into complete replay events on one owner thread."""

    def __init__(
        self,
        integer_source: IntegerSource,
        presence_source: PresenceSource,
        *,
        incident_source: IncidentSource | None = None,
        policy: SettlementPolicy = SettlementPolicy(),
    ) -> None:
        if not callable(integer_source) or not callable(presence_source):
            raise ValueError("settlement sources must be callable")
        if incident_source is not None and not callable(incident_source):
            raise ValueError("incident source must be callable or none")
        if not isinstance(policy, SettlementPolicy):
            raise ValueError("settlement policy is invalid")
        self._integer_source = integer_source
        self._presence_source = presence_source
        self._incident_source = incident_source
        self.policy = policy
        self._owner_thread = threading.get_ident()

    def __call__(self, state: GameState, context: IRCCommandContext) -> ReplayEvent:
        self._ensure_owner()
        if not isinstance(state, GameState):
            raise ValueError("settlement resolver requires a game state")
        if not isinstance(context, IRCCommandContext):
            raise ValueError("settlement resolver requires a command context")
        if context.now_ns < state.now_ns:
            raise ValueError("settlement resolver cannot move the game clock backwards")
        current = advance_time(state, context.now_ns).state
        if context.command.kind is CommandKind.SHOP and context.command.arguments:
            return self._purchase_event(current, context)
        if context.command.kind is CommandKind.SHOT:
            return self._shot_event(current, context)
        return ReplayEvent.runtime_command(
            context.now_ns,
            context.nickname,
            context.command,
        )

    def _purchase_event(
        self,
        state: GameState,
        context: IRCCommandContext,
    ) -> ReplayEvent:
        item_id = int(context.command.arguments[0])
        target_nickname = (
            context.command.arguments[1]
            if len(context.command.arguments) == 2
            else None
        )
        item = shop_item(item_id)
        if (
            target_nickname is not None
            and item is not None
            and item.grant_kind is not GrantKind.TARGET_EFFECT
        ):
            raise EventResolutionError("Cet objet n'accepte pas de cible.")

        target_present = None
        if target_nickname is not None:
            target_present = self._presence_source(context.channel, target_nickname)
            if type(target_present) is not bool:
                raise ValueError("presence source must return a truth value")

        actor = _resolved_player(state, context.nickname)
        charged_cost = 0
        magnitude = None
        scheduled_for_ns = None
        fatigue_relief_centi = None
        fatigue_target_centi = None
        if item is not None:
            discount = promotion_discount_percent(state, actor.key)
            charged_cost = settled_shop_cost(item.base_cost, discount)
            if item.requires_magnitude:
                assert item.magnitude_min is not None and item.magnitude_max is not None
                magnitude = self._draw(item.magnitude_min, item.magnitude_max)
            if item.grant_kind is GrantKind.CHANNEL_ACTION:
                assert item.schedule_min_ns is not None
                assert item.schedule_max_ns is not None
                scheduled_for_ns = self._draw(
                    context.now_ns + item.schedule_min_ns,
                    context.now_ns + item.schedule_max_ns,
                )
            if item.item_id == 25:
                assert item.fatigue_relief_max is not None
                fatigue_target_centi = self._draw(
                    0,
                    item.fatigue_relief_max * FATIGUE_SCALE,
                )
            elif item.fatigue_relief_max is not None:
                fatigue_player = actor
                if item.item_id == 27 and target_nickname is not None:
                    target = state.player(rfc1459_casefold(target_nickname))
                    if target is not None:
                        fatigue_player = target
                fatigue_relief_centi = min(
                    item.fatigue_relief_max * FATIGUE_SCALE,
                    fatigue_player.fatigue_centi,
                )

        return ReplayEvent.runtime_purchase(
            context.now_ns,
            context.nickname,
            item_id,
            charged_cost,
            magnitude=magnitude,
            replace_active_effect=item_id == 10,
            target_nickname=target_nickname,
            target_present=target_present,
            scheduled_for_ns=scheduled_for_ns,
            fatigue_relief_centi=fatigue_relief_centi,
            fatigue_target_centi=fatigue_target_centi,
        )

    def _shot_event(
        self,
        state: GameState,
        context: IRCCommandContext,
    ) -> ReplayEvent:
        player = state.player(rfc1459_casefold(context.nickname))
        player_level = 1 if player is None else player.level
        calibrated = level_policy(player_level)
        karma = (
            0
            if player is None
            else player_karma_basis_points(
                decay_karma_modifier(player, context.now_ns)
            )
        )
        recycler_successes = (
            0
            if player is None
            else ammunition_recycler_successes_per_thirty(state, player.key)
        )
        attempt = ShotAttempt(
            base_accuracy_bps=(
                calibrated.accuracy_bps
                if self.policy.base_accuracy_bps is None
                else self.policy.base_accuracy_bps
            ),
            base_jam_bps=karma_adjusted_jam_basis_points(
                calibrated.jam_bps
                if self.policy.base_jam_bps is None
                else self.policy.base_jam_bps,
                karma,
            ),
            accuracy_roll=self._draw(1, 10_000),
            jam_roll=self._draw(1, 10_000),
            recycler_roll=(
                self._draw(1, 30) if recycler_successes else None
            ),
            frighten_on_miss=self.policy.frighten_on_miss is True,
            miss_penalty=(
                calibrated.miss_penalty
                if self.policy.miss_penalty is None
                else self.policy.miss_penalty
            ),
            wild_penalty=(
                calibrated.wild_penalty
                if self.policy.wild_penalty is None
                else self.policy.wild_penalty
            ),
            fatigue_gain_centi=self.policy.fatigue_gain_centi,
        )
        unerring = _active_curse(
            state,
            context.nickname,
            "unerring_miss",
        )
        late_shot = late_shot_delay_ms(state, context.now_ns) is not None
        if unerring is not None and not late_shot:
            incident = self._resolve_incident(state, context, attempt, required=True)
            attempt = replace(attempt, incident=incident)

        preview = apply_command(
            state,
            context.nickname,
            context.command,
            context.now_ns,
            shot_attempt=attempt,
        )
        if unerring is None and _fired_at_active_flight(preview):
            incident = self._resolve_incident(state, context, attempt, required=False)
            if incident is not None:
                attempt = replace(attempt, incident=incident)
                preview = apply_command(
                    state,
                    context.nickname,
                    context.command,
                    context.now_ns,
                    shot_attempt=attempt,
                )
        if (
            self.policy.frighten_on_miss is None
            and not calibrated.silent
            and attempt.incident is None
            and _missed_active_flight(preview)
        ):
            attempt = replace(
                attempt,
                frighten_on_miss=(
                    self._draw(1, 10_000)
                    <= HISTORICAL_NOISY_MISS_ESCAPE_BPS
                ),
            )
            if attempt.frighten_on_miss:
                preview = apply_command(
                    state,
                    context.nickname,
                    context.command,
                    context.now_ns,
                    shot_attempt=attempt,
                )
        standard_kill = any(
            outcome.kind is OutcomeKind.HIT
            and outcome.flight_kind is FlightKind.STANDARD
            for outcome in preview.outcomes
        )
        if standard_kill:
            loot = self._select_standard_loot(preview.state, context)
            if loot is not None:
                attempt = replace(attempt, loot=loot)
                apply_command(
                    state,
                    context.nickname,
                    context.command,
                    context.now_ns,
                    shot_attempt=attempt,
                )

        return ReplayEvent.runtime_command(
            context.now_ns,
            context.nickname,
            context.command,
            shot_attempt=attempt,
        )

    def _resolve_incident(
        self,
        state: GameState,
        context: IRCCommandContext,
        attempt: ShotAttempt,
        *,
        required: bool,
    ) -> IncidentAttempt | None:
        if self._incident_source is None:
            if required:
                raise EventResolutionError(
                    "Ce tir exige un règlement d'incident indisponible."
                )
            return None
        incident = self._incident_source(state, context, attempt)
        if incident is None:
            if required:
                raise EventResolutionError(
                    "Ce tir exige un règlement d'incident indisponible."
                )
            return None
        if not isinstance(incident, IncidentAttempt):
            raise ValueError("incident source returned an invalid settlement")
        return incident

    def _select_standard_loot(
        self,
        state: GameState,
        context: IRCCommandContext,
    ) -> LootAward | None:
        rolls = tuple(self._draw(1, 1_000) for _ in STANDARD_LOOT_CATALOG)
        multiplier = loot_chance_multiplier(state, context.nickname)
        player = state.player(rfc1459_casefold(context.nickname))
        karma = 0 if player is None else player_karma_basis_points(player)
        magnitude = None
        for spec, roll in zip(STANDARD_LOOT_CATALOG, rolls, strict=True):
            if roll <= standard_loot_threshold(
                spec,
                chance_multiplier=multiplier,
                karma_basis_points=karma,
            ):
                item = shop_item(spec.item_id) if spec.item_id is not None else None
                if item is not None and item.requires_magnitude:
                    assert item.magnitude_min is not None
                    assert item.magnitude_max is not None
                    magnitude = self._draw(item.magnitude_min, item.magnitude_max)
                break
        return select_runtime_loot(
            state,
            context.nickname,
            rolls,
            magnitude=magnitude,
        )

    def _draw(self, minimum: int, maximum: int) -> int:
        value = self._integer_source(minimum, maximum)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("integer source returned a value outside its bounds")
        return value

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("settlement resolver is owned by one event-loop thread")


def _resolved_player(state: GameState, nickname: str) -> PlayerState:
    player = state.player(rfc1459_casefold(nickname))
    return player if player is not None else PlayerState(
        rfc1459_casefold(nickname),
        nickname,
    )


def _missed_active_flight(transition: Transition) -> bool:
    return any(
        outcome.kind is OutcomeKind.MISS and outcome.flight_id is not None
        for outcome in transition.outcomes
    )


def _fired_at_active_flight(transition: Transition) -> bool:
    return any(
        outcome.kind in (OutcomeKind.HIT, OutcomeKind.FLIGHT_SURVIVED)
        or (outcome.kind is OutcomeKind.MISS and outcome.flight_id is not None)
        for outcome in transition.outcomes
    )


def _active_curse(
    state: GameState,
    nickname: str,
    key: str,
) -> ActiveCurse | None:
    owner_key = rfc1459_casefold(nickname)
    return next(
        (
            curse
            for curse in state.curses
            if curse.owner_key == owner_key and curse.key == key
        ),
        None,
    )
