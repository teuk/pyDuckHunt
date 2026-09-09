from __future__ import annotations

import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyduckhunt.configuration import PartylineConfiguration
from pyduckhunt.game.model import (
    ActiveEffect,
    DailySchedule,
    EffectScope,
    FlightKind,
    GameState,
    PlayerState,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.message import parse_irc_line
from pyduckhunt.partyline.runtime import PartylineController, parse_dcc_chat
from pyduckhunt.persistence.event import EventKind
from pyduckhunt.persistence.journal import GENESIS_DIGEST, JournalFile
from pyduckhunt.persistence.snapshot import Snapshot, SnapshotStore
from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator


def drain(stream: socket.socket) -> bytes:
    stream.settimeout(0.03)
    payload = bytearray()
    while True:
        try:
            part = stream.recv(65_536)
        except (TimeoutError, socket.timeout, BlockingIOError):
            break
        if not part:
            break
        payload.extend(part)
    return bytes(payload)


class PartylineRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state_directory = self.root / "state"
        state = GameState(
            daily_schedule=DailySchedule(
                day_start_ns=0,
                deadlines_ns=tuple(
                    index * 1_000_000_000 for index in range(1, 19)
                ),
                next_index=4,
            ),
            players=(
                PlayerState(
                    key=rfc1459_casefold("Hunter"),
                    nickname="Hunter",
                    ammo=2,
                    magazines=0,
                    confiscated=True,
                    fatigue_centi=1_200,
                ),
            ),
            next_effect_id=2,
            effects=(
                ActiveEffect(
                    1,
                    22,
                    "duck_detector",
                    EffectScope.PLAYER,
                    rfc1459_casefold("Hunter"),
                    None,
                    0,
                    remaining_uses=1,
                ),
            ),
        )
        snapshots = SnapshotStore(self.state_directory / "snapshot.json")
        snapshots.write(Snapshot(0, GENESIS_DIGEST, state))
        self.journal = JournalFile(self.state_directory / "events.jsonl")
        self.wires: list[tuple[bytes, ...]] = []
        self.runtime, _ = RuntimeOrchestrator.open(
            self.journal,
            snapshots,
            self.wires.append,
        )
        self.events: list[str] = []
        self.controller = PartylineController(
            PartylineConfiguration(
                enabled=True,
                bind_host="127.0.0.1",
                port=0,
                bootstrap_accounts=("Operator",),
                bootstrap_masks=("Op[e]rator!*@trusted.example",),
                dcc_public_ip="203.0.113.10",
                dcc_port_min=0,
                dcc_port_max=0,
            ),
            self.runtime,
            self.state_directory,
            lambda: ("Coin", "ready", True, ("#marsh",)),
            observer=self.events.append,
            flight_lifetime_ns=10,
            anti_cheat=True,
            integer_source=lambda minimum, maximum: maximum,
            ranking_url="https://io.teuk.org/DuckHunt/rankings/",
        )
        self.controller.start(0)
        self.streams: list[socket.socket] = []
        self.addCleanup(self._close)

    def _close(self) -> None:
        for stream in self.streams:
            stream.close()
        self.controller.close("test")
        if self.runtime.persistence.state.value in ("running", "closing"):
            self.runtime.close(2)

    def _poll_twice(self, now_ns: int) -> None:
        self.controller.poll(now_ns)
        self.controller.poll(now_ns)

    def _bootstrap_over_offered_dcc(self, credential: str) -> socket.socket:
        hello = parse_irc_line(
            "@account=Operator :Op[e]rator!user@trusted.example PRIVMSG Coin :hello"
        )
        self.assertTrue(self.controller.handle_irc(1, hello, "Coin"))
        request = parse_irc_line(
            ":Op[e]rator!user@trusted.example PRIVMSG Coin :\x01CHAT\x01"
        )
        self.assertTrue(self.controller.handle_irc(2, request, "Coin"))
        rendered = b"".join(wire for batch in self.wires for wire in batch)
        match = re.search(rb"DCC CHAT chat \d+ (\d+)", rendered)
        self.assertIsNotNone(match)
        assert match is not None
        stream = socket.create_connection(("127.0.0.1", int(match.group(1))), timeout=1)
        self.streams.append(stream)
        self._poll_twice(3)
        self.assertIn(b"Coin Partyline", drain(stream))
        stream.sendall(b"Op[e]rator\n")
        self._poll_twice(4)
        self.assertIn(b"Choose a new password", drain(stream))
        stream.sendall(credential.encode() + b"\n")
        self._poll_twice(5)
        self.assertIn(b"Confirm password", drain(stream))
        stream.sendall(credential.encode() + b"\n")
        self._poll_twice(6)
        welcome = drain(stream)
        self.assertIn(b"Owner created", welcome)
        self.assertIn(b"IRC ready", welcome)
        return stream

    def test_bootstrap_dcc_login_profile_mutations_and_broadcast(self) -> None:
        credential = "one very private password"
        dcc = self._bootstrap_over_offered_dcc(credential)
        database = self.state_directory / "partyline-users.json"
        self.assertNotIn(credential, database.read_text(encoding="utf-8"))
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)

        dcc.sendall(b".player Hunter\n")
        self._poll_twice(7)
        profile = drain(dcc)
        self.assertIn(b"Player Hunter", profile)
        self.assertIn(b"ammo=2/6", profile)
        self.assertIn(b"confiscated=yes", profile)

        dcc.sendall(
            b".giveammo Hunter\n"
            b".givemag Hunter 2\n"
            b".returnweapon Hunter\n"
            b".unjam Hunter\n"
            b".setplayer Hunter fatigue 17\n"
            b".dccstat\n"
        )
        self._poll_twice(8)
        output = drain(dcc)
        self.assertIn(b"ammo 2 -> 3", output)
        self.assertIn(b"magazines 0 -> 2", output)
        self.assertIn(b"returned Hunter's weapon", output)
        self.assertIn(b"jammed no -> no", output)
        self.assertIn(b"fatigue_centi 12.00% -> 17.00%", output)
        self.assertIn(b"DCC Partyline status", output)
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertEqual(selected.ammo, 3)
        self.assertEqual(selected.magazines, 2)
        self.assertFalse(selected.confiscated)
        self.assertFalse(selected.permanently_confiscated)
        self.assertFalse(selected.jammed)
        self.assertEqual(selected.fatigue_centi, 1_700)
        self.runtime.persistence.flush(2)
        records = self.journal.read_records()
        self.assertEqual(len(records), 5)
        self.assertEqual(records[0].event.admin_actor, "Op[e]rator")

        port = self.controller.bound_port
        assert port is not None
        telnet = socket.create_connection(("127.0.0.1", port), timeout=1)
        self.streams.append(telnet)
        self._poll_twice(9)
        self.assertIn(b"Handle:", drain(telnet))
        telnet.sendall(b"Op[e]rator\n")
        self._poll_twice(10)
        password_prompt = drain(telnet)
        self.assertIn(bytes((255, 251, 1)), password_prompt)
        self.assertIn(b"Password:", password_prompt)
        telnet.sendall(credential.encode() + b"\n")
        self._poll_twice(11)
        authenticated = drain(telnet)
        self.assertIn(bytes((255, 252, 1)), authenticated)
        self.assertIn(b"Welcome to the Coin partyline", authenticated)
        drain(dcc)

        telnet.sendall(b"hello operators\n")
        self._poll_twice(12)
        self.assertIn(b"<Op[e]rator> hello operators", drain(telnet))
        self.assertIn(b"<Op[e]rator> hello operators", drain(dcc))
        self.assertFalse(any(credential in event for event in self.events))

        self.controller.observe_runtime(
            "APPLICATION dispatched=1 invalid=0 ignored=0 commands=shot"
        )
        self.controller.observe_runtime("DEBUG private diagnostic")
        self._poll_twice(13)
        observations = drain(telnet)
        self.assertIn(b"Coin APPLICATION", observations)
        self.assertNotIn(b"private diagnostic", observations)

        replacement = "replacement owner password"
        telnet.sendall(b".passwd\n")
        self._poll_twice(14)
        password_change = drain(telnet)
        self.assertIn(bytes((255, 251, 1)), password_change)
        self.assertIn(b"New password", password_change)
        telnet.sendall(replacement.encode() + b"\n")
        self._poll_twice(15)
        self.assertIn(b"Confirm new password", drain(telnet))
        telnet.sendall(replacement.encode() + b"\n")
        self._poll_twice(16)
        changed = drain(telnet)
        self.assertIn(bytes((255, 252, 1)), changed)
        self.assertIn(b"previous credential revoked", changed)
        self.assertIsNone(self.controller.user_store.verify("Op[e]rator", credential))
        self.assertIsNotNone(
            self.controller.user_store.verify("Op[e]rator", replacement)
        )
        self.assertFalse(any(replacement in event for event in self.events))

    def test_bootstrap_identity_is_required_and_password_is_refused_on_irc(self) -> None:
        denied = parse_irc_line(
            "@account=Other :Other!u@elsewhere PRIVMSG Coin :hello"
        )
        self.assertTrue(self.controller.handle_irc(1, denied, "Coin"))
        password_message = parse_irc_line(
            ":Other!u@elsewhere PRIVMSG Coin :pass secret-value"
        )
        self.assertTrue(self.controller.handle_irc(2, password_message, "Coin"))
        wires = b"".join(wire for batch in self.wires for wire in batch)
        self.assertIn("refusée".encode(), wires)
        self.assertIn(b"Mot de passe refuse", wires.replace("é".encode(), b"e"))
        self.assertNotIn(b"secret-value", wires)
        self.assertFalse(self.controller.user_store.has_users())

        allowed_by_literal_bracket_mask = parse_irc_line(
            ":Op[e]rator!user@trusted.example PRIVMSG Coin :hello"
        )
        self.assertTrue(
            self.controller.handle_irc(3, allowed_by_literal_bracket_mask, "Coin")
        )
        wires = b"".join(wire for batch in self.wires for wire in batch)
        self.assertIn(b"Bootstrap owner", wires)

    def test_authorized_irc_reset_replaces_lost_owner_credential(self) -> None:
        old_password = "old owner credential"
        replacement = "replacement owner credential"
        original = self._bootstrap_over_offered_dcc(old_password)
        self.wires.clear()

        repeated_hello = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :hello"
        )
        self.assertTrue(self.controller.handle_irc(20, repeated_hello, "Coin"))
        self.assertIn(b"/msg Coin reset", b"".join(self.wires[-1]))

        denied = parse_irc_line(
            "@account=Other :Op[e]rator!changed@elsewhere PRIVMSG Coin :reset"
        )
        self.assertTrue(self.controller.handle_irc(21, denied, "Coin"))
        self.assertIn("refusée".encode(), b"".join(self.wires[-1]))

        authorized = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :reset"
        )
        self.assertTrue(self.controller.handle_irc(22, authorized, "Coin"))
        self.assertIn("armée".encode(), b"".join(self.wires[-2]))
        request = parse_irc_line(
            ":Op[e]rator!changed@elsewhere PRIVMSG Coin :\x01CHAT\x01"
        )
        self.assertTrue(self.controller.handle_irc(23, request, "Coin"))
        rendered = b"".join(wire for batch in self.wires for wire in batch)
        offers = re.findall(rb"DCC CHAT chat \d+ (\d+)", rendered)
        self.assertTrue(offers)
        recovered = socket.create_connection(
            ("127.0.0.1", int(offers[-1])),
            timeout=1,
        )
        self.streams.append(recovered)
        self._poll_twice(24)
        self.assertIn(b"Coin Partyline", drain(recovered))
        recovered.sendall(b"Op[e]rator\n")
        self._poll_twice(25)
        self.assertIn(b"replacement password", drain(recovered))
        recovered.sendall(replacement.encode() + b"\n")
        self._poll_twice(26)
        self.assertIn(b"Confirm replacement", drain(recovered))
        recovered.sendall(replacement.encode() + b"\n")
        self._poll_twice(27)
        completed = drain(recovered)
        self.assertIn(b"Password reset complete", completed)
        self.assertIn(b"Welcome to the Coin partyline", completed)
        self.assertIsNone(self.controller.user_store.verify("Op[e]rator", old_password))
        self.assertIsNotNone(
            self.controller.user_store.verify("Op[e]rator", replacement)
        )
        self.assertIn(b"Credential reset", drain(original))
        self.assertFalse(any(replacement in event for event in self.events))
        self.assertTrue(
            any("event=password-reset handle=Op[e]rator" in event for event in self.events)
        )

    def test_owner_launches_standard_and_golden_flights_without_consuming_schedule(self) -> None:
        dcc = self._bootstrap_over_offered_dcc("another very private password")
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None

        dcc.sendall(b".duck\n")
        self._poll_twice(20)
        standard_output = drain(dcc)
        self.assertIn(b"launched duck #1 on #marsh", standard_output)
        self.assertEqual(self.runtime.state.flight.kind, FlightKind.STANDARD)
        self.assertEqual(self.runtime.state.daily_schedule, schedule)
        standard_wires = b"".join(wire for batch in self.wires for wire in batch)
        self.assertIn(b"PRIVMSG #marsh :", standard_wires)
        self.assertIn(b"NOTICE Hunter :", standard_wires)
        self.assertEqual(self.runtime.state.effects, ())

        dcc.sendall(b".goldenduck\n")
        self._poll_twice(21)
        self.assertIn(b"duck #1 is still active", drain(dcc))
        self.runtime.persistence.flush(2)
        self.assertEqual(len(self.journal.read_records()), 1)

        dcc.sendall(b".golden #MARSH\n")
        self._poll_twice(31)
        golden_output = drain(dcc)
        self.assertIn(b"launched golden duck #2 on #marsh (hp=5)", golden_output)
        flight = self.runtime.state.flight
        assert flight is not None
        self.assertEqual(flight.kind, FlightKind.GOLDEN)
        self.assertEqual(flight.health, 5)
        self.assertEqual(flight.reward_experience, 60)
        self.assertEqual(self.runtime.state.daily_schedule, schedule)
        golden_wires = b"".join(wire for batch in self.wires for wire in batch)
        self.assertNotIn("CANARD DORÉ".encode(), golden_wires)
        self.runtime.persistence.flush(2)
        records = self.journal.read_records()
        self.assertEqual([record.event.kind for record in records], [EventKind.START_FLIGHT] * 2)
        self.assertTrue(any("event=flight-launch" in event for event in self.events))

    def test_owner_private_message_launch_is_strict_silent_and_schedule_neutral(self) -> None:
        self._bootstrap_over_offered_dcc("private launch owner password")
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None

        spoof = parse_irc_line(
            "@account=Other :Op[e]rator!user@trusted.example PRIVMSG Coin :ducklaunch #marsh"
        )
        before_wires = len(self.wires)
        self.assertTrue(self.controller.handle_irc(20, spoof, "Coin"))
        self.assertIsNone(self.runtime.state.flight)
        self.assertEqual(len(self.wires), before_wires)

        malformed = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :ducklaunch #marsh 0"
        )
        self.assertTrue(self.controller.handle_irc(21, malformed, "Coin"))
        self.assertIsNone(self.runtime.state.flight)
        self.assertIn(b"ducklaunch #canal [1]", self.wires[-1][0])

        standard = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :ducklaunch #MARSH"
        )
        self.assertTrue(self.controller.handle_irc(22, standard, "Coin"))
        flight = self.runtime.state.flight
        assert flight is not None
        self.assertEqual(flight.kind, FlightKind.STANDARD)
        self.assertEqual(self.runtime.state.daily_schedule, schedule)
        rendered = b"".join(wire for batch in self.wires for wire in batch)
        self.assertIn(b"NOTICE Op[e]rator :Canard #1 lance", rendered.replace("é".encode(), b"e"))

        golden = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :ducklaunch #marsh 1"
        )
        self.assertTrue(self.controller.handle_irc(33, golden, "Coin"))
        flight = self.runtime.state.flight
        assert flight is not None
        self.assertEqual(flight.kind, FlightKind.GOLDEN)
        self.assertEqual(flight.health, 5)
        self.assertEqual(flight.reward_experience, 60)
        self.assertEqual(self.runtime.state.daily_schedule, schedule)
        self.runtime.persistence.flush(2)
        self.assertEqual(
            [record.event.kind for record in self.journal.read_records()],
            [EventKind.START_FLIGHT, EventKind.START_FLIGHT],
        )

    def test_spontaneous_launch_announces_then_starts_without_schedule_drift(self) -> None:
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        self.controller.configuration = PartylineConfiguration(
            enabled=True,
            bind_host="127.0.0.1",
            port=0,
            bootstrap_accounts=("Operator",),
            bootstrap_masks=("Op[e]rator!*@trusted.example",),
            dcc_public_ip="203.0.113.10",
            dcc_port_min=0,
            dcc_port_max=0,
            spontaneous_launch_enabled=True,
            spontaneous_launch_channel="#marsh",
            spontaneous_launch_min_seconds=900,
            spontaneous_launch_max_seconds=900,
            spontaneous_launch_announcement="allez, je lance un canard",
        )
        self.controller._next_spontaneous_launch_ns = 20
        self.assertTrue(self.controller.poll(20))
        flight = self.runtime.state.flight
        assert flight is not None
        self.assertEqual(flight.kind, FlightKind.STANDARD)
        self.assertEqual(self.runtime.state.daily_schedule, schedule)
        batch = self.wires[-1]
        channel_lines = tuple(wire for wire in batch if wire.startswith(b"PRIVMSG #marsh :"))
        self.assertGreaterEqual(len(channel_lines), 2)
        self.assertIn(b"allez, je lance un canard", channel_lines[0])
        self.assertNotIn(b"allez, je lance un canard", channel_lines[1])
        self.assertEqual(
            self.controller._next_spontaneous_launch_ns,
            20 + 900 * 1_000_000_000,
        )

        self.runtime.persistence.flush(2)
        before_records = len(self.journal.read_records())
        before_wires = len(self.wires)
        self.controller._next_spontaneous_launch_ns = 21
        self.assertTrue(self.controller.poll(21))
        self.runtime.persistence.flush(2)
        self.assertEqual(len(self.journal.read_records()), before_records)
        self.assertEqual(len(self.wires), before_wires)
        self.assertTrue(
            any("event=spontaneous-launch-skipped" in event for event in self.events)
        )

    def test_summary_lists_top_five_profiles_inventories_and_last_shooter(self) -> None:
        players = tuple(
            sorted(
                (
                    PlayerState(
                        name.casefold(),
                        name,
                        hits=hits,
                        best_time_ms=1_000 + hits,
                    )
                    for name, hits in (
                        ("Alpha", 50),
                        ("Bravo", 40),
                        ("Charlie", 30),
                        ("Delta", 20),
                        ("Echo", 10),
                        ("Zulu", 1),
                    )
                ),
                key=lambda player: player.key,
            )
        )
        self.runtime._state = GameState(
            players=players,
            last_shooter_key="zulu",
        )
        lines = self.controller._summary_lines()
        rendered = "\n".join(lines)
        self.assertIn("Coin · résumé DuckHunt", rendered)
        self.assertIn("[TOP 5]", rendered)
        self.assertIn("https://io.teuk.org/DuckHunt/rankings/", rendered)
        self.assertIn("--- #5 · Echo ---", rendered)
        self.assertNotIn("--- #6", rendered)
        self.assertIn("=== Dernier tireur ===\n--- Zulu ---", rendered)
        self.assertEqual(rendered.count("[Profil]"), 6)
        self.assertEqual(rendered.count("[Inventaire]"), 6)
        self.assertNotIn("\x03", rendered)

        self.controller._statistics_excluded_nicknames = ("Alpha",)
        excluded = "\n".join(self.controller._summary_lines())
        self.assertNotIn("--- #1 · Alpha ---", excluded)
        self.assertIn("--- #1 · Bravo ---", excluded)

        self.runtime._state = GameState(
            players=players,
            last_shooter_key="alpha",
        )
        excluded_last = "\n".join(self.controller._summary_lines())
        self.assertNotIn("=== Dernier tireur ===\n--- Alpha", excluded_last)
        self.assertIn("=== Dernier tireur ===\nAucun tir enregistré.", excluded_last)

    def test_irc_weapon_control_requires_the_registered_partyline_owner(self) -> None:
        self._bootstrap_over_offered_dcc("owner weapon control password")
        spoof = parse_irc_line(
            "@account=Other :Op[e]rator!user@trusted.example PRIVMSG #marsh :!unarm -permanent Hunter"
        )
        before_wires = len(self.wires)
        self.assertTrue(self.controller.handle_irc(20, spoof, "Coin"))
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertFalse(selected.permanently_confiscated)
        self.assertEqual(len(self.wires), before_wires)

        owner = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG #marsh :!unarm -permanent Hunter"
        )
        self.assertTrue(self.controller.handle_irc(21, owner, "Coin"))
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertTrue(selected.confiscated)
        self.assertTrue(selected.permanently_confiscated)
        self.assertIn("façon permanente".encode(), self.wires[-1][0])

        owner_without_account_tag = parse_irc_line(
            ":Op[e]rator!user@trusted.example PRIVMSG #marsh :!rearm Hunter"
        )
        self.assertTrue(
            self.controller.handle_irc(22, owner_without_account_tag, "Coin")
        )
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertFalse(selected.confiscated)
        self.assertFalse(selected.permanently_confiscated)
        self.assertIn("Arme de Hunter restituée".encode(), self.wires[-1][0])

        private_temporary = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :unarm Hunter"
        )
        self.assertTrue(self.controller.handle_irc(23, private_temporary, "Coin"))
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertTrue(selected.confiscated)
        self.assertFalse(selected.permanently_confiscated)
        self.assertIn(b"NOTICE Op[e]rator :", self.wires[-1][0])
        self.assertIn("minuit, heure de Paris".encode(), self.wires[-1][0])

        private_permanent = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :unarm -permanent Hunter"
        )
        self.assertTrue(self.controller.handle_irc(24, private_permanent, "Coin"))
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertTrue(selected.permanently_confiscated)
        self.assertIn("façon permanente".encode(), self.wires[-1][0])

        private_rearm = parse_irc_line(
            "@account=Operator :Op[e]rator!changed@elsewhere PRIVMSG Coin :rearm Hunter"
        )
        self.assertTrue(self.controller.handle_irc(25, private_rearm, "Coin"))
        selected = self.runtime.state.player("hunter")
        assert selected is not None
        self.assertFalse(selected.confiscated)
        self.assertFalse(selected.permanently_confiscated)
        self.assertIn("Arme de Hunter restituée".encode(), self.wires[-1][0])
        self.runtime.persistence.flush(2)
        self.assertEqual(
            [record.event.kind for record in self.journal.read_records()],
            [EventKind.ADMIN_WEAPON_CONTROL] * 5,
        )

    def test_owner_channel_items_are_free_replayable_and_admin_only(self) -> None:
        self._bootstrap_over_offered_dcc("owner channel item password")
        spoof = parse_irc_line(
            "@account=Other :Op[e]rator!user@trusted.example PRIVMSG #marsh :!pain"
        )
        before_wires = len(self.wires)
        self.assertTrue(self.controller.handle_irc(20, spoof, "Coin"))
        self.assertEqual(len(self.runtime.state.effects), 1)
        self.assertEqual(len(self.wires), before_wires)

        pain = parse_irc_line(
            "@account=Operator :ChangedNick!elsewhere@changed PRIVMSG #marsh :!pain"
        )
        self.assertTrue(self.controller.handle_irc(21, pain, "Coin"))
        self.assertEqual(len(self.runtime.state.players), 1)
        self.assertEqual(
            sum(effect.item_id == 21 for effect in self.runtime.state.effects),
            1,
        )
        self.assertIn("déposes un morceau de pain".encode(), self.wires[-1][0])
        self.assertTrue(all(wire.startswith(b"NOTICE ChangedNick :") for wire in self.wires[-1]))
        self.assertIn(b"prochain envol quotidien ne change pas", self.wires[-1][0])

        appeau = parse_irc_line(
            "@account=Operator :AnotherNick!elsewhere@changed PRIVMSG #marsh :!appeau"
        )
        self.assertTrue(self.controller.handle_irc(22, appeau, "Coin"))
        self.assertEqual(len(self.runtime.state.players), 1)
        self.assertEqual(self.runtime.state.scheduled_actions[-1].item_id, 20)
        self.assertEqual(
            self.runtime.state.scheduled_actions[-1].due_at_ns,
            22 + 10 * 60 * 1_000_000_000,
        )
        self.assertTrue(all(wire.startswith(b"NOTICE AnotherNick :") for wire in self.wires[-1]))
        self.assertIn(b"01/01 01:10:00 CET", self.wires[-1][0])
        self.assertIn(b"prochain envol quotidien ne change pas", self.wires[-1][0])

        malformed = parse_irc_line(
            "@account=Operator :Op[e]rator!elsewhere@changed PRIVMSG #marsh :!pain extra"
        )
        self.assertTrue(self.controller.handle_irc(23, malformed, "Coin"))
        self.assertIn(b"Usage : !pain", self.wires[-1][0])
        self.assertTrue(all(wire.startswith(b"NOTICE Op[e]rator :") for wire in self.wires[-1]))
        self.assertTrue(all(
            wire.startswith(b"NOTICE ")
            for batch in self.wires[before_wires:] for wire in batch
        ))
        self.runtime.persistence.flush(2)
        self.assertEqual(
            [record.event.kind for record in self.journal.read_records()],
            [EventKind.ADMIN_CHANNEL_ITEM, EventKind.ADMIN_CHANNEL_ITEM],
        )

    def test_owner_item_rejections_remain_private_without_mutating_state(self) -> None:
        self._bootstrap_over_offered_dcc("private rejection password")
        original = self.runtime.state
        for command in ("!pain", "!appeau"):
            message = parse_irc_line(
                "@account=Operator :ChangedNick!elsewhere@changed "
                f"PRIVMSG #marsh :{command}"
            )
            for refusal in ("validation", "backpressure"):
                with self.subTest(command=command, refusal=refusal):
                    before = len(self.wires)
                    if refusal == "validation":
                        gate = patch(
                            "pyduckhunt.partyline.runtime.apply_admin_channel_item",
                            side_effect=ValueError("invalid item"),
                        )
                    else:
                        gate = patch.object(self.runtime.persistence, "reserve", return_value=None)
                    with gate:
                        self.assertTrue(self.controller.handle_irc(20, message, "Coin"))
                    replies = tuple(wire for batch in self.wires[before:] for wire in batch)
                    self.assertTrue(replies)
                    self.assertTrue(all(wire.startswith(b"NOTICE ChangedNick :") for wire in replies))
                    self.assertEqual(self.runtime.state, original)
        self.runtime.persistence.flush(2)
        self.assertEqual(self.journal.read_records(), ())

    def test_hourly_owner_bread_is_private_and_delays_without_consumption(self) -> None:
        from pyduckhunt.persistence.event import ReplayEvent
        self.runtime.dispatch(ReplayEvent.enable_hourly_bread(self.runtime.state.now_ns), lambda t: ())
        dcc = self._bootstrap_over_offered_dcc("hourly owner bread password")
        message = parse_irc_line(
            "@account=Operator :ChangedNick!elsewhere@changed PRIVMSG #marsh :!pain")
        before = len(self.wires)
        self.controller.handle_irc(20, message, "Coin")
        replies = tuple(wire for batch in self.wires[before:] for wire in batch)
        self.assertTrue(replies)
        self.assertTrue(all(wire.startswith(b"NOTICE ChangedNick :") for wire in replies))
        self.assertIn(b"Actif 1h", b" ".join(replies))
        self.assertIn("conservé".encode(), b" ".join(replies))
        self.runtime.dispatch(ReplayEvent.start_flight(21, 300_000_000_000), lambda t: ())
        self.assertEqual(self.runtime.state.flight.expires_at_ns, 21 + 320_000_000_000)
        self.assertTrue(any(e.item_id == 21 for e in self.runtime.state.effects))
        dcc.sendall(b".duckplanning\n")
        self._poll_twice(22)
        self.assertIn("pain conservé".encode(), drain(dcc))

    def test_duckplanning_is_owner_private_complete_and_partyline_live(self) -> None:
        dcc = self._bootstrap_over_offered_dcc("owner duckplanning password")
        self.runtime._state = GameState(
            daily_schedule=DailySchedule(
                day_start_ns=0,
                deadlines_ns=tuple(
                    index * 3_600_000_000_000 + 1_800_000_000_000
                    for index in range(24)
                ),
                next_index=9,
            ),
            effects=self.runtime.state.effects,
            next_effect_id=self.runtime.state.next_effect_id,
            players=self.runtime.state.players,
        )

        before = len(self.wires)
        channel = parse_irc_line(
            "@account=Operator :ChangedNick!elsewhere@changed "
            "PRIVMSG #marsh :!duckplanning"
        )
        self.assertTrue(self.controller.handle_irc(20, channel, "Coin"))
        channel_wires = tuple(wire for batch in self.wires[before:] for wire in batch)
        self.assertTrue(channel_wires)
        self.assertTrue(all(wire.startswith(b"NOTICE ChangedNick :") for wire in channel_wires))
        rendered = b" ".join(channel_wires)
        self.assertIn(b"9/24", rendered)
        self.assertIn(b"Vols 01-06", rendered)
        self.assertIn(b"Vols 19-24", rendered)
        self.assertIn(b"24", rendered)
        self.assertIn(b"Europe/Paris", rendered)
        self.assertIn(b"Prochain quotidien", rendered)

        private = parse_irc_line(
            "@account=Operator :YetAnotherNick!elsewhere@changed "
            "PRIVMSG Coin :duckplanning"
        )
        before = len(self.wires)
        self.assertTrue(self.controller.handle_irc(21, private, "Coin"))
        private_wires = tuple(wire for batch in self.wires[before:] for wire in batch)
        self.assertTrue(private_wires)
        self.assertTrue(all(wire.startswith(b"NOTICE YetAnotherNick :") for wire in private_wires))

        spoof = parse_irc_line(
            "@account=Other :ChangedNick!elsewhere@changed "
            "PRIVMSG #marsh :!duckplanning"
        )
        before = len(self.wires)
        self.assertTrue(self.controller.handle_irc(22, spoof, "Coin"))
        self.assertEqual(len(self.wires), before)

        dcc.sendall(b".duckplanning\n")
        self._poll_twice(23)
        partyline = drain(dcc)
        self.assertIn(b"Duckplanning #marsh", partyline)
        self.assertIn(b"Vols 19-24", partyline)

        self.controller.observe_runtime(
            "DUCKPLANNING reason=channel-items-change actions=1 bread=2"
        )
        self._poll_twice(24)
        automatic = drain(dcc)
        self.assertIn(b"duckplanning changed", automatic)
        self.assertIn(b"Vols 01-06", automatic)
        self.assertIn(b"Pains=", automatic)
        self.assertEqual(len(self.wires), before)

    def test_manual_launch_requires_an_unambiguous_joined_channel(self) -> None:
        dcc = self._bootstrap_over_offered_dcc("one more private password")
        self.controller._network_status = lambda: (
            "Coin",
            "ready",
            True,
            ("#marsh", "#pond"),
        )
        dcc.sendall(b".duck\n")
        self._poll_twice(20)
        self.assertIn(b"specify one joined channel", drain(dcc))
        self.assertIsNone(self.runtime.state.flight)

        dcc.sendall(b".duck #elsewhere\n")
        self._poll_twice(21)
        self.assertIn(b"not joined to #elsewhere", drain(dcc))
        self.assertIsNone(self.runtime.state.flight)

    def test_dcc_parser_accepts_active_and_passive_and_rejects_ssrf_targets(self) -> None:
        active = parse_dcc_chat("DCC CHAT chat 134744072 50000")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual((str(active[0]), active[1], active[2]), ("8.8.8.8", 50000, None))
        self.assertEqual(
            parse_dcc_chat("DCC CHAT chat 0 0 token-42"),
            (None, 0, "token-42"),
        )
        for payload in (
            "DCC CHAT chat 2130706433 50000",
            "DCC CHAT chat 3232235777 50000",
            "DCC CHAT chat 134744072 22",
            "DCC CHAT chat 134744072 50000 extra-token",
            "DCC CHAT chat 0 0 bad/token",
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(parse_dcc_chat(payload))

    def test_fragmented_telnet_negotiation_is_not_treated_as_a_handle(self) -> None:
        port = self.controller.bound_port
        assert port is not None
        telnet = socket.create_connection(("127.0.0.1", port), timeout=1)
        self.streams.append(telnet)
        self._poll_twice(1)
        self.assertIn(b"Handle:", drain(telnet))

        telnet.sendall(bytes((255, 253)))
        self._poll_twice(2)
        telnet.sendall(bytes((1, 255, 250, 31, 0, 80, 0, 24, 255, 240)))
        self._poll_twice(3)
        telnet.sendall(b"Unknown\n")
        self._poll_twice(4)
        response = drain(telnet)
        self.assertIn(b"Initialization requires", response)
        self.assertNotIn(b"Invalid UTF-8", response)


if __name__ == "__main__":
    unittest.main()
