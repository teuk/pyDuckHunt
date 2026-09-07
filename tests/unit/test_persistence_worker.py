from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pyduckhunt.game.model import GameState
from pyduckhunt.persistence import (
    GENESIS_DIGEST,
    JournalFile,
    ReplayEvent,
    ReplayResult,
    SnapshotStore,
)
from pyduckhunt.runtime import (
    PersistenceWorker,
    PersistenceWorkerClosed,
    PersistenceWorkerError,
    PersistenceWorkerFailed,
    PersistenceWorkerState,
)


class PersistenceWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")
        self.empty = ReplayResult(GameState(), 0, GENESIS_DIGEST, ())
        self.workers: list[PersistenceWorker] = []
        self.addCleanup(self._close_workers)

    def _worker(self, **options: object) -> PersistenceWorker:
        worker = PersistenceWorker(
            self.journal,
            self.snapshots,
            self.empty,
            **options,
        )
        worker.start()
        self.workers.append(worker)
        return worker

    def _close_workers(self) -> None:
        for worker in self.workers:
            if worker.state in (
                PersistenceWorkerState.RUNNING,
                PersistenceWorkerState.CLOSING,
            ):
                worker.close(2)

    def test_capacity_is_reserved_without_waiting(self) -> None:
        worker = self._worker(capacity=1)
        reservation = worker.reserve()
        self.assertIsNotNone(reservation)
        self.assertIsNone(worker.reserve())
        assert reservation is not None
        reservation.cancel()
        replacement = worker.reserve()
        self.assertIsNotNone(replacement)
        assert replacement is not None
        replacement.cancel()

    def test_context_manager_returns_a_cancelled_slot(self) -> None:
        worker = self._worker(capacity=1)
        with worker.reserve() as reservation:
            self.assertTrue(reservation.active)
        replacement = worker.reserve()
        self.assertIsNotNone(replacement)
        assert replacement is not None
        replacement.cancel()

    def test_worker_appends_accepted_events_in_order(self) -> None:
        worker = self._worker(capacity=2, snapshot_interval=None)
        first = worker.reserve()
        second = worker.reserve()
        assert first is not None and second is not None
        first_ticket = first.commit(ReplayEvent.advance_time(1))
        second_ticket = second.commit(ReplayEvent.advance_time(2))
        self.assertEqual(first_ticket.wait(2).sequence, 1)
        self.assertEqual(second_ticket.wait(2).sequence, 2)
        self.assertEqual(
            tuple(record.event.now_ns for record in self.journal.read_records()),
            (1, 2),
        )

    def test_processing_request_keeps_its_capacity_slot(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original_append = self.journal.append

        def blocking_append(event: ReplayEvent):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test did not release journal append")
            return original_append(event)

        worker = self._worker(capacity=1)
        with patch.object(self.journal, "append", side_effect=blocking_append):
            reservation = worker.reserve()
            assert reservation is not None
            ticket = reservation.commit(ReplayEvent.advance_time(1))
            self.assertTrue(entered.wait(2))
            self.assertIsNone(worker.reserve())
            release.set()
            ticket.wait(2)
        replacement = worker.reserve()
        self.assertIsNotNone(replacement)
        assert replacement is not None
        replacement.cancel()

    def test_periodic_snapshot_uses_worker_replay_state(self) -> None:
        worker = self._worker(capacity=2, snapshot_interval=2)
        first = worker.reserve()
        second = worker.reserve()
        assert first is not None and second is not None
        first.commit(ReplayEvent.advance_time(10)).wait(2)
        second.commit(ReplayEvent.advance_time(20)).wait(2)
        worker.flush(2)
        snapshot = self.snapshots.read()
        assert snapshot is not None
        self.assertEqual(snapshot.journal_sequence, 2)
        self.assertEqual(snapshot.state.now_ns, 20)

    def test_state_publisher_observes_each_durable_transition(self) -> None:
        published: list[GameState] = []
        worker = self._worker(
            snapshot_interval=None,
            state_publisher=published.append,
        )
        reservation = worker.reserve()
        assert reservation is not None
        reservation.commit(ReplayEvent.advance_time(7)).wait(2)
        self.assertEqual(tuple(state.now_ns for state in published), (7,))
        self.assertEqual(worker.publication_attempts, 1)
        self.assertEqual(worker.publication_failures, 0)
        self.assertIsNone(worker.last_publication_error)

    def test_state_publisher_failure_never_latches_persistence(self) -> None:
        def failed_publisher(state: GameState) -> None:
            del state
            raise OSError("publisher unavailable")

        worker = self._worker(
            snapshot_interval=None,
            state_publisher=failed_publisher,
        )
        reservation = worker.reserve()
        assert reservation is not None
        self.assertEqual(
            reservation.commit(ReplayEvent.advance_time(8)).wait(2).sequence,
            1,
        )
        self.assertEqual(worker.state, PersistenceWorkerState.RUNNING)
        self.assertEqual(worker.publication_attempts, 1)
        self.assertEqual(worker.publication_failures, 1)
        self.assertEqual(worker.last_publication_error, "OSError")

    def test_clean_close_writes_the_final_snapshot(self) -> None:
        worker = self._worker(snapshot_interval=None)
        reservation = worker.reserve()
        assert reservation is not None
        reservation.commit(ReplayEvent.advance_time(25)).wait(2)
        worker.close(2)
        snapshot = self.snapshots.read()
        assert snapshot is not None
        self.assertEqual(snapshot.journal_sequence, 1)
        self.assertEqual(snapshot.state.now_ns, 25)
        self.assertEqual(worker.state, PersistenceWorkerState.CLOSED)

    def test_flush_and_close_reject_an_open_reservation(self) -> None:
        worker = self._worker()
        reservation = worker.reserve()
        assert reservation is not None
        with self.assertRaises(PersistenceWorkerError):
            worker.flush(0)
        with self.assertRaises(PersistenceWorkerError):
            worker.close(0)
        reservation.cancel()

    def test_failed_append_is_latched_and_stops_admission(self) -> None:
        worker = self._worker()
        with patch.object(self.journal, "append", side_effect=OSError("disk stopped")):
            reservation = worker.reserve()
            assert reservation is not None
            ticket = reservation.commit(ReplayEvent.advance_time(1))
            with self.assertRaises(PersistenceWorkerFailed):
                ticket.wait(2)
        self.assertEqual(worker.state, PersistenceWorkerState.FAILED)
        with self.assertRaises(PersistenceWorkerFailed):
            worker.reserve()
        with self.assertRaises(PersistenceWorkerFailed):
            worker.flush(2)
        with self.assertRaises(PersistenceWorkerFailed):
            worker.close(2)

    def test_failed_periodic_snapshot_is_latched_after_journal_append(self) -> None:
        worker = self._worker(snapshot_interval=1)
        with patch.object(
            self.snapshots,
            "write",
            side_effect=OSError("snapshot stopped"),
        ):
            reservation = worker.reserve()
            assert reservation is not None
            ticket = reservation.commit(ReplayEvent.advance_time(1))
            with self.assertRaises(PersistenceWorkerFailed):
                ticket.wait(2)
        self.assertEqual(worker.state, PersistenceWorkerState.FAILED)
        self.assertEqual(len(self.journal.read_records()), 1)
        self.assertIsNone(self.snapshots.read())
        with self.assertRaises(PersistenceWorkerFailed):
            worker.reserve()

    def test_failure_marks_every_queued_ticket(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def failed_append(event: ReplayEvent):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test did not release failed append")
            raise OSError("disk stopped")

        worker = self._worker(capacity=2)
        with patch.object(self.journal, "append", side_effect=failed_append):
            first = worker.reserve()
            second = worker.reserve()
            assert first is not None and second is not None
            first_ticket = first.commit(ReplayEvent.advance_time(1))
            self.assertTrue(entered.wait(2))
            second_ticket = second.commit(ReplayEvent.advance_time(2))
            release.set()
            with self.assertRaises(PersistenceWorkerFailed):
                first_ticket.wait(2)
            with self.assertRaises(PersistenceWorkerFailed):
                second_ticket.wait(2)
        self.assertEqual(worker.pending_count, 0)

    def test_lifecycle_and_timeout_contracts_are_strict(self) -> None:
        worker = PersistenceWorker(self.journal, self.snapshots, self.empty)
        with self.assertRaises(PersistenceWorkerClosed):
            worker.reserve()
        worker.start()
        self.workers.append(worker)
        with self.assertRaises(PersistenceWorkerError):
            worker.start()
        reservation = worker.reserve()
        assert reservation is not None
        ticket = reservation.commit(ReplayEvent.advance_time(1))
        with self.assertRaises(ValueError):
            ticket.wait(True)
        ticket.wait(2)
        worker.close(2)
        worker.close(2)
        with self.assertRaises(PersistenceWorkerClosed):
            worker.reserve()

    def test_constructor_rejects_truth_values_as_numeric_policy(self) -> None:
        with self.assertRaises(ValueError):
            PersistenceWorker(
                self.journal,
                self.snapshots,
                self.empty,
                capacity=True,
            )
        with self.assertRaises(ValueError):
            PersistenceWorker(
                self.journal,
                self.snapshots,
                self.empty,
                snapshot_interval=True,
            )


if __name__ == "__main__":
    unittest.main()
