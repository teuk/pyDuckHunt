from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.configuration import parse_application_configuration
from pyduckhunt.game.commands import CommandKind
from pyduckhunt.irc import IRCSocketConnector
from pyduckhunt.persistence import JournalFile, SnapshotStore, recover
from pyduckhunt.runtime import (
    BridgeStatus,
    CalibratedEventResolver,
    DevelopmentPilotGate,
    ProcessShellState,
    build_development_pilot,
)


def configuration(root: Path):
    return parse_application_configuration(
        {
            "irc": {
                "host": "irc.pilot.example",
                "port": 6667,
                "tls": False,
                "nickname": "DuckBot",
                "fallback_nickname": "DuckBot_",
                "channels": ["#pond"],
                "password_environment": "PYDUCKHUNT_IRC_PASSWORD",
            },
            "runtime": {
                "log_level": "INFO",
                "state_directory": str(root / "state"),
                "log_directory": str(root / "logs"),
            },
            "game": {
                "enabled": True,
                "flights_per_day": 18,
                "golden_weight_per_eighteen": 1,
                "flight_lifetime_seconds": 300,
                "unusual_loot_chance_per_thousand": 0,
                "shop_url": "https://games.example/duckhunt/shop/",
                "ranking_url": "https://rankings.example/duckhunt/",
            },
        }
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


class ControlledPilotIntegrationTests(unittest.TestCase):
    def test_gate_composition_command_persistence_and_clean_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = configuration(root)
            client, server = socket.socketpair()
            server.setblocking(False)
            self.addCleanup(client.close)
            self.addCleanup(server.close)
            calls: list[tuple[tuple[str, int], float]] = []
            connector = IRCSocketConnector(
                config.irc.endpoint(),
                dialer=lambda address, timeout: (
                    calls.append((address, timeout)) or client
                ),
            )
            resolver = CalibratedEventResolver(
                lambda minimum, maximum: (_ for _ in ()).throw(
                    AssertionError("query must not draw entropy")
                ),
                lambda channel, nickname: (_ for _ in ()).throw(
                    AssertionError("query must not inspect presence")
                ),
            )
            pilot = build_development_pilot(
                config,
                DevelopmentPilotGate(True, config.irc.endpoint(), ("#POND",)),
                {},
                resolver,
                connector=connector,
                snapshot_interval=None,
            )
            self.assertEqual(calls, [])

            self.assertEqual(pilot.shell.start(0).state, ProcessShellState.RUNNING)
            self.assertEqual(calls, [(('irc.pilot.example', 6667), 10.0)])
            self.assertEqual(
                read_available(server),
                b"NICK DuckBot\r\nUSER pyduckhunt 0 * pyDuckHunt\r\n",
            )
            server.sendall(
                b":server 001 DuckBot :welcome\r\n"
                b":DuckBot!u@h JOIN #pond\r\n"
                b":Hunter!u@h PRIVMSG #pond :!duckstats\r\n"
                b":Hunter!u@h PRIVMSG #pond :!shop\r\n"
                b":Hunter!u@h PRIVMSG #pond :!duckrank\r\n"
            )
            handled = pilot.shell.poll(1)
            self.assertEqual(len(handled.bridge_results), 3)
            self.assertTrue(
                all(
                    result.status is BridgeStatus.DISPATCHED
                    for result in handled.bridge_results
                )
            )
            for result in handled.bridge_results:
                assert result.dispatch is not None
                ticket = result.dispatch.persistence_ticket
                assert ticket is not None
                ticket.wait(2)
            response = read_available(server)
            self.assertIn(b"NOTICE Hunter :", response)
            self.assertIn(b"https://games.example/duckhunt/shop/", response)
            self.assertIn(b"PRIVMSG #pond :", response)
            self.assertIn(b"https://rankings.example/duckhunt/", response)

            visible = pilot.shell.runtime.state
            self.assertEqual(
                pilot.shell.stop(2, "pilot complete").state,
                ProcessShellState.STOPPING,
            )
            self.assertEqual(read_available(server), b"QUIT :pilot complete\r\n")
            server.close()
            self.assertEqual(pilot.shell.poll(3).state, ProcessShellState.STOPPED)

            journal = JournalFile(root / "state" / "events.jsonl")
            snapshot = SnapshotStore(root / "state" / "snapshot.json")
            records = journal.read_records()
            self.assertEqual(len(records), 3)
            self.assertEqual(records[0].event.command_kind, CommandKind.STATS)
            self.assertEqual(records[1].event.command_kind, CommandKind.SHOP)
            self.assertEqual(records[2].event.command_kind, CommandKind.RANK)
            self.assertEqual(recover(snapshot, journal).state, visible)


if __name__ == "__main__":
    unittest.main()
