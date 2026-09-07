"""Bounded asynchronous persistence with explicit lifecycle ownership."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pyduckhunt.game.model import GameState
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import GENESIS_DIGEST, JournalFile, JournalRecord
from pyduckhunt.persistence.replay import (
    ReplayResult,
    apply_replay_event,
    recover,
)
from pyduckhunt.persistence.snapshot import Snapshot, SnapshotStore


StatePublisher = Callable[[GameState], None]


class PersistenceWorkerState(str, Enum):
    NEW = "new"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class PersistenceWorkerError(RuntimeError):
    """Base class for persistence lifecycle failures."""


class PersistenceWorkerClosed(PersistenceWorkerError):
    """Raised when work is submitted outside the running lifecycle."""


class PersistenceWorkerFailed(PersistenceWorkerError):
    """Raised after the worker latches an asynchronous failure."""


class PersistenceTicket:
    """Completion handle for one accepted replay intent."""

    def __init__(self, event: ReplayEvent) -> None:
        self.event = event
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._record: JournalRecord | None = None
        self._error: Exception | None = None

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> JournalRecord:
        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ValueError("ticket timeout must be non-negative")
        if not self._done.wait(timeout):
            raise TimeoutError("persistence ticket did not complete in time")
        with self._lock:
            if self._error is not None:
                raise PersistenceWorkerFailed(
                    "asynchronous persistence failed"
                ) from self._error
            assert self._record is not None
            return self._record

    def _succeed(self, record: JournalRecord) -> None:
        with self._lock:
            if self._done.is_set():
                raise PersistenceWorkerError("persistence ticket completed twice")
            self._record = record
            self._done.set()

    def _fail(self, error: Exception) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._error = error
            self._done.set()


@dataclass(frozen=True, slots=True)
class _WriteRequest:
    event: ReplayEvent
    ticket: PersistenceTicket


@dataclass(frozen=True, slots=True)
class _StopRequest:
    done: threading.Event


class PersistenceReservation:
    """One capacity slot reserved before a game transition is made visible."""

    def __init__(self, worker: PersistenceWorker) -> None:
        self._worker = worker
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def commit(self, event: ReplayEvent) -> PersistenceTicket:
        if not isinstance(event, ReplayEvent):
            raise ValueError("persistence intent must be a replay event")
        if not self._active:
            raise PersistenceWorkerError("persistence reservation is already settled")
        ticket = self._worker._commit_reservation(event)
        self._active = False
        return ticket

    def cancel(self) -> None:
        if not self._active:
            raise PersistenceWorkerError("persistence reservation is already settled")
        self._worker._cancel_reservation()
        self._active = False

    def __enter__(self) -> PersistenceReservation:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._active:
            self.cancel()


class PersistenceWorker:
    """Own journal and snapshot I/O on one bounded background worker."""

    def __init__(
        self,
        journal: JournalFile,
        snapshots: SnapshotStore,
        recovered: ReplayResult,
        *,
        capacity: int = 64,
        snapshot_interval: int | None = 128,
        snapshot_on_close: bool = True,
        state_publisher: StatePublisher | None = None,
    ) -> None:
        if not isinstance(journal, JournalFile):
            raise ValueError("persistence worker requires a journal")
        if not isinstance(snapshots, SnapshotStore):
            raise ValueError("persistence worker requires a snapshot store")
        if not isinstance(recovered, ReplayResult):
            raise ValueError("persistence worker requires a recovered state")
        if type(capacity) is not int or capacity < 1:
            raise ValueError("persistence capacity must be a positive integer")
        if snapshot_interval is not None and (
            type(snapshot_interval) is not int or snapshot_interval < 1
        ):
            raise ValueError("snapshot interval must be a positive integer or none")
        if not isinstance(snapshot_on_close, bool):
            raise ValueError("snapshot-on-close must be a truth value")
        if state_publisher is not None and not callable(state_publisher):
            raise ValueError("state publisher must be callable or none")
        if recovered.last_sequence < 0 or not _valid_digest(recovered.last_digest):
            raise ValueError("recovered journal boundary is invalid")
        if recovered.last_sequence == 0 and recovered.last_digest != GENESIS_DIGEST:
            raise ValueError("empty recovery must use the genesis digest")

        self.journal = journal
        self.snapshots = snapshots
        self.capacity = capacity
        self.snapshot_interval = snapshot_interval
        self.snapshot_on_close = snapshot_on_close
        self._state_publisher = state_publisher
        self._replay_state = recovered.state
        self._last_sequence = recovered.last_sequence
        self._last_digest = recovered.last_digest
        self._last_snapshot_sequence = recovered.last_sequence
        self._wrote_since_start = False
        self._state = PersistenceWorkerState.NEW
        self._failure: Exception | None = None
        self._state_lock = threading.Lock()
        self._pending_condition = threading.Condition(self._state_lock)
        self._slots = threading.BoundedSemaphore(capacity)
        self._requests: queue.Queue[_WriteRequest | _StopRequest] = queue.Queue()
        self._pending_count = 0
        self._open_reservations = 0
        self._thread: threading.Thread | None = None
        self._stop_request: _StopRequest | None = None
        self._publication_attempts = 0
        self._publication_failures = 0
        self._last_publication_error: str | None = None

    @classmethod
    def open(
        cls,
        journal: JournalFile,
        snapshots: SnapshotStore,
        *,
        capacity: int = 64,
        snapshot_interval: int | None = 128,
        snapshot_on_close: bool = True,
        state_publisher: StatePublisher | None = None,
    ) -> tuple[PersistenceWorker, ReplayResult]:
        """Recover synchronously at startup, then start the I/O owner thread."""

        recovered = recover(snapshots, journal)
        worker = cls(
            journal,
            snapshots,
            recovered,
            capacity=capacity,
            snapshot_interval=snapshot_interval,
            snapshot_on_close=snapshot_on_close,
            state_publisher=state_publisher,
        )
        worker._publish_state_best_effort(recovered.state)
        worker.start()
        return worker, recovered

    @property
    def state(self) -> PersistenceWorkerState:
        with self._state_lock:
            return self._state

    @property
    def pending_count(self) -> int:
        with self._state_lock:
            return self._pending_count

    @property
    def failure(self) -> Exception | None:
        with self._state_lock:
            return self._failure

    @property
    def publication_attempts(self) -> int:
        with self._state_lock:
            return self._publication_attempts

    @property
    def publication_failures(self) -> int:
        with self._state_lock:
            return self._publication_failures

    @property
    def last_publication_error(self) -> str | None:
        with self._state_lock:
            return self._last_publication_error

    def start(self) -> None:
        with self._state_lock:
            if self._state is not PersistenceWorkerState.NEW:
                raise PersistenceWorkerError("persistence worker can only start once")
            self._state = PersistenceWorkerState.RUNNING
            thread = threading.Thread(
                target=self._run,
                name="pyduckhunt-persistence",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._state = PersistenceWorkerState.NEW
                self._thread = None
                raise

    def reserve(self) -> PersistenceReservation | None:
        """Reserve one outstanding slot without waiting or touching disk."""

        with self._state_lock:
            self._raise_unless_running()
            if not self._slots.acquire(blocking=False):
                return None
            self._open_reservations += 1
            return PersistenceReservation(self)

    def flush(self, timeout: float | None = None) -> None:
        """Wait for accepted writes; this is never a priority-path operation."""

        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ValueError("flush timeout must be non-negative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._pending_condition:
            if self._open_reservations:
                raise PersistenceWorkerError(
                    "cannot flush with unsettled persistence reservations"
                )
            while self._pending_count:
                if self._state is PersistenceWorkerState.FAILED:
                    self._raise_failure()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("persistence flush did not complete in time")
                self._pending_condition.wait(remaining)
            if self._state is PersistenceWorkerState.FAILED:
                self._raise_failure()

    def close(self, timeout: float | None = None) -> None:
        """Stop admissions, drain accepted writes and commit the final snapshot."""

        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ValueError("close timeout must be non-negative")
        with self._state_lock:
            if self._state is PersistenceWorkerState.CLOSED:
                return
            if self._state is PersistenceWorkerState.FAILED:
                self._raise_failure()
            if self._state is PersistenceWorkerState.NEW:
                self._state = PersistenceWorkerState.CLOSED
                return
            if self._state is PersistenceWorkerState.RUNNING:
                if self._open_reservations:
                    raise PersistenceWorkerError(
                        "cannot close with unsettled persistence reservations"
                    )
                self._state = PersistenceWorkerState.CLOSING
                self._stop_request = _StopRequest(threading.Event())
                self._requests.put_nowait(self._stop_request)
            stop_request = self._stop_request
            thread = self._thread
        assert stop_request is not None
        assert thread is not None
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("persistence worker did not stop in time")
        with self._state_lock:
            if self._state is PersistenceWorkerState.FAILED:
                self._raise_failure()
            if self._state is not PersistenceWorkerState.CLOSED:
                raise PersistenceWorkerError("persistence worker stopped unexpectedly")

    def _raise_unless_running(self) -> None:
        if self._state is PersistenceWorkerState.FAILED:
            self._raise_failure()
        if self._state is not PersistenceWorkerState.RUNNING:
            raise PersistenceWorkerClosed("persistence worker is not accepting work")

    def _raise_failure(self) -> None:
        assert self._failure is not None
        raise PersistenceWorkerFailed("persistence worker has failed") from self._failure

    def _cancel_reservation(self) -> None:
        with self._state_lock:
            if self._open_reservations < 1:
                raise PersistenceWorkerError("no persistence reservation is open")
            self._open_reservations -= 1
            self._slots.release()
            self._pending_condition.notify_all()

    def _commit_reservation(self, event: ReplayEvent) -> PersistenceTicket:
        ticket = PersistenceTicket(event)
        with self._state_lock:
            if self._open_reservations < 1:
                raise PersistenceWorkerError("no persistence reservation is open")
            self._open_reservations -= 1
            if self._state is PersistenceWorkerState.FAILED:
                assert self._failure is not None
                ticket._fail(self._failure)
                self._slots.release()
                self._pending_condition.notify_all()
                return ticket
            if self._state is not PersistenceWorkerState.RUNNING:
                self._slots.release()
                self._pending_condition.notify_all()
                raise PersistenceWorkerClosed(
                    "persistence worker stopped before reservation commit"
                )
            self._pending_count += 1
            self._requests.put_nowait(_WriteRequest(event, ticket))
            return ticket

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            if isinstance(request, _StopRequest):
                try:
                    if (
                        self.snapshot_on_close
                        and self._wrote_since_start
                        and self._last_snapshot_sequence != self._last_sequence
                    ):
                        self._write_snapshot()
                except Exception as error:
                    self._latch_failure(error)
                else:
                    with self._state_lock:
                        self._state = PersistenceWorkerState.CLOSED
                        self._pending_condition.notify_all()
                finally:
                    request.done.set()
                    self._requests.task_done()
                return

            try:
                transition = apply_replay_event(self._replay_state, request.event)
                record = self.journal.append(request.event)
                if (
                    record.sequence != self._last_sequence + 1
                    or record.previous_digest != self._last_digest
                ):
                    raise PersistenceWorkerError(
                        "journal append diverged from the recovered boundary"
                    )
                self._replay_state = transition.state
                self._last_sequence = record.sequence
                self._last_digest = record.digest
                self._wrote_since_start = True
                if (
                    self.snapshot_interval is not None
                    and record.sequence % self.snapshot_interval == 0
                ):
                    self._write_snapshot()
                self._publish_state_best_effort(self._replay_state)
                request.ticket._succeed(record)
            except Exception as error:
                request.ticket._fail(error)
                self._complete_request()
                self._latch_failure(error)
                self._requests.task_done()
                self._fail_queued_requests(error)
                return
            self._complete_request()
            self._requests.task_done()

    def _write_snapshot(self) -> None:
        self.snapshots.write(
            Snapshot(
                self._last_sequence,
                self._last_digest,
                self._replay_state,
            )
        )
        self._last_snapshot_sequence = self._last_sequence

    def _publish_state_best_effort(self, state: GameState) -> None:
        publisher = self._state_publisher
        if publisher is None:
            return
        error_name: str | None = None
        try:
            publisher(state)
        except Exception as error:
            error_name = type(error).__name__
        with self._state_lock:
            self._publication_attempts += 1
            if error_name is not None:
                self._publication_failures += 1
            self._last_publication_error = error_name

    def _complete_request(self) -> None:
        self._slots.release()
        with self._pending_condition:
            self._pending_count -= 1
            self._pending_condition.notify_all()

    def _latch_failure(self, error: Exception) -> None:
        with self._pending_condition:
            self._failure = error
            self._state = PersistenceWorkerState.FAILED
            self._pending_condition.notify_all()

    def _fail_queued_requests(self, error: Exception) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                return
            if isinstance(request, _WriteRequest):
                request.ticket._fail(error)
                self._complete_request()
            else:
                request.done.set()
            self._requests.task_done()


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
