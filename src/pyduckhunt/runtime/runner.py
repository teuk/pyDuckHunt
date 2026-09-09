"""Explicit operator-controlled loop for one development pilot runtime."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pyduckhunt.game.bread import active_channel_breads
from pyduckhunt.game.model import GameState, OutcomeKind
from pyduckhunt.irc.message import render_irc_message
from pyduckhunt.irc.transport import IRCTransportState
from pyduckhunt.runtime.application import BridgeStatus
from pyduckhunt.runtime.orchestrator import DispatchStatus
from pyduckhunt.runtime.pilot import PilotRuntime
from pyduckhunt.runtime.process import ProcessShellResult, ProcessShellState
from pyduckhunt.publishing import RuntimeMetricsSnapshot
from pyduckhunt.runtime.scheduling import (
    RuntimeSchedulingAdapter,
    ScheduleStepResult,
    SystemRuntimeClock,
)


Sleeper = Callable[[float], None]
PilotObserver = Callable[[str], None]
RuntimeMetricsPublisher = Callable[[RuntimeMetricsSnapshot, GameState], None]
SCHEDULE_HEARTBEAT_NS = 30 * 60 * 1_000_000_000
METRICS_HEARTBEAT_NS = 15 * 1_000_000_000


@dataclass(frozen=True, slots=True)
class PilotTelemetry:
    """Privacy-safe facts retained from one foreground pilot execution."""

    ready_observed: bool
    ready_entries: int
    bridge_dispatched: int
    bridge_invalid: int
    bridge_ignored: int
    schedule_accepted: int
    schedule_backpressured: int
    network_failures: int

    def __post_init__(self) -> None:
        if type(self.ready_observed) is not bool:
            raise ValueError("pilot ready observation must be a truth value")
        for field_name in (
            "ready_entries",
            "bridge_dispatched",
            "bridge_invalid",
            "bridge_ignored",
            "schedule_accepted",
            "schedule_backpressured",
            "network_failures",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"pilot {field_name} must be a non-negative integer")
        if self.ready_observed != (self.ready_entries > 0):
            raise ValueError("pilot ready telemetry is inconsistent")


class PilotControl:
    """Thread-safe, first-writer-wins stop request for an operator loop."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = "operator stop"
        self._lock = threading.Lock()

    @property
    def stop_requested(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def request_stop(self, reason: str = "operator stop") -> None:
        if type(reason) is not str or not reason or any(
            character in reason for character in ("\x00", "\r", "\n")
        ):
            raise ValueError("pilot stop reason must be safe non-empty text")
        render_irc_message("QUIT", (reason,))
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            self._event.set()


class OperatorPilotRunner:
    """Start only on direct invocation and stop only through explicit control."""

    def __init__(
        self,
        pilot: PilotRuntime,
        scheduling: RuntimeSchedulingAdapter,
        *,
        clock: SystemRuntimeClock | Callable[[], int] | None = None,
        sleeper: Sleeper = time.sleep,
        poll_interval_seconds: float = 0.05,
        observer: PilotObserver | None = None,
        debug_enabled: bool = False,
        schedule_heartbeat_ns: int = SCHEDULE_HEARTBEAT_NS,
        metrics_publisher: RuntimeMetricsPublisher | None = None,
        metrics_heartbeat_ns: int = METRICS_HEARTBEAT_NS,
    ) -> None:
        if not isinstance(pilot, PilotRuntime):
            raise ValueError("operator runner requires an authorized pilot")
        if not isinstance(scheduling, RuntimeSchedulingAdapter):
            raise ValueError("operator runner requires a scheduling adapter")
        if scheduling.runtime is not pilot.shell.runtime:
            raise ValueError("operator runner components must share one runtime")
        if clock is None:
            clock = SystemRuntimeClock()
        if not isinstance(clock, SystemRuntimeClock) and not callable(clock):
            raise ValueError("operator runner clock is invalid")
        if not callable(sleeper):
            raise ValueError("operator runner sleeper must be callable")
        if observer is not None and not callable(observer):
            raise ValueError("operator runner observer must be callable or none")
        if type(debug_enabled) is not bool:
            raise ValueError("operator debug policy must be a truth value")
        if type(schedule_heartbeat_ns) is not int or schedule_heartbeat_ns < 1:
            raise ValueError("operator schedule heartbeat must be positive")
        if metrics_publisher is not None and not callable(metrics_publisher):
            raise ValueError("operator metrics publisher must be callable or none")
        if type(metrics_heartbeat_ns) is not int or metrics_heartbeat_ns < 1:
            raise ValueError("operator metrics heartbeat must be positive")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0 < poll_interval_seconds <= 1
        ):
            raise ValueError("operator poll interval must be in (0, 1]")
        self.pilot = pilot
        self.scheduling = scheduling
        self._clock = clock
        self._sleeper = sleeper
        self._observer = observer
        self._debug_enabled = debug_enabled
        self._schedule_heartbeat_ns = schedule_heartbeat_ns
        self._metrics_publisher = metrics_publisher
        self._metrics_heartbeat_ns = metrics_heartbeat_ns
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._last_now_ns: int | None = None
        self._last_observed_state: tuple[
            ProcessShellState,
            IRCTransportState,
            bool,
        ] | None = None
        self._ready_entries = 0
        self._bridge_dispatched = 0
        self._bridge_invalid = 0
        self._bridge_ignored = 0
        self._schedule_accepted = 0
        self._schedule_backpressured = 0
        self._network_failures = 0
        self._last_schedule_fingerprint: tuple[object, ...] | None = None
        self._last_channel_items_fingerprint: tuple[object, ...] | None = None
        self._last_schedule_report_ns: int | None = None
        self._last_publication_observation = (0, 0)
        self._last_schedule_status = None
        self._started_at_ns: int | None = None
        self._last_metrics_report_ns: int | None = None
        self._metrics_dirty = True
        self._metrics_publication_attempts = 0
        self._metrics_publication_failures = 0
        self._owner_thread = threading.get_ident()

    @property
    def telemetry(self) -> PilotTelemetry:
        return PilotTelemetry(
            self._ready_entries > 0,
            self._ready_entries,
            self._bridge_dispatched,
            self._bridge_invalid,
            self._bridge_ignored,
            self._schedule_accepted,
            self._schedule_backpressured,
            self._network_failures,
        )

    def run(self, control: PilotControl) -> ProcessShellResult:
        self._ensure_owner()
        if not isinstance(control, PilotControl):
            raise ValueError("operator runner requires pilot control")
        if self.pilot.shell.state is not ProcessShellState.NEW:
            raise RuntimeError("operator pilot runner can only run once")
        now_ns = self._now_ns()
        self._started_at_ns = now_ns
        if now_ns < self.pilot.recovered.state.now_ns:
            raise RuntimeError("operator clock precedes recovered durable state")
        if control.stop_requested:
            result = self.pilot.shell.stop(now_ns, control.reason)
            self._record_process(result)
            return result

        result = self.pilot.shell.start(now_ns)
        self._record_process(result)
        try:
            while result.state not in (
                ProcessShellState.STOPPED,
                ProcessShellState.FAILED,
            ):
                now_ns = self._now_ns()
                if control.stop_requested and result.state is ProcessShellState.RUNNING:
                    result = self.pilot.shell.stop(now_ns, control.reason)
                    self._record_process(result)
                elif (
                    result.state is ProcessShellState.RUNNING
                    and self.pilot.shell.adapter.transport.state
                    is IRCTransportState.READY
                ):
                    scheduled = self.scheduling.step(now_ns)
                    self._record_schedule(scheduled, now_ns)

                if result.state in (
                    ProcessShellState.RUNNING,
                    ProcessShellState.STOPPING,
                ):
                    result = self.pilot.shell.poll(now_ns)
                    self._record_process(result)
                if result.state not in (
                    ProcessShellState.STOPPED,
                    ProcessShellState.FAILED,
                ):
                    self._sleeper(self.poll_interval_seconds)
        except KeyboardInterrupt:
            control.request_stop("operator interrupt")
            return self._finish_after_interrupt(control)
        except BaseException:
            self._force_bounded_shutdown("runner failure")
            raise
        return result

    def _finish_after_interrupt(self, control: PilotControl) -> ProcessShellResult:
        try:
            while self.pilot.shell.state not in (
                ProcessShellState.STOPPED,
                ProcessShellState.FAILED,
            ):
                now_ns = self._now_ns()
                if self.pilot.shell.state is ProcessShellState.RUNNING:
                    result = self.pilot.shell.stop(now_ns, control.reason)
                else:
                    result = self.pilot.shell.poll(now_ns)
                self._record_process(result)
                if result.state not in (
                    ProcessShellState.STOPPED,
                    ProcessShellState.FAILED,
                ):
                    self._sleeper(self.poll_interval_seconds)
            return result
        except BaseException:
            self._force_bounded_shutdown("interrupt shutdown failure")
            raise

    def _force_bounded_shutdown(self, reason: str) -> None:
        state = self.pilot.shell.state
        if state in (ProcessShellState.STOPPED, ProcessShellState.FAILED):
            return
        now_ns = self._last_now_ns if self._last_now_ns is not None else 0
        try:
            result = self.pilot.shell.stop(now_ns, reason)
            self._record_process(result)
            if result.state is ProcessShellState.STOPPING:
                deadline_ns = (
                    now_ns
                    + self.pilot.shell.adapter.transport.policy.stop_timeout_ns
                )
                result = self.pilot.shell.poll(deadline_ns)
                self._record_process(result)
        except Exception:
            return

    def _record_process(self, result: ProcessShellResult) -> None:
        observed_state = (
            result.state,
            result.network.state,
            result.network.connected,
        )
        previous = self._last_observed_state
        if result.network.state is IRCTransportState.READY and (
            previous is None or previous[1] is not IRCTransportState.READY
        ):
            self._ready_entries += 1
        if observed_state != previous:
            self._emit(
                "STATE "
                f"process={result.state.value} "
                f"transport={result.network.state.value} "
                f"connected={'yes' if result.network.connected else 'no'}"
            )
            self._last_observed_state = observed_state
            self._metrics_dirty = True

        graceful_peer_close = (
            result.state is ProcessShellState.STOPPED
            and previous is not None
            and previous[0] is ProcessShellState.STOPPING
        )
        if result.network.failure is not None and not graceful_peer_close:
            self._network_failures += 1
            self._metrics_dirty = True
            self._emit(
                f"NETWORK failure={result.network.failure.replace(' ', '_')}"
            )

        statuses = tuple(bridge.status for bridge in result.bridge_results)
        if statuses:
            dispatched = statuses.count(BridgeStatus.DISPATCHED)
            invalid = statuses.count(BridgeStatus.INVALID)
            ignored = statuses.count(BridgeStatus.IGNORED)
            self._bridge_dispatched += dispatched
            self._bridge_invalid += invalid
            self._bridge_ignored += ignored
            self._metrics_dirty = True
            if dispatched or invalid:
                command_kinds = sorted(
                    {
                        bridge.command.kind.value
                        for bridge in result.bridge_results
                        if bridge.command is not None
                    }
                )
                self._emit(
                    "APPLICATION "
                    f"dispatched={dispatched} invalid={invalid} ignored={ignored} "
                    f"commands={','.join(command_kinds) or 'none'}"
                )
        self._record_publication()
        self._publish_metrics(result)

    def _record_publication(self) -> None:
        persistence = self.pilot.shell.runtime.persistence
        observation = (
            persistence.publication_attempts,
            persistence.publication_failures,
        )
        if observation == self._last_publication_observation:
            return
        previous_failures = self._last_publication_observation[1]
        status = "failed" if observation[1] > previous_failures else "updated"
        error = persistence.last_publication_error or "none"
        self._emit(
            f"{'PUBLICATION' if self._metrics_publisher is not None else 'RANKING'} "
            f"status={status} attempts={observation[0]} "
            f"failures={observation[1]} error={error}"
        )
        self._last_publication_observation = observation
        self._metrics_dirty = True

    def _record_schedule(self, result: ScheduleStepResult, now_ns: int) -> None:
        statuses = tuple(dispatch.status for dispatch in result.dispatches)
        accepted = statuses.count(DispatchStatus.ACCEPTED)
        backpressured = statuses.count(DispatchStatus.BACKPRESSURED)
        self._schedule_accepted += accepted
        self._schedule_backpressured += backpressured
        status = result.status
        previous_status = self._last_schedule_status
        self._last_schedule_status = status
        if accepted or backpressured or status != previous_status:
            self._metrics_dirty = True
        if result.plan_installed and status is not None:
            self._emit(
                "SCHEDULE event=plan-installed "
                f"day={_format_utc_day(status.day_start_ns)} "
                f"band={status.band} progress={status.community_progress} "
                f"flights={status.flight_count}"
            )
        if result.plan_expanded and status is not None:
            self._emit(
                "SCHEDULE event=plan-expanded "
                f"day={_format_utc_day(status.day_start_ns)} "
                f"flights={status.flight_count} cursor={status.next_index}"
            )
        if result.plan_replanned and status is not None:
            self._emit("SCHEDULE event=bread-replanned "
                f"base=24 bread={len(active_channel_breads(self.scheduling.runtime.state, now_ns))} "
                f"flights={status.flight_count} next={_format_utc_ns(status.next_deadline_ns)}")
        if backpressured:
            self._emit(
                "SCHEDULE event=backpressured "
                f"accepted={accepted} backpressured={backpressured}"
            )
        if status is not None:
            runtime_deadline_ns = (
                status.next_deadline_ns
                if result.next_deadline_ns is None
                else result.next_deadline_ns
            )
            actions = tuple(
                (action.action_id, action.item_id, action.due_at_ns)
                for action in self.scheduling.runtime.state.scheduled_actions
            )
            breads = tuple(effect.effect_id for effect in
                           active_channel_breads(self.scheduling.runtime.state, now_ns))
            schedule = self.scheduling.runtime.state.daily_schedule
            channel_items_fingerprint = (actions, breads,
                None if schedule is None else (schedule.day_start_ns, schedule.deadlines_ns))
            if channel_items_fingerprint != self._last_channel_items_fingerprint:
                reason = (
                    "startup"
                    if self._last_channel_items_fingerprint is None
                    else "channel-items-change"
                )
                self._emit(
                    f"DUCKPLANNING reason={reason} "
                    f"next={_format_utc_ns(status.next_deadline_ns)} "
                    f"wake={_format_utc_ns(runtime_deadline_ns)} "
                    f"actions={len(actions)} bread={len(breads)}"
                )
                self._last_channel_items_fingerprint = channel_items_fingerprint
        for dispatch in result.dispatches:
            if dispatch.status is not DispatchStatus.ACCEPTED or dispatch.transition is None:
                continue
            transition = dispatch.transition
            for outcome in transition.outcomes:
                if outcome.kind is OutcomeKind.FLIGHT_STARTED:
                    kind = "unknown" if outcome.flight_kind is None else outcome.flight_kind.value
                    if outcome.channel_effect_count:
                        self._emit("BREAD event=flight-delay "
                            f"pieces={outcome.channel_effect_count} extra_seconds={outcome.effect_magnitude} "
                            f"flight_id={outcome.flight_id}")
                    self._emit(
                        "SCHEDULE event=flight-started "
                        f"kind={kind} deadline={_format_optional_utc(result.attempted_deadline_ns)} "
                        f"lateness_ms={_milliseconds(result.lateness_ns)}"
                    )
                elif outcome.kind is OutcomeKind.FLIGHT_EXPIRED:
                    ended_at_ns = (
                        transition.state.now_ns
                        if transition.state.last_flight is None
                        else transition.state.last_flight.ended_at_ns
                    )
                    self._emit(
                        "FLIGHT event=expired "
                        f"flight_id={outcome.flight_id or 0} at={_format_utc_ns(ended_at_ns)}"
                    )
            skipped = tuple(
                deadline
                for outcome in transition.outcomes
                if outcome.kind is OutcomeKind.SCHEDULED_FLIGHT_SKIPPED
                for deadline in outcome.skipped_deadlines_ns
            )
            if skipped:
                self._emit(
                    "SCHEDULE event=flight-skipped "
                    f"count={len(skipped)} reason={result.skip_reason or 'unspecified'} "
                    f"first={_format_utc_ns(skipped[0])} last={_format_utc_ns(skipped[-1])} "
                    f"lateness_ms={_milliseconds(result.lateness_ns)}"
                )
        if not self._debug_enabled or status is None:
            return
        runtime_deadline_ns = (
            status.next_deadline_ns
            if result.next_deadline_ns is None
            else result.next_deadline_ns
        )
        pending_actions = len(self.scheduling.runtime.state.scheduled_actions)
        bread_count = len(active_channel_breads(self.scheduling.runtime.state, now_ns))
        fingerprint = (
            status.day_start_ns,
            status.flight_count,
            status.next_index,
            status.next_deadline_ns,
            runtime_deadline_ns,
            pending_actions,
            bread_count,
            status.recommended_flight_count,
            status.flight_active,
        )
        changed = fingerprint != self._last_schedule_fingerprint
        heartbeat_due = self._last_schedule_report_ns is None or (
            now_ns - self._last_schedule_report_ns >= self._schedule_heartbeat_ns
        )
        if not changed and not heartbeat_due:
            return
        self._emit(
            "DEBUG SCHEDULE "
            f"reason={'change' if changed else 'heartbeat'} "
            f"day={_format_utc_day(status.day_start_ns)} band={status.band} "
            f"progress={status.community_progress} flights={status.flight_count} "
            f"recommended={status.recommended_flight_count} "
            f"cursor={status.next_index}/{status.flight_count} "
            f"next={_format_utc_ns(status.next_deadline_ns)} "
            f"wake={_format_utc_ns(runtime_deadline_ns)} "
            f"actions={pending_actions} bread={bread_count} "
            f"flight={'active' if status.flight_active else 'none'} "
            f"accepted_total={self._schedule_accepted} "
            f"backpressured_total={self._schedule_backpressured} "
            f"commands_total={self._bridge_dispatched} "
            f"ignored_total={self._bridge_ignored} "
            f"network_failures={self._network_failures}"
        )
        self._last_schedule_fingerprint = fingerprint
        self._last_schedule_report_ns = now_ns

    def _publish_metrics(self, result: ProcessShellResult) -> None:
        publisher = self._metrics_publisher
        now_ns = self._last_now_ns
        started_at_ns = self._started_at_ns
        if publisher is None or now_ns is None or started_at_ns is None:
            return
        heartbeat_due = self._last_metrics_report_ns is None or (
            now_ns - self._last_metrics_report_ns >= self._metrics_heartbeat_ns
        )
        if not self._metrics_dirty and not heartbeat_due:
            return
        schedule = self._last_schedule_status
        persistence = self.pilot.shell.runtime.persistence
        snapshot = RuntimeMetricsSnapshot(
            generated_at_ns=now_ns,
            started_at_ns=started_at_ns,
            process_state=result.state.value,
            transport_state=result.network.state.value,
            connected=result.network.connected,
            ready_entries=self._ready_entries,
            bridge_dispatched=self._bridge_dispatched,
            bridge_invalid=self._bridge_invalid,
            bridge_ignored=self._bridge_ignored,
            schedule_accepted=self._schedule_accepted,
            schedule_backpressured=self._schedule_backpressured,
            network_failures=self._network_failures,
            persistence_pending=persistence.pending_count,
            state_publication_attempts=persistence.publication_attempts,
            state_publication_failures=persistence.publication_failures,
            metrics_publication_attempts=self._metrics_publication_attempts,
            metrics_publication_failures=self._metrics_publication_failures,
            schedule_flight_count=0 if schedule is None else schedule.flight_count,
            schedule_next_index=0 if schedule is None else schedule.next_index,
            schedule_next_deadline_ns=(
                0 if schedule is None else schedule.next_deadline_ns
            ),
            schedule_community_progress=(
                0 if schedule is None else schedule.community_progress
            ),
            schedule_recommended_flight_count=(
                0 if schedule is None else schedule.recommended_flight_count
            ),
        )
        self._metrics_publication_attempts += 1
        try:
            publisher(snapshot, self.pilot.shell.runtime.state)
        except Exception as error:
            self._metrics_publication_failures += 1
            self._emit(
                "METRICS status=failed "
                f"attempts={self._metrics_publication_attempts} "
                f"failures={self._metrics_publication_failures} "
                f"error={type(error).__name__}"
            )
        self._last_metrics_report_ns = now_ns
        self._metrics_dirty = False

    def _emit(self, message: str) -> None:
        if self._observer is not None:
            self._observer(message)

    def _now_ns(self) -> int:
        value = (
            self._clock.now_ns()
            if isinstance(self._clock, SystemRuntimeClock)
            else self._clock()
        )
        if type(value) is not int or value < 0:
            raise RuntimeError("operator runner clock returned an invalid timestamp")
        if self._last_now_ns is not None and value < self._last_now_ns:
            raise RuntimeError("operator runner clock moved backwards")
        self._last_now_ns = value
        return value

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("operator runner is owned by one event-loop thread")


def _format_utc_ns(value_ns: int) -> str:
    seconds, nanoseconds = divmod(value_ns, 1_000_000_000)
    value = datetime.fromtimestamp(seconds, UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanoseconds // 1_000_000:03d}Z"


def _format_optional_utc(value_ns: int | None) -> str:
    return "none" if value_ns is None else _format_utc_ns(value_ns)


def _format_utc_day(value_ns: int) -> str:
    return _format_utc_ns(value_ns)[:10]


def _milliseconds(value_ns: int | None) -> str:
    return "none" if value_ns is None else str(value_ns // 1_000_000)
