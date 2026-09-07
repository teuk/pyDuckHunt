"""TCP/TLS and non-blocking wire adapters for the IRC transport."""

from __future__ import annotations

import socket
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pyduckhunt.irc.message import IRCMessage, IRCProtocolError
from pyduckhunt.irc.stream import IRCLineBuffer
from pyduckhunt.irc.transport import (
    IRCTransport,
    IRCTransportActionKind,
    IRCTransportState,
    IRCTransportStep,
)


@runtime_checkable
class IRCByteStream(Protocol):
    """Minimum connected-stream surface required by the wire adapter."""

    def recv(self, size: int) -> bytes: ...

    def send(self, data: bytes | memoryview) -> int: ...

    def setblocking(self, flag: bool) -> None: ...

    def close(self) -> None: ...


Dialer = Callable[[tuple[str, int], float], IRCByteStream]
TLSContextFactory = Callable[[], ssl.SSLContext]


@dataclass(frozen=True, slots=True)
class IRCEndpoint:
    host: str
    port: int
    tls: bool
    connect_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or not self.host
            or len(self.host) > 253
            or any(character.isspace() for character in self.host)
            or any(character in self.host for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("IRC endpoint host is invalid")
        if type(self.port) is not int or not 1 <= self.port <= 65_535:
            raise ValueError("IRC endpoint port must be between 1 and 65535")
        if type(self.tls) is not bool:
            raise ValueError("IRC endpoint TLS flag must be a truth value")
        if (
            type(self.connect_timeout_seconds) not in (int, float)
            or self.connect_timeout_seconds <= 0
        ):
            raise ValueError("IRC connect timeout must be positive")


class IRCSocketConnector:
    """Open one verified TCP stream and optionally wrap it in client TLS."""

    def __init__(
        self,
        endpoint: IRCEndpoint,
        *,
        dialer: Dialer = socket.create_connection,
        tls_context_factory: TLSContextFactory = ssl.create_default_context,
    ) -> None:
        if not isinstance(endpoint, IRCEndpoint):
            raise ValueError("IRC socket connector requires an endpoint")
        if not callable(dialer) or not callable(tls_context_factory):
            raise ValueError("IRC socket connector factories must be callable")
        self.endpoint = endpoint
        self._dialer = dialer
        self._tls_context_factory = tls_context_factory

    def open(self) -> IRCByteStream:
        """Open a stream; the caller owns and must close the returned object."""

        stream: IRCByteStream | None = None
        try:
            stream = self._dialer(
                (self.endpoint.host, self.endpoint.port),
                float(self.endpoint.connect_timeout_seconds),
            )
            _validate_stream(stream)
            if self.endpoint.tls:
                context = self._tls_context_factory()
                if not isinstance(context, ssl.SSLContext) and not callable(
                    getattr(context, "wrap_socket", None)
                ):
                    raise ValueError("TLS context factory returned an invalid context")
                stream = context.wrap_socket(
                    stream,
                    server_hostname=self.endpoint.host,
                )
                _validate_stream(stream)
            stream.setblocking(False)
            return stream
        except Exception:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise


@dataclass(frozen=True, slots=True)
class IRCAdapterResult:
    messages: tuple[IRCMessage, ...]
    state: IRCTransportState
    connected: bool
    pending_output_bytes: int
    failure: str | None = None


class IRCSocketAdapter:
    """Execute transport actions against one non-blocking connected stream."""

    def __init__(
        self,
        transport: IRCTransport,
        connector: IRCSocketConnector,
        *,
        receive_bytes: int = 4096,
        max_reads_per_poll: int = 16,
        max_pending_output_bytes: int = 8192,
    ) -> None:
        if not isinstance(transport, IRCTransport):
            raise ValueError("IRC socket adapter requires a transport")
        if not isinstance(connector, IRCSocketConnector):
            raise ValueError("IRC socket adapter requires a connector")
        _validate_positive_integer(receive_bytes, "receive byte count")
        _validate_positive_integer(max_reads_per_poll, "read count")
        _validate_positive_integer(max_pending_output_bytes, "output byte limit")
        if max_pending_output_bytes < 512:
            raise ValueError("IRC output byte limit must hold one complete wire line")
        self.transport = transport
        self.connector = connector
        self._receive_bytes = receive_bytes
        self._max_reads_per_poll = max_reads_per_poll
        self._max_pending_output_bytes = max_pending_output_bytes
        self._stream: IRCByteStream | None = None
        self._framer = IRCLineBuffer()
        self._pending_output = bytearray()
        self._owner_thread = threading.get_ident()
        self._failure: str | None = None
        self._last_now_ns: int | None = None

    @property
    def connected(self) -> bool:
        return self._stream is not None

    @property
    def pending_output_bytes(self) -> int:
        return len(self._pending_output)

    def start(self, now_ns: int) -> IRCAdapterResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        self._failure = None
        messages = self._apply_step(now_ns, self.transport.start(now_ns))
        self._flush(now_ns)
        return self._result(messages)

    def poll(self, now_ns: int) -> IRCAdapterResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        self._failure = None
        messages: list[IRCMessage] = []
        self._flush(now_ns)
        if self._stream is not None:
            messages.extend(self._receive_available(now_ns))
        messages.extend(self._apply_step(now_ns, self.transport.tick(now_ns)))
        self._flush(now_ns)
        return self._result(messages)

    def stop(self, now_ns: int, reason: str = "shutdown") -> IRCAdapterResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        self._failure = None
        messages = self._apply_step(now_ns, self.transport.stop(now_ns, reason))
        self._flush(now_ns)
        return self._result(messages)

    def queue_application(self, wires: tuple[bytes, ...]) -> None:
        """Atomically reserve adapter output capacity for one priority batch."""

        self._ensure_owner()
        if self._stream is None:
            raise RuntimeError("IRC application output requires a connected stream")
        step = self.transport.send_application(wires)
        encoded = tuple(
            action.wire
            for action in step.actions
            if action.kind is IRCTransportActionKind.SEND
        )
        if any(wire is None for wire in encoded):  # pragma: no cover - action contract.
            raise RuntimeError("IRC application output action is incomplete")
        required = sum(len(wire) for wire in encoded if wire is not None)
        if len(self._pending_output) + required > self._max_pending_output_bytes:
            raise BufferError("IRC application output exceeds adapter capacity")
        for wire in encoded:
            assert wire is not None
            self._pending_output.extend(wire)

    def flush(self, now_ns: int) -> IRCAdapterResult:
        """Attempt pending writes without receiving or advancing transport timeouts."""

        self._ensure_owner()
        self._accept_now(now_ns)
        self._failure = None
        self._flush(now_ns)
        return self._result([])

    def _apply_step(self, now_ns: int, step: IRCTransportStep) -> list[IRCMessage]:
        messages = list(step.messages)
        for action in step.actions:
            if action.kind is IRCTransportActionKind.CONNECT:
                if self._stream is not None:
                    raise RuntimeError("IRC connect action found an open stream")
                try:
                    self._stream = self.connector.open()
                except Exception:
                    self._failure = "connect failed"
                    messages.extend(
                        self._apply_step(
                            now_ns,
                            self.transport.connection_lost(
                                now_ns,
                                "connection attempt failed",
                            ),
                        )
                    )
                    break
                self._framer.reset()
                messages.extend(
                    self._apply_step(now_ns, self.transport.connected(now_ns))
                )
            elif action.kind is IRCTransportActionKind.SEND:
                assert action.wire is not None
                if len(self._pending_output) + len(action.wire) > (
                    self._max_pending_output_bytes
                ):
                    self._fail_connection(now_ns, "outbound buffer full")
                    break
                self._pending_output.extend(action.wire)
            else:
                self._close_stream()
        return messages

    def _receive_available(self, now_ns: int) -> list[IRCMessage]:
        messages: list[IRCMessage] = []
        for _ in range(self._max_reads_per_poll):
            stream = self._stream
            if stream is None:
                break
            try:
                chunk = stream.recv(self._receive_bytes)
            except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                break
            except Exception:
                self._fail_connection(now_ns, "receive failed")
                break
            if type(chunk) is not bytes:
                self._fail_connection(now_ns, "receive contract failed")
                break
            if not chunk:
                self._fail_connection(now_ns, "peer closed connection")
                break
            try:
                lines = self._framer.feed(chunk)
                for line in lines:
                    messages.extend(
                        self._apply_step(now_ns, self.transport.receive(now_ns, line))
                    )
                    if self._stream is None:
                        break
            except IRCProtocolError:
                self._fail_connection(now_ns, "protocol error")
                break
        return messages

    def _flush(self, now_ns: int) -> None:
        while self._stream is not None and self._pending_output:
            try:
                sent = self._stream.send(bytes(self._pending_output))
            except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                return
            except Exception:
                self._fail_connection(now_ns, "send failed")
                return
            if type(sent) is not int or sent < 1 or sent > len(self._pending_output):
                self._fail_connection(now_ns, "send contract failed")
                return
            del self._pending_output[:sent]

    def _fail_connection(self, now_ns: int, reason: str) -> None:
        self._failure = reason
        self._close_stream()
        if self.transport.state not in (
            IRCTransportState.NEW,
            IRCTransportState.STOPPED,
        ):
            self._apply_step(now_ns, self.transport.connection_lost(now_ns, reason))

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        self._framer.reset()
        self._pending_output.clear()
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _result(self, messages: list[IRCMessage]) -> IRCAdapterResult:
        return IRCAdapterResult(
            tuple(messages),
            self.transport.state,
            self._stream is not None,
            len(self._pending_output),
            self._failure,
        )

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("IRC socket adapter is owned by one I/O thread")

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("IRC adapter timestamp must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("IRC adapter clock cannot move backwards")
        self._last_now_ns = now_ns


def _validate_stream(value: object) -> None:
    if not isinstance(value, IRCByteStream):
        raise ValueError("IRC connector returned an invalid byte stream")


def _validate_positive_integer(value: object, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"IRC {label} must be a positive integer")
