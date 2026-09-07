"""In-memory IRC peer for transport integration tests."""

from __future__ import annotations

from pyduckhunt.irc import (
    IRCLineBuffer,
    IRCMessage,
    IRCTransport,
    IRCTransportActionKind,
    IRCTransportStep,
    parse_irc_line,
)


class FakeIRCServer:
    """Drive a transport with synthetic chunks and record client effects."""

    def __init__(self, transport: IRCTransport, *, now_ns: int = 0) -> None:
        if not isinstance(transport, IRCTransport):
            raise ValueError("fake IRC server requires a transport")
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("fake IRC server timestamp must be non-negative")
        self.transport = transport
        self.now_ns = now_ns
        self.framer = IRCLineBuffer()
        self.connect_requests = 0
        self.close_reasons: list[str] = []
        self.client_wire: list[bytes] = []
        self.client_messages: list[IRCMessage] = []
        self.application_messages: list[IRCMessage] = []
        self.connected = False

    def start(self) -> None:
        self._apply(self.transport.start(self.now_ns))

    def accept(self) -> None:
        self.connected = True
        self._apply(self.transport.connected(self.now_ns))

    def send_chunk(self, chunk: bytes) -> None:
        for line in self.framer.feed(chunk):
            self._apply(self.transport.receive(self.now_ns, line))

    def send_line(self, line: str) -> None:
        if type(line) is not str or "\r" in line or "\n" in line:
            raise ValueError("fake IRC line must be unterminated text")
        self.send_chunk((line + "\r\n").encode())

    def drop(self, reason: str = "synthetic disconnect") -> None:
        self.connected = False
        self.framer.reset()
        self._apply(self.transport.connection_lost(self.now_ns, reason))

    def advance(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < self.now_ns:
            raise ValueError("fake IRC server clock cannot move backwards")
        self.now_ns = now_ns
        self._apply(self.transport.tick(now_ns))

    def stop(self, reason: str = "test shutdown") -> None:
        self._apply(self.transport.stop(self.now_ns, reason))

    def _apply(self, step: IRCTransportStep) -> None:
        self.application_messages.extend(step.messages)
        for action in step.actions:
            if action.kind is IRCTransportActionKind.CONNECT:
                self.connect_requests += 1
            elif action.kind is IRCTransportActionKind.SEND:
                assert action.wire is not None
                self.client_wire.append(action.wire)
                self.client_messages.append(parse_irc_line(action.wire))
            else:
                assert action.reason is not None
                self.connected = False
                self.close_reasons.append(action.reason)
