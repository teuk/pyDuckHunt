from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import GameState, OutcomeKind, ShotAttempt
from pyduckhunt.persistence import (
    GENESIS_DIGEST,
    JournalFile,
    JournalIntegrityError,
    ReplayEvent,
    Snapshot,
    SnapshotStore,
    recover,
    replay_records,
)
from pyduckhunt.persistence.replay import snapshot_from_result
from pyduckhunt.persistence.codec import canonical_json_bytes


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")


class RecoveryReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")

    def _record_complete_round(self) -> None:
        self.journal.append(ReplayEvent.start_flight(1_000_000_000, 5_000_000_000))
        self.journal.append(ReplayEvent.command(2_463_000_000, "Hunter", SHOT))
        self.journal.append(ReplayEvent.command(3_000_000_000, "Hunter", RELOAD))

    def test_replay_matches_direct_engine_state(self) -> None:
        self._record_complete_round()
        direct = start_flight(GameState(), 1_000_000_000, lifetime_ns=5_000_000_000)
        hit = apply_command(direct.state, "Hunter", SHOT, 2_463_000_000)
        reloaded = apply_command(hit.state, "Hunter", RELOAD, 3_000_000_000)
        replayed = replay_records(self.journal.read_records())
        self.assertEqual(replayed.state, reloaded.state)
        self.assertEqual(replayed.transitions[1].outcomes[-1].kind, OutcomeKind.HIT)
        self.assertEqual(replayed.transitions[1].outcomes[-1].elapsed_ms, 1463)

    def test_recover_without_snapshot_replays_genesis(self) -> None:
        self._record_complete_round()
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.last_sequence, 3)
        self.assertEqual(recovered.state.players[0].ammo, 5)

    def test_recover_from_snapshot_applies_only_tail(self) -> None:
        self._record_complete_round()
        records = self.journal.read_records()
        prefix = replay_records(records[:2])
        self.snapshots.write(snapshot_from_result(prefix))
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.last_sequence, 3)
        self.assertEqual(len(recovered.transitions), 1)
        self.assertEqual(recovered.state.players[0].ammo, 5)

    def test_schema_13_snapshot_replays_level_one_armament(self) -> None:
        self.journal.append(ReplayEvent.command(1, "Hunter", SHOT))
        result = replay_records(self.journal.read_records())
        self.snapshots.write(snapshot_from_result(result))
        raw = json.loads(self.snapshots.path.read_text(encoding="utf-8"))
        raw["schema"] = 13
        del raw["state"]["last_flight"]
        del raw["state"]["last_shooter_key"]
        del raw["state"]["players"][0]["permanently_confiscated"]
        for field in (
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del raw["state"]["players"][0][field]
        raw["state"]["players"][0]["ammo"] = 0
        raw["state"]["players"][0]["capacity"] = 1
        body = {
            key: raw[key]
            for key in ("journal_digest", "journal_sequence", "schema", "state")
        }
        raw["checksum"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        self.snapshots.path.write_bytes(canonical_json_bytes(raw) + b"\n")
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(
            (
                recovered.state.players[0].ammo,
                recovered.state.players[0].capacity,
            ),
            (5, 6),
        )
        self.assertEqual(len(recovered.transitions), 1)

    def test_schema_14_snapshot_replays_the_complete_journal(self) -> None:
        self.journal.append(ReplayEvent.command(1, "Hunter", SHOT))
        result = replay_records(self.journal.read_records())
        self.snapshots.write(snapshot_from_result(result))
        raw = json.loads(self.snapshots.path.read_text(encoding="utf-8"))
        raw["schema"] = 14
        del raw["state"]["last_flight"]
        del raw["state"]["last_shooter_key"]
        del raw["state"]["players"][0]["permanently_confiscated"]
        for field in (
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del raw["state"]["players"][0][field]
        body = {
            key: raw[key]
            for key in ("journal_digest", "journal_sequence", "schema", "state")
        }
        raw["checksum"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        self.snapshots.path.write_bytes(canonical_json_bytes(raw) + b"\n")
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.state.players[0].wild_shots, 1)
        self.assertEqual(len(recovered.transitions), 1)

    def test_snapshot_ahead_of_journal_is_rejected(self) -> None:
        self.snapshots.write(Snapshot(1, "1" * 64, GameState()))
        with self.assertRaises(JournalIntegrityError):
            recover(self.snapshots, self.journal)

    def test_snapshot_chain_mismatch_is_rejected(self) -> None:
        self.journal.append(ReplayEvent.advance_time(1))
        self.snapshots.write(Snapshot(1, "1" * 64, GameState(now_ns=1)))
        with self.assertRaises(JournalIntegrityError):
            recover(self.snapshots, self.journal)

    def test_empty_snapshot_uses_genesis(self) -> None:
        self.snapshots.write(Snapshot(0, GENESIS_DIGEST, GameState()))
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.last_digest, GENESIS_DIGEST)

    def test_schema_11_snapshot_replays_full_journal_to_rebuild_wild_shots(self) -> None:
        self.journal.append(ReplayEvent.command(1, "Hunter", SHOT))
        result = replay_records(self.journal.read_records())
        self.snapshots.write(snapshot_from_result(result))
        raw = json.loads(self.snapshots.path.read_text(encoding="utf-8"))
        raw["schema"] = 11
        del raw["state"]["last_flight"]
        del raw["state"]["last_shooter_key"]
        del raw["state"]["players"][0]["permanently_confiscated"]
        for field in (
            "compulsive_reloads",
            "empty_shots",
            "jammed_shots",
            "karma_decay_at_ns",
            "karma_modifier_basis_points",
            "wild_shots",
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del raw["state"]["players"][0][field]
        body = {
            key: raw[key]
            for key in ("journal_digest", "journal_sequence", "schema", "state")
        }
        raw["checksum"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        self.snapshots.path.write_bytes(canonical_json_bytes(raw) + b"\n")
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.state.players[0].wild_shots, 1)
        self.assertEqual(len(recovered.transitions), 1)

    def test_schema_19_snapshot_replays_full_journal_to_rebuild_profile_totals(self) -> None:
        self.journal.append(ReplayEvent.start_flight(1_000, 10_000))
        self.journal.append(ReplayEvent.command(2_000, "Hunter", SHOT))
        self.journal.append(ReplayEvent.purchase(3_000, "Hunter", 1, 7))
        self.journal.append(
            ReplayEvent.command(
                4_000,
                "Hunter",
                SHOT,
                shot_attempt=ShotAttempt(base_jam_bps=10_000, jam_roll=1),
            )
        )
        result = replay_records(self.journal.read_records())
        self.snapshots.write(snapshot_from_result(result))
        raw = json.loads(self.snapshots.path.read_text(encoding="utf-8"))
        raw["schema"] = 19
        for field in ("experience_spent", "jams", "shots_fired"):
            del raw["state"]["players"][0][field]
        body = {
            key: raw[key]
            for key in ("journal_digest", "journal_sequence", "schema", "state")
        }
        raw["checksum"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        self.snapshots.path.write_bytes(canonical_json_bytes(raw) + b"\n")

        recovered = recover(self.snapshots, self.journal)
        hunter = recovered.state.player("hunter")
        assert hunter is not None
        self.assertEqual(hunter.shots_fired, 1)
        self.assertEqual(hunter.jams, 1)
        self.assertEqual(hunter.experience_spent, 7)
        self.assertEqual(len(recovered.transitions), 4)


if __name__ == "__main__":
    unittest.main()
