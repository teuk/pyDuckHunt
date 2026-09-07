from __future__ import annotations

import unittest

from pyduckhunt.irc import IRCTransport, IRCTransportPolicy, IRCTransportState
from tests.support.fake_irc import FakeIRCServer


SECOND = 1_000_000_000


def fake_server() -> FakeIRCServer:
    transport = IRCTransport(
        IRCTransportPolicy(
            nickname="DuckBot",
            fallback_nickname="DuckBot_",
            username="duck",
            realname="synthetic duck",
            channels=("#pond",),
            reconnect_delays_ns=(SECOND, 5 * SECOND),
            handshake_timeout_ns=10 * SECOND,
            idle_timeout_ns=30 * SECOND,
            stop_timeout_ns=3 * SECOND,
        )
    )
    return FakeIRCServer(transport)


class FakeIRCTransportIntegrationTests(unittest.TestCase):
    def test_fragmented_welcome_join_and_privmsg_reach_application(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        self.assertEqual(server.connect_requests, 1)
        self.assertEqual(
            tuple(message.command for message in server.client_messages),
            ("NICK", "USER"),
        )
        server.send_chunk(b":server 001 Duck")
        server.send_chunk(b"Bot :welcome\r\n:DuckBot!u@h JOIN #pond\r")
        server.send_chunk(b"\n:Hunter!u@h PRIVMSG #pond :!bang\r\n")
        self.assertEqual(server.transport.state, IRCTransportState.READY)
        self.assertEqual(server.client_messages[-1].command, "JOIN")
        self.assertEqual(
            tuple(message.command for message in server.application_messages),
            ("JOIN", "PRIVMSG"),
        )
        self.assertEqual(server.application_messages[1].params[-1], "!bang")

    def test_ping_is_answered_when_split_at_crlf_boundary(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        server.send_chunk(b"PING :token\r")
        self.assertEqual(server.client_messages[-1].command, "USER")
        server.send_chunk(b"\n")
        self.assertEqual(server.client_messages[-1].command, "PONG")
        self.assertEqual(server.client_messages[-1].params, ("token",))

    def test_nickname_fallback_can_complete_registration(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        server.send_line(":server 433 * DuckBot :in use")
        self.assertEqual(server.client_messages[-1].params, ("DuckBot_",))
        server.send_line(":server 001 DuckBot_ :welcome")
        server.send_line(":duckbot_!u@h JOIN #POND")
        self.assertEqual(server.transport.state, IRCTransportState.READY)

    def test_drop_and_exact_backoff_request_one_new_connection(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        server.drop("synthetic reset")
        self.assertEqual(server.transport.reconnect_at_ns, SECOND)
        server.advance(SECOND - 1)
        self.assertEqual(server.connect_requests, 1)
        server.advance(SECOND)
        self.assertEqual(server.connect_requests, 2)

    def test_handshake_timeout_closes_then_reconnects(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        server.advance(10 * SECOND)
        self.assertEqual(server.close_reasons, ["handshake timeout"])
        self.assertEqual(server.transport.state, IRCTransportState.BACKOFF)
        server.advance(11 * SECOND)
        self.assertEqual(server.connect_requests, 2)

    def test_clean_stop_never_schedules_reconnection(self) -> None:
        server = fake_server()
        server.start()
        server.accept()
        server.send_line(":server 001 DuckBot :welcome")
        server.send_line(":DuckBot!u@h JOIN #pond")
        server.stop("maintenance")
        self.assertEqual(server.client_messages[-1].command, "QUIT")
        server.drop("server acknowledged quit")
        server.advance(100 * SECOND)
        self.assertEqual(server.transport.state, IRCTransportState.STOPPED)
        self.assertEqual(server.connect_requests, 1)


if __name__ == "__main__":
    unittest.main()
