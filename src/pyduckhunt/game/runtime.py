"""Pure runtime scheduling, admission and entropy adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.karma import player_karma_basis_points
from pyduckhunt.game.loot import select_standard_loot, validate_loot_award
from pyduckhunt.game.model import (
    DailySchedule,
    FlightKind,
    GameState,
    LootAward,
    Outcome,
    OutcomeKind,
    ShotAttempt,
    ThrottleWindow,
    Transition,
)
from pyduckhunt.game.rewards import active_reward_effect
from pyduckhunt.game.shop import purchase
from pyduckhunt.game.targets import flight_reward
from pyduckhunt.identity import rfc1459_casefold


SECOND_NS = 1_000_000_000
DAY_NS = 86_400 * SECOND_NS
FLIGHT_LIFETIME_NS = 300 * SECOND_NS
DAILY_FLIGHT_COUNT = 18
GROWTH_DAILY_FLIGHT_COUNT = 21
BOOTSTRAP_DAILY_FLIGHT_COUNT = 24
BOOTSTRAP_COMMUNITY_HITS_MAX = 24
GROWTH_COMMUNITY_HITS_MAX = 99
SUPPORTED_DAILY_FLIGHT_COUNTS = frozenset(
    (DAILY_FLIGHT_COUNT, GROWTH_DAILY_FLIGHT_COUNT, BOOTSTRAP_DAILY_FLIGHT_COUNT)
)
DAILY_GOLDEN_WEIGHT = 1
THROTTLE_NOTICE_INTERVAL_NS = 60 * SECOND_NS


@dataclass(frozen=True, slots=True)
class FlightSelection:
    kind: FlightKind
    health: int
    reward_experience: int
    lifetime_ns: int = FLIGHT_LIFETIME_NS

    def __post_init__(self) -> None:
        if self.lifetime_ns != FLIGHT_LIFETIME_NS:
            raise ValueError("scheduled flight lifetime must be exactly five minutes")
        if self.reward_experience != flight_reward(self.kind, self.health):
            raise ValueError("scheduled flight reward differs from the target catalog")


@dataclass(frozen=True, slots=True)
class RateLimit:
    maximum: int
    window_ns: int

    def __post_init__(self) -> None:
        if type(self.maximum) is not int or self.maximum < 1:
            raise ValueError("rate maximum must be a positive integer")
        if type(self.window_ns) is not int or self.window_ns < 1:
            raise ValueError("rate window must be a positive integer")


COMMAND_RATE_LIMITS = {
    CommandKind.SHOT: RateLimit(30, 600 * SECOND_NS),
    CommandKind.RELOAD: RateLimit(15, 120 * SECOND_NS),
    CommandKind.STATS: RateLimit(2, 120 * SECOND_NS),
    CommandKind.LAST_FLIGHT: RateLimit(1, 300 * SECOND_NS),
    CommandKind.SHOP: RateLimit(3, 600 * SECOND_NS),
}
GLOBAL_RATE_LIMIT = RateLimit(30, 600 * SECOND_NS)


def validate_daily_schedule(day_start_ns: int, deadlines_ns: tuple[int, ...]) -> None:
    """Validate one injected exact UTC-day schedule."""

    if type(day_start_ns) is not int or day_start_ns < 0:
        raise ValueError("day start must be a non-negative integer")
    if day_start_ns % DAY_NS:
        raise ValueError("day start must align with a UTC-day boundary")
    if (
        type(deadlines_ns) is not tuple
        or len(deadlines_ns) not in SUPPORTED_DAILY_FLIGHT_COUNTS
    ):
        raise ValueError("daily schedule flight count is outside the adaptive policy")
    if any(type(value) is not int for value in deadlines_ns):
        raise ValueError("daily schedule deadlines must be integers")
    if deadlines_ns != tuple(sorted(set(deadlines_ns))):
        raise ValueError("daily schedule deadlines must be unique and sorted")
    if any(
        value < day_start_ns or value >= day_start_ns + DAY_NS
        for value in deadlines_ns
    ):
        raise ValueError("daily schedule deadline falls outside its UTC day")


def validate_daily_schedule_state(schedule: DailySchedule) -> None:
    """Validate the durable cursor against the exact daily schedule contract."""

    if not isinstance(schedule, DailySchedule):
        raise ValueError("daily schedule must satisfy the domain contract")
    validate_daily_schedule(schedule.day_start_ns, schedule.deadlines_ns)


def build_daily_schedule(
    day_start_ns: int,
    hours: tuple[int, ...],
    minutes: tuple[int, ...],
) -> tuple[int, ...]:
    """Turn injected hour and minute choices into one canonical daily plan."""

    if type(hours) is not tuple or len(hours) not in SUPPORTED_DAILY_FLIGHT_COUNTS:
        raise ValueError("schedule hour count is outside the adaptive policy")
    if type(minutes) is not tuple or len(minutes) != len(hours):
        raise ValueError("schedule requires one injected minute per hour")
    if any(type(value) is not int or not 0 <= value <= 23 for value in hours):
        raise ValueError("schedule hours must be integers from zero through twenty-three")
    if len(set(hours)) != len(hours):
        raise ValueError("standard schedule hours must be distinct")
    if any(type(value) is not int or not 0 <= value <= 59 for value in minutes):
        raise ValueError("schedule minutes must be integers from zero through fifty-nine")
    deadlines = tuple(
        sorted(
            day_start_ns
            + hour * 3_600 * SECOND_NS
            + (1 if hour == 0 and minute == 0 else minute) * 60 * SECOND_NS
            for hour, minute in zip(hours, minutes, strict=True)
        )
    )
    validate_daily_schedule(day_start_ns, deadlines)
    return deadlines


def community_hunt_progress(state: GameState) -> int:
    """Return the monotonic channel-wide count of successful hunts."""

    if not isinstance(state, GameState):
        raise ValueError("community progress requires a game state")
    return sum(player.hits for player in state.players)


def adaptive_daily_flight_count(state: GameState) -> int:
    """Select the next UTC day's immutable flight count from durable progress."""

    progress = community_hunt_progress(state)
    if progress <= BOOTSTRAP_COMMUNITY_HITS_MAX:
        return BOOTSTRAP_DAILY_FLIGHT_COUNT
    if progress <= GROWTH_COMMUNITY_HITS_MAX:
        return GROWTH_DAILY_FLIGHT_COUNT
    return DAILY_FLIGHT_COUNT


def install_daily_schedule(
    state: GameState,
    now_ns: int,
    day_start_ns: int,
    deadlines_ns: tuple[int, ...],
) -> Transition:
    """Durably install one injected plan without resetting an existing cursor."""

    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("schedule installation time must be a non-negative integer")
    validate_daily_schedule(day_start_ns, deadlines_ns)
    if not day_start_ns <= now_ns < day_start_ns + DAY_NS:
        raise ValueError("daily schedule can only be installed during its UTC day")
    advanced = advance_time(state, now_ns)
    current = advanced.state.daily_schedule
    if current is not None:
        validate_daily_schedule_state(current)
        if current.day_start_ns == day_start_ns:
            if current.deadlines_ns != deadlines_ns:
                raise ValueError("installed day cannot be replaced with different entropy")
            return advanced
        if day_start_ns <= current.day_start_ns:
            raise ValueError("daily schedules must advance by UTC day")
        if now_ns < current.day_start_ns + DAY_NS:
            raise ValueError("current daily schedule has not reached its day boundary")
    return Transition(
        state=replace(
            advanced.state,
            daily_schedule=DailySchedule(day_start_ns, deadlines_ns),
        ),
        outcomes=advanced.outcomes,
    )


def tick_daily_schedule(
    state: GameState,
    now_ns: int,
    *,
    selection: FlightSelection | None = None,
) -> Transition:
    """Consume missed deadlines or dispatch one exact due scheduled flight."""

    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("schedule tick time must be a non-negative integer")
    advanced = advance_time(state, now_ns)
    schedule = advanced.state.daily_schedule
    if schedule is None:
        raise ValueError("schedule tick requires an installed daily schedule")
    validate_daily_schedule_state(schedule)
    if selection is not None and not isinstance(selection, FlightSelection):
        raise ValueError("schedule selection must satisfy the runtime contract")

    index = schedule.next_index
    skipped: list[int] = []
    while index < len(schedule.deadlines_ns) and schedule.deadlines_ns[index] < now_ns:
        skipped.append(schedule.deadlines_ns[index])
        index += 1

    exact_due = (
        index < len(schedule.deadlines_ns)
        and schedule.deadlines_ns[index] == now_ns
    )
    if selection is not None and (not exact_due or advanced.state.flight is not None):
        raise ValueError("scheduled selection requires an exact unblocked deadline")

    dispatch = selection is not None and exact_due
    if exact_due:
        if not dispatch:
            skipped.append(schedule.deadlines_ns[index])
        index += 1

    scheduled_state = replace(
        advanced.state,
        daily_schedule=replace(schedule, next_index=index),
    )
    skipped_outcomes = (
        (
            Outcome(
                OutcomeKind.SCHEDULED_FLIGHT_SKIPPED,
                skipped_deadlines_ns=tuple(skipped),
            ),
        )
        if skipped
        else ()
    )
    if not dispatch:
        return Transition(
            state=scheduled_state,
            outcomes=advanced.outcomes + skipped_outcomes,
        )

    assert selection is not None
    started = start_flight(
        scheduled_state,
        now_ns,
        lifetime_ns=selection.lifetime_ns,
        health=selection.health,
        kind=selection.kind,
        reward_experience=selection.reward_experience,
    )
    return Transition(
        state=started.state,
        outcomes=advanced.outcomes + skipped_outcomes + started.outcomes,
    )


def select_scheduled_flight(
    kind_roll: int,
    *,
    golden_health_roll: int | None = None,
) -> FlightSelection:
    """Resolve the observed one-in-eighteen golden weighting."""

    if type(kind_roll) is not int or not 1 <= kind_roll <= DAILY_FLIGHT_COUNT:
        raise ValueError("flight kind roll must be between one and eighteen")
    if kind_roll <= DAILY_GOLDEN_WEIGHT:
        if type(golden_health_roll) is not int or not 3 <= golden_health_roll <= 5:
            raise ValueError("golden flight requires an injected health from three to five")
        kind = FlightKind.GOLDEN
        health = golden_health_roll
    else:
        if golden_health_roll is not None:
            raise ValueError("standard flight cannot carry a golden health roll")
        kind = FlightKind.STANDARD
        health = 1
    return FlightSelection(kind, health, flight_reward(kind, health))


def _window_key(window: ThrottleWindow) -> tuple[str, str]:
    return (
        "" if window.player_key is None else window.player_key,
        "" if window.command is None else window.command.value,
    )


def _limit_for(window: ThrottleWindow) -> RateLimit:
    if window.player_key is None:
        return GLOBAL_RATE_LIMIT
    assert window.command is not None
    try:
        return COMMAND_RATE_LIMITS[window.command]
    except KeyError as error:
        raise ValueError("throttle window command has no calibrated policy") from error


def validate_throttle_window(window: ThrottleWindow) -> None:
    """Validate one durable window against the calibrated rate catalog."""

    if not isinstance(window, ThrottleWindow):
        raise ValueError("throttle window must satisfy the domain contract")
    limit = _limit_for(window)
    if len(window.expires_at_ns) > limit.maximum:
        raise ValueError("throttle window exceeds its calibrated maximum")


def _prune_windows(state: GameState, now_ns: int) -> GameState:
    retained: list[ThrottleWindow] = []
    for window in state.throttle_windows:
        validate_throttle_window(window)
        expirations = tuple(value for value in window.expires_at_ns if value > now_ns)
        if not expirations:
            continue
        limit = _limit_for(window)
        retained.append(
            replace(
                window,
                expires_at_ns=expirations,
                notice_after_ns=(
                    window.notice_after_ns
                    if len(expirations) >= limit.maximum
                    else 0
                ),
            )
        )
    return replace(state, throttle_windows=tuple(sorted(retained, key=_window_key)))


def _find_window(
    windows: tuple[ThrottleWindow, ...],
    player_key: str | None,
    command: CommandKind | None,
) -> ThrottleWindow | None:
    return next(
        (
            window
            for window in windows
            if window.player_key == player_key and window.command is command
        ),
        None,
    )


def _replace_window(state: GameState, replacement: ThrottleWindow) -> GameState:
    retained = tuple(
        window
        for window in state.throttle_windows
        if _window_key(window) != _window_key(replacement)
    )
    return replace(
        state,
        throttle_windows=tuple(sorted((*retained, replacement), key=_window_key)),
    )


def _admit_command(
    state: GameState,
    nickname: str,
    command: CommandKind,
    now_ns: int,
) -> tuple[Transition, bool]:
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("runtime command time must be a non-negative integer")
    if not isinstance(nickname, str) or not nickname:
        raise ValueError("runtime command nickname must not be empty")
    if not isinstance(command, CommandKind):
        raise ValueError("runtime command kind is invalid")
    advanced = advance_time(state, now_ns)
    current = _prune_windows(advanced.state, now_ns)
    player_key = rfc1459_casefold(nickname)
    personal_limit = COMMAND_RATE_LIMITS.get(command)
    personal = (
        None
        if personal_limit is None
        else _find_window(current.throttle_windows, player_key, command)
    )
    global_window = _find_window(current.throttle_windows, None, None)
    blocked = None
    if (
        personal is not None
        and personal_limit is not None
        and len(personal.expires_at_ns) >= personal_limit.maximum
    ):
        blocked = personal
    elif (
        global_window is not None
        and len(global_window.expires_at_ns) >= GLOBAL_RATE_LIMIT.maximum
    ):
        blocked = global_window

    if blocked is not None:
        notice_emitted = now_ns >= blocked.notice_after_ns
        if notice_emitted:
            blocked = replace(
                blocked,
                notice_after_ns=now_ns + THROTTLE_NOTICE_INTERVAL_NS,
            )
            current = _replace_window(current, blocked)
        return (
            Transition(
                state=current,
                outcomes=advanced.outcomes
                + (
                    Outcome(
                        OutcomeKind.COMMAND_THROTTLED,
                        actor=nickname,
                        command=command,
                        due_at_ns=now_ns,
                        defer_until_ns=blocked.expires_at_ns[0],
                        notice_emitted=notice_emitted,
                    ),
                ),
            ),
            False,
        )

    if personal_limit is not None:
        expirations = () if personal is None else personal.expires_at_ns
        current = _replace_window(
            current,
            ThrottleWindow(
                player_key,
                command,
                tuple(sorted((*expirations, now_ns + personal_limit.window_ns))),
            ),
        )
    global_expirations = () if global_window is None else global_window.expires_at_ns
    current = _replace_window(
        current,
        ThrottleWindow(
            None,
            None,
            tuple(sorted((*global_expirations, now_ns + GLOBAL_RATE_LIMIT.window_ns))),
        ),
    )
    return Transition(current, advanced.outcomes), True


def apply_runtime_command(
    state: GameState,
    nickname: str,
    command: Command,
    now_ns: int,
    *,
    shot_attempt: ShotAttempt | None = None,
    delay_settled: bool = False,
) -> Transition:
    """Admit and apply one public command as a replayable atomic transition."""

    if not isinstance(command, Command):
        raise ValueError("runtime command must satisfy the parser contract")
    admission, accepted = _admit_command(state, nickname, command.kind, now_ns)
    if not accepted:
        return admission
    applied = apply_command(
        admission.state,
        nickname,
        command,
        now_ns,
        shot_attempt=shot_attempt,
        delay_settled=delay_settled,
    )
    return Transition(applied.state, admission.outcomes + applied.outcomes)


def apply_runtime_purchase(
    state: GameState,
    nickname: str,
    item_id: int,
    now_ns: int,
    *,
    charged_cost: int,
    magnitude: int | None = None,
    replace_active_effect: bool = False,
    target_nickname: str | None = None,
    target_present: bool | None = None,
    scheduled_for_ns: int | None = None,
    fatigue_relief_centi: int | None = None,
    fatigue_target_centi: int | None = None,
) -> Transition:
    """Admit and settle one public shop purchase under the shop rate window."""

    admission, accepted = _admit_command(
        state,
        nickname,
        CommandKind.SHOP,
        now_ns,
    )
    if not accepted:
        return admission
    applied = purchase(
        admission.state,
        nickname,
        item_id,
        now_ns,
        charged_cost=charged_cost,
        magnitude=magnitude,
        replace_active_effect=replace_active_effect,
        target_nickname=target_nickname,
        target_present=target_present,
        scheduled_for_ns=scheduled_for_ns,
        fatigue_relief_centi=fatigue_relief_centi,
        fatigue_target_centi=fatigue_target_centi,
    )
    return Transition(applied.state, admission.outcomes + applied.outcomes)


def loot_chance_multiplier(state: GameState, nickname: str) -> int:
    """Expose the bounded abundance modifier to the runtime selector."""

    key = rfc1459_casefold(nickname)
    return 2 if active_reward_effect(state, key, "abundance_amulet") else 1


def select_runtime_loot(
    state: GameState,
    nickname: str,
    standard_rolls: tuple[int, ...],
    *,
    magnitude: int | None = None,
    unusual_award: LootAward | None = None,
) -> LootAward | None:
    """Select standard loot or accept one externally selected unusual award."""

    if unusual_award is not None:
        spec = validate_loot_award(unusual_award)
        if spec.threshold_per_thousand is not None:
            raise ValueError("injected unusual award references standard loot")
        return unusual_award
    player = state.player(rfc1459_casefold(nickname))
    karma = 0 if player is None else player_karma_basis_points(player)
    return select_standard_loot(
        standard_rolls,
        chance_multiplier=loot_chance_multiplier(state, nickname),
        karma_basis_points=karma,
        magnitude=magnitude,
    )
