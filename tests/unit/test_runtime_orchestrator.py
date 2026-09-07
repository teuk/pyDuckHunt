from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pyduckhunt.game.model import GameState
from pyduckhunt.persistence import (
    JournalFile,
    ReplayEvent,
    SnapshotStore,
    recover,
)
from pyduckhunt.runtime import (
    DispatchStatus,
    PersistenceWorkerFailed,
    RuntimeOrchestrator,
)


class RuntimeOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")
        self.batches: list[tuple[bytes, ...]] = []
        self.runtime, self.recovered = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            self.batches.append,
            persistence_capacity=2,
            snapshot_interval=None,
        )
        self.addCleanup(self._close_runtime)

    def _close_runtime(self) -> None:
        if self.runtime.persistence.state.value in ("running", "closing"):
            self.runtime.close(2)

    @staticmethod
    def _render_time(transition) -> tuple[bytes, ...]:
        return (f"now={transition.state.now_ns}".encode(),)

    def test_priority_batch_is_enqueued_before_journal_append(self) -> None:
        order: list[str] = []
        original_append = self.journal.append

        def observed_append(event: ReplayEvent):
            order.append("append")
            return original_append(event)

        def sink(batch: tuple[bytes, ...]) -> None:
            order.append("priority")
            self.batches.append(batch)

        self.runtime._priority_sink = sink
        with patch.object(self.journal, "append", side_effect=observed_append):
            result = self.runtime.dispatch(
                ReplayEvent.advance_time(10),
                self._render_time,
            )
            assert result.persistence_ticket is not None
            result.persistence_ticket.wait(2)
        self.assertEqual(order, ["priority", "append"])
        self.assertEqual(result.status, DispatchStatus.ACCEPTED)
        self.assertEqual(self.runtime.state.now_ns, 10)

    def test_backpressure_emits_busy_batch_without_state_mutation(self) -> None:
        first = self.runtime.persistence.reserve()
        second = self.runtime.persistence.reserve()
        assert first is not None and second is not None
        result = self.runtime.dispatch(
            ReplayEvent.advance_time(10),
            self._render_time,
            backpressure_response=(b"busy",),
        )
        self.assertEqual(result.status, DispatchStatus.BACKPRESSURED)
        self.assertIsNone(result.transition)
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.batches, [(b"busy",)])
        self.assertEqual(self.journal.read_records(), ())
        first.cancel()
        second.cancel()

    def test_renderer_failure_cancels_reservation_and_state(self) -> None:
        def broken_renderer(transition):
            raise ValueError("render failed")

        with self.assertRaises(ValueError):
            self.runtime.dispatch(ReplayEvent.advance_time(10), broken_renderer)
        self.assertEqual(self.runtime.state, GameState())
        accepted = self.runtime.dispatch(
            ReplayEvent.advance_time(10),
            self._render_time,
        )
        assert accepted.persistence_ticket is not None
        accepted.persistence_ticket.wait(2)

    def test_priority_sink_failure_cancels_reservation_and_state(self) -> None:
        def broken_sink(batch: tuple[bytes, ...]) -> None:
            raise OSError("outbox stopped")

        self.runtime._priority_sink = broken_sink
        with self.assertRaises(OSError):
            self.runtime.dispatch(
                ReplayEvent.advance_time(10),
                self._render_time,
            )
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.runtime.persistence.pending_count, 0)

    def test_transition_failure_cancels_reservation(self) -> None:
        accepted = self.runtime.dispatch(
            ReplayEvent.advance_time(10),
            self._render_time,
        )
        assert accepted.persistence_ticket is not None
        accepted.persistence_ticket.wait(2)
        with self.assertRaises(ValueError):
            self.runtime.dispatch(
                ReplayEvent.advance_time(9),
                self._render_time,
            )
        self.assertEqual(self.runtime.state.now_ns, 10)
        reservation = self.runtime.persistence.reserve()
        self.assertIsNotNone(reservation)
        assert reservation is not None
        reservation.cancel()

    def test_clean_close_recovers_the_visible_runtime_state(self) -> None:
        first = self.runtime.dispatch(
            ReplayEvent.advance_time(10),
            self._render_time,
        )
        second = self.runtime.dispatch(
            ReplayEvent.advance_time(20),
            self._render_time,
        )
        assert first.persistence_ticket is not None
        assert second.persistence_ticket is not None
        first.persistence_ticket.wait(2)
        second.persistence_ticket.wait(2)
        visible_state = self.runtime.state
        self.runtime.close(2)
        self.assertEqual(recover(self.snapshots, self.journal).state, visible_state)

    def test_worker_failure_latches_after_visible_response(self) -> None:
        with patch.object(self.journal, "append", side_effect=OSError("disk stopped")):
            result = self.runtime.dispatch(
                ReplayEvent.advance_time(10),
                self._render_time,
            )
            self.assertEqual(self.runtime.state.now_ns, 10)
            self.assertEqual(self.batches[-1], (b"now=10",))
            assert result.persistence_ticket is not None
            with self.assertRaises(PersistenceWorkerFailed):
                result.persistence_ticket.wait(2)
        with self.assertRaises(PersistenceWorkerFailed):
            self.runtime.dispatch(
                ReplayEvent.advance_time(20),
                self._render_time,
            )

    def test_dispatch_is_rejected_from_another_thread(self) -> None:
        errors: list[Exception] = []

        def foreign_dispatch() -> None:
            try:
                self.runtime.dispatch(
                    ReplayEvent.advance_time(1),
                    self._render_time,
                )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_dispatch)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(self.runtime.state, GameState())

    def test_priority_batch_rejects_mutable_or_text_values(self) -> None:
        with self.assertRaises(ValueError):
            self.runtime.dispatch(
                ReplayEvent.advance_time(1),
                lambda transition: [b"mutable"],
            )
        with self.assertRaises(ValueError):
            self.runtime.dispatch(
                ReplayEvent.advance_time(1),
                lambda transition: ("text",),
            )

    def test_nonpersistent_priority_emission_uses_the_same_validated_sink(self) -> None:
        emitted = self.runtime.emit_priority((b"syntax",))
        self.assertEqual(emitted, (b"syntax",))
        self.assertEqual(self.batches, [(b"syntax",)])
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.journal.read_records(), ())
        with self.assertRaises(ValueError):
            self.runtime.emit_priority([b"mutable"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
