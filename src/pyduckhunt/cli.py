"""Side-effect-free metadata plus an explicitly confirmed pilot command."""

from __future__ import annotations

import argparse
import getpass
import hmac
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pyduckhunt.irc.socket_adapter import IRCEndpoint
from pyduckhunt.partyline.users import PartylineUserStore
from pyduckhunt.runtime.operator import (
    OperatorPilotPlan,
    OperatorPilotResult,
    prepare_operator_pilot,
    run_operator_pilot,
    run_service_pilot,
)

from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build metadata and explicit development-pilot commands."""

    parser = argparse.ArgumentParser(
        prog="pyduckhunt",
        description="Fast, deterministic IRC game bot",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser(
        "pilot-check",
        help="validate one exact development target without connecting",
    )
    _add_pilot_target_arguments(check)
    run = commands.add_parser(
        "pilot-run",
        help="run one exact confirmed development target in the foreground",
    )
    _add_pilot_target_arguments(run)
    run.add_argument("--confirm-live", required=True)
    service = commands.add_parser(
        "service-run",
        help="run one exact confirmed target with bounded service signals",
    )
    _add_pilot_target_arguments(service)
    service.add_argument("--confirm-live", required=True)
    password_reset = commands.add_parser(
        "partyline-password-reset",
        help="interactively rotate one existing partyline credential",
    )
    password_reset.add_argument("--state-directory", required=True)
    password_reset.add_argument("--handle", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    live_runner: Callable[
        [OperatorPilotPlan, str, Mapping[str, str]],
        OperatorPilotResult,
    ] = run_operator_pilot,
    service_runner: Callable[
        [OperatorPilotPlan, str, Mapping[str, str]],
        OperatorPilotResult,
    ] = run_service_pilot,
    password_reader: Callable[[str], str] = getpass.getpass,
) -> int:
    """Run metadata, preflight, foreground pilot or bounded service command."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    if arguments.command == "partyline-password-reset":
        try:
            return _reset_partyline_password(
                arguments.state_directory,
                arguments.handle,
                password_reader,
            )
        except (OSError, RuntimeError, ValueError) as error:
            parser.exit(2, f"pyduckhunt: {error}\n")
    selected_environment = os.environ if environment is None else environment
    try:
        plan = prepare_operator_pilot(
            arguments.config,
            IRCEndpoint(
                arguments.allow_host,
                arguments.allow_port,
                arguments.allow_tls,
            ),
            tuple(arguments.allow_channel),
            selected_environment,
        )
        if arguments.command == "pilot-check":
            print(f"[OK] Pilot preflight: {plan.target}")
            print(f"[INFO] Confirmation: {plan.confirmation}")
            print("[INFO] No connection or runtime file was opened.")
            return 0
        selected_runner = (
            service_runner if arguments.command == "service-run" else live_runner
        )
        result = selected_runner(plan, arguments.confirm_live, selected_environment)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"pyduckhunt: {error}\n")
    print(f"[OK] Pilot finished: {result.process.state.value}")
    print(f"[INFO] Operator log: {result.log_path}")
    print(f"[INFO] Application log: {result.application_log_path}")
    print(
        "[INFO] Pilot telemetry: "
        f"ready={'yes' if result.telemetry.ready_observed else 'no'} "
        f"commands={result.telemetry.bridge_dispatched} "
        f"schedules={result.telemetry.schedule_accepted} "
        f"network_failures={result.telemetry.network_failures}"
    )
    if not result.telemetry.ready_observed:
        print("[KO] Pilot never reached IRC READY.")
    return 0 if result.process.state.value == "stopped" and (
        result.telemetry.ready_observed
    ) else 1


def _add_pilot_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--allow-host", required=True)
    parser.add_argument("--allow-port", required=True, type=int)
    security = parser.add_mutually_exclusive_group(required=True)
    security.add_argument("--allow-tls", dest="allow_tls", action="store_true")
    security.add_argument("--allow-plain", dest="allow_tls", action="store_false")
    parser.add_argument("--allow-channel", action="append", required=True)


def _reset_partyline_password(
    state_directory: str,
    handle: str,
    password_reader: Callable[[str], str],
) -> int:
    """Rotate one credential without accepting a secret on the command line."""

    state_path = Path(state_directory)
    if not state_path.is_absolute():
        raise ValueError("partyline state directory must be absolute")
    if state_path.is_symlink() or not state_path.is_dir():
        raise ValueError("partyline state directory must be a real directory")
    store = PartylineUserStore(state_path / "partyline-users.json")
    user = store.find(handle)
    if user is None:
        raise ValueError("partyline owner does not exist")
    password = password_reader("New password (12-128 characters): ")
    confirmation = password_reader("Confirm new password: ")
    if not hmac.compare_digest(password, confirmation):
        raise ValueError("partyline passwords differ; credential unchanged")
    updated = store.change_password(user.handle, password)
    if store.verify(updated.handle, password) is None:
        raise RuntimeError("partyline credential verification failed")
    print(f"[OK] Partyline credential rotated for {updated.handle}.")
    print("[INFO] No password was accepted through argv or written to output.")
    return 0
