from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyduckhunt.configuration import parse_application_configuration
from pyduckhunt.game.model import GameState
from pyduckhunt.irc import IRCEndpoint, IRCSocketConnector
from pyduckhunt.persistence import ReplayEvent
from pyduckhunt.runtime import (
    DevelopmentPilotGate,
    IRCCommandContext,
    ProcessShellState,
    authorize_development_pilot,
    build_development_pilot,
)


def configuration(
    root: Path,
    *,
    enabled: bool = True,
    host: str = "irc.pilot.example",
    partyline: bool = False,
):
    raw = {
            "irc": {
                "host": host,
                "port": 6697,
                "tls": True,
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
                "enabled": enabled,
                "flights_per_day": 18,
                "golden_weight_per_eighteen": 1,
                "flight_lifetime_seconds": 300,
                "unusual_loot_chance_per_thousand": 0,
                "ranking_url": "https://rank.example/ducks/",
            },
        }
    if partyline:
        raw["partyline"] = {
            "enabled": True,
            "bind_host": "127.0.0.1",
            "port": 0,
            "bootstrap_accounts": ["Operator"],
            "bootstrap_masks": [],
            "dcc_public_ip": "",
            "dcc_port_min": 0,
            "dcc_port_max": 0,
        }
    return parse_application_configuration(raw)


def resolver(state: GameState, context: IRCCommandContext) -> ReplayEvent:
    return ReplayEvent.runtime_command(
        context.now_ns,
        context.nickname,
        context.command,
    )


class PilotGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = configuration(self.root)
        self.endpoint = self.config.irc.endpoint()

    def test_authorization_requires_both_switches_and_exact_destination(self) -> None:
        with self.assertRaises(RuntimeError):
            authorize_development_pilot(
                configuration(self.root, enabled=False),
                DevelopmentPilotGate(True, self.endpoint, ("#pond",)),
            )
        with self.assertRaises(RuntimeError):
            authorize_development_pilot(
                self.config,
                DevelopmentPilotGate(False, self.endpoint, ("#pond",)),
            )
        with self.assertRaises(RuntimeError):
            authorize_development_pilot(
                self.config,
                DevelopmentPilotGate(
                    True,
                    IRCEndpoint("other.example", 6697, True),
                    ("#pond",),
                ),
            )
        with self.assertRaises(RuntimeError):
            authorize_development_pilot(
                self.config,
                DevelopmentPilotGate(True, self.endpoint, ("#elsewhere",)),
            )

    def test_placeholder_endpoint_can_never_be_authorized(self) -> None:
        placeholder = configuration(self.root, host="irc.dev.invalid")
        with self.assertRaises(RuntimeError):
            authorize_development_pilot(
                placeholder,
                DevelopmentPilotGate(True, placeholder.irc.endpoint(), ("#pond",)),
            )

    def test_authorized_build_recovers_without_opening_a_stream(self) -> None:
        calls: list[tuple[tuple[str, int], float]] = []
        connector = IRCSocketConnector(
            self.endpoint,
            dialer=lambda address, timeout: calls.append((address, timeout)),
        )
        built = build_development_pilot(
            self.config,
            DevelopmentPilotGate(True, self.endpoint, ("#POND",)),
            {},
            resolver,
            connector=connector,
            snapshot_interval=None,
        )
        self.assertEqual(calls, [])
        self.assertEqual(built.recovered.state, GameState())
        self.assertEqual(built.shell.state, ProcessShellState.NEW)
        self.assertEqual(built.shell.stop(0).state, ProcessShellState.STOPPED)

    def test_authorized_build_composes_the_configured_partyline(self) -> None:
        configured = configuration(self.root, partyline=True)
        built = build_development_pilot(
            configured,
            DevelopmentPilotGate(True, configured.irc.endpoint(), ("#pond",)),
            {},
            resolver,
            snapshot_interval=None,
        )
        self.assertIsNotNone(built.shell.partyline)
        assert built.shell.partyline is not None
        self.assertEqual(built.shell.partyline.configuration.bind_host, "127.0.0.1")
        self.assertEqual(built.shell.partyline.configuration.port, 0)
        self.assertEqual(built.shell.partyline._flight_lifetime_ns, 300_000_000_000)
        self.assertEqual(
            built.shell.partyline._ranking_url,
            "https://rank.example/ducks/",
        )
        built.shell.partyline.start(0)
        self.assertIsNotNone(built.shell.partyline.bound_port)
        built.shell.partyline.close("test")
        self.assertEqual(built.shell.stop(1).state, ProcessShellState.STOPPED)

    def test_builder_rejects_a_connector_for_another_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            build_development_pilot(
                self.config,
                DevelopmentPilotGate(True, self.endpoint, ("#pond",)),
                {},
                resolver,
                connector=IRCSocketConnector(
                    IRCEndpoint("other.example", 6697, True)
                ),
            )

    def test_gate_rejects_cross_typed_and_duplicate_channels(self) -> None:
        with self.assertRaises(ValueError):
            DevelopmentPilotGate(1, self.endpoint, ("#pond",))
        with self.assertRaises(ValueError):
            DevelopmentPilotGate(True, self.endpoint, ("#Pond", "#pond"))
        with self.assertRaises(ValueError):
            DevelopmentPilotGate(True, self.endpoint, ("pond",))
        with self.assertRaises(ValueError):
            DevelopmentPilotGate(True, self.endpoint, ("#pond", 1))


if __name__ == "__main__":
    unittest.main()
