from __future__ import annotations

import os
import signal
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pyduckhunt.irc import IRCEndpoint, IRCSocketConnector
from pyduckhunt.runtime import (
    PilotControl,
    ProcessShellState,
    prepare_operator_pilot,
    run_operator_pilot,
    run_service_pilot,
)


def write_configuration(
    path: Path,
    *,
    enabled: bool = True,
    anti_cheat: bool = False,
    state_directory: str = "state",
    log_directory: str = "logs",
    log_level: str = "INFO",
    ranking_page_path: str | None = None,
    metrics_page_path: str | None = None,
) -> None:
    ranking_line = (
        ""
        if ranking_page_path is None
        else f'ranking_page_path = "{ranking_page_path}"\n'
    )
    metrics_line = (
        ""
        if metrics_page_path is None
        else f'metrics_page_path = "{metrics_page_path}"\n'
    )
    path.write_text(
        f"""[irc]
host = "irc.pilot.example"
port = 6667
tls = false
nickname = "DuckBot"
fallback_nickname = "DuckBot_"
channels = ["#pond"]
password_environment = "PYDUCKHUNT_IRC_PASSWORD"

[runtime]
log_level = "{log_level}"
state_directory = "{state_directory}"
log_directory = "{log_directory}"
{ranking_line}
{metrics_line}

[game]
enabled = {str(enabled).lower()}
flights_per_day = 18
golden_weight_per_eighteen = 1
flight_lifetime_seconds = 300
unusual_loot_chance_per_thousand = 0
anti_cheat = {str(anti_cheat).lower()}
""",
        encoding="utf-8",
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


class OperatorLauncherTests(unittest.TestCase):
    def test_preflight_resolves_paths_without_files_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path)
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#POND",),
                {"PYDUCKHUNT_IRC_PASSWORD": "synthetic-secret"},
            )
            self.assertEqual(plan.configuration_path, config_path)
            self.assertEqual(plan.configuration.runtime.state_directory, root / "state")
            self.assertEqual(plan.configuration.runtime.log_directory, root / "logs")
            self.assertEqual(plan.target, "irc://irc.pilot.example:6667/#pond")
            self.assertEqual(
                plan.confirmation,
                "CONNECT irc://irc.pilot.example:6667/#pond AS DuckBot",
            )
            self.assertTrue(plan.password_configured)
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "logs").exists())

    def test_preflight_rejects_disabled_mismatch_and_overlapping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path, enabled=False)
            with self.assertRaises(RuntimeError):
                prepare_operator_pilot(
                    config_path,
                    IRCEndpoint("irc.pilot.example", 6667, False),
                    ("#pond",),
                    {},
                )

            write_configuration(config_path)
            with self.assertRaises(RuntimeError):
                prepare_operator_pilot(
                    config_path,
                    IRCEndpoint("other.example", 6667, False),
                    ("#pond",),
                    {},
                )

            write_configuration(
                config_path,
                state_directory="runtime",
                log_directory="runtime/logs",
            )
            with self.assertRaises(ValueError):
                prepare_operator_pilot(
                    config_path,
                    IRCEndpoint("irc.pilot.example", 6667, False),
                    ("#pond",),
                    {},
                )

    def test_wrong_confirmation_precedes_log_or_stream_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path)
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#pond",),
                {},
            )
            calls: list[tuple[tuple[str, int], float]] = []
            connector = IRCSocketConnector(
                plan.configuration.irc.endpoint(),
                dialer=lambda address, timeout: calls.append((address, timeout)),
            )
            with self.assertRaises(RuntimeError):
                run_operator_pilot(plan, "CONNECT something else", {}, connector=connector)
            self.assertEqual(calls, [])
            self.assertFalse((root / "logs").exists())
            self.assertFalse((root / "state").exists())

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'nickname = "DuckBot"',
                    'nickname = "ChangedBot"',
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_operator_pilot(
                    plan,
                    plan.confirmation,
                    {},
                    connector=connector,
                )
            self.assertEqual(calls, [])
            self.assertFalse((root / "logs").exists())

    def test_confirmed_foreground_run_stops_and_writes_public_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            ranking_directory = root / "public"
            ranking_directory.mkdir()
            ranking_path = ranking_directory / "player-rankings.html"
            metrics_directory = root / "metrics"
            metrics_directory.mkdir()
            metrics_path = metrics_directory / "pyduckhunt.prom"
            write_configuration(
                config_path,
                anti_cheat=True,
                log_level="DEBUG",
                ranking_page_path=str(ranking_path),
                metrics_page_path=str(metrics_path),
            )
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#pond",),
                {},
            )
            client, server = socket.socketpair()
            server.setblocking(False)
            self.addCleanup(client.close)
            self.addCleanup(server.close)
            connector = IRCSocketConnector(
                plan.configuration.irc.endpoint(),
                dialer=lambda address, timeout: client,
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

            integers = MinimumIntegerSource()
            with mock.patch(
                "pyduckhunt.runtime.operator.RandomizedFlightAppearanceSource"
            ) as appearance_factory:
                result = run_operator_pilot(
                    plan,
                    plan.confirmation,
                    {},
                    connector=connector,
                    control=control,
                    clock=IncrementingClock(),
                    sleeper=sleeper,
                    integer_source=integers,
                )
            appearance_factory.assert_called_once_with(integers)
            self.assertEqual(result.process.state, ProcessShellState.STOPPED)
            self.assertTrue(result.telemetry.ready_observed)
            self.assertEqual(result.telemetry.ready_entries, 1)
            self.assertEqual(result.telemetry.schedule_accepted, 1)
            self.assertEqual(result.telemetry.network_failures, 0)
            self.assertEqual(os.stat(result.log_path).st_mode & 0o777, 0o644)
            self.assertEqual(os.stat(result.application_log_path).st_mode & 0o777, 0o644)
            transcript = result.log_path.read_text(encoding="utf-8")
            self.assertIn("START target=irc://irc.pilot.example:6667/#pond", transcript)
            self.assertIn("RECOVERED sequence=0", transcript)
            self.assertIn(
                "STATE process=running transport=ready connected=yes",
                transcript,
            )
            self.assertIn("SCHEDULE event=plan-installed", transcript)
            self.assertEqual(result.application_log_path, root / "logs" / "pyduckhunt.log")
            self.assertIn("SUMMARY ready=yes", result.application_log_path.read_text())
            self.assertIn("DEBUG SCHEDULE reason=change", transcript)
            self.assertTrue(ranking_path.is_file())
            self.assertIn("PYDUCKHUNT_RANKING_PAGE_V1", ranking_path.read_text())
            self.assertTrue(metrics_path.is_file())
            metrics = metrics_path.read_text(encoding="ascii")
            self.assertIn("pyduckhunt_ready_entries_total 1", metrics)
            self.assertIn('pyduckhunt_process_state{state="stopped"} 1', metrics)
            self.assertIn("PUBLICATION status=updated", transcript)
            self.assertIn("SUMMARY ready=yes ready_entries=1", transcript)
            self.assertIn("STOP state=stopped failure=none", transcript)

    def test_service_signal_requests_stop_and_restores_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path)
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#pond",),
                {},
            )
            installed: dict[signal.Signals, object] = {}
            restored: list[tuple[signal.Signals, object]] = []
            previous = {
                signal.SIGTERM: object(),
                signal.SIGINT: object(),
            }

            def exchange_handler(signum: signal.Signals, handler: object) -> object:
                if callable(handler):
                    installed[signum] = handler
                    return previous[signum]
                restored.append((signum, handler))
                return installed[signum]

            expected = object()

            def fake_runner(*args: object, **kwargs: object) -> object:
                self.assertEqual(args[:3], (plan, plan.confirmation, {}))
                control = kwargs["control"]
                self.assertIsInstance(control, PilotControl)
                self.assertFalse(control.stop_requested)
                handler = installed[signal.SIGTERM]
                self.assertTrue(callable(handler))
                handler(signal.SIGTERM, None)
                self.assertTrue(control.stop_requested)
                self.assertEqual(control.reason, "service stop")
                return expected

            with (
                mock.patch(
                    "pyduckhunt.runtime.operator.signal.signal",
                    side_effect=exchange_handler,
                ),
                mock.patch(
                    "pyduckhunt.runtime.operator.run_operator_pilot",
                    side_effect=fake_runner,
                ),
            ):
                actual = run_service_pilot(plan, plan.confirmation, {})

            self.assertIs(actual, expected)
            self.assertEqual(
                restored,
                [
                    (signal.SIGINT, previous[signal.SIGINT]),
                    (signal.SIGTERM, previous[signal.SIGTERM]),
                ],
            )
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "logs").exists())

    def test_service_confirmation_precedes_signal_or_runtime_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path)
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#pond",),
                {},
            )
            with (
                mock.patch("pyduckhunt.runtime.operator.signal.signal") as signal_call,
                mock.patch(
                    "pyduckhunt.runtime.operator.run_operator_pilot"
                ) as runner_call,
            ):
                with self.assertRaises(RuntimeError):
                    run_service_pilot(plan, "wrong target", {})
            signal_call.assert_not_called()
            runner_call.assert_not_called()
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "logs").exists())

    def test_service_sigterm_completes_transport_and_persistence_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_configuration(config_path)
            plan = prepare_operator_pilot(
                config_path,
                IRCEndpoint("irc.pilot.example", 6667, False),
                ("#pond",),
                {},
            )
            client, server = socket.socketpair()
            server.setblocking(False)
            self.addCleanup(client.close)
            self.addCleanup(server.close)
            connector = IRCSocketConnector(
                plan.configuration.irc.endpoint(),
                dialer=lambda address, timeout: client,
            )
            installed: dict[signal.Signals, object] = {}

            def exchange_handler(signum: signal.Signals, handler: object) -> object:
                if callable(handler):
                    installed[signum] = handler
                return signal.SIG_DFL

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
                    handler = installed[signal.SIGTERM]
                    self.assertTrue(callable(handler))
                    handler(signal.SIGTERM, None)
                elif sleep_calls == 4:
                    self.assertEqual(
                        read_available(server),
                        b"QUIT :service stop\r\n",
                    )
                    server.close()

            with mock.patch(
                "pyduckhunt.runtime.operator.signal.signal",
                side_effect=exchange_handler,
            ):
                result = run_service_pilot(
                    plan,
                    plan.confirmation,
                    {},
                    connector=connector,
                    clock=IncrementingClock(),
                    sleeper=sleeper,
                    integer_source=MinimumIntegerSource(),
                )

            self.assertEqual(result.process.state, ProcessShellState.STOPPED)
            self.assertTrue(result.telemetry.ready_observed)
            self.assertTrue((root / "state" / "snapshot.json").is_file())
            transcript = result.log_path.read_text(encoding="utf-8")
            self.assertIn("STOP state=stopped failure=none", transcript)


if __name__ == "__main__":
    unittest.main()
