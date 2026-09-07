from __future__ import annotations

import socket
import unittest

from pyduckhunt.irc import (
    IRCEndpoint,
    IRCSocketAdapter,
    IRCSocketConnector,
    IRCTransport,
    IRCTransportPolicy,
    IRCTransportState,
)


SECOND = 1_000_000_000


def policy(**changes: object) -> IRCTransportPolicy:
    values: dict[str, object] = {
        "nickname": "DuckBot",
        "fallback_nickname": "DuckBot_",
        "username": "duck",
        "realname": "pyDuckHunt integration",
        "channels": ("#pond",),
        "reconnect_delays_ns": (SECOND, 5 * SECOND),
        "handshake_timeout_ns": 10 * SECOND,
        "idle_timeout_ns": 30 * SECOND,
        "stop_timeout_ns": 3 * SECOND,
    }
    values.update(changes)
    return IRCTransportPolicy(**values)


class SocketQueue:
    def __init__(self, streams: list[socket.socket]) -> None:
        self.streams = streams
        self.calls: list[tuple[tuple[str, int], float]] = []

    def __call__(self, address: tuple[str, int], timeout: float) -> socket.socket:
        self.calls.append((address, timeout))
        if not self.streams:
            raise OSError("no synthetic stream")
        return self.streams.pop(0)


def read_available(stream: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = stream.recv(4096)
        except BlockingIOError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def adapter_with_streams(
    streams: list[socket.socket],
) -> tuple[IRCSocketAdapter, SocketQueue]:
    queue = SocketQueue(streams)
    connector = IRCSocketConnector(
        IRCEndpoint("irc.integration.invalid", 6697, False),
        dialer=queue,
    )
    return IRCSocketAdapter(IRCTransport(policy()), connector), queue


class SocketIRCAdapterIntegrationTests(unittest.TestCase):
    def test_socketpair_bot_mode_is_sent_before_join(self) -> None:
        client, server = socket.socketpair()
        server.setblocking(False)
        self.addCleanup(server.close)
        queue = SocketQueue([client])
        connector = IRCSocketConnector(
            IRCEndpoint("irc.integration.invalid", 6697, False),
            dialer=queue,
        )
        adapter = IRCSocketAdapter(
            IRCTransport(policy(bot_mode=True)),
            connector,
        )

        adapter.start(0)
        read_available(server)
        server.sendall(b":server 001 DuckBot :welcome\r\n")
        adapter.poll(1)
        self.assertEqual(
            read_available(server),
            b"MODE DuckBot +B\r\nJOIN #pond\r\n",
        )

    def test_socketpair_registration_ping_and_application_flow(self) -> None:
        client, server = socket.socketpair()
        server.setblocking(False)
        self.addCleanup(server.close)
        adapter, queue = adapter_with_streams([client])

        adapter.start(0)
        self.assertEqual(
            read_available(server),
            b"NICK DuckBot\r\nUSER duck 0 * :pyDuckHunt integration\r\n",
        )
        self.assertEqual(queue.calls, [(('irc.integration.invalid', 6697), 10.0)])

        server.sendall(b":server 001 DuckBot :wel")
        adapter.poll(1)
        server.sendall(
            b"come\r\n:DuckBot!u@h JOIN #pond\r\n"
            b"PING :token\r\n"
            b":Hunter!u@h PRIVMSG #pond :!bang\r\n"
        )
        result = adapter.poll(2)
        self.assertEqual(result.state, IRCTransportState.READY)
        self.assertEqual(
            tuple(message.command for message in result.messages),
            ("JOIN", "PRIVMSG"),
        )
        self.assertEqual(result.messages[1].nickname, "Hunter")
        self.assertEqual(
            read_available(server),
            b"JOIN #pond\r\nPONG token\r\n",
        )

    def test_socketpair_fallback_nickname_completes_registration(self) -> None:
        client, server = socket.socketpair()
        server.setblocking(False)
        self.addCleanup(server.close)
        adapter, _ = adapter_with_streams([client])
        adapter.start(0)
        read_available(server)
        server.sendall(b":server 433 * DuckBot :in use\r\n")
        adapter.poll(1)
        self.assertEqual(read_available(server), b"NICK DuckBot_\r\n")
        server.sendall(
            b":server 001 DuckBot_ :welcome\r\n"
            b":DuckBot_!u@h JOIN #pond\r\n"
        )
        result = adapter.poll(2)
        self.assertEqual(result.state, IRCTransportState.READY)
        self.assertEqual(adapter.transport.nickname, "DuckBot_")

    def test_socketpair_drop_reconnects_once_at_the_exact_deadline(self) -> None:
        first_client, first_server = socket.socketpair()
        second_client, second_server = socket.socketpair()
        first_server.setblocking(False)
        second_server.setblocking(False)
        self.addCleanup(first_server.close)
        self.addCleanup(second_server.close)
        adapter, queue = adapter_with_streams([first_client, second_client])
        adapter.start(0)
        read_available(first_server)
        first_server.close()
        dropped = adapter.poll(1)
        self.assertEqual(dropped.state, IRCTransportState.BACKOFF)
        self.assertEqual(len(queue.calls), 1)
        adapter.poll(SECOND)
        self.assertEqual(len(queue.calls), 1)
        reconnected = adapter.poll(SECOND + 1)
        self.assertEqual(reconnected.state, IRCTransportState.REGISTERING)
        self.assertEqual(len(queue.calls), 2)
        self.assertTrue(read_available(second_server).startswith(b"NICK DuckBot\r\n"))

    def test_socketpair_clean_stop_never_reconnects(self) -> None:
        client, server = socket.socketpair()
        server.setblocking(False)
        adapter, queue = adapter_with_streams([client])
        adapter.start(0)
        read_available(server)
        server.sendall(
            b":server 001 DuckBot :welcome\r\n"
            b":DuckBot!u@h JOIN #pond\r\n"
        )
        adapter.poll(1)
        stopping = adapter.stop(2, "maintenance")
        self.assertEqual(stopping.state, IRCTransportState.STOPPING)
        self.assertEqual(read_available(server), b"JOIN #pond\r\nQUIT maintenance\r\n")
        server.close()
        stopped = adapter.poll(3)
        self.assertEqual(stopped.state, IRCTransportState.STOPPED)
        adapter.poll(100 * SECOND)
        self.assertEqual(len(queue.calls), 1)


if __name__ == "__main__":
    unittest.main()
