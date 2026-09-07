from __future__ import annotations

import threading
import unittest

from pyduckhunt.irc import (
    IRCAdapterResult,
    IRCEndpoint,
    IRCSocketAdapter,
    IRCSocketConnector,
    IRCTransport,
    IRCTransportPolicy,
    IRCTransportState,
)


SECOND = 1_000_000_000


class FakeStream:
    def __init__(self) -> None:
        self.receives: list[bytes | Exception | object] = []
        self.send_plan: list[int | Exception] = []
        self.sent = bytearray()
        self.blocking: list[bool] = []
        self.closed = False

    def recv(self, size: int) -> bytes:
        if not self.receives:
            raise BlockingIOError
        value = self.receives.pop(0)
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[return-value]

    def send(self, data: bytes | memoryview) -> int:
        if self.send_plan:
            planned = self.send_plan.pop(0)
            if isinstance(planned, Exception):
                raise planned
            count = planned
        else:
            count = len(data)
        self.sent.extend(bytes(data[:count]))
        return count

    def setblocking(self, flag: bool) -> None:
        self.blocking.append(flag)

    def close(self) -> None:
        self.closed = True


class FakeTLSContext:
    def __init__(self, wrapped: FakeStream, *, failure: Exception | None = None) -> None:
        self.wrapped = wrapped
        self.failure = failure
        self.calls: list[tuple[FakeStream, str | None]] = []

    def wrap_socket(
        self,
        stream: FakeStream,
        *,
        server_hostname: str | None = None,
    ) -> FakeStream:
        self.calls.append((stream, server_hostname))
        if self.failure is not None:
            raise self.failure
        return self.wrapped


def transport_policy(**changes: object) -> IRCTransportPolicy:
    values: dict[str, object] = {
        "nickname": "DuckBot",
        "fallback_nickname": "DuckBot_",
        "username": "duck",
        "realname": "pyDuckHunt test",
        "channels": ("#pond",),
        "reconnect_delays_ns": (SECOND, 5 * SECOND),
        "handshake_timeout_ns": 10 * SECOND,
        "idle_timeout_ns": 30 * SECOND,
        "stop_timeout_ns": 3 * SECOND,
    }
    values.update(changes)
    return IRCTransportPolicy(**values)


def adapter_for(
    stream: FakeStream,
    *,
    policy: IRCTransportPolicy | None = None,
    max_pending_output_bytes: int = 8192,
) -> IRCSocketAdapter:
    connector = IRCSocketConnector(
        IRCEndpoint("irc.example.test", 6697, False),
        dialer=lambda address, timeout: stream,
    )
    return IRCSocketAdapter(
        IRCTransport(policy or transport_policy()),
        connector,
        max_pending_output_bytes=max_pending_output_bytes,
    )


class IRCSocketAdapterTests(unittest.TestCase):
    def test_endpoint_contract_rejects_unsafe_or_cross_typed_values(self) -> None:
        for values in (
            ("", 6697, True, 10.0),
            ("bad host", 6697, True, 10.0),
            ("irc.test", True, True, 10.0),
            ("irc.test", 0, True, 10.0),
            ("irc.test", 6697, 1, 10.0),
            ("irc.test", 6697, True, True),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                IRCEndpoint(*values)

    def test_plain_connector_dials_exact_endpoint_and_sets_nonblocking(self) -> None:
        stream = FakeStream()
        calls: list[tuple[tuple[str, int], float]] = []

        def dialer(address: tuple[str, int], timeout: float) -> FakeStream:
            calls.append((address, timeout))
            return stream

        connector = IRCSocketConnector(
            IRCEndpoint("irc.example.test", 6667, False, 4.5),
            dialer=dialer,
        )
        self.assertIs(connector.open(), stream)
        self.assertEqual(calls, [(('irc.example.test', 6667), 4.5)])
        self.assertEqual(stream.blocking, [False])

    def test_tls_connector_uses_verified_hostname_and_wrapped_stream(self) -> None:
        raw = FakeStream()
        wrapped = FakeStream()
        context = FakeTLSContext(wrapped)
        connector = IRCSocketConnector(
            IRCEndpoint("irc.example.test", 6697, True),
            dialer=lambda address, timeout: raw,
            tls_context_factory=lambda: context,  # type: ignore[arg-type]
        )
        self.assertIs(connector.open(), wrapped)
        self.assertEqual(context.calls, [(raw, "irc.example.test")])
        self.assertEqual(wrapped.blocking, [False])

    def test_tls_failure_closes_the_raw_stream(self) -> None:
        raw = FakeStream()
        context = FakeTLSContext(FakeStream(), failure=OSError("synthetic"))
        connector = IRCSocketConnector(
            IRCEndpoint("irc.example.test", 6697, True),
            dialer=lambda address, timeout: raw,
            tls_context_factory=lambda: context,  # type: ignore[arg-type]
        )
        with self.assertRaises(OSError):
            connector.open()
        self.assertTrue(raw.closed)

    def test_start_connects_and_flushes_exact_registration(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream)
        result = adapter.start(0)
        self.assertIsInstance(result, IRCAdapterResult)
        self.assertEqual(result.state, IRCTransportState.REGISTERING)
        self.assertTrue(result.connected)
        self.assertEqual(
            bytes(stream.sent),
            b"NICK DuckBot\r\nUSER duck 0 * :pyDuckHunt test\r\n",
        )
        self.assertEqual(stream.blocking, [False])

    def test_partial_nonblocking_send_is_preserved_for_later_poll(self) -> None:
        stream = FakeStream()
        stream.send_plan.extend((4, BlockingIOError()))
        adapter = adapter_for(stream)
        started = adapter.start(0)
        self.assertGreater(started.pending_output_bytes, 0)
        self.assertEqual(bytes(stream.sent), b"NICK")
        completed = adapter.poll(1)
        self.assertEqual(completed.pending_output_bytes, 0)
        self.assertEqual(
            bytes(stream.sent),
            b"NICK DuckBot\r\nUSER duck 0 * :pyDuckHunt test\r\n",
        )

    def test_fragmented_input_reaches_ready_and_forwards_application_message(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream)
        adapter.start(0)
        stream.receives.extend(
            (
                b":server 001 DuckBot :wel",
                b"come\r\n:DuckBot!u@h JOIN #pond\r\n",
                b":Hunter!u@h PRIVMSG #pond :!bang\r\n",
                BlockingIOError(),
            )
        )
        result = adapter.poll(1)
        self.assertEqual(result.state, IRCTransportState.READY)
        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.messages[0].command, "JOIN")
        self.assertEqual(result.messages[1].params, ("#pond", "!bang"))
        self.assertIn(b"JOIN #pond\r\n", bytes(stream.sent))

    def test_application_batch_reserves_capacity_atomically_then_flushes(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream, max_pending_output_bytes=600)
        adapter.start(0)
        stream.receives.extend(
            (
                b":server 001 DuckBot :welcome\r\n",
                b":DuckBot!u@h JOIN #pond\r\n",
                BlockingIOError(),
            )
        )
        adapter.poll(1)
        before = bytes(stream.sent)
        batch = (
            b"PRIVMSG #pond :first\r\n",
            b"PRIVMSG #pond :second\r\n",
        )
        adapter.queue_application(batch)
        self.assertEqual(adapter.pending_output_bytes, sum(map(len, batch)))
        adapter.flush(1)
        self.assertEqual(bytes(stream.sent), before + b"".join(batch))

        oversized = (b"PRIVMSG #pond :" + b"x" * 480 + b"\r\n",) * 2
        with self.assertRaises(BufferError):
            adapter.queue_application(oversized)
        self.assertEqual(adapter.pending_output_bytes, 0)

    def test_application_output_requires_a_ready_connected_adapter(self) -> None:
        adapter = adapter_for(FakeStream())
        with self.assertRaises(RuntimeError):
            adapter.queue_application((b"PRIVMSG #pond :early\r\n",))
        adapter.start(0)
        with self.assertRaises(RuntimeError):
            adapter.queue_application((b"PRIVMSG #pond :registering\r\n",))

    def test_peer_close_and_protocol_failure_enter_backoff_without_raw_data(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream)
        adapter.start(0)
        stream.receives.append(b"")
        closed = adapter.poll(1)
        self.assertEqual(closed.state, IRCTransportState.BACKOFF)
        self.assertEqual(closed.failure, "peer closed connection")
        self.assertTrue(stream.closed)

        second = FakeStream()
        second.receives.append(b"PING :bad\n")
        protocol_adapter = adapter_for(second)
        protocol_adapter.start(0)
        failed = protocol_adapter.poll(1)
        self.assertEqual(failed.state, IRCTransportState.BACKOFF)
        self.assertEqual(failed.failure, "protocol error")

    def test_connect_and_send_failures_are_latched_as_bounded_categories(self) -> None:
        connector = IRCSocketConnector(
            IRCEndpoint("irc.example.test", 6697, False),
            dialer=lambda address, timeout: (_ for _ in ()).throw(
                OSError("private connector detail")
            ),
        )
        adapter = IRCSocketAdapter(IRCTransport(transport_policy()), connector)
        failed = adapter.start(0)
        self.assertEqual(failed.failure, "connect failed")
        self.assertEqual(failed.state, IRCTransportState.BACKOFF)
        self.assertNotIn("private", repr(failed))

        stream = FakeStream()
        stream.send_plan.append(OSError("private send detail"))
        send_adapter = adapter_for(stream)
        send_failed = send_adapter.start(0)
        self.assertEqual(send_failed.failure, "send failed")
        self.assertEqual(send_failed.state, IRCTransportState.BACKOFF)

    def test_receive_contract_and_output_capacity_fail_closed(self) -> None:
        stream = FakeStream()
        stream.receives.append("not bytes")
        adapter = adapter_for(stream)
        adapter.start(0)
        result = adapter.poll(1)
        self.assertEqual(result.failure, "receive contract failed")
        self.assertEqual(result.state, IRCTransportState.BACKOFF)

        full = FakeStream()
        policy = transport_policy(server_password="x" * 490)
        bounded = adapter_for(full, policy=policy, max_pending_output_bytes=512)
        overflow = bounded.start(0)
        self.assertEqual(overflow.failure, "outbound buffer full")
        self.assertEqual(overflow.state, IRCTransportState.BACKOFF)
        self.assertEqual(overflow.pending_output_bytes, 0)

    def test_clean_stop_flushes_quit_then_forces_close_at_exact_timeout(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream)
        adapter.start(0)
        stream.receives.extend(
            (
                b":server 001 DuckBot :welcome\r\n",
                b":DuckBot!u@h JOIN #pond\r\n",
                BlockingIOError(),
            )
        )
        adapter.poll(1)
        stopping = adapter.stop(2, "maintenance")
        self.assertEqual(stopping.state, IRCTransportState.STOPPING)
        self.assertTrue(bytes(stream.sent).endswith(b"QUIT maintenance\r\n"))
        before = adapter.poll(3 * SECOND + 1)
        self.assertEqual(before.state, IRCTransportState.STOPPING)
        stopped = adapter.poll(3 * SECOND + 2)
        self.assertEqual(stopped.state, IRCTransportState.STOPPED)
        self.assertFalse(stopped.connected)
        self.assertTrue(stream.closed)

    def test_adapter_policy_rejects_truth_values_and_tiny_output_limit(self) -> None:
        stream = FakeStream()
        connector = IRCSocketConnector(
            IRCEndpoint("irc.example.test", 6697, False),
            dialer=lambda address, timeout: stream,
        )
        for keyword in (
            {"receive_bytes": True},
            {"max_reads_per_poll": 0},
            {"max_pending_output_bytes": 511},
        ):
            with self.subTest(keyword=keyword), self.assertRaises(ValueError):
                IRCSocketAdapter(
                    IRCTransport(transport_policy()),
                    connector,
                    **keyword,
                )

    def test_adapter_rejects_invalid_time_before_stream_io(self) -> None:
        stream = FakeStream()
        adapter = adapter_for(stream)
        with self.assertRaises(ValueError):
            adapter.start(True)
        self.assertEqual(stream.blocking, [])
        adapter.start(10)
        stream.receives.append(b"PING :preserved\r\n")
        with self.assertRaises(ValueError):
            adapter.poll(9)
        self.assertEqual(stream.receives, [b"PING :preserved\r\n"])
        with self.assertRaises(ValueError):
            adapter.stop(False)

    def test_adapter_rejects_mutation_from_another_thread(self) -> None:
        adapter = adapter_for(FakeStream())
        errors: list[Exception] = []

        def foreign_start() -> None:
            try:
                adapter.start(0)
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_start)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(adapter.transport.state, IRCTransportState.NEW)


if __name__ == "__main__":
    unittest.main()
