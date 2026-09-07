from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.configuration import parse_application_configuration
from pyduckhunt.game.model import GameState
from pyduckhunt.irc import IRCSocketConnector
from pyduckhunt.persistence import JournalFile, ReplayEvent
from pyduckhunt.runtime import (
    CalibratedScheduleSource,
    DevelopmentPilotGate,
    IRCCommandContext,
    OperatorPilotRunner,
    PilotControl,
    ProcessShellState,
    ScheduleStatus,
    ScheduleStepResult,
    RuntimeSchedulingAdapter,
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
            },
        }
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


class MinimumIntegerSource:
    def __call__(self, minimum: int, maximum: int) -> int:
        return minimum


class IncrementingClock:
    def __init__(self) -> None:
        self.value = -1

    def __call__(self) -> int:
        self.value += 1
        return self.value


class OperatorPilotRunnerIntegrationTests(unittest.TestCase):
    def test_debug_schedule_reports_change_then_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = configuration(root)

            def reject_connection(address: tuple[str, int], timeout: float) -> socket.socket:
                del address, timeout
                raise AssertionError("diagnostic runner must not connect")

            pilot = build_development_pilot(
                config,
                DevelopmentPilotGate(True, config.irc.endpoint(), ("#pond",)),
                {},
                resolver,
                connector=IRCSocketConnector(config.irc.endpoint(), dialer=reject_connection),
                snapshot_interval=None,
            )
            scheduling = RuntimeSchedulingAdapter(
                pilot.shell.runtime,
                config.irc.channels,
                CalibratedScheduleSource(MinimumIntegerSource()),
            )
            observed: list[str] = []
            runner = OperatorPilotRunner(
                pilot,
                scheduling,
                observer=observed.append,
                debug_enabled=True,
                schedule_heartbeat_ns=10,
            )
            status = ScheduleStatus(0, 24, 0, 60_000_000_000, 0, 24, False)
            runner._record_schedule(
                ScheduleStepResult((), 60_000_000_000, status, plan_installed=True),
                0,
            )
            waiting = ScheduleStepResult((), 60_000_000_000, status)
            runner._record_schedule(waiting, 9)
            runner._record_schedule(waiting, 10)
            debug = tuple(message for message in observed if message.startswith("DEBUG SCHEDULE"))
            self.assertEqual(len(debug), 2)
            self.assertIn("reason=change", debug[0])
            self.assertIn("reason=heartbeat", debug[1])
            pilot.shell.stop(1, "diagnostic complete")

    def test_explicit_run_installs_schedule_and_obeys_operator_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = configuration(root)
            client, server = socket.socketpair()
            server.setblocking(False)
            self.addCleanup(client.close)
            self.addCleanup(server.close)
            connector = IRCSocketConnector(
                config.irc.endpoint(),
                dialer=lambda address, timeout: client,
            )
            pilot = build_development_pilot(
                config,
                DevelopmentPilotGate(True, config.irc.endpoint(), ("#POND",)),
                {},
                resolver,
                connector=connector,
                snapshot_interval=None,
            )
            scheduling = RuntimeSchedulingAdapter(
                pilot.shell.runtime,
                config.irc.channels,
                CalibratedScheduleSource(MinimumIntegerSource()),
            )
            control = PilotControl()
            sleep_calls = 0

            def sleeper(seconds: float) -> None:
                nonlocal sleep_calls
                self.assertEqual(seconds, 0.05)
                sleep_calls += 1
                if sleep_calls == 1:
                    self.assertEqual(
                        read_available(server),
                        b"NICK DuckBot\r\nUSER pyduckhunt 0 * pyDuckHunt\r\n",
                    )
                    server.sendall(
                        b":server 001 DuckBot :welcome\r\n"
                        b":DuckBot!u@h JOIN #pond\r\n"
                    )
                elif sleep_calls == 2:
                    self.assertEqual(read_available(server), b"JOIN #pond\r\n")
                elif sleep_calls == 3:
                    control.request_stop("pilot complete")
                elif sleep_calls == 4:
                    self.assertEqual(
                        read_available(server),
                        b"QUIT :pilot complete\r\n",
                    )
                    server.close()

            runner = OperatorPilotRunner(
                pilot,
                scheduling,
                clock=IncrementingClock(),
                sleeper=sleeper,
            )
            result = runner.run(control)
            self.assertEqual(result.state, ProcessShellState.STOPPED)
            self.assertTrue(runner.telemetry.ready_observed)
            self.assertEqual(runner.telemetry.ready_entries, 1)
            self.assertEqual(runner.telemetry.schedule_accepted, 1)
            self.assertEqual(runner.telemetry.network_failures, 0)
            self.assertIsNotNone(pilot.shell.runtime.state.daily_schedule)
            records = JournalFile(root / "state" / "events.jsonl").read_records()
            self.assertEqual(len(records), 1)

    def test_stop_requested_before_run_opens_no_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = configuration(root)
            calls: list[tuple[tuple[str, int], float]] = []
            pilot = build_development_pilot(
                config,
                DevelopmentPilotGate(True, config.irc.endpoint(), ("#pond",)),
                {},
                resolver,
                connector=IRCSocketConnector(
                    config.irc.endpoint(),
                    dialer=lambda address, timeout: calls.append((address, timeout)),
                ),
                snapshot_interval=None,
            )
            scheduling = RuntimeSchedulingAdapter(
                pilot.shell.runtime,
                config.irc.channels,
                CalibratedScheduleSource(MinimumIntegerSource()),
            )
            control = PilotControl()
            control.request_stop("cancelled before start")
            runner = OperatorPilotRunner(
                pilot,
                scheduling,
                clock=lambda: 0,
            )
            result = runner.run(control)
            self.assertEqual(result.state, ProcessShellState.STOPPED)
            self.assertFalse(runner.telemetry.ready_observed)
            self.assertEqual(calls, [])

    def test_runner_failure_forces_bounded_transport_and_runtime_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = configuration(root)
            client, server = socket.socketpair()
            server.setblocking(False)
            self.addCleanup(client.close)
            self.addCleanup(server.close)
            pilot = build_development_pilot(
                config,
                DevelopmentPilotGate(True, config.irc.endpoint(), ("#pond",)),
                {},
                resolver,
                connector=IRCSocketConnector(
                    config.irc.endpoint(),
                    dialer=lambda address, timeout: client,
                ),
                snapshot_interval=None,
            )
            scheduling = RuntimeSchedulingAdapter(
                pilot.shell.runtime,
                config.irc.channels,
                CalibratedScheduleSource(MinimumIntegerSource()),
            )

            def broken_sleep(seconds: float) -> None:
                raise LookupError("injected runner failure")

            runner = OperatorPilotRunner(
                pilot,
                scheduling,
                clock=IncrementingClock(),
                sleeper=broken_sleep,
            )
            with self.assertRaises(LookupError):
                runner.run(PilotControl())
            self.assertEqual(pilot.shell.state, ProcessShellState.STOPPED)
            self.assertIn(b"QUIT :runner failure\r\n", read_available(server))

    def test_control_and_runner_policy_reject_ambiguous_values(self) -> None:
        control = PilotControl()
        with self.assertRaises(ValueError):
            control.request_stop("bad\nreason")
        with self.assertRaises(ValueError):
            control.request_stop(1)


if __name__ == "__main__":
    unittest.main()
