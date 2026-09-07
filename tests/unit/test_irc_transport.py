from __future__ import annotations

import threading
import unittest

from pyduckhunt.irc import (
    IRCProtocolError,
    IRCTransport,
    IRCTransportAction,
    IRCTransportActionKind,
    IRCTransportPolicy,
    IRCTransportState,
)


SECOND = 1_000_000_000


def policy(**changes: object) -> IRCTransportPolicy:
    values: dict[str, object] = {
        "nickname": "DuckBot",
        "fallback_nickname": "DuckBot_",
        "username": "duck",
        "realname": "pyDuckHunt development",
        "channels": ("#pond", "#marsh"),
        "reconnect_delays_ns": (SECOND, 5 * SECOND),
        "handshake_timeout_ns": 10 * SECOND,
        "idle_timeout_ns": 30 * SECOND,
        "stop_timeout_ns": 3 * SECOND,
    }
    values.update(changes)
    return IRCTransportPolicy(**values)


def ready_transport() -> IRCTransport:
    transport = IRCTransport(policy())
    transport.start(0)
    transport.connected(0)
    transport.receive(1, ":server 001 DuckBot :welcome")
    transport.receive(2, ":duckbot!u@h JOIN #POND")
    transport.receive(3, ":DuckBot!u@h JOIN #marsh")
    return transport


class IRCTransportTests(unittest.TestCase):
    def test_policy_rejects_unsafe_or_ambiguous_values(self) -> None:
        with self.assertRaises(ValueError):
            policy(nickname="bad nick")
        with self.assertRaises(ValueError):
            policy(fallback_nickname="duckbot")
        with self.assertRaises(ValueError):
            policy(channels=("#Pond", "#pond"))
        with self.assertRaises(ValueError):
            policy(channels=("pond",))
        with self.assertRaises(ValueError):
            policy(handshake_timeout_ns=True)
        with self.assertRaises(ValueError):
            policy(reconnect_delays_ns=(0,))
        with self.assertRaises(ValueError):
            policy(bot_mode=1)

    def test_actions_reject_invalid_wire_and_close_reasons(self) -> None:
        with self.assertRaises(IRCProtocolError):
            IRCTransportAction.send(b"PING :unterminated")
        with self.assertRaises(ValueError):
            IRCTransportAction.close("unsafe\r\nQUIT")
        with self.assertRaises(IRCProtocolError):
            IRCTransportAction.close("x" * 600)

    def test_start_and_connected_emit_exact_registration_actions(self) -> None:
        transport = IRCTransport(policy())
        start = transport.start(0)
        self.assertEqual(start.actions[0].kind, IRCTransportActionKind.CONNECT)
        self.assertEqual(transport.state, IRCTransportState.CONNECTING)
        registration = transport.connected(1)
        self.assertEqual(
            tuple(action.wire for action in registration.actions),
            (
                b"NICK DuckBot\r\n",
                b"USER duck 0 * :pyDuckHunt development\r\n",
            ),
        )
        self.assertEqual(transport.deadline_ns, 10 * SECOND + 1)

    def test_bot_mode_precedes_joins_and_uses_current_nickname(self) -> None:
        transport = IRCTransport(policy(bot_mode=True))
        transport.start(0)
        transport.connected(0)
        primary = transport.receive(1, ":server 001 DuckBot :welcome")
        self.assertEqual(
            tuple(action.wire for action in primary.actions),
            (
                b"MODE DuckBot +B\r\n",
                b"JOIN #pond\r\n",
                b"JOIN #marsh\r\n",
            ),
        )

        fallback = IRCTransport(policy(bot_mode=True))
        fallback.start(0)
        fallback.connected(0)
        fallback.receive(1, ":server 433 * DuckBot :in use")
        joined = fallback.receive(2, ":server 001 DuckBot_ :welcome")
        self.assertEqual(joined.actions[0].wire, b"MODE DuckBot_ +B\r\n")

    def test_welcome_joins_every_channel_and_self_joins_reach_ready(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connected(0)
        joins = transport.receive(1, ":server 001 DuckBot :welcome")
        self.assertEqual(
            tuple(action.wire for action in joins.actions),
            (b"JOIN #pond\r\n", b"JOIN #marsh\r\n"),
        )
        transport.receive(2, ":DUCKBOT!u@h JOIN #POND")
        self.assertEqual(transport.state, IRCTransportState.JOINING)
        transport.receive(3, ":DuckBot!u@h JOIN #marsh")
        self.assertEqual(transport.state, IRCTransportState.READY)
        self.assertEqual(transport.joined_channels, ("#pond", "#marsh"))

    def test_ping_is_answered_during_registration_and_ready(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connected(0)
        first = transport.receive(1, "PING :registration")
        self.assertEqual(first.actions[0].wire, b"PONG registration\r\n")
        transport.receive(2, ":server 001 DuckBot :welcome")
        transport.receive(3, ":DuckBot!u@h JOIN #pond")
        transport.receive(4, ":DuckBot!u@h JOIN #marsh")
        second = transport.receive(5, "PING one :two")
        self.assertEqual(second.actions[0].wire, b"PONG one two\r\n")

    def test_ready_privmsg_is_forwarded_as_an_application_message(self) -> None:
        transport = ready_transport()
        result = transport.receive(
            4,
            ":Hunter!user@example.test PRIVMSG #pond :!bang",
        )
        self.assertEqual(result.actions, ())
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].nickname, "Hunter")
        self.assertEqual(result.messages[0].params, ("#pond", "!bang"))

    def test_membership_messages_are_forwarded_for_the_live_roster(self) -> None:
        transport = ready_transport()
        names = transport.receive(
            4,
            ":server 353 DuckBot = #pond :@DuckBot +Alice Bob",
        )
        end = transport.receive(5, ":server 366 DuckBot #pond :End of NAMES")
        part = transport.receive(6, ":Bob!u@h PART #pond :bye")
        self.assertEqual(names.messages[0].command, "353")
        self.assertEqual(end.messages[0].command, "366")
        self.assertEqual(part.messages[0].nickname, "Bob")

    def test_application_output_is_ready_only_immutable_and_ordered(self) -> None:
        transport = IRCTransport(policy())
        with self.assertRaises(RuntimeError):
            transport.send_application((b"PRIVMSG #pond :early\r\n",))
        transport = ready_transport()
        with self.assertRaises(ValueError):
            transport.send_application([b"PRIVMSG #pond :mutable\r\n"])  # type: ignore[arg-type]
        with self.assertRaises(IRCProtocolError):
            transport.send_application((b"PRIVMSG #pond :unterminated",))
        step = transport.send_application(
            (
                b"PRIVMSG #pond :first\r\n",
                b"PRIVMSG #pond :second\r\n",
            )
        )
        self.assertEqual(
            tuple(action.wire for action in step.actions),
            (
                b"PRIVMSG #pond :first\r\n",
                b"PRIVMSG #pond :second\r\n",
            ),
        )

    def test_primary_collision_uses_fallback_then_closes(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connected(0)
        fallback = transport.receive(1, ":server 433 * DuckBot :in use")
        self.assertEqual(fallback.actions[0].wire, b"NICK DuckBot_\r\n")
        self.assertEqual(transport.nickname, "DuckBot_")
        failed = transport.receive(2, ":server 433 * DuckBot_ :in use")
        self.assertEqual(failed.actions[0].kind, IRCTransportActionKind.CLOSE)
        self.assertEqual(transport.state, IRCTransportState.BACKOFF)
        self.assertEqual(transport.reconnect_at_ns, SECOND + 2)

    def test_connection_loss_uses_exact_escalating_backoff(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connection_lost(1, "refused")
        self.assertEqual(transport.reconnect_at_ns, SECOND + 1)
        self.assertEqual(transport.tick(SECOND).actions, ())
        reconnect = transport.tick(SECOND + 1)
        self.assertEqual(reconnect.actions[0].kind, IRCTransportActionKind.CONNECT)
        transport.connection_lost(SECOND + 2, "refused again")
        self.assertEqual(transport.reconnect_at_ns, 6 * SECOND + 2)

    def test_ready_session_resets_backoff_to_first_delay(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connection_lost(1, "first")
        transport.tick(SECOND + 1)
        transport.connected(SECOND + 2)
        transport.receive(SECOND + 3, ":server 001 DuckBot :welcome")
        transport.receive(SECOND + 4, ":DuckBot!u@h JOIN #pond")
        transport.receive(SECOND + 5, ":DuckBot!u@h JOIN #marsh")
        transport.connection_lost(SECOND + 6, "after ready")
        self.assertEqual(transport.reconnect_at_ns, 2 * SECOND + 6)

    def test_handshake_timeout_closes_at_the_exact_deadline(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connected(0)
        self.assertEqual(transport.tick(10 * SECOND - 1).actions, ())
        timeout = transport.tick(10 * SECOND)
        self.assertEqual(timeout.actions[0].reason, "handshake timeout")
        self.assertEqual(transport.state, IRCTransportState.BACKOFF)

    def test_idle_timeout_is_reset_by_any_valid_server_message(self) -> None:
        transport = ready_transport()
        transport.receive(10 * SECOND, ":server NOTICE DuckBot :still here")
        self.assertEqual(transport.tick(40 * SECOND - 1).actions, ())
        timeout = transport.tick(40 * SECOND)
        self.assertEqual(timeout.actions[0].reason, "idle timeout")

    def test_kick_of_current_nickname_rejoins_only_that_channel(self) -> None:
        transport = ready_transport()
        result = transport.receive(
            4,
            ":operator KICK #pond dUCKbOT :synthetic test",
        )
        self.assertEqual(result.actions[0].wire, b"JOIN #pond\r\n")
        self.assertEqual(transport.state, IRCTransportState.JOINING)
        self.assertEqual(transport.joined_channels, ("#marsh",))
        transport.receive(5, ":DuckBot!u@h JOIN #pond")
        self.assertEqual(transport.state, IRCTransportState.READY)

    def test_graceful_stop_sends_quit_then_remote_close_finishes(self) -> None:
        transport = ready_transport()
        stopping = transport.stop(4, "maintenance")
        self.assertEqual(stopping.actions[0].wire, b"QUIT maintenance\r\n")
        self.assertEqual(transport.state, IRCTransportState.STOPPING)
        transport.connection_lost(5, "server closed")
        self.assertEqual(transport.state, IRCTransportState.STOPPED)
        self.assertEqual(transport.tick(100 * SECOND).actions, ())

    def test_stop_timeout_forces_close_without_reconnect(self) -> None:
        transport = ready_transport()
        transport.stop(4)
        self.assertEqual(transport.tick(3 * SECOND + 3).actions, ())
        forced = transport.tick(3 * SECOND + 4)
        self.assertEqual(forced.actions[0].kind, IRCTransportActionKind.CLOSE)
        self.assertEqual(transport.state, IRCTransportState.STOPPED)

    def test_server_error_during_stop_cannot_schedule_reconnection(self) -> None:
        transport = ready_transport()
        transport.stop(4)
        closed = transport.receive(5, "ERROR :closing link")
        self.assertEqual(closed.actions[0].kind, IRCTransportActionKind.CLOSE)
        self.assertEqual(transport.state, IRCTransportState.STOPPED)
        self.assertIsNone(transport.reconnect_at_ns)
        self.assertEqual(transport.tick(100 * SECOND).actions, ())

    def test_stop_before_connection_is_immediate(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        stopped = transport.stop(1)
        self.assertEqual(stopped.actions[0].kind, IRCTransportActionKind.CLOSE)
        self.assertEqual(transport.state, IRCTransportState.STOPPED)

    def test_invalid_welcome_nickname_is_rejected(self) -> None:
        transport = IRCTransport(policy())
        transport.start(0)
        transport.connected(0)
        with self.assertRaises(IRCProtocolError):
            transport.receive(1, ":server 001 Intruder :welcome")
        with self.assertRaises(IRCProtocolError):
            transport.receive(1, ":server 001")
        self.assertEqual(transport.tick(0).actions, ())

    def test_time_travel_truth_values_and_out_of_order_calls_are_rejected(self) -> None:
        transport = IRCTransport(policy())
        with self.assertRaises(ValueError):
            transport.start(True)
        transport.start(10)
        with self.assertRaises(ValueError):
            transport.tick(9)
        with self.assertRaises(RuntimeError):
            transport.start(11)
        with self.assertRaises(RuntimeError):
            transport.receive(11, "PING :early")
        self.assertEqual(transport.tick(10).actions, ())

    def test_transport_rejects_mutation_from_another_thread(self) -> None:
        transport = IRCTransport(policy())
        errors: list[Exception] = []

        def foreign_start() -> None:
            try:
                transport.start(0)
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_start)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(transport.state, IRCTransportState.NEW)


if __name__ == "__main__":
    unittest.main()
