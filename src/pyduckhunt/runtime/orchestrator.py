"""Single-owner runtime orchestration without socket or disk callbacks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pyduckhunt.game.model import GameState, Transition
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import ReplayResult, apply_replay_event
from pyduckhunt.persistence.snapshot import SnapshotStore
from pyduckhunt.runtime.persistence import (
    PersistenceTicket,
    PersistenceWorker,
    StatePublisher,
)


PriorityBatch = tuple[bytes, ...]
PrioritySink = Callable[[PriorityBatch], None]
TransitionRenderer = Callable[[Transition], PriorityBatch]


class DispatchStatus(str, Enum):
    ACCEPTED = "accepted"
    BACKPRESSURED = "backpressured"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: DispatchStatus
    priority_batch: PriorityBatch
    transition: Transition | None = None
    persistence_ticket: PersistenceTicket | None = None


class RuntimeOrchestrator:
    """Apply one event at a time and hand durability to a bounded worker."""

    def __init__(
        self,
        state: GameState,
        persistence: PersistenceWorker,
        priority_sink: PrioritySink,
    ) -> None:
        if not isinstance(state, GameState):
            raise ValueError("runtime orchestrator requires a game state")
        if not isinstance(persistence, PersistenceWorker):
            raise ValueError("runtime orchestrator requires a persistence worker")
        if not callable(priority_sink):
            raise ValueError("runtime orchestrator requires a priority sink")
        self._state = state
        self._persistence = persistence
        self._priority_sink = priority_sink
        self._owner_thread = threading.get_ident()

    @classmethod
    def open(
        cls,
        journal: JournalFile,
        snapshots: SnapshotStore,
        priority_sink: PrioritySink,
        *,
        persistence_capacity: int = 64,
        snapshot_interval: int | None = 128,
        state_publisher: StatePublisher | None = None,
    ) -> tuple[RuntimeOrchestrator, ReplayResult]:
        """Recover before accepting input, then start asynchronous durability."""

        worker, recovered = PersistenceWorker.open(
            journal,
            snapshots,
            capacity=persistence_capacity,
            snapshot_interval=snapshot_interval,
            state_publisher=state_publisher,
        )
        return cls(recovered.state, worker, priority_sink), recovered

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def persistence(self) -> PersistenceWorker:
        return self._persistence

    def dispatch(
        self,
        event: ReplayEvent,
        renderer: TransitionRenderer,
        *,
        backpressure_response: PriorityBatch = (),
    ) -> DispatchResult:
        """Queue the priority response before committing the replay intent."""

        self._ensure_owner()
        if not isinstance(event, ReplayEvent):
            raise ValueError("runtime dispatch requires a replay event")
        if not callable(renderer):
            raise ValueError("runtime dispatch requires a transition renderer")
        rejected_batch = _validate_batch(backpressure_response)
        reservation = self._persistence.reserve()
        if reservation is None:
            self._priority_sink(rejected_batch)
            return DispatchResult(DispatchStatus.BACKPRESSURED, rejected_batch)

        try:
            transition = apply_replay_event(self._state, event)
            priority_batch = _validate_batch(renderer(transition))
            self._priority_sink(priority_batch)
        except Exception:
            reservation.cancel()
            raise

        self._state = transition.state
        ticket = reservation.commit(event)
        return DispatchResult(
            DispatchStatus.ACCEPTED,
            priority_batch,
            transition,
            ticket,
        )

    def close(self, timeout: float | None = None) -> None:
        self._ensure_owner()
        self._persistence.close(timeout)

    def emit_priority(self, batch: PriorityBatch) -> PriorityBatch:
        """Emit one validated non-persistent batch on the event-loop owner."""

        self._ensure_owner()
        validated = _validate_batch(batch)
        self._priority_sink(validated)
        return validated

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("runtime orchestrator is owned by one event-loop thread")


def _validate_batch(value: object) -> PriorityBatch:
    if type(value) is not tuple or any(not isinstance(line, bytes) for line in value):
        raise ValueError("priority response must be a tuple of wire bytes")
    return value
