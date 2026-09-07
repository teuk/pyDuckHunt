"""Incrementally frame strict IRC byte streams without opening a socket."""

from __future__ import annotations

from pyduckhunt.irc.message import IRCProtocolError, MAX_WIRE_BYTES


class IRCLineBuffer:
    """Collect arbitrary byte chunks and return complete CRLF-terminated lines."""

    def __init__(self) -> None:
        self._pending = b""

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    def feed(self, chunk: bytes) -> tuple[bytes, ...]:
        if type(chunk) is not bytes:
            raise ValueError("IRC stream chunks must be bytes")
        if not chunk:
            return ()

        candidate = self._pending + chunk
        framed: list[bytes] = []
        while True:
            ending = candidate.find(b"\r\n")
            if ending < 0:
                break
            line = candidate[: ending + 2]
            if len(line) > MAX_WIRE_BYTES:
                raise IRCProtocolError("IRC line exceeds 512 wire bytes")
            if line == b"\r\n":
                raise IRCProtocolError("IRC line is empty")
            framed.append(line)
            candidate = candidate[ending + 2 :]

        for index, value in enumerate(candidate):
            if value == 10:
                raise IRCProtocolError("IRC stream contains a bare line feed")
            if value == 13 and index != len(candidate) - 1:
                raise IRCProtocolError("IRC stream contains an embedded carriage return")

        maximum_pending = MAX_WIRE_BYTES - 2
        if len(candidate) > maximum_pending:
            incomplete_crlf = (
                len(candidate) == maximum_pending + 1 and candidate.endswith(b"\r")
            )
            if not incomplete_crlf:
                raise IRCProtocolError("unterminated IRC line exceeds 512 wire bytes")

        self._pending = candidate
        return tuple(framed)

    def reset(self) -> None:
        self._pending = b""
