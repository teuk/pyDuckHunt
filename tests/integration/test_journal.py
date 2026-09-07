from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.persistence import JournalFile, JournalIntegrityError, ReplayEvent
from pyduckhunt.persistence.codec import canonical_json_bytes


class JournalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state" / "events.jsonl"

    def test_append_and_read_digest_chain(self) -> None:
        journal = JournalFile(self.path)
        first = journal.append(ReplayEvent.start_flight(1_000, 10_000))
        second = journal.append(
            ReplayEvent.command(2_000, "Hunter", Command(CommandKind.SHOT, "bang"))
        )
        records = journal.read_records()
        self.assertEqual(records, (first, second))
        self.assertEqual(second.previous_digest, first.digest)

    def test_new_writer_continues_existing_sequence(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        second = JournalFile(self.path).append(ReplayEvent.advance_time(2))
        self.assertEqual(second.sequence, 2)

    def test_journal_mode_is_private(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_tampered_payload_is_rejected(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["event"]["now_ns"] = 2
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(JournalIntegrityError):
            JournalFile(self.path).read_records()

    def test_partial_final_record_is_rejected(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        with self.path.open("ab") as handle:
            handle.write(b'{"partial":')
        with self.assertRaises(JournalIntegrityError):
            JournalFile(self.path).read_records()

    def test_unknown_schema_is_rejected(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["schema"] = 99
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(JournalIntegrityError):
            JournalFile(self.path).read_records()

    def test_schema_11_record_remains_readable_with_its_original_digest(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["schema"] = 11
        body = {
            key: record[key]
            for key in ("event", "previous_digest", "schema", "sequence")
        }
        record["digest"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        self.path.write_bytes(canonical_json_bytes(record) + b"\n")
        decoded = JournalFile(self.path).read_records()
        self.assertEqual(decoded[0].source_schema, 11)

    def test_unknown_event_kind_is_reported_as_integrity_failure(self) -> None:
        JournalFile(self.path).append(ReplayEvent.advance_time(1))
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["event"]["kind"] = "future_kind"
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(JournalIntegrityError):
            JournalFile(self.path).read_records()


if __name__ == "__main__":
    unittest.main()
