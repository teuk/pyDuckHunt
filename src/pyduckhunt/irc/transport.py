"""Process-neutral IRC connection state machine with explicit side effects."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from pyduckhunt.identity import rfc1459_casefold, same_irc_name
from pyduckhunt.irc.message import (
    IRCMessage,
    IRCProtocolError,
    parse_irc_line,
    render_irc_message,
    render_pong,
)


NANOSECONDS_PER_SECOND = 1_000_000_000
_CONNECTED_STATES = frozenset(
    (
        "registering",
        "joining",
        "ready",
        "stopping",
    )
)
_APPLICATION_COMMANDS = frozenset(("PRIVMSG", "NOTICE", "TAGMSG"))
_MEMBERSHIP_COMMANDS = frozenset(("JOIN", "PART", "QUIT", "NICK", "KICK", "353", "366"))


class IRCTransportState(str, Enum):
    NEW = "new"
    CONNECTING = "connecting"
    REGISTERING = "registering"
    JOINING = "joining"
    READY = "ready"
    BACKOFF = "backoff"
    STOPPING = "stopping"
    STOPPED = "stopped"


class IRCTransportActionKind(str, Enum):
    CONNECT = "connect"
    SEND = "send"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class IRCTransportAction:
    kind: IRCTransportActionKind
    wire: bytes | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, IRCTransportActionKind):
            raise ValueError("IRC transport action kind is invalid")
        if self.kind is IRCTransportActionKind.CONNECT:
            if self.wire is not None or self.reason is not None:
                raise ValueError("connect action cannot carry payload")
        elif self.kind is IRCTransportActionKind.SEND:
            if type(self.wire) is not bytes or self.reason is not None:
                raise ValueError("send action requires wire bytes only")
            if not self.wire.endswith(b"\r\n"):
                raise IRCProtocolError("outgoing IRC action must end with CRLF")
            parse_irc_line(self.wire)
        else:
            if self.wire is not None:
                raise ValueError("close action cannot carry wire bytes")
            _validate_reason(self.reason)

    @classmethod
    def connect(cls) -> IRCTransportAction:
        return cls(IRCTransportActionKind.CONNECT)

    @classmethod
    def send(cls, wire: bytes) -> IRCTransportAction:
        return cls(IRCTransportActionKind.SEND, wire=wire)

    @classmethod
    def close(cls, reason: str) -> IRCTransportAction:
        return cls(IRCTransportActionKind.CLOSE, reason=reason)


@dataclass(frozen=True, slots=True)
class IRCTransportStep:
    actions: tuple[IRCTransportAction, ...] = ()
    messages: tuple[IRCMessage, ...] = ()

    def __post_init__(self) -> None:
        if type(self.actions) is not tuple or any(
            not isinstance(action, IRCTransportAction) for action in self.actions
        ):
            raise ValueError("IRC transport actions must be an immutable tuple")
        if type(self.messages) is not tuple or any(
            not isinstance(message, IRCMessage) for message in self.messages
        ):
            raise ValueError("IRC transport messages must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class IRCTransportPolicy:
    nickname: str
    fallback_nickname: str
    username: str
    realname: str
    channels: tuple[str, ...]
    reconnect_delays_ns: tuple[int, ...] = (
        NANOSECONDS_PER_SECOND,
        5 * NANOSECONDS_PER_SECOND,
        30 * NANOSECONDS_PER_SECOND,
    )
    handshake_timeout_ns: int = 30 * NANOSECONDS_PER_SECOND
    idle_timeout_ns: int = 180 * NANOSECONDS_PER_SECOND
    stop_timeout_ns: int = 5 * NANOSECONDS_PER_SECOND
    server_password: str | None = field(default=None, repr=False)
    bot_mode: bool = False

    def __post_init__(self) -> None:
        _validate_token(self.nickname, "nickname")
        _validate_token(self.fallback_nickname, "fallback nickname")
        if same_irc_name(self.nickname, self.fallback_nickname):
            raise ValueError("fallback nickname must be distinct")
        _validate_token(self.username, "username")
        if type(self.realname) is not str or not self.realname:
            raise ValueError("realname must be a non-empty string")
        if type(self.channels) is not tuple or not self.channels:
            raise ValueError("channels must be a non-empty immutable tuple")
        if type(self.bot_mode) is not bool:
            raise ValueError("bot mode flag must be a truth value")
        canonical_channels: set[str] = set()
        for channel in self.channels:
            _validate_channel(channel)
            canonical = rfc1459_casefold(channel)
            if canonical in canonical_channels:
                raise ValueError("channels must be unique under IRC casemapping")
            canonical_channels.add(canonical)
        if self.server_password is not None:
            _validate_secret(self.server_password)
        if type(self.reconnect_delays_ns) is not tuple or not self.reconnect_delays_ns:
            raise ValueError("reconnect delays must be a non-empty immutable tuple")
        for delay in self.reconnect_delays_ns:
            _validate_positive_integer(delay, "reconnect delay")
        _validate_positive_integer(self.handshake_timeout_ns, "handshake timeout")
        _validate_positive_integer(self.idle_timeout_ns, "idle timeout")
        _validate_positive_integer(self.stop_timeout_ns, "stop timeout")

        render_irc_message("NICK", (self.nickname,))
        render_irc_message("NICK", (self.fallback_nickname,))
        if self.server_password is not None:
            render_irc_message("PASS", (self.server_password,))
        render_irc_message("USER", (self.username, "0", "*", self.realname))
        if self.bot_mode:
            render_irc_message("MODE", (self.nickname, "+B"))
            render_irc_message("MODE", (self.fallback_nickname, "+B"))
        for channel in self.channels:
            render_irc_message("JOIN", (channel,))


class IRCTransport:
    """Drive one IRC session from a single event-loop thread."""

    def __init__(self, policy: IRCTransportPolicy) -> None:
        if not isinstance(policy, IRCTransportPolicy):
            raise ValueError("IRC transport requires a validated policy")
        self.policy = policy
        self._state = IRCTransportState.NEW
        self._nickname = policy.nickname
        self._joined: set[str] = set()
        self._reconnect_index = 0
        self._reconnect_at_ns: int | None = None
        self._deadline_ns: int | None = None
        self._last_receive_ns: int | None = None
        self._last_now_ns: int | None = None
        self._owner_thread = threading.get_ident()

    @property
    def state(self) -> IRCTransportState:
        return self._state

    @property
    def nickname(self) -> str:
        return self._nickname

    @property
    def joined_channels(self) -> tuple[str, ...]:
        return tuple(
            channel
            for channel in self.policy.channels
            if rfc1459_casefold(channel) in self._joined
        )

    @property
    def reconnect_at_ns(self) -> int | None:
        return self._reconnect_at_ns

    @property
    def deadline_ns(self) -> int | None:
        return self._deadline_ns

    def start(self, now_ns: int) -> IRCTransportStep:
        self._ensure_owner()
        if self._state is not IRCTransportState.NEW:
            raise RuntimeError("IRC transport can only start once")
        self._accept_now(now_ns)
        self._state = IRCTransportState.CONNECTING
        return IRCTransportStep((IRCTransportAction.connect(),))

    def connected(self, now_ns: int) -> IRCTransportStep:
        self._ensure_owner()
        if self._state is not IRCTransportState.CONNECTING:
            raise RuntimeError("IRC connection was not requested")
        self._accept_now(now_ns)
        self._state = IRCTransportState.REGISTERING
        self._nickname = self.policy.nickname
        self._joined.clear()
        self._reconnect_at_ns = None
        self._deadline_ns = now_ns + self.policy.handshake_timeout_ns
        self._last_receive_ns = now_ns
        registration: list[IRCTransportAction] = []
        if self.policy.server_password is not None:
            registration.append(
                IRCTransportAction.send(
                    render_irc_message("PASS", (self.policy.server_password,))
                )
            )
        registration.extend(
            (
                IRCTransportAction.send(
                    render_irc_message("NICK", (self._nickname,))
                ),
                IRCTransportAction.send(
                    render_irc_message(
                        "USER",
                        (self.policy.username, "0", "*", self.policy.realname),
                    )
                ),
            )
        )
        return IRCTransportStep(
            tuple(registration)
        )

    def receive(self, now_ns: int, line: str | bytes) -> IRCTransportStep:
        self._ensure_owner()
        message = parse_irc_line(line)
        if self._state.value not in _CONNECTED_STATES:
            raise RuntimeError("IRC input arrived without an active connection")
        if message.command == "001" and self._state is IRCTransportState.REGISTERING:
            if not message.params or not same_irc_name(
                message.params[0], self._nickname
            ):
                raise IRCProtocolError(
                    "welcome nickname does not match registration"
                )
        self._accept_now(now_ns)
        self._last_receive_ns = now_ns

        if message.command == "PING":
            return IRCTransportStep((IRCTransportAction.send(render_pong(message)),))
        if message.command == "ERROR":
            if self._state is IRCTransportState.STOPPING:
                self._finish_stop()
                return IRCTransportStep(
                    (IRCTransportAction.close("server closed during shutdown"),)
                )
            return self._begin_backoff(now_ns, "server error")
        if message.command == "433" and self._state is IRCTransportState.REGISTERING:
            return self._nickname_unavailable(now_ns)
        if message.command == "001" and self._state is IRCTransportState.REGISTERING:
            return self._welcome(now_ns, message)
        if message.command == "JOIN":
            return self._joined_channel(message)
        if message.command == "KICK":
            return self._kicked(now_ns, message)
        if self._state in (IRCTransportState.JOINING, IRCTransportState.READY) and (
            message.command in _MEMBERSHIP_COMMANDS
        ):
            return IRCTransportStep(messages=(message,))
        if self._state is IRCTransportState.READY and (
            message.command in _APPLICATION_COMMANDS
        ):
            return IRCTransportStep(messages=(message,))
        return IRCTransportStep()

    def connection_lost(self, now_ns: int, reason: str) -> IRCTransportStep:
        self._ensure_owner()
        _validate_reason(reason)
        current_state = self._state
        if current_state not in (
            IRCTransportState.BACKOFF,
            IRCTransportState.STOPPING,
            IRCTransportState.CONNECTING,
            IRCTransportState.REGISTERING,
            IRCTransportState.JOINING,
            IRCTransportState.READY,
        ):
            raise RuntimeError("IRC connection loss is out of sequence")
        self._accept_now(now_ns)
        if current_state is IRCTransportState.BACKOFF:
            return IRCTransportStep()
        if current_state is IRCTransportState.STOPPING:
            self._finish_stop()
            return IRCTransportStep()
        return self._schedule_backoff(now_ns)

    def tick(self, now_ns: int) -> IRCTransportStep:
        self._ensure_owner()
        self._accept_now(now_ns)
        if (
            self._state is IRCTransportState.BACKOFF
            and self._reconnect_at_ns is not None
            and now_ns >= self._reconnect_at_ns
        ):
            self._state = IRCTransportState.CONNECTING
            self._nickname = self.policy.nickname
            self._reconnect_at_ns = None
            return IRCTransportStep((IRCTransportAction.connect(),))
        if self._state in (IRCTransportState.REGISTERING, IRCTransportState.JOINING):
            if self._deadline_ns is not None and now_ns >= self._deadline_ns:
                return self._begin_backoff(now_ns, "handshake timeout")
        if self._state is IRCTransportState.READY:
            assert self._last_receive_ns is not None
            if now_ns - self._last_receive_ns >= self.policy.idle_timeout_ns:
                return self._begin_backoff(now_ns, "idle timeout")
        if (
            self._state is IRCTransportState.STOPPING
            and self._deadline_ns is not None
            and now_ns >= self._deadline_ns
        ):
            self._finish_stop()
            return IRCTransportStep(
                (IRCTransportAction.close("graceful shutdown timeout"),)
            )
        return IRCTransportStep()

    def stop(self, now_ns: int, reason: str = "shutdown") -> IRCTransportStep:
        self._ensure_owner()
        _validate_reason(reason)
        self._accept_now(now_ns)
        if self._state in (IRCTransportState.NEW, IRCTransportState.BACKOFF):
            self._finish_stop()
            return IRCTransportStep()
        if self._state is IRCTransportState.CONNECTING:
            self._finish_stop()
            return IRCTransportStep((IRCTransportAction.close(reason),))
        if self._state in (
            IRCTransportState.REGISTERING,
            IRCTransportState.JOINING,
            IRCTransportState.READY,
        ):
            self._state = IRCTransportState.STOPPING
            self._deadline_ns = now_ns + self.policy.stop_timeout_ns
            self._reconnect_at_ns = None
            return IRCTransportStep(
                (IRCTransportAction.send(render_irc_message("QUIT", (reason,))),)
            )
        if self._state in (IRCTransportState.STOPPING, IRCTransportState.STOPPED):
            return IRCTransportStep()
        raise RuntimeError("IRC transport cannot stop from its current state")

    def send_application(self, wires: tuple[bytes, ...]) -> IRCTransportStep:
        """Validate one immutable application batch while the session is ready."""

        self._ensure_owner()
        if self._state is not IRCTransportState.READY:
            raise RuntimeError("IRC application output requires a ready session")
        if type(wires) is not tuple:
            raise ValueError("IRC application output must be an immutable tuple")
        actions = tuple(IRCTransportAction.send(wire) for wire in wires)
        return IRCTransportStep(actions)

    def _nickname_unavailable(self, now_ns: int) -> IRCTransportStep:
        if same_irc_name(self._nickname, self.policy.nickname):
            self._nickname = self.policy.fallback_nickname
            return IRCTransportStep(
                (
                    IRCTransportAction.send(
                        render_irc_message("NICK", (self._nickname,))
                    ),
                )
            )
        return self._begin_backoff(now_ns, "nicknames unavailable")

    def _welcome(self, now_ns: int, message: IRCMessage) -> IRCTransportStep:
        self._state = IRCTransportState.JOINING
        self._deadline_ns = now_ns + self.policy.handshake_timeout_ns
        registration: list[IRCTransportAction] = []
        if self.policy.bot_mode:
            registration.append(
                IRCTransportAction.send(
                    render_irc_message("MODE", (self._nickname, "+B"))
                )
            )
        registration.extend(
            IRCTransportAction.send(render_irc_message("JOIN", (channel,)))
            for channel in self.policy.channels
        )
        return IRCTransportStep(
            tuple(registration)
        )

    def _joined_channel(self, message: IRCMessage) -> IRCTransportStep:
        if self._state not in (IRCTransportState.JOINING, IRCTransportState.READY):
            return IRCTransportStep()
        if message.nickname is None or not same_irc_name(message.nickname, self._nickname):
            return IRCTransportStep(messages=(message,))
        if not message.params:
            return IRCTransportStep()
        canonical = rfc1459_casefold(message.params[0])
        expected = {rfc1459_casefold(channel) for channel in self.policy.channels}
        if canonical not in expected:
            return IRCTransportStep()
        self._joined.add(canonical)
        if self._joined == expected:
            self._state = IRCTransportState.READY
            self._deadline_ns = None
            self._reconnect_index = 0
        return IRCTransportStep(messages=(message,))

    def _kicked(self, now_ns: int, message: IRCMessage) -> IRCTransportStep:
        if self._state is not IRCTransportState.READY or len(message.params) < 2:
            return IRCTransportStep()
        channel, target = message.params[:2]
        canonical = rfc1459_casefold(channel)
        if canonical not in self._joined or not same_irc_name(target, self._nickname):
            return IRCTransportStep(messages=(message,))
        self._joined.remove(canonical)
        self._state = IRCTransportState.JOINING
        self._deadline_ns = now_ns + self.policy.handshake_timeout_ns
        return IRCTransportStep(
            (IRCTransportAction.send(render_irc_message("JOIN", (channel,))),),
            (message,),
        )

    def _begin_backoff(self, now_ns: int, reason: str) -> IRCTransportStep:
        step = self._schedule_backoff(now_ns)
        return IRCTransportStep((IRCTransportAction.close(reason),), step.messages)

    def _schedule_backoff(self, now_ns: int) -> IRCTransportStep:
        delay_index = min(
            self._reconnect_index,
            len(self.policy.reconnect_delays_ns) - 1,
        )
        delay = self.policy.reconnect_delays_ns[delay_index]
        if self._reconnect_index < len(self.policy.reconnect_delays_ns) - 1:
            self._reconnect_index += 1
        self._state = IRCTransportState.BACKOFF
        self._joined.clear()
        self._deadline_ns = None
        self._last_receive_ns = None
        self._reconnect_at_ns = now_ns + delay
        return IRCTransportStep()

    def _finish_stop(self) -> None:
        self._state = IRCTransportState.STOPPED
        self._joined.clear()
        self._reconnect_at_ns = None
        self._deadline_ns = None
        self._last_receive_ns = None

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("IRC transport timestamp must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("IRC transport clock cannot move backwards")
        self._last_now_ns = now_ns

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("IRC transport is owned by one event-loop thread")


def _validate_positive_integer(value: object, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _validate_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.startswith(":")
        or any(character in value for character in (" ", ",", "\x00", "\r", "\n"))
    ):
        raise ValueError(f"{label} is not a safe IRC token")


def _validate_channel(value: object) -> None:
    _validate_token(value, "channel")
    assert isinstance(value, str)
    if not value.startswith(("#", "&")):
        raise ValueError("channel must start with # or &")


def _validate_secret(value: object) -> None:
    if type(value) is not str or not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ValueError("IRC server password must be a safe non-empty string")


def _validate_reason(value: object) -> None:
    if type(value) is not str or not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ValueError("IRC close reason must be a safe non-empty string")
    assert isinstance(value, str)
    render_irc_message("QUIT", (value,))
