from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.admin import (
    PlayerAdministrationError,
    apply_player_update,
    apply_weapon_control,
)
from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.persistence.codec import SCHEMA_VERSION
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, replay_records


def player(**changes: object) -> PlayerState:
    values: dict[str, object] = {
        "key": rfc1459_casefold("Hunter"),
        "nickname": "Hunter",
        "ammo": 2,
        "capacity": 6,
        "magazines": 1,
        "magazine_capacity": 2,
        "experience": 4,
        "fatigue_centi": 2_500,
        "confiscated": True,
        "jammed": True,
    }
    values.update(changes)
    return PlayerState(**values)


class PartylineAdminTests(unittest.TestCase):
    def test_ammunition_and_magazine_grants_are_saturating(self) -> None:
        state = GameState(players=(player(),))
        ammunition = apply_player_update(
            state,
            "Hunter",
            1,
            field="ammo",
            operation="add",
            value=100,
        )
        magazines = apply_player_update(
            ammunition.state,
            "Hunter",
            2,
            field="magazines",
            operation="add",
            value=100,
        )
        self.assertEqual(
            (magazines.state.players[0].ammo, magazines.state.players[0].magazines),
            (6, 2),
        )

    def test_return_unjam_and_bounded_field_updates_preserve_invariants(self) -> None:
        state = GameState(players=(player(),))
        returned = apply_player_update(
            state,
            "Hunter",
            1,
            field="confiscated",
            operation="set",
            value=0,
        )
        unjammed = apply_player_update(
            returned.state,
            "Hunter",
            2,
            field="jammed",
            operation="set",
            value=0,
        )
        smaller = apply_player_update(
            unjammed.state,
            "Hunter",
            3,
            field="capacity",
            operation="set",
            value=1,
        )
        selected = smaller.state.players[0]
        self.assertFalse(selected.confiscated)
        self.assertFalse(selected.jammed)
        self.assertEqual((selected.capacity, selected.ammo), (1, 1))

    def test_invalid_player_field_value_and_identity_fail_closed(self) -> None:
        state = GameState(players=(player(),))
        for nickname, field, operation, value in (
            ("Unknown", "ammo", "add", 1),
            ("Hunter", "ammo", "add", 0),
            ("Hunter", "capacity", "set", 101),
            ("Hunter", "confiscated", "set", 2),
            ("Hunter", "experience", "set", 20),
            ("Hunter", "nickname", "set", 1),
        ):
            with self.subTest(nickname=nickname, field=field), self.assertRaises(
                PlayerAdministrationError
            ):
                apply_player_update(
                    state,
                    nickname,
                    1,
                    field=field,
                    operation=operation,
                    value=value,
                )

    def test_admin_events_round_trip_and_replay_from_schema_nineteen(self) -> None:
        event = ReplayEvent.admin_player_update(
            1,
            "Operator",
            "Hunter",
            field="ammo",
            operation="add",
            value=1,
        )
        self.assertEqual(event.kind, EventKind.ADMIN_PLAYER_UPDATE)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        applied = apply_replay_event(GameState(players=(player(),)), event)
        self.assertEqual(applied.state.players[0].ammo, 3)
        weapon_event = ReplayEvent.admin_weapon_control(
            2,
            "Op[e]rator",
            "Hunter",
            operation="unarm_permanent",
        )
        self.assertEqual(ReplayEvent.from_payload(weapon_event.to_payload()), weapon_event)
        disarmed = apply_replay_event(applied.state, weapon_event)
        self.assertTrue(disarmed.state.players[0].permanently_confiscated)
        rearmed = apply_weapon_control(
            disarmed.state,
            "Hunter",
            3,
            operation="rearm",
        )
        self.assertFalse(rearmed.state.players[0].confiscated)
        self.assertFalse(rearmed.state.players[0].permanently_confiscated)
        self.assertEqual(SCHEMA_VERSION, 20)

        with tempfile.TemporaryDirectory() as directory:
            journal = JournalFile(Path(directory) / "events.jsonl")
            record = journal.append(event)
            self.assertEqual(record.source_schema, 20)
            replayed = replay_records(
                journal.read_records(),
                initial_state=GameState(players=(player(),)),
            )
            self.assertEqual(replayed.state.players[0].ammo, 3)


if __name__ == "__main__":
    unittest.main()
