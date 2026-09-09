"""Validated bridge from ready IRC messages to replayable game intents."""

from __future__ import annotations

from pyduckhunt.i18n import validate_language, tr, localized, localized_method

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pyduckhunt.game.commands import (
    Command,
    CommandKind,
    CommandSyntaxError,
    parse_command,
    validate_command,
)
from pyduckhunt.game.model import GameState, OutcomeKind, Transition
from pyduckhunt.identity import rfc1459_casefold, same_irc_name
from pyduckhunt.irc.message import IRCMessage
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.public_url import normalize_ranking_url, normalize_shop_url
from pyduckhunt.rendering.responses import (
    MAX_RESPONSE_LINES,
    render_outcomes,
    render_query,
    render_wire_notice,
    render_wire_response,
)
from pyduckhunt.runtime.orchestrator import DispatchResult, RuntimeOrchestrator


@dataclass(frozen=True, slots=True)
class IRCCommandContext:
    """Exact application facts presented to the injected settlement boundary."""

    now_ns: int
    nickname: str
    channel: str
    command: Command

    def __post_init__(self) -> None:
        if type(self.now_ns) is not int or self.now_ns < 0:
            raise ValueError("command context time must be a non-negative integer")
        if type(self.nickname) is not str or not self.nickname:
            raise ValueError("command context nickname must not be empty")
        if type(self.channel) is not str or not self.channel.startswith(("#", "&")):
            raise ValueError("command context channel is invalid")
        if not isinstance(self.command, Command):
            raise ValueError("command context requires a parsed command")


EventResolver = Callable[[GameState, IRCCommandContext], ReplayEvent]
LastFlightProvider = Callable[[GameState, int], int | None]


class EventResolutionError(ValueError):
    """One safe public rejection from the settlement boundary."""

    def __init__(self, public_message: str) -> None:
        if (
            type(public_message) is not str
            or not public_message
            or len(public_message) > 240
            or any(character in public_message for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("resolution rejection message is invalid")
        self.public_message = public_message
        super().__init__("command settlement was rejected")


class BridgeStatus(str, Enum):
    IGNORED = "ignored"
    INVALID = "invalid"
    DISPATCHED = "dispatched"


@dataclass(frozen=True, slots=True)
class BridgeResult:
    status: BridgeStatus
    command: Command | None = None
    dispatch: DispatchResult | None = None
    priority_batch: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, BridgeStatus):
            raise ValueError("bridge result status is invalid")
        if self.command is not None and not isinstance(self.command, Command):
            raise ValueError("bridge result command is invalid")
        if self.dispatch is not None and not isinstance(self.dispatch, DispatchResult):
            raise ValueError("bridge dispatch result is invalid")
        if type(self.priority_batch) is not tuple or any(
            type(wire) is not bytes for wire in self.priority_batch
        ):
            raise ValueError("bridge priority batch must be immutable wire bytes")


class IRCGameBridge:
    """Own command parsing, settlement validation, rendering and dispatch."""

    def __init__(
        self,
        runtime: RuntimeOrchestrator,
        channels: tuple[str, ...],
        event_resolver: EventResolver,
        *,
        last_flight_provider: LastFlightProvider | None = None,
        language: str = "fr",
        shop_url: str | None = None,
        ranking_url: str | None = None,
        statistics_excluded_nicknames: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(runtime, RuntimeOrchestrator):
            raise ValueError("IRC game bridge requires a runtime orchestrator")
        if type(channels) is not tuple or not channels:
            raise ValueError("IRC game bridge requires immutable channels")
        canonical: set[str] = set()
        for channel in channels:
            if (
                type(channel) is not str
                or not channel.startswith(("#", "&"))
                or any(character in channel for character in (" ", "\x00", "\r", "\n"))
            ):
                raise ValueError("IRC game bridge channel is invalid")
            folded = rfc1459_casefold(channel)
            if folded in canonical:
                raise ValueError("IRC game bridge channels must be unique")
            canonical.add(folded)
        if not callable(event_resolver):
            raise ValueError("IRC game bridge requires an event resolver")
        if last_flight_provider is not None and not callable(last_flight_provider):
            raise ValueError("last-flight provider must be callable")
        normalized_shop_url = normalize_shop_url(shop_url)
        normalized_ranking_url = normalize_ranking_url(ranking_url)
        self.language = validate_language(language)
        self.runtime = runtime
        self.channels = channels
        self._canonical_channels = frozenset(canonical)
        self._event_resolver = event_resolver
        self._last_flight_provider = last_flight_provider
        self._shop_url = normalized_shop_url
        self._ranking_url = normalized_ranking_url
        self._statistics_excluded_nicknames = statistics_excluded_nicknames
        self._last_now_ns: int | None = None
        self._owner_thread = threading.get_ident()

    @localized_method
    def handle(self, now_ns: int, message: IRCMessage) -> BridgeResult:
        """Handle one ready transport message without reading clocks or entropy."""

        self._ensure_owner()
        self._accept_now(now_ns)
        if not isinstance(message, IRCMessage):
            raise ValueError("IRC game bridge requires a parsed IRC message")
        if (
            message.command != "PRIVMSG"
            or message.nickname is None
            or len(message.params) != 2
            or rfc1459_casefold(message.params[0]) not in self._canonical_channels
        ):
            return BridgeResult(BridgeStatus.IGNORED)

        nickname = message.nickname
        channel, text = message.params
        command = parse_command(text)
        if command is None:
            return BridgeResult(BridgeStatus.IGNORED)
        try:
            validate_command(command)
        except CommandSyntaxError as error:
            batch = _render_command_response(
                command,
                nickname,
                channel,
                (f"{nickname} > {error}",),
            )
            self.runtime.emit_priority(batch)
            return BridgeResult(
                BridgeStatus.INVALID,
                command=command,
                priority_batch=batch,
            )

        context = IRCCommandContext(now_ns, nickname, channel, command)
        try:
            event = self._event_resolver(self.runtime.state, context)
        except EventResolutionError as error:
            batch = _render_command_response(
                command,
                nickname,
                channel,
                (f"{nickname} > {error.public_message}",),
            )
            self.runtime.emit_priority(batch)
            return BridgeResult(
                BridgeStatus.INVALID,
                command=command,
                priority_batch=batch,
            )
        _validate_resolved_event(context, event)

        def renderer(transition: Transition) -> tuple[bytes, ...]:
            elapsed = None
            if (
                command.kind is CommandKind.LAST_FLIGHT
                and self._last_flight_provider is not None
            ):
                elapsed = self._last_flight_provider(transition.state, now_ns)
                if elapsed is not None and (type(elapsed) is not int or elapsed < 0):
                    raise ValueError(
                        tr('last-flight provider must return non-negative integer or None')
                    )
            lines = _render_transition(
                transition,
                context,
                elapsed,
                self._shop_url,
                self._ranking_url,
                self._statistics_excluded_nicknames,
            )
            return _render_command_response(command, nickname, channel, lines)

        busy = _render_command_response(
            command,
            nickname,
            channel,
            (tr('{0} > Service occupé ; réessaie dans un instant.', nickname),),
        )
        dispatch = self.runtime.dispatch(
            event,
            renderer,
            backpressure_response=busy,
        )
        return BridgeResult(
            BridgeStatus.DISPATCHED,
            command=command,
            dispatch=dispatch,
            priority_batch=dispatch.priority_batch,
        )

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("IRC game bridge time must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("IRC game bridge clock cannot move backwards")
        self._last_now_ns = now_ns

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("IRC game bridge is owned by one event-loop thread")


def _validate_resolved_event(
    context: IRCCommandContext,
    event: ReplayEvent,
) -> None:
    if not isinstance(event, ReplayEvent):
        raise ValueError("command resolver must return a replay event")
    if event.now_ns != context.now_ns or event.nickname is None or not same_irc_name(
        event.nickname,
        context.nickname,
    ):
        raise ValueError("resolved event differs from the IRC command identity")

    command = context.command
    if command.kind is CommandKind.SHOP and command.arguments:
        expected_target = command.arguments[1] if len(command.arguments) == 2 else None
        target_matches = (
            event.target_nickname is None
            if expected_target is None
            else event.target_nickname is not None
            and same_irc_name(event.target_nickname, expected_target)
        )
        if (
            event.kind is not EventKind.RUNTIME_PURCHASE
            or event.item_id != int(command.arguments[0])
            or not target_matches
        ):
            raise ValueError("resolved purchase differs from the parsed shop command")
        return

    if (
        event.kind is not EventKind.RUNTIME_COMMAND
        or event.command_kind is not command.kind
        or event.invoked_as != command.invoked_as
        or event.arguments != command.arguments
    ):
        raise ValueError("resolved command differs from the parsed IRC command")


def _render_command_response(
    command: Command,
    nickname: str,
    channel: str,
    lines: tuple[str, ...],
) -> tuple[bytes, ...]:
    private_query = command.kind in (CommandKind.STATS, CommandKind.INVENTORY) or (
        command.kind is CommandKind.SHOP and not command.arguments
    )
    if private_query:
        return render_wire_notice(nickname, lines)
    if command.kind in (CommandKind.SHOT, CommandKind.RANK) and len(lines) > 1:
        return tuple(
            wire
            for line in lines
            for wire in render_wire_response(channel, (line,))
        )
    return render_wire_response(channel, lines)


def _render_transition(
    transition: Transition,
    context: IRCCommandContext,
    last_flight_elapsed_ns: int | None,
    shop_url: str | None,
    ranking_url: str | None,
    statistics_excluded_nicknames: tuple[str, ...],
) -> tuple[str, ...]:
    query = any(outcome.kind is OutcomeKind.QUERY for outcome in transition.outcomes)
    visible = render_outcomes(
        tuple(
            outcome
            for outcome in transition.outcomes
            if outcome.kind is not OutcomeKind.QUERY
        ),
        channel=context.channel,
    )
    query_lines = (
        render_query(
            transition.state,
            context.nickname,
            context.command,
            last_flight_elapsed_ns=last_flight_elapsed_ns,
            shop_url=shop_url,
            ranking_url=ranking_url,
            statistics_excluded_nicknames=statistics_excluded_nicknames,
            channel=context.channel,
        )
        if query
        else ()
    )
    lines = visible + query_lines
    if len(lines) <= MAX_RESPONSE_LINES:
        return lines
    retained = lines[: MAX_RESPONSE_LINES - 1]
    omitted = len(lines) - len(retained)
    return retained + (tr('\x0314[+{0} événements]\x0f', omitted),)
