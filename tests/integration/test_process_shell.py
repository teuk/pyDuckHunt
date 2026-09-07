from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.model import GameState
from pyduckhunt.irc import (
    IRCEndpoint,
    IRCSocketAdapter,
    IRCSocketConnector,
    IRCTransport,
    IRCTransportPolicy,
)
from pyduckhunt.persistence import JournalFile, ReplayEvent, SnapshotStore, recover
from pyduckhunt.runtime import (
    BridgeStatus,
    IRCCommandContext,
    IRCGameBridge,
    ProcessShell,
    ProcessShellState,
    RuntimeOrchestrator,
)


SECOND = 1_000_000_000


def policy(channels: tuple[str, ...] = ("#pond",)) -> IRCTransportPolicy:
    return IRCTransportPolicy(
        nickname="DuckBot",
        fallback_nickname="DuckBot_",
        username="duck",
        realname="pyDuckHunt process test",
        channels=channels,
        reconnect_delays_ns=(SECOND,),
        handshake_timeout_ns=10 * SECOND,
        idle_timeout_ns=30 * SECOND,
        stop_timeout_ns=3 * SECOND,
    )


def resolver(state: GameState, context: IRCCommandContext) -> ReplayEvent:
    return ReplayEvent.runtime_command(
        context.now_ns,
        context.nickname,
        context.command,
    )


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


class ProcessShellIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")
        self.client, self.server = socket.socketpair()
        self.server.setblocking(False)
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)

    def build_shell(
        self,
        *,
        enabled: bool = True,
        event_resolver=resolver,
        transport_channels: tuple[str, ...] = ("#pond",),
        bridge_channels: tuple[str, ...] = ("#pond",),
    ) -> ProcessShell:
        connector = IRCSocketConnector(
            IRCEndpoint("irc.process.invalid", 6697, False),
            dialer=lambda address, timeout: self.client,
        )
        adapter = IRCSocketAdapter(
            IRCTransport(policy(transport_channels)),
            connector,
        )
        runtime, _ = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            adapter.queue_application,
            persistence_capacity=4,
            snapshot_interval=None,
        )
        bridge = IRCGameBridge(runtime, bridge_channels, event_resolver)
        return ProcessShell(runtime, bridge, adapter, enabled=enabled)

    def test_socketpair_command_response_persistence_and_clean_stop(self) -> None:
        shell = self.build_shell()
        started = shell.start(0)
        self.assertEqual(started.state, ProcessShellState.RUNNING)
        self.assertEqual(
            read_available(self.server),
            b"NICK DuckBot\r\nUSER duck 0 * :pyDuckHunt process test\r\n",
        )

        self.server.sendall(
            b":server 001 DuckBot :welcome\r\n"
            b":DuckBot!u@h JOIN #pond\r\n"
            b":Hunter!u@h PRIVMSG #pond :!duckstats\r\n"
        )
        handled = shell.poll(1)
        self.assertEqual(len(handled.bridge_results), 1)
        self.assertEqual(handled.bridge_results[0].status, BridgeStatus.DISPATCHED)
        dispatch = handled.bridge_results[0].dispatch
        assert dispatch is not None and dispatch.persistence_ticket is not None
        dispatch.persistence_ticket.wait(2)
        wire = read_available(self.server)
        self.assertTrue(wire.startswith(b"JOIN #pond\r\n"))
        self.assertIn(b"NOTICE Hunter :", wire)

        visible = shell.runtime.state
        stopping = shell.stop(2, "maintenance")
        self.assertEqual(stopping.state, ProcessShellState.STOPPING)
        self.assertEqual(read_available(self.server), b"QUIT maintenance\r\n")
        self.server.close()
        stopped = shell.poll(3)
        self.assertEqual(stopped.state, ProcessShellState.STOPPED)
        self.assertEqual(recover(self.snapshots, self.journal).state, visible)
        self.assertEqual(len(self.journal.read_records()), 1)
        self.assertEqual(
            self.journal.read_records()[0].event.command_kind,
            CommandKind.STATS,
        )

    def test_disabled_guard_opens_no_stream_and_can_close_runtime(self) -> None:
        calls: list[tuple[tuple[str, int], float]] = []
        connector = IRCSocketConnector(
            IRCEndpoint("irc.process.invalid", 6697, False),
            dialer=lambda address, timeout: calls.append((address, timeout)) or self.client,
        )
        adapter = IRCSocketAdapter(IRCTransport(policy()), connector)
        runtime, _ = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            adapter.queue_application,
            snapshot_interval=None,
        )
        bridge = IRCGameBridge(runtime, ("#pond",), resolver)
        shell = ProcessShell(runtime, bridge, adapter, enabled=False)
        with self.assertRaises(RuntimeError):
            shell.start(0)
        self.assertEqual(calls, [])
        self.assertEqual(shell.state, ProcessShellState.NEW)
        self.assertEqual(shell.stop(0).state, ProcessShellState.STOPPED)

    def test_application_failure_is_bounded_and_stops_admission(self) -> None:
        def failed_resolver(state: GameState, context: IRCCommandContext) -> ReplayEvent:
            raise ValueError("private settlement detail")

        shell = self.build_shell(event_resolver=failed_resolver)
        shell.start(0)
        read_available(self.server)
        self.server.sendall(
            b":server 001 DuckBot :welcome\r\n"
            b":DuckBot!u@h JOIN #pond\r\n"
            b":Hunter!u@h PRIVMSG #pond :!reload\r\n"
        )
        failed = shell.poll(1)
        self.assertEqual(failed.state, ProcessShellState.STOPPING)
        self.assertEqual(failed.failure, "application failed")
        self.assertNotIn("private", repr(failed))
        self.assertEqual(shell.runtime.state, GameState())
        self.assertTrue(read_available(self.server).endswith(b"QUIT :application failure\r\n"))
        self.server.close()
        self.assertEqual(shell.poll(2).state, ProcessShellState.STOPPED)

    def test_shell_rejects_cross_typed_policy_and_channel_mismatch(self) -> None:
        shell = self.build_shell()
        with self.assertRaises(ValueError):
            ProcessShell(
                shell.runtime,
                shell.bridge,
                shell.adapter,
                enabled=1,  # type: ignore[arg-type]
            )
        mismatched_runtime, _ = RuntimeOrchestrator.open(
            JournalFile(Path(self.temporary.name) / "other.jsonl"),
            SnapshotStore(Path(self.temporary.name) / "other-snapshot.json"),
            lambda batch: None,
            snapshot_interval=None,
        )
        self.addCleanup(
            lambda: mismatched_runtime.close(2)
            if mismatched_runtime.persistence.state.value in ("running", "closing")
            else None
        )
        mismatched_bridge = IRCGameBridge(
            mismatched_runtime,
            ("#elsewhere",),
            resolver,
        )
        with self.assertRaises(ValueError):
            ProcessShell(
                mismatched_runtime,
                mismatched_bridge,
                shell.adapter,
                enabled=True,
            )
        shell.stop(0)


if __name__ == "__main__":
    unittest.main()
