"""Strict preflight and explicit foreground launch for a development pilot."""

from __future__ import annotations

import os
import signal
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pyduckhunt.configuration import (
    ApplicationConfiguration,
    ProcessConfiguration,
    load_application_configuration,
    resolve_irc_server_password,
)
from pyduckhunt.irc.socket_adapter import IRCEndpoint, IRCSocketConnector
from pyduckhunt.publishing import (
    PrometheusMetricsPublisher,
    RankingPagePublisher,
    StatePublisherFanout,
)
from pyduckhunt.rendering.flight_appearance import RandomizedFlightAppearanceSource
from pyduckhunt.runtime.pilot import (
    DevelopmentPilotGate,
    authorize_development_pilot,
    build_development_pilot,
)
from pyduckhunt.runtime.process import ProcessShellResult, ProcessShellState
from pyduckhunt.runtime.incidents import CalibratedIncidentSource, IRCChannelRoster
from pyduckhunt.runtime.runner import (
    OperatorPilotRunner,
    PilotControl,
    PilotTelemetry,
    Sleeper,
)
from pyduckhunt.runtime.scheduling import (
    CalibratedScheduleSource,
    RuntimeSchedulingAdapter,
    SystemRuntimeClock,
)
from pyduckhunt.runtime.settlement import (
    CalibratedEventResolver,
    IntegerSource,
    SystemIntegerSource,
)


@dataclass(frozen=True, slots=True)
class OperatorPilotPlan:
    """One validated, side-effect-free live-pilot plan."""

    configuration_path: Path
    configuration: ApplicationConfiguration
    gate: DevelopmentPilotGate
    confirmation: str
    password_configured: bool

    def __post_init__(self) -> None:
        if not self.configuration_path.is_absolute():
            raise ValueError("operator configuration path must be absolute")
        if not isinstance(self.configuration, ApplicationConfiguration):
            raise ValueError("operator plan configuration is invalid")
        if not isinstance(self.gate, DevelopmentPilotGate) or not self.gate.armed:
            raise ValueError("operator plan requires an armed development gate")
        if type(self.confirmation) is not str or not self.confirmation:
            raise ValueError("operator confirmation must be non-empty text")
        if type(self.password_configured) is not bool:
            raise ValueError("operator password state must be a truth value")

    @property
    def target(self) -> str:
        endpoint = self.configuration.irc.endpoint()
        scheme = "ircs" if endpoint.tls else "irc"
        host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
        channels = ",".join(self.configuration.irc.channels)
        return f"{scheme}://{host}:{endpoint.port}/{channels}"


@dataclass(frozen=True, slots=True)
class OperatorPilotResult:
    """Terminal foreground-pilot result plus its public operator transcript."""

    process: ProcessShellResult
    log_path: Path
    application_log_path: Path
    telemetry: PilotTelemetry

    def __post_init__(self) -> None:
        if not isinstance(self.process, ProcessShellResult):
            raise ValueError("operator result requires a process result")
        if not isinstance(self.log_path, Path) or not self.log_path.is_absolute():
            raise ValueError("operator result log path must be absolute")
        if not isinstance(self.application_log_path, Path) or not self.application_log_path.is_absolute():
            raise ValueError("operator result application log path must be absolute")
        if not isinstance(self.telemetry, PilotTelemetry):
            raise ValueError("operator result telemetry is invalid")


def prepare_operator_pilot(
    configuration_path: str | Path,
    allowed_endpoint: IRCEndpoint,
    allowed_channels: tuple[str, ...],
    environment: Mapping[str, str],
) -> OperatorPilotPlan:
    """Validate an exact live target without creating files or opening a stream."""

    if not isinstance(allowed_endpoint, IRCEndpoint):
        raise ValueError("operator preflight requires an allowed IRC endpoint")
    if type(allowed_channels) is not tuple or not allowed_channels:
        raise ValueError("operator preflight requires immutable allowed channels")
    if not isinstance(environment, Mapping):
        raise ValueError("operator preflight requires an environment mapping")

    requested_path = Path(configuration_path)
    if requested_path.is_symlink():
        raise ValueError("operator configuration cannot be a symbolic link")
    try:
        resolved_path = requested_path.resolve(strict=True)
    except OSError as error:
        raise ValueError("operator configuration file cannot be resolved") from error
    if not resolved_path.is_file():
        raise ValueError("operator configuration path is not a regular file")

    configuration = load_application_configuration(resolved_path)
    runtime = ProcessConfiguration(
        configuration.runtime.log_level,
        _resolve_runtime_directory(
            configuration.runtime.state_directory,
            resolved_path.parent,
            "state",
        ),
        _resolve_runtime_directory(
            configuration.runtime.log_directory,
            resolved_path.parent,
            "log",
        ),
        configuration.runtime.ranking_page_path,
        configuration.runtime.metrics_page_path,
    )
    configuration = replace(configuration, runtime=runtime)
    _require_separate_directories(runtime.state_directory, runtime.log_directory)

    gate = DevelopmentPilotGate(True, allowed_endpoint, allowed_channels)
    authorize_development_pilot(configuration, gate)
    password = resolve_irc_server_password(configuration.irc, environment)
    configuration.irc.transport_policy(server_password=password)
    target = _target_label(configuration)
    return OperatorPilotPlan(
        resolved_path,
        configuration,
        gate,
        f"CONNECT {target} AS {configuration.irc.nickname}",
        password is not None,
    )


def run_operator_pilot(
    plan: OperatorPilotPlan,
    confirmation: str,
    environment: Mapping[str, str],
    *,
    connector: IRCSocketConnector | None = None,
    control: PilotControl | None = None,
    clock: SystemRuntimeClock | Callable[[], int] | None = None,
    sleeper: Sleeper = time.sleep,
    integer_source: IntegerSource | None = None,
) -> OperatorPilotResult:
    """Run one explicitly confirmed pilot in the foreground until bounded stop."""

    if not isinstance(plan, OperatorPilotPlan):
        raise ValueError("operator launch requires a validated plan")
    if type(confirmation) is not str or confirmation != plan.confirmation:
        raise RuntimeError("live pilot confirmation does not match the exact target")
    if not isinstance(environment, Mapping):
        raise ValueError("operator launch requires an environment mapping")
    if control is not None and not isinstance(control, PilotControl):
        raise ValueError("operator launch control is invalid")
    if integer_source is not None and not callable(integer_source):
        raise ValueError("operator launch integer source is invalid")

    refreshed = prepare_operator_pilot(
        plan.configuration_path,
        plan.gate.endpoint,
        plan.gate.channels,
        environment,
    )
    if refreshed != plan:
        raise RuntimeError("operator pilot plan changed after preflight")
    _validate_directory_target(plan.configuration.runtime.state_directory, "state")
    _validate_directory_target(plan.configuration.runtime.log_directory, "log")
    log_path, log_handle, application_log_path, application_log_handle = _open_operator_logs(
        plan.configuration.runtime.log_directory
    )
    handles = (log_handle, application_log_handle)
    with log_handle, application_log_handle:
        _write_logs(handles, f"START target={plan.target}")
        _write_logs(
            handles,
            f"CONFIG path={plan.configuration_path} password={'yes' if plan.password_configured else 'no'}",
        )
        _write_logs(
            handles,
            f"LOGGING level={plan.configuration.runtime.log_level} application={application_log_path}",
        )
        _write_logs(
            handles,
            "PARTYLINE "
            f"enabled={'yes' if plan.configuration.partyline.enabled else 'no'} "
            f"bind={plan.configuration.partyline.bind_host} "
            f"port={plan.configuration.partyline.port} "
            f"dcc={'yes' if plan.configuration.partyline.dcc_public_ip else 'no'}",
        )
        selected_integers = integer_source or SystemIntegerSource()
        roster = IRCChannelRoster(
            plan.configuration.irc.channels,
            (
                plan.configuration.irc.nickname,
                plan.configuration.irc.fallback_nickname,
            ),
        )
        resolver = CalibratedEventResolver(
            selected_integers,
            roster.present,
            incident_source=CalibratedIncidentSource(
                selected_integers,
                roster,
                observer=lambda message: _observe_pilot(handles, message),
            ),
        )
        ranking_publisher = (
            None
            if plan.configuration.runtime.ranking_page_path is None
            else RankingPagePublisher(
                plan.configuration.runtime.ranking_page_path,
                excluded_nicknames=(
                    plan.configuration.game.statistics_excluded_nicknames
                ),
            )
        )
        metrics_publisher = (
            None
            if plan.configuration.runtime.metrics_page_path is None
            else PrometheusMetricsPublisher(
                plan.configuration.runtime.metrics_page_path,
                excluded_nicknames=(
                    plan.configuration.game.statistics_excluded_nicknames
                ),
            )
        )
        publishers = tuple(
            publisher
            for publisher in (
                None if ranking_publisher is None else ranking_publisher.publish,
                None if metrics_publisher is None else metrics_publisher.publish_state,
            )
            if publisher is not None
        )
        state_publisher = (
            None if not publishers else StatePublisherFanout(publishers).publish
        )
        pilot = None
        try:
            pilot = build_development_pilot(
                plan.configuration,
                plan.gate,
                environment,
                resolver,
                connector=connector,
                state_publisher=state_publisher,
                partyline_observer=lambda message: _observe_pilot(handles, message),
                partyline_integer_source=selected_integers,
                message_observer=roster.observe,
            )
            scheduling = RuntimeSchedulingAdapter(
                pilot.shell.runtime,
                plan.configuration.irc.channels,
                CalibratedScheduleSource(selected_integers),
                anti_cheat=plan.configuration.game.anti_cheat,
                flight_appearance_source=(
                    RandomizedFlightAppearanceSource(selected_integers)
                    if plan.configuration.game.anti_cheat
                    else None
                ),
            )
            _write_logs(
                handles,
                f"RECOVERED sequence={pilot.recovered.last_sequence}",
            )
            def observe_runtime(message: str) -> None:
                _observe_pilot(handles, message)
                if pilot is not None and pilot.shell.partyline is not None:
                    pilot.shell.partyline.observe_runtime(message)

            runner = OperatorPilotRunner(
                pilot,
                scheduling,
                clock=clock,
                sleeper=sleeper,
                observer=observe_runtime,
                debug_enabled=plan.configuration.runtime.log_level == "DEBUG",
                metrics_publisher=(
                    None
                    if metrics_publisher is None
                    else metrics_publisher.publish_runtime
                ),
            )
            process = runner.run(control or PilotControl())
            telemetry = runner.telemetry
        except BaseException as error:
            _write_logs(handles, f"FAILED category={type(error).__name__}")
            if pilot is not None and pilot.shell.state is ProcessShellState.NEW:
                pilot.shell.stop(pilot.recovered.state.now_ns, "launch failure")
            raise
        _write_logs(
            handles,
            "SUMMARY "
            f"ready={'yes' if telemetry.ready_observed else 'no'} "
            f"ready_entries={telemetry.ready_entries} "
            f"bridge_dispatched={telemetry.bridge_dispatched} "
            f"bridge_invalid={telemetry.bridge_invalid} "
            f"bridge_ignored={telemetry.bridge_ignored} "
            f"schedule_accepted={telemetry.schedule_accepted} "
            f"schedule_backpressured={telemetry.schedule_backpressured} "
            f"network_failures={telemetry.network_failures}",
        )
        _write_logs(
            handles,
            f"STOP state={process.state.value} failure={process.failure or 'none'}",
        )
    return OperatorPilotResult(process, log_path, application_log_path, telemetry)


def run_service_pilot(
    plan: OperatorPilotPlan,
    confirmation: str,
    environment: Mapping[str, str],
    *,
    connector: IRCSocketConnector | None = None,
    clock: SystemRuntimeClock | Callable[[], int] | None = None,
    sleeper: Sleeper = time.sleep,
    integer_source: IntegerSource | None = None,
) -> OperatorPilotResult:
    """Run an authorized pilot with bounded SIGINT and SIGTERM handling."""

    if not isinstance(plan, OperatorPilotPlan):
        raise ValueError("service launch requires a validated operator plan")
    if type(confirmation) is not str or confirmation != plan.confirmation:
        raise RuntimeError("live service confirmation does not match the exact target")
    if not isinstance(environment, Mapping):
        raise ValueError("service launch requires an environment mapping")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("service signals can only be owned by the main thread")

    control = PilotControl()
    previous_handlers: list[tuple[signal.Signals, object]] = []

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        control.request_stop("service stop")

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers.append((signum, signal.signal(signum, request_stop)))
        return run_operator_pilot(
            plan,
            confirmation,
            environment,
            connector=connector,
            control=control,
            clock=clock,
            sleeper=sleeper,
            integer_source=integer_source,
        )
    finally:
        for signum, previous in reversed(previous_handlers):
            signal.signal(signum, previous)


def _resolve_runtime_directory(path: Path, base: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else base / path
    absolute = Path(os.path.abspath(candidate))
    _validate_directory_target(absolute, label)
    return absolute


def _target_label(configuration: ApplicationConfiguration) -> str:
    endpoint = configuration.irc.endpoint()
    scheme = "ircs" if endpoint.tls else "irc"
    host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
    channels = ",".join(configuration.irc.channels)
    return f"{scheme}://{host}:{endpoint.port}/{channels}"


def _validate_directory_target(path: Path, label: str) -> None:
    if not path.is_absolute() or path == Path("/"):
        raise ValueError(f"operator {label} directory must be a safe absolute path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"operator {label} directory cannot cross a symbolic link")
        if current.exists() and not current.is_dir():
            raise ValueError(f"operator {label} directory crosses a non-directory")
    existing = path
    while not existing.exists():
        existing = existing.parent
    if not os.access(existing, os.R_OK | os.W_OK | os.X_OK):
        raise ValueError(f"operator {label} directory is not accessible")


def _require_separate_directories(state: Path, logs: Path) -> None:
    if state == logs or state in logs.parents or logs in state.parents:
        raise ValueError("operator state and log directories must be separate")


def _open_operator_logs(directory: Path):
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    _validate_directory_target(directory, "log")
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"pilot_{stamp}.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    os.fchmod(descriptor, 0o644)
    application_path = directory / "pyduckhunt.log"
    application_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_CLOEXEC"):
        application_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        application_flags |= os.O_NOFOLLOW
    application_descriptor = None
    try:
        application_descriptor = os.open(application_path, application_flags, 0o644)
        application_stat = os.fstat(application_descriptor)
        if not stat.S_ISREG(application_stat.st_mode) or application_stat.st_nlink != 1:
            raise ValueError("application log must be one regular file")
        os.fchmod(application_descriptor, 0o644)
    except BaseException:
        if application_descriptor is not None:
            os.close(application_descriptor)
        os.close(descriptor)
        raise
    return (
        path,
        os.fdopen(descriptor, "w", encoding="utf-8"),
        application_path,
        os.fdopen(application_descriptor, "a", encoding="utf-8"),
    )


def _write_logs(handles: tuple[object, ...], message: str) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f UTC")
    for handle in handles:
        handle.write(f"{timestamp} {message}\n")
        handle.flush()


def _observe_pilot(handles: tuple[object, ...], message: str) -> None:
    _write_logs(handles, message)
    print(f"[LIVE] {message}", flush=True)
