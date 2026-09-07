"""Atomic Prometheus text snapshots with bounded-cardinality observations."""

from __future__ import annotations

import os
import stat
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pyduckhunt.game.model import FlightKind, GameState, LastFlightConclusion
from pyduckhunt.game.progression import available_experience
from pyduckhunt.version import __version__


MAX_METRICS_PAGE_BYTES = 256 * 1024
_PROCESS_STATES = ("new", "running", "stopping", "stopped", "failed")
_TRANSPORT_STATES = (
    "new",
    "connecting",
    "registering",
    "joining",
    "ready",
    "backoff",
    "stopping",
    "stopped",
)


@dataclass(frozen=True, slots=True)
class RuntimeMetricsSnapshot:
    """One privacy-safe runtime observation emitted by the owner loop."""

    generated_at_ns: int
    started_at_ns: int
    process_state: str
    transport_state: str
    connected: bool
    ready_entries: int
    bridge_dispatched: int
    bridge_invalid: int
    bridge_ignored: int
    schedule_accepted: int
    schedule_backpressured: int
    network_failures: int
    persistence_pending: int
    state_publication_attempts: int
    state_publication_failures: int
    metrics_publication_attempts: int
    metrics_publication_failures: int
    schedule_flight_count: int = 0
    schedule_next_index: int = 0
    schedule_next_deadline_ns: int = 0
    schedule_community_progress: int = 0
    schedule_recommended_flight_count: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.generated_at_ns) is not int
            or type(self.started_at_ns) is not int
            or self.generated_at_ns < 0
            or not 0 <= self.started_at_ns <= self.generated_at_ns
        ):
            raise ValueError("metrics timestamps are invalid")
        if self.process_state not in _PROCESS_STATES:
            raise ValueError("metrics process state is invalid")
        if self.transport_state not in _TRANSPORT_STATES:
            raise ValueError("metrics transport state is invalid")
        if type(self.connected) is not bool:
            raise ValueError("metrics connection state must be a truth value")
        for name in (
            "ready_entries",
            "bridge_dispatched",
            "bridge_invalid",
            "bridge_ignored",
            "schedule_accepted",
            "schedule_backpressured",
            "network_failures",
            "persistence_pending",
            "state_publication_attempts",
            "state_publication_failures",
            "metrics_publication_attempts",
            "metrics_publication_failures",
            "schedule_flight_count",
            "schedule_next_index",
            "schedule_next_deadline_ns",
            "schedule_community_progress",
            "schedule_recommended_flight_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"metrics {name} must be a non-negative integer")
        if self.schedule_next_index > self.schedule_flight_count:
            raise ValueError("metrics schedule cursor is invalid")
        if self.state_publication_failures > self.state_publication_attempts:
            raise ValueError("metrics state publication counters are inconsistent")
        if self.metrics_publication_failures > self.metrics_publication_attempts:
            raise ValueError("metrics publication counters are inconsistent")


class StatePublicationError(RuntimeError):
    """One or more independent best-effort state publishers failed."""


class StatePublisherFanout:
    """Run every configured publisher even when an earlier one fails."""

    def __init__(self, publishers: tuple[Callable[[GameState], None], ...]) -> None:
        if type(publishers) is not tuple or not publishers or any(
            not callable(publisher) for publisher in publishers
        ):
            raise ValueError("state publisher fanout requires immutable callables")
        self.publishers = publishers

    def publish(self, state: GameState) -> None:
        if not isinstance(state, GameState):
            raise ValueError("state publisher fanout requires a game state")
        failures: list[str] = []
        for publisher in self.publishers:
            try:
                publisher(state)
            except Exception as error:
                failures.append(type(error).__name__)
        if failures:
            raise StatePublicationError("state publisher fanout failed")


class PrometheusMetricsPublisher:
    """Merge durable and runtime facts into one atomic text snapshot."""

    def __init__(self, path: str | Path) -> None:
        target = Path(path)
        if (
            not target.is_absolute()
            or target == Path("/")
            or target.name in ("", ".", "..")
            or target.suffix.casefold() != ".prom"
            or ".." in target.parts
        ):
            raise ValueError("metrics target must be a safe absolute .prom path")
        self.path = target
        self._lock = threading.Lock()
        self._state: GameState | None = None
        self._runtime: RuntimeMetricsSnapshot | None = None

    def publish_state(self, state: GameState) -> None:
        if not isinstance(state, GameState):
            raise ValueError("metrics publisher requires a game state")
        with self._lock:
            self._state = state
            if self._runtime is not None:
                self._write_locked()

    def publish_runtime(
        self,
        snapshot: RuntimeMetricsSnapshot,
        state: GameState,
    ) -> None:
        if not isinstance(snapshot, RuntimeMetricsSnapshot):
            raise ValueError("metrics publisher requires a runtime snapshot")
        if not isinstance(state, GameState):
            raise ValueError("metrics publisher requires a game state")
        with self._lock:
            self._runtime = snapshot
            self._state = state
            self._write_locked()

    def _write_locked(self) -> None:
        assert self._state is not None
        assert self._runtime is not None
        encoded = render_prometheus_metrics(self._state, self._runtime)
        if len(encoded) > MAX_METRICS_PAGE_BYTES:
            raise ValueError("metrics page exceeds the bounded size")
        parent = self.path.parent
        _validate_publish_directory(parent)
        _validate_existing_target(self.path)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.fchmod(handle.fileno(), 0o644)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def render_prometheus_metrics(
    state: GameState,
    runtime: RuntimeMetricsSnapshot,
) -> bytes:
    """Render aggregate metrics only; player identities never become labels."""

    if not isinstance(state, GameState) or not isinstance(
        runtime,
        RuntimeMetricsSnapshot,
    ):
        raise ValueError("Prometheus rendering requires state and runtime metrics")

    players = state.players
    values = {
        "players": len(players),
        "hits": sum(player.hits for player in players),
        "golden_hits": sum(player.golden_hits for player in players),
        "misses": sum(player.misses for player in players),
        "wild_shots": sum(player.wild_shots for player in players),
        "empty_shots": sum(player.empty_shots for player in players),
        "jammed_shots": sum(player.jammed_shots for player in players),
        "confiscations": sum(player.confiscations for player in players),
        "incidents": sum(player.incidents_caused for player in players),
        "deaths": sum(player.deaths for player in players),
        "available_experience": sum(available_experience(player) for player in players),
    }
    best_time_ms = min(
        (player.best_time_ms for player in players if player.best_time_ms is not None),
        default=0,
    )

    lines = [
        "# pyDuckHunt aggregate metrics; player identities are intentionally absent.",
        _sample("pyduckhunt_build_info", 1, labels={"version": __version__}),
        _sample(
            "pyduckhunt_metrics_generated_timestamp_seconds",
            _seconds(runtime.generated_at_ns),
        ),
        _sample(
            "pyduckhunt_process_started_timestamp_seconds",
            _seconds(runtime.started_at_ns),
        ),
        _sample("pyduckhunt_durable_state_timestamp_seconds", _seconds(state.now_ns)),
        _sample("pyduckhunt_irc_connected", int(runtime.connected)),
        _sample("pyduckhunt_irc_ready", int(runtime.transport_state == "ready")),
        _sample("pyduckhunt_ready_entries_total", runtime.ready_entries),
        _sample("pyduckhunt_commands_dispatched_total", runtime.bridge_dispatched),
        _sample("pyduckhunt_commands_invalid_total", runtime.bridge_invalid),
        _sample("pyduckhunt_messages_ignored_total", runtime.bridge_ignored),
        _sample("pyduckhunt_schedule_dispatches_total", runtime.schedule_accepted),
        _sample(
            "pyduckhunt_schedule_backpressure_total",
            runtime.schedule_backpressured,
        ),
        _sample("pyduckhunt_network_failures_total", runtime.network_failures),
        _sample("pyduckhunt_persistence_pending", runtime.persistence_pending),
        _sample(
            "pyduckhunt_state_publication_attempts_total",
            runtime.state_publication_attempts,
        ),
        _sample(
            "pyduckhunt_state_publication_failures_total",
            runtime.state_publication_failures,
        ),
        _sample(
            "pyduckhunt_metrics_publication_attempts_total",
            runtime.metrics_publication_attempts,
        ),
        _sample(
            "pyduckhunt_metrics_publication_failures_total",
            runtime.metrics_publication_failures,
        ),
        _sample("pyduckhunt_players", values["players"]),
        _sample("pyduckhunt_hits_total", values["hits"]),
        _sample("pyduckhunt_golden_hits_total", values["golden_hits"]),
        _sample("pyduckhunt_misses_total", values["misses"]),
        _sample("pyduckhunt_wild_shots_total", values["wild_shots"]),
        _sample("pyduckhunt_empty_shots_total", values["empty_shots"]),
        _sample("pyduckhunt_jammed_shots_total", values["jammed_shots"]),
        _sample("pyduckhunt_confiscations_total", values["confiscations"]),
        _sample("pyduckhunt_incidents_total", values["incidents"]),
        _sample("pyduckhunt_deaths_total", values["deaths"]),
        _sample("pyduckhunt_available_experience", values["available_experience"]),
        _sample("pyduckhunt_best_time_seconds", best_time_ms / 1000),
        _sample("pyduckhunt_flights_started_total", state.next_flight_id - 1),
        _sample("pyduckhunt_flight_active", int(state.flight is not None)),
        _sample("pyduckhunt_active_effects", len(state.effects)),
        _sample("pyduckhunt_active_curses", len(state.curses)),
        _sample("pyduckhunt_scheduled_actions", len(state.scheduled_actions)),
        _sample("pyduckhunt_schedule_flights", runtime.schedule_flight_count),
        _sample("pyduckhunt_schedule_next_index", runtime.schedule_next_index),
        _sample(
            "pyduckhunt_schedule_next_deadline_timestamp_seconds",
            _seconds(runtime.schedule_next_deadline_ns),
        ),
        _sample(
            "pyduckhunt_community_progress",
            runtime.schedule_community_progress,
        ),
        _sample(
            "pyduckhunt_recommended_daily_flights",
            runtime.schedule_recommended_flight_count,
        ),
    ]
    lines.extend(
        _sample(
            "pyduckhunt_process_state",
            int(runtime.process_state == candidate),
            labels={"state": candidate},
        )
        for candidate in _PROCESS_STATES
    )
    lines.extend(
        _sample(
            "pyduckhunt_transport_state",
            int(runtime.transport_state == candidate),
            labels={"state": candidate},
        )
        for candidate in _TRANSPORT_STATES
    )
    lines.extend(
        _sample(
            "pyduckhunt_active_flight_kind",
            int(state.flight is not None and state.flight.kind is candidate),
            labels={"kind": candidate.value},
        )
        for candidate in FlightKind
    )
    lines.extend(
        _sample(
            "pyduckhunt_last_flight_conclusion",
            int(
                state.last_flight is not None
                and state.last_flight.conclusion is candidate
            ),
            labels={"conclusion": candidate.value},
        )
        for candidate in LastFlightConclusion
    )
    lines.append("")
    return "\n".join(lines).encode("ascii")


def _sample(
    name: str,
    value: int | float,
    *,
    labels: dict[str, str] | None = None,
) -> str:
    suffix = ""
    if labels:
        encoded = ",".join(
            f'{key}="{_escape_label(label)}"' for key, label in sorted(labels.items())
        )
        suffix = "{" + encoded + "}"
    return f"{name}{suffix} {_number(value)}"


def _number(value: int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Prometheus sample value must be numeric")
    if isinstance(value, int):
        return str(value)
    return format(value, ".9g")


def _seconds(value_ns: int) -> float:
    return value_ns / 1_000_000_000


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _validate_publish_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("metrics parent must be a real directory")
    details = path.stat()
    if details.st_mode & 0o022:
        raise ValueError("metrics parent must not be group/world writable")


def _validate_existing_target(path: Path) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("metrics target must be one regular file")
    if details.st_mode & 0o022:
        raise ValueError("metrics target must not be group/world writable")
