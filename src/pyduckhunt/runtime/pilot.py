"""Explicit target authorization and side-effect-bounded pilot composition."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass

from pyduckhunt.configuration import (
    ApplicationConfiguration,
    resolve_irc_server_password,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.message import IRCMessage
from pyduckhunt.irc.socket_adapter import IRCEndpoint, IRCSocketAdapter, IRCSocketConnector
from pyduckhunt.irc.transport import IRCTransport
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import ReplayResult
from pyduckhunt.persistence.snapshot import SnapshotStore
from pyduckhunt.partyline.runtime import PartylineController, PartylineObserver
from pyduckhunt.runtime.application import EventResolver, IRCGameBridge, LastFlightProvider
from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator
from pyduckhunt.runtime.persistence import StatePublisher
from pyduckhunt.runtime.process import ProcessShell


@dataclass(frozen=True, slots=True)
class DevelopmentPilotGate:
    """One explicit allowlist for a development endpoint and channel set."""

    armed: bool
    endpoint: IRCEndpoint
    channels: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.armed) is not bool:
            raise ValueError("pilot armed flag must be a truth value")
        if not isinstance(self.endpoint, IRCEndpoint):
            raise ValueError("pilot gate requires an IRC endpoint")
        canonical = _validated_channels(self.channels, "pilot gate")
        if len(set(canonical)) != len(canonical):
            raise ValueError("pilot gate channels must be unique")


@dataclass(frozen=True, slots=True)
class PilotAuthorization:
    endpoint: IRCEndpoint
    channels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, IRCEndpoint):
            raise ValueError("pilot authorization endpoint is invalid")
        _validated_channels(self.channels, "pilot authorization")


@dataclass(frozen=True, slots=True)
class PilotRuntime:
    authorization: PilotAuthorization
    shell: ProcessShell
    recovered: ReplayResult

    def __post_init__(self) -> None:
        if not isinstance(self.authorization, PilotAuthorization):
            raise ValueError("pilot runtime authorization is invalid")
        if not isinstance(self.shell, ProcessShell):
            raise ValueError("pilot runtime shell is invalid")
        if not isinstance(self.recovered, ReplayResult):
            raise ValueError("pilot runtime recovery result is invalid")


def authorize_development_pilot(
    configuration: ApplicationConfiguration,
    gate: DevelopmentPilotGate,
) -> PilotAuthorization:
    """Require both configuration activation and an exact injected allowlist."""

    if not isinstance(configuration, ApplicationConfiguration):
        raise ValueError("pilot authorization requires application configuration")
    if not isinstance(gate, DevelopmentPilotGate):
        raise ValueError("pilot authorization requires a development gate")
    if not configuration.game.enabled:
        raise RuntimeError("game activation is disabled by configuration")
    if not gate.armed:
        raise RuntimeError("development pilot gate is not armed")
    endpoint = configuration.irc.endpoint()
    if endpoint != gate.endpoint:
        raise RuntimeError("configured IRC endpoint differs from the pilot allowlist")
    configured_channels = tuple(
        rfc1459_casefold(channel) for channel in configuration.irc.channels
    )
    allowed_channels = tuple(rfc1459_casefold(channel) for channel in gate.channels)
    if configured_channels != allowed_channels:
        raise RuntimeError("configured IRC channels differ from the pilot allowlist")
    if endpoint.host.casefold() == "invalid" or endpoint.host.casefold().endswith(
        ".invalid"
    ):
        raise RuntimeError("placeholder IRC endpoint cannot be authorized")
    return PilotAuthorization(endpoint, configuration.irc.channels)


def build_development_pilot(
    configuration: ApplicationConfiguration,
    gate: DevelopmentPilotGate,
    environment: Mapping[str, str],
    event_resolver: EventResolver,
    *,
    connector: IRCSocketConnector | None = None,
    last_flight_provider: LastFlightProvider | None = None,
    persistence_capacity: int = 64,
    snapshot_interval: int | None = 128,
    state_publisher: StatePublisher | None = None,
    partyline_observer: PartylineObserver | None = None,
    partyline_integer_source: Callable[[int, int], int] | None = None,
    message_observer: Callable[[IRCMessage], None] | None = None,
) -> PilotRuntime:
    """Recover and compose a pilot shell without starting its IRC connection."""

    if not isinstance(configuration, ApplicationConfiguration):
        raise ValueError("pilot build requires application configuration")
    authorization = authorize_development_pilot(configuration, gate)
    if not callable(event_resolver):
        raise ValueError("pilot build requires an event resolver")
    endpoint = configuration.irc.endpoint()
    if (
        authorization.endpoint != endpoint
        or authorization.channels != configuration.irc.channels
        or not configuration.game.enabled
    ):
        raise RuntimeError("pilot authorization no longer matches configuration")
    server_password = resolve_irc_server_password(configuration.irc, environment)
    selected_connector = connector or IRCSocketConnector(endpoint)
    if selected_connector.endpoint != endpoint:
        raise ValueError("pilot connector endpoint differs from authorization")

    transport = IRCTransport(
        configuration.irc.transport_policy(server_password=server_password)
    )
    adapter = IRCSocketAdapter(transport, selected_connector)
    state_directory = configuration.runtime.state_directory
    runtime, recovered = RuntimeOrchestrator.open(
        JournalFile(state_directory / "events.jsonl"),
        SnapshotStore(state_directory / "snapshot.json"),
        adapter.queue_application,
        persistence_capacity=persistence_capacity,
        snapshot_interval=snapshot_interval,
        state_publisher=state_publisher,
    )
    try:
        bridge = IRCGameBridge(
            runtime,
            configuration.irc.channels,
            event_resolver,
            last_flight_provider=last_flight_provider,
            shop_url=configuration.game.shop_url,
            language=configuration.game.language,
            ranking_url=configuration.game.ranking_url,
            statistics_excluded_nicknames=(
                configuration.game.statistics_excluded_nicknames
            ),
        )
        partyline = (
            None
            if not configuration.partyline.enabled
            else PartylineController(
                configuration.partyline,
                runtime,
                state_directory,
                lambda: (
                    transport.nickname,
                    transport.state.value,
                    adapter.connected,
                    transport.joined_channels,
                ),
                observer=partyline_observer,
                flight_lifetime_ns=(
                    configuration.game.flight_lifetime_seconds * 1_000_000_000
                ),
                anti_cheat=configuration.game.anti_cheat,
                language=configuration.game.language,
                integer_source=partyline_integer_source,
                ranking_url=configuration.game.ranking_url,
                statistics_excluded_nicknames=(
                    configuration.game.statistics_excluded_nicknames
                ),
            )
        )
        shell = ProcessShell(
            runtime,
            bridge,
            adapter,
            enabled=True,
            partyline=partyline,
            message_observer=message_observer,
        )
    except Exception:
        runtime.close(5)
        raise
    return PilotRuntime(authorization, shell, recovered)


def _validated_channels(channels: object, label: str) -> tuple[str, ...]:
    if type(channels) is not tuple or not channels:
        raise ValueError(f"{label} channels must be a non-empty tuple")
    canonical: list[str] = []
    for channel in channels:
        if (
            type(channel) is not str
            or not channel.startswith(("#", "&"))
            or any(character in channel for character in (" ", "\x00", "\r", "\n"))
        ):
            raise ValueError(f"{label} channel is invalid")
        canonical.append(rfc1459_casefold(channel))
    return tuple(canonical)
