from __future__ import annotations

import contextlib
import io
import unittest
import tempfile
from pathlib import Path

from pyduckhunt.cli import build_parser, main
from pyduckhunt.partyline.users import PartylineUserStore
from pyduckhunt.version import __version__


def write_pilot_configuration(path: Path) -> None:
    path.write_text(
        """[irc]
host = "irc.pilot.example"
port = 6697
tls = true
nickname = "DuckBot"
fallback_nickname = "DuckBot_"
channels = ["#pond"]
password_environment = "PYDUCKHUNT_IRC_PASSWORD"

[runtime]
log_level = "INFO"
state_directory = "state"
log_directory = "logs"

[game]
enabled = true
flights_per_day = 18
golden_weight_per_eighteen = 1
flight_lifetime_seconds = 300
unusual_loot_chance_per_thousand = 0
""",
        encoding="utf-8",
    )


class CliTests(unittest.TestCase):
    def test_version_output(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                build_parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"pyduckhunt {__version__}")

    def test_empty_command_is_side_effect_free(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("usage: pyduckhunt", output.getvalue())

    def test_pilot_check_prints_confirmation_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_pilot_configuration(config_path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "pilot-check",
                        "--config",
                        str(config_path),
                        "--allow-host",
                        "irc.pilot.example",
                        "--allow-port",
                        "6697",
                        "--allow-tls",
                        "--allow-channel",
                        "#pond",
                    ],
                    environment={},
                )
            self.assertEqual(result, 0)
            self.assertIn(
                "CONNECT ircs://irc.pilot.example:6697/#pond AS DuckBot",
                output.getvalue(),
            )
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "logs").exists())

    def test_pilot_run_rejects_wrong_confirmation_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pilot.toml"
            write_pilot_configuration(config_path)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as raised:
                    main(
                        [
                            "pilot-run",
                            "--config",
                            str(config_path),
                            "--allow-host",
                            "irc.pilot.example",
                            "--allow-port",
                            "6697",
                            "--allow-tls",
                            "--allow-channel",
                            "#pond",
                            "--confirm-live",
                            "wrong target",
                        ],
                        environment={},
                    )
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("confirmation does not match", errors.getvalue())
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "logs").exists())

    def test_service_run_requires_the_same_explicit_target_contract(self) -> None:
        arguments = build_parser().parse_args(
            [
                "service-run",
                "--config",
                "/configuration.toml",
                "--allow-host",
                "irc.pilot.example",
                "--allow-port",
                "6697",
                "--allow-tls",
                "--allow-channel",
                "#pond",
                "--confirm-live",
                "CONNECT exact target",
            ]
        )
        self.assertEqual(arguments.command, "service-run")
        self.assertEqual(arguments.allow_channel, ["#pond"])
        self.assertEqual(arguments.confirm_live, "CONNECT exact target")

    def test_partyline_password_reset_prompts_twice_and_rotates_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            store = PartylineUserStore(state / "partyline-users.json")
            old_password = "old private owner password"
            new_password = "new private owner password"
            store.create_first_owner(
                "Op[e]rator",
                old_password,
                42,
                irc_account="Operator",
                irc_mask="Op[e]rator!user@example",
            )
            responses = iter((new_password, new_password))
            prompts: list[str] = []

            def password_reader(prompt: str) -> str:
                prompts.append(prompt)
                return next(responses)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "partyline-password-reset",
                        "--state-directory",
                        str(state),
                        "--handle",
                        "op{e}rator",
                    ],
                    password_reader=password_reader,
                )
            self.assertEqual(result, 0)
            self.assertEqual(len(prompts), 2)
            self.assertIsNone(store.verify("Op[e]rator", old_password))
            self.assertIsNotNone(store.verify("Op[e]rator", new_password))
            self.assertNotIn(old_password, output.getvalue())
            self.assertNotIn(new_password, output.getvalue())

    def test_partyline_password_reset_mismatch_preserves_old_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            store = PartylineUserStore(state / "partyline-users.json")
            old_password = "old private owner password"
            store.create_first_owner(
                "Owner",
                old_password,
                42,
                irc_account="Owner",
                irc_mask="Owner!user@example",
            )
            responses = iter(("first replacement password", "different replacement"))
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as raised:
                    main(
                        [
                            "partyline-password-reset",
                            "--state-directory",
                            str(state),
                            "--handle",
                            "Owner",
                        ],
                        password_reader=lambda _prompt: next(responses),
                    )
            self.assertEqual(raised.exception.code, 2)
            self.assertIsNotNone(store.verify("Owner", old_password))
            self.assertIn("credential unchanged", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
