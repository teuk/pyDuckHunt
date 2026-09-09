"""Concrete UTC-anchored clock and durable daily-schedule adapters."""

from __future__ import annotations

from pyduckhunt.i18n import validate_language, localized_method, tr

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from pyduckhunt.game.bread import (active_channel_breads, bread_identifiers,
    preserved_bread_deadline, MAX_CHANNEL_BREAD)
from pyduckhunt.game.model import (
    DailySchedule,
    FlightKind,
    GameState,
    OutcomeKind,
    ScheduledAction,
    Transition,
)
from pyduckhunt.game.runtime import (
    BOOTSTRAP_DAILY_FLIGHT_COUNT,
    DAILY_FLIGHT_COUNT,
    DAY_NS,
    FIXED_DAILY_FLIGHT_COUNT,
    FLIGHT_LIFETIME_NS,
    GROWTH_DAILY_FLIGHT_COUNT,
    SUPPORTED_DAILY_FLIGHT_COUNTS,
    FlightSelection,
    build_daily_schedule,
    community_hunt_progress,
    select_scheduled_flight,
)
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.rendering.flight_appearance import FlightAppearance
from pyduckhunt.rendering.responses import (
    render_detector_notice,
    render_outcomes,
    render_wire_notice,
    render_wire_response,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.runtime.orchestrator import (
    DispatchResult,
    DispatchStatus,
    RuntimeOrchestrator,
)
from pyduckhunt.runtime.settlement import IntegerSource


NanosecondSource = Callable[[], int]
FlightAppearanceSource = Callable[[], FlightAppearance]


class SystemRuntimeClock:
    """Project a monotonic source onto one UTC-compatible nanosecond timeline."""

    def __init__(
        self,
        monotonic_source: NanosecondSource = time.monotonic_ns,
        wall_source: NanosecondSource = time.time_ns,
    ) -> None:
        if not callable(monotonic_source) or not callable(wall_source):
            raise ValueError("runtime clock sources must be callable")
        self._monotonic_source = monotonic_source
        self._anchor_wall_ns = _sample_nanoseconds(wall_source, "wall clock")
        self._anchor_monotonic_ns = _sample_nanoseconds(
            monotonic_source,
            "monotonic clock",
        )
        self._last_monotonic_ns = self._anchor_monotonic_ns
        self._last_now_ns = self._anchor_wall_ns
        self._owner_thread = threading.get_ident()

    def now_ns(self) -> int:
        self._ensure_owner()
        monotonic_ns = _sample_nanoseconds(
            self._monotonic_source,
            "monotonic clock",
        )
        if monotonic_ns < self._last_monotonic_ns:
            raise RuntimeError("system monotonic clock moved backwards")
        now_ns = self._anchor_wall_ns + (
            monotonic_ns - self._anchor_monotonic_ns
        )
        if now_ns < self._last_now_ns:
            raise RuntimeError("projected runtime clock moved backwards")
        self._last_monotonic_ns = monotonic_ns
        self._last_now_ns = now_ns
        return now_ns

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("runtime clock is owned by one event-loop thread")


class CalibratedScheduleSource:
    """Resolve one daily plan and each due flight from injected integer draws."""

    def __init__(self, integer_source: IntegerSource) -> None:
        if not callable(integer_source):
            raise ValueError("schedule source requires an integer source")
        self._integer_source = integer_source
        self._owner_thread = threading.get_ident()

    def daily_schedule(
        self,
        day_start_ns: int,
        flight_count: int = FIXED_DAILY_FLIGHT_COUNT,
    ) -> tuple[int, ...]:
        self._ensure_owner()
        if type(day_start_ns) is not int or day_start_ns < 0 or day_start_ns % DAY_NS:
            raise ValueError("schedule day start must align with UTC")
        if type(flight_count) is not int or flight_count not in SUPPORTED_DAILY_FLIGHT_COUNTS:
            raise ValueError("schedule flight count is outside the supported policy")
        available_hours = list(range(24))
        selected_hours: list[int] = []
        for _ in range(flight_count):
            index = self._draw(0, len(available_hours) - 1)
            selected_hours.append(available_hours.pop(index))
        minutes = tuple(self._draw(0, 59) for _ in range(flight_count))
        return build_daily_schedule(
            day_start_ns,
            tuple(selected_hours),
            minutes,
        )

    def bread_schedule(self, state: GameState, now_ns: int) -> tuple[int, ...]:
        """Draw the reference method-2 plan: base + bread, hourly rounds."""
        self._ensure_owner()
        day = now_ns - now_ns % DAY_NS
        count = FIXED_DAILY_FLIGHT_COUNT + min(MAX_CHANNEL_BREAD,
                                              len(active_channel_breads(state, now_ns)))
        keep = preserved_bread_deadline(state, now_ns)
        chosen = set(() if keep is None else (keep,))
        hours = list(range(24))
        while len(chosen) < count:
            hour = hours.pop(self._draw(0, len(hours) - 1))
            if not hours:
                hours = list(range(24))
            # Equivalent to retrying duplicate minute draws, with bounded work.
            # Midnight itself is not a valid time bind in the reference.
            candidates = [day + (hour * 60 + minute) * 60_000_000_000
                          for minute in range(60) if hour != 0 or minute != 0]
            minute = self._draw(0, 59)
            initial = day + (hour * 60 + (1 if hour == 0 and minute == 0 else minute)) * 60_000_000_000
            if initial in chosen:
                candidates = [d for d in candidates if d not in chosen]
                initial = candidates[self._draw(0, len(candidates) - 1)]
            chosen.add(initial)
        return tuple(sorted(chosen))

    def flight_selection(self) -> FlightSelection:
        self._ensure_owner()
        kind_roll = self._draw(1, DAILY_FLIGHT_COUNT)
        golden_health = self._draw(3, 5) if kind_roll == 1 else None
        return select_scheduled_flight(
            kind_roll,
            golden_health_roll=golden_health,
        )

    def expanded_daily_schedule(
        self,
        schedule: DailySchedule,
        now_ns: int,
        flight_count: int = FIXED_DAILY_FLIGHT_COUNT,
    ) -> tuple[int, ...]:
        """Add randomized future minutes while preserving today's durable plan."""

        self._ensure_owner()
        if not isinstance(schedule, DailySchedule):
            raise ValueError("schedule expansion requires one daily schedule")
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("schedule expansion time must be non-negative")
        if type(flight_count) is not int or flight_count not in SUPPORTED_DAILY_FLIGHT_COUNTS:
            raise ValueError("schedule expansion count is outside the fixed policy")
        missing = flight_count - len(schedule.deadlines_ns)
        if missing <= 0:
            return schedule.deadlines_ns
        minute_ns = 60 * 1_000_000_000
        first = ((now_ns // minute_ns) + 1) * minute_ns
        end = schedule.day_start_ns + DAY_NS
        existing = set(schedule.deadlines_ns)
        available = [
            deadline
            for deadline in range(first, end, minute_ns)
            if deadline not in existing
        ]
        if len(available) < missing:
            return schedule.deadlines_ns
        additions: list[int] = []
        for _ in range(missing):
            additions.append(available.pop(self._draw(0, len(available) - 1)))
        return tuple(sorted((*schedule.deadlines_ns, *additions)))

    def _draw(self, minimum: int, maximum: int) -> int:
        value = self._integer_source(minimum, maximum)
        if type(value) is not int or not minimum <= value <= maximum:
            raise RuntimeError("schedule integer source violated its bounds")
        return value

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("schedule source is owned by one event-loop thread")


@dataclass(frozen=True, slots=True)
class SchedulingPolicy:
    maximum_lateness_ns: int = 1_000_000_000

    def __post_init__(self) -> None:
        if type(self.maximum_lateness_ns) is not int or self.maximum_lateness_ns < 0:
            raise ValueError("schedule lateness must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ScheduleStatus:
    day_start_ns: int
    flight_count: int
    next_index: int
    next_deadline_ns: int
    community_progress: int
    recommended_flight_count: int
    flight_active: bool

    def __post_init__(self) -> None:
        if type(self.day_start_ns) is not int or self.day_start_ns < 0 or self.day_start_ns % DAY_NS:
            raise ValueError("schedule status day is invalid")
        if (type(self.flight_count) is not int or
                (self.flight_count not in SUPPORTED_DAILY_FLIGHT_COUNTS
                 and not 24 <= self.flight_count <= 24 + MAX_CHANNEL_BREAD)):
            raise ValueError("schedule status flight count is invalid")
        if type(self.next_index) is not int or not 0 <= self.next_index <= self.flight_count:
            raise ValueError("schedule status cursor is invalid")
        if type(self.next_deadline_ns) is not int or self.next_deadline_ns < 0:
            raise ValueError("schedule status next deadline is invalid")
        if type(self.community_progress) is not int or self.community_progress < 0:
            raise ValueError("schedule status community progress is invalid")
        if self.recommended_flight_count not in SUPPORTED_DAILY_FLIGHT_COUNTS:
            raise ValueError("schedule status recommendation is invalid")
        if type(self.flight_active) is not bool:
            raise ValueError("schedule status active-flight flag is invalid")

    @property
    def band(self) -> str:
        if self.flight_count >= BOOTSTRAP_DAILY_FLIGHT_COUNT:
            return "fixed" if self.flight_count == 24 else "bread"
        if self.flight_count == GROWTH_DAILY_FLIGHT_COUNT:
            return "legacy-21"
        return "legacy-18"


@dataclass(frozen=True, slots=True)
class ScheduleStepResult:
    dispatches: tuple[DispatchResult, ...]
    next_deadline_ns: int | None
    status: ScheduleStatus | None = None
    plan_installed: bool = False
    plan_expanded: bool = False
    attempted_deadline_ns: int | None = None
    lateness_ns: int | None = None
    skip_reason: str | None = None

    plan_replanned: bool = False

    def __post_init__(self) -> None:
        if type(self.dispatches) is not tuple or any(
            not isinstance(dispatch, DispatchResult) for dispatch in self.dispatches
        ):
            raise ValueError("schedule dispatches must be immutable")
        if self.next_deadline_ns is not None and (
            type(self.next_deadline_ns) is not int or self.next_deadline_ns < 0
        ):
            raise ValueError("next schedule deadline is invalid")
        if self.status is not None and not isinstance(self.status, ScheduleStatus):
            raise ValueError("schedule result status is invalid")
        if type(self.plan_replanned) is not bool:
            raise ValueError("bread replan flag is invalid")
        if type(self.plan_installed) is not bool:
            raise ValueError("schedule installation observation is invalid")
        if type(self.plan_expanded) is not bool:
            raise ValueError("schedule expansion observation is invalid")
        if (self.attempted_deadline_ns is None) != (self.lateness_ns is None):
            raise ValueError("schedule attempt timing must be paired")
        if self.attempted_deadline_ns is not None and (
            type(self.attempted_deadline_ns) is not int
            or self.attempted_deadline_ns < 0
            or type(self.lateness_ns) is not int
            or self.lateness_ns < 0
        ):
            raise ValueError("schedule attempt timing is invalid")
        if self.skip_reason not in (None, "active-flight", "durable-clock", "late"):
            raise ValueError("schedule skip reason is invalid")
        if self.skip_reason is not None and self.attempted_deadline_ns is None:
            raise ValueError("schedule skip reason requires one attempted deadline")


class RuntimeSchedulingAdapter:
    """Install, catch up and dispatch the durable daily schedule."""

    def __init__(
        self,
        runtime: RuntimeOrchestrator,
        channels: tuple[str, ...],
        source: CalibratedScheduleSource,
        *,
        policy: SchedulingPolicy = SchedulingPolicy(),
        anti_cheat: bool = False,
        language: str = "fr",
        flight_appearance_source: FlightAppearanceSource | None = None,
    ) -> None:
        if not isinstance(runtime, RuntimeOrchestrator):
            raise ValueError("scheduling adapter requires a runtime orchestrator")
        if not isinstance(source, CalibratedScheduleSource):
            raise ValueError("scheduling adapter requires a calibrated source")
        if not isinstance(policy, SchedulingPolicy):
            raise ValueError("scheduling policy is invalid")
        if type(anti_cheat) is not bool:
            raise ValueError("anti-cheat policy must be a truth value")
        if anti_cheat != (flight_appearance_source is not None):
            raise ValueError(
                "anti-cheat requires exactly one flight appearance source"
            )
        if flight_appearance_source is not None and not callable(
            flight_appearance_source
        ):
            raise ValueError("flight appearance source must be callable")
        if type(channels) is not tuple or not channels:
            raise ValueError("scheduling adapter requires immutable channels")
        canonical_channels: set[str] = set()
        for channel in channels:
            if (
                type(channel) is not str
                or not channel.startswith(("#", "&"))
                or any(character in channel for character in (" ", "\x00", "\r", "\n"))
            ):
                raise ValueError("scheduling adapter channel is invalid")
            folded = rfc1459_casefold(channel)
            if folded in canonical_channels:
                raise ValueError("scheduling adapter channels must be unique")
            canonical_channels.add(folded)
        self.language = validate_language(language)
        self.runtime = runtime
        self.channels = channels
        self.source = source
        self.policy = policy
        self.anti_cheat = anti_cheat
        self._flight_appearance_source = flight_appearance_source
        self._last_now_ns: int | None = None
        self._owner_thread = threading.get_ident()

    @localized_method
    def step(self, now_ns: int) -> ScheduleStepResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        if now_ns < self.runtime.state.now_ns:
            raise ValueError("schedule clock precedes durable game time")
        dispatches: list[DispatchResult] = []
        plan_installed = False
        plan_expanded = False
        if self.runtime.state.bread_plan_effect_ids is None:
            enabled = self.runtime.dispatch(
                ReplayEvent.enable_hourly_bread(self.runtime.state.now_ns), self._render)
            dispatches.append(enabled)
            if enabled.status is DispatchStatus.BACKPRESSURED:
                return self._result(tuple(dispatches), None, now_ns)
        active_flight = self.runtime.state.flight
        if active_flight is not None and now_ns >= active_flight.expires_at_ns:
            action = _next_due_channel_action(
                self.runtime.state,
                active_flight.expires_at_ns,
            )
            expired = self.runtime.dispatch(
                _channel_action_event(action, active_flight.expires_at_ns)
                if action is not None
                else ReplayEvent.advance_time(active_flight.expires_at_ns),
                self._render,
            )
            dispatches.append(expired)
            if expired.status is DispatchStatus.BACKPRESSURED:
                return self._result(tuple(dispatches), active_flight.expires_at_ns, now_ns)
        if self.runtime.state.flight is None:
            action = _next_due_channel_action(self.runtime.state, now_ns)
            if action is not None:
                action_now_ns = max(action.due_at_ns, self.runtime.state.now_ns)
                launched = self.runtime.dispatch(
                    _channel_action_event(action, action_now_ns),
                    self._render,
                )
                dispatches.append(launched)
                if launched.status is DispatchStatus.BACKPRESSURED:
                    return self._result(tuple(dispatches), action_now_ns, now_ns)
        day_start_ns = now_ns - now_ns % DAY_NS
        schedule = self.runtime.state.daily_schedule
        if schedule is not None and schedule.day_start_ns > day_start_ns:
            raise RuntimeError("durable schedule is ahead of the runtime clock")
        if schedule is None or schedule.day_start_ns < day_start_ns:
            if active_channel_breads(self.runtime.state, now_ns):
                deadlines = self.source.bread_schedule(self.runtime.state, now_ns)
                event = ReplayEvent.replan_bread_schedule(now_ns, day_start_ns, deadlines)
            else:
                deadlines = self.source.daily_schedule(day_start_ns, FIXED_DAILY_FLIGHT_COUNT)
                event = ReplayEvent.install_daily_schedule(now_ns, day_start_ns, deadlines)
            installed = self.runtime.dispatch(event, self._render)
            dispatches.append(installed)
            if installed.status is DispatchStatus.BACKPRESSURED:
                return self._result(tuple(dispatches), None, now_ns)
            plan_installed = True
            schedule = self.runtime.state.daily_schedule

        assert schedule is not None
        if len(schedule.deadlines_ns) < FIXED_DAILY_FLIGHT_COUNT:
            expanded_deadlines = self.source.expanded_daily_schedule(schedule, now_ns)
            if expanded_deadlines != schedule.deadlines_ns:
                expanded = self.runtime.dispatch(
                    ReplayEvent.expand_daily_schedule(
                        now_ns,
                        schedule.day_start_ns,
                        expanded_deadlines,
                    ),
                    self._render,
                )
                dispatches.append(expanded)
                if expanded.status is DispatchStatus.BACKPRESSURED:
                    return self._result(tuple(dispatches), None, now_ns)
                plan_expanded = True
                schedule = self.runtime.state.daily_schedule
                assert schedule is not None
        identifiers = bread_identifiers(self.runtime.state, now_ns)
        due_daily = (schedule.next_index < len(schedule.deadlines_ns)
                     and schedule.deadlines_ns[schedule.next_index] <= now_ns)
        if self.runtime.state.bread_plan_effect_ids != identifiers and not due_daily:
            deadlines = self.source.bread_schedule(self.runtime.state, now_ns)
            replanned = self.runtime.dispatch(
                ReplayEvent.replan_bread_schedule(now_ns, day_start_ns, deadlines), self._render)
            dispatches.append(replanned)
            next_deadline = min((d for d in deadlines if d > now_ns), default=day_start_ns + DAY_NS)
            return self._result(tuple(dispatches),
                None if replanned.status is DispatchStatus.BACKPRESSURED else
                _next_runtime_deadline(self.runtime.state, next_deadline), now_ns,
                plan_installed=plan_installed, plan_expanded=plan_expanded,
                plan_replanned=replanned.status is DispatchStatus.ACCEPTED)
        if schedule.next_index >= len(schedule.deadlines_ns):
            return self._result(
                tuple(dispatches),
                _next_runtime_deadline(self.runtime.state, day_start_ns + DAY_NS),
                now_ns,
                plan_installed=plan_installed,
                plan_expanded=plan_expanded,
            )
        deadline_ns = schedule.deadlines_ns[schedule.next_index]
        if deadline_ns > now_ns:
            return self._result(
                tuple(dispatches),
                _next_runtime_deadline(self.runtime.state, deadline_ns),
                now_ns,
                plan_installed=plan_installed,
                plan_expanded=plan_expanded,
            )

        lateness_ns = now_ns - deadline_ns
        exact_timestamp_available = deadline_ns >= self.runtime.state.now_ns
        within_lateness = lateness_ns <= self.policy.maximum_lateness_ns
        event_now_ns = (
            deadline_ns
            if exact_timestamp_available and within_lateness
            else now_ns
        )
        selection = None
        active_at_deadline = _flight_active_at(
            self.runtime.state,
            deadline_ns,
        )
        skip_reason = None
        if not exact_timestamp_available:
            skip_reason = "durable-clock"
        elif not within_lateness:
            skip_reason = "late"
        elif active_at_deadline:
            skip_reason = "active-flight"
        else:
            selection = self.source.flight_selection()
        ticked = self.runtime.dispatch(
            ReplayEvent.schedule_tick(event_now_ns, selection=selection),
            self._render,
        )
        dispatches.append(ticked)
        if ticked.status is DispatchStatus.BACKPRESSURED:
            return self._result(
                tuple(dispatches),
                deadline_ns,
                now_ns,
                plan_installed=plan_installed,
                plan_expanded=plan_expanded,
                attempted_deadline_ns=deadline_ns,
                lateness_ns=lateness_ns,
                skip_reason=skip_reason,
            )
        current = self.runtime.state.daily_schedule
        assert current is not None
        next_deadline = (
            day_start_ns + DAY_NS
            if current.next_index >= len(current.deadlines_ns)
            else current.deadlines_ns[current.next_index]
        )
        return self._result(
            tuple(dispatches),
            _next_runtime_deadline(self.runtime.state, next_deadline),
            now_ns,
            plan_installed=plan_installed,
            plan_expanded=plan_expanded,
            attempted_deadline_ns=deadline_ns,
            lateness_ns=lateness_ns,
            skip_reason=skip_reason,
        )

    def _result(
        self,
        dispatches: tuple[DispatchResult, ...],
        next_deadline_ns: int | None,
        now_ns: int,
        *,
        plan_installed: bool = False,
        plan_expanded: bool = False,
        plan_replanned: bool = False,
        attempted_deadline_ns: int | None = None,
        lateness_ns: int | None = None,
        skip_reason: str | None = None,
    ) -> ScheduleStepResult:
        schedule = self.runtime.state.daily_schedule
        status = None
        if schedule is not None:
            status = ScheduleStatus(
                day_start_ns=schedule.day_start_ns,
                flight_count=len(schedule.deadlines_ns),
                next_index=schedule.next_index,
                next_deadline_ns=(
                    schedule.day_start_ns + DAY_NS
                    if schedule.next_index >= len(schedule.deadlines_ns)
                    else schedule.deadlines_ns[schedule.next_index]
                ),
                community_progress=community_hunt_progress(self.runtime.state),
                recommended_flight_count=FIXED_DAILY_FLIGHT_COUNT,
                flight_active=_flight_active_at(self.runtime.state, now_ns),
            )
        return ScheduleStepResult(
            dispatches=dispatches,
            next_deadline_ns=next_deadline_ns,
            status=status,
            plan_installed=plan_installed,
            plan_expanded=plan_expanded,
            plan_replanned=plan_replanned,
            attempted_deadline_ns=attempted_deadline_ns,
            lateness_ns=lateness_ns,
            skip_reason=skip_reason,
        )

    def _render(self, transition: Transition) -> tuple[bytes, ...]:
        appearance = None
        if self.anti_cheat and any(
            outcome.kind is OutcomeKind.FLIGHT_STARTED
            for outcome in transition.outcomes
        ):
            assert self._flight_appearance_source is not None
            appearance = self._flight_appearance_source()
            if not isinstance(appearance, FlightAppearance):
                raise RuntimeError("flight appearance source returned an invalid value")
        channel_batch = tuple(
            wire
            for channel in self.channels
            for wire in render_wire_response(
                channel,
                render_outcomes(
                    transition.outcomes,
                    flight_appearance=appearance,
                    channel=channel,
                ),
            )
        )
        detector_batch = tuple(
            wire
            for outcome in transition.outcomes
            if outcome.kind is OutcomeKind.DUCK_ALERT and outcome.actor is not None
            for wire in render_wire_notice(
                outcome.actor,
                render_detector_notice(outcome),
            )
        )
        return channel_batch + detector_batch

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("schedule time must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("schedule clock cannot move backwards")
        self._last_now_ns = now_ns

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("scheduling adapter is owned by one event-loop thread")


def _sample_nanoseconds(source: NanosecondSource, label: str) -> int:
    value = source()
    if type(value) is not int or value < 0:
        raise RuntimeError(f"{label} returned an invalid timestamp")
    return value


def _flight_active_at(state: GameState, now_ns: int) -> bool:
    return state.flight is not None and state.flight.expires_at_ns > now_ns


def _next_runtime_deadline(state: GameState, schedule_deadline_ns: int) -> int:
    deadlines = [schedule_deadline_ns]
    if state.bread_plan_effect_ids is not None:
        deadlines.extend(effect.expires_at_ns for effect in active_channel_breads(state, state.now_ns)
                         if effect.expires_at_ns is not None)
    if state.flight is not None:
        deadlines.append(state.flight.expires_at_ns)
    else:
        deadlines.extend(action.due_at_ns for action in state.scheduled_actions)
    return min(deadlines)


def _next_due_channel_action(
    state: GameState,
    now_ns: int,
) -> ScheduledAction | None:
    return min(
        (
            action
            for action in state.scheduled_actions
            if action.due_at_ns <= now_ns and action.item_id in (20, 23)
        ),
        key=lambda action: (action.due_at_ns, action.action_id),
        default=None,
    )


def _channel_action_event(action: ScheduledAction, now_ns: int) -> ReplayEvent:
    kind = FlightKind.STANDARD if action.item_id == 20 else FlightKind.MECHANICAL
    return ReplayEvent.start_flight(
        now_ns,
        FLIGHT_LIFETIME_NS,
        kind=kind,
    )
