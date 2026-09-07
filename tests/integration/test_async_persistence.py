from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyduckhunt.persistence import JournalFile, ReplayEvent, SnapshotStore, recover
from pyduckhunt.runtime import PersistenceWorker, RuntimeOrchestrator


class AsyncPersistenceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")

    def test_worker_open_recovers_then_appends_a_new_tail(self) -> None:
        self.journal.append(ReplayEvent.advance_time(10))
        worker, recovered = PersistenceWorker.open(
            self.journal,
            self.snapshots,
            snapshot_interval=None,
        )
        self.assertEqual(recovered.state.now_ns, 10)
        reservation = worker.reserve()
        assert reservation is not None
        reservation.commit(ReplayEvent.advance_time(20)).wait(2)
        worker.close(2)
        final = recover(self.snapshots, self.journal)
        self.assertEqual(final.last_sequence, 2)
        self.assertEqual(final.state.now_ns, 20)

    def test_orchestrator_reopens_from_final_snapshot(self) -> None:
        first, _ = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            lambda batch: None,
            snapshot_interval=None,
        )
        result = first.dispatch(
            ReplayEvent.advance_time(30),
            lambda transition: (b"priority",),
        )
        assert result.persistence_ticket is not None
        result.persistence_ticket.wait(2)
        first.close(2)

        second, recovered = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            lambda batch: None,
            snapshot_interval=None,
        )
        self.assertEqual(recovered.state.now_ns, 30)
        self.assertEqual(second.state, recovered.state)
        second.close(2)

    def test_periodic_snapshot_and_journal_tail_recover_together(self) -> None:
        worker, _ = PersistenceWorker.open(
            self.journal,
            self.snapshots,
            capacity=3,
            snapshot_interval=2,
            snapshot_on_close=False,
        )
        tickets = []
        for now_ns in (10, 20, 30):
            reservation = worker.reserve()
            assert reservation is not None
            tickets.append(reservation.commit(ReplayEvent.advance_time(now_ns)))
        for ticket in tickets:
            ticket.wait(2)
        worker.close(2)
        snapshot = self.snapshots.read()
        assert snapshot is not None
        self.assertEqual(snapshot.journal_sequence, 2)
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.last_sequence, 3)
        self.assertEqual(recovered.state.now_ns, 30)
        self.assertEqual(len(recovered.transitions), 1)


if __name__ == "__main__":
    unittest.main()
