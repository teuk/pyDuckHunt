from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.persistence import GENESIS_DIGEST, Snapshot, SnapshotStore
from pyduckhunt.persistence.codec import CodecError, canonical_json_bytes


class SnapshotIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state" / "snapshot.json"
        self.store = SnapshotStore(self.path)

    def test_missing_snapshot_returns_none(self) -> None:
        self.assertIsNone(self.store.read())

    def test_atomic_round_trip(self) -> None:
        snapshot = Snapshot(0, GENESIS_DIGEST, GameState(now_ns=12))
        self.store.write(snapshot)
        self.assertEqual(self.store.read(), snapshot)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_replacement_leaves_no_temporary_file(self) -> None:
        self.store.write(Snapshot(0, GENESIS_DIGEST, GameState(now_ns=1)))
        self.store.write(Snapshot(0, GENESIS_DIGEST, GameState(now_ns=2)))
        self.assertEqual(self.store.read().state.now_ns, 2)
        leftovers = list(self.path.parent.glob(f".{self.path.name}.*"))
        self.assertEqual(leftovers, [])

    def test_failed_replace_preserves_previous_snapshot(self) -> None:
        original = Snapshot(0, GENESIS_DIGEST, GameState(now_ns=1))
        self.store.write(original)
        with patch("pyduckhunt.persistence.snapshot.os.replace", side_effect=OSError("stop")):
            with self.assertRaises(OSError):
                self.store.write(Snapshot(0, GENESIS_DIGEST, GameState(now_ns=2)))
        self.assertEqual(self.store.read(), original)
        self.assertEqual(list(self.path.parent.glob(f".{self.path.name}.*")), [])

    def test_checksum_detects_tampering(self) -> None:
        self.store.write(Snapshot(0, GENESIS_DIGEST, GameState(now_ns=1)))
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["state"]["now_ns"] = 2
        self.path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        with self.assertRaises(CodecError):
            self.store.read()

    def test_zero_sequence_requires_genesis_digest(self) -> None:
        with self.assertRaises(ValueError):
            Snapshot(0, "1" * 64, GameState())

    def test_schema_11_snapshot_is_validated_and_marked_for_migration(self) -> None:
        self.store.write(
            Snapshot(
                0,
                GENESIS_DIGEST,
                GameState(players=(PlayerState("hunter", "Hunter"),)),
            )
        )
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["schema"] = 11
        del raw["state"]["last_flight"]
        del raw["state"]["last_shooter_key"]
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
            "permanently_confiscated",
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
        self.path.write_bytes(canonical_json_bytes(raw) + b"\n")
        migrated = self.store.read()
        assert migrated is not None
        self.assertEqual(migrated.source_schema, 11)
        self.assertEqual(migrated.state.players[0].wild_shots, 0)


if __name__ == "__main__":
    unittest.main()
