"""Deterministically recover game state from snapshots and journal intents."""

from __future__ import annotations

from dataclasses import dataclass

from pyduckhunt.game.admin import (
    apply_admin_channel_item,
    apply_player_update,
    apply_weapon_control,
)
from pyduckhunt.game.commands import Command
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.model import GameState, Transition
from pyduckhunt.game.shop import purchase
from pyduckhunt.game.runtime import (
    FlightSelection,
    apply_runtime_command,
    apply_runtime_purchase,
    expand_daily_schedule,
    enable_hourly_bread,
    replan_bread_schedule,
    install_daily_schedule,
    tick_daily_schedule,
)
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.persistence.journal import (
    GENESIS_DIGEST,
    JournalFile,
    JournalIntegrityError,
    JournalRecord,
)
from pyduckhunt.persistence.snapshot import Snapshot, SnapshotStore
from pyduckhunt.persistence.codec import SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ReplayResult:
    state: GameState
    last_sequence: int
    last_digest: str
    transitions: tuple[Transition, ...]


def apply_replay_event(state: GameState, event: ReplayEvent) -> Transition:
    if event.kind is EventKind.ENABLE_HOURLY_BREAD:
        return enable_hourly_bread(state, event.now_ns)
    if event.kind is EventKind.REPLAN_BREAD_SCHEDULE:
        return replan_bread_schedule(state, event.now_ns,
            event.schedule_day_start_ns, event.schedule_deadlines_ns)
    if event.kind is EventKind.START_FLIGHT:
        assert event.lifetime_ns is not None
        assert event.flight_health is not None
        assert event.flight_kind is not None
        assert event.flight_reward_experience is not None
        return start_flight(
            state,
            event.now_ns,
            lifetime_ns=event.lifetime_ns,
            health=event.flight_health,
            kind=event.flight_kind,
            reward_experience=event.flight_reward_experience,
        )
    if event.kind is EventKind.INSTALL_DAILY_SCHEDULE:
        assert event.schedule_day_start_ns is not None
        return install_daily_schedule(
            state,
            event.now_ns,
            event.schedule_day_start_ns,
            event.schedule_deadlines_ns,
        )
    if event.kind is EventKind.EXPAND_DAILY_SCHEDULE:
        return expand_daily_schedule(
            state,
            event.now_ns,
            event.schedule_deadlines_ns,
        )
    if event.kind is EventKind.SCHEDULE_TICK:
        selection = None
        if event.flight_kind is not None:
            assert event.lifetime_ns is not None
            assert event.flight_health is not None
            assert event.flight_reward_experience is not None
            selection = FlightSelection(
                event.flight_kind,
                event.flight_health,
                event.flight_reward_experience,
                event.lifetime_ns,
            )
        return tick_daily_schedule(state, event.now_ns, selection=selection)
    if event.kind is EventKind.ADVANCE_TIME:
        return advance_time(state, event.now_ns)
    if event.kind is EventKind.ADMIN_PLAYER_UPDATE:
        assert event.nickname is not None
        assert event.admin_field is not None
        assert event.admin_operation is not None
        assert event.admin_value is not None
        return apply_player_update(
            state,
            event.nickname,
            event.now_ns,
            field=event.admin_field,
            operation=event.admin_operation,
            value=event.admin_value,
        )
    if event.kind is EventKind.ADMIN_WEAPON_CONTROL:
        assert event.nickname is not None
        assert event.admin_operation is not None
        return apply_weapon_control(
            state,
            event.nickname,
            event.now_ns,
            operation=event.admin_operation,
        )
    if event.kind is EventKind.ADMIN_CHANNEL_ITEM:
        assert event.admin_actor is not None
        assert event.item_id is not None
        return apply_admin_channel_item(
            state,
            event.admin_actor,
            event.item_id,
            event.now_ns,
            scheduled_for_ns=event.scheduled_for_ns,
        )
    if event.kind is EventKind.PURCHASE:
        assert event.nickname is not None
        assert event.item_id is not None
        assert event.charged_cost is not None
        return purchase(
            state,
            event.nickname,
            event.item_id,
            event.now_ns,
            charged_cost=event.charged_cost,
            magnitude=event.magnitude,
            replace_active_effect=event.replace_active_effect,
            target_nickname=event.target_nickname,
            target_present=event.target_present,
            scheduled_for_ns=event.scheduled_for_ns,
            fatigue_relief_centi=event.fatigue_relief_centi,
            fatigue_target_centi=event.fatigue_target_centi,
        )
    if event.kind is EventKind.RUNTIME_PURCHASE:
        assert event.nickname is not None
        assert event.item_id is not None
        assert event.charged_cost is not None
        return apply_runtime_purchase(
            state,
            event.nickname,
            event.item_id,
            event.now_ns,
            charged_cost=event.charged_cost,
            magnitude=event.magnitude,
            replace_active_effect=event.replace_active_effect,
            target_nickname=event.target_nickname,
            target_present=event.target_present,
            scheduled_for_ns=event.scheduled_for_ns,
            fatigue_relief_centi=event.fatigue_relief_centi,
            fatigue_target_centi=event.fatigue_target_centi,
        )
    assert event.nickname is not None
    assert event.command_kind is not None
    assert event.invoked_as is not None
    command = Command(event.command_kind, event.invoked_as, event.arguments)
    if event.kind is EventKind.RUNTIME_COMMAND:
        return apply_runtime_command(
            state,
            event.nickname,
            command,
            event.now_ns,
            shot_attempt=event.shot_attempt,
            delay_settled=event.delay_settled,
        )
    return apply_command(
        state,
        event.nickname,
        command,
        event.now_ns,
        shot_attempt=event.shot_attempt,
        delay_settled=event.delay_settled,
    )


def replay_records(
    records: tuple[JournalRecord, ...],
    *,
    initial_state: GameState | None = None,
    after_sequence: int = 0,
    initial_digest: str = GENESIS_DIGEST,
) -> ReplayResult:
    if after_sequence < 0:
        raise ValueError("after_sequence must not be negative")
    state = initial_state if initial_state is not None else GameState()
    sequence = after_sequence
    digest = initial_digest
    transitions: list[Transition] = []
    for record in records:
        if record.sequence <= after_sequence:
            continue
        if record.sequence != sequence + 1 or record.previous_digest != digest:
            raise JournalIntegrityError("replay records are not contiguous with recovery state")
        transition = apply_replay_event(state, record.event)
        state = transition.state
        transitions.append(transition)
        sequence = record.sequence
        digest = record.digest
    return ReplayResult(state, sequence, digest, tuple(transitions))


def recover(snapshot_store: SnapshotStore, journal: JournalFile) -> ReplayResult:
    records = journal.read_records()
    snapshot = snapshot_store.read()
    if snapshot is None:
        return replay_records(records)

    if snapshot.journal_sequence > len(records):
        raise JournalIntegrityError("snapshot is ahead of the journal")
    expected_digest = (
        GENESIS_DIGEST
        if snapshot.journal_sequence == 0
        else records[snapshot.journal_sequence - 1].digest
    )
    if snapshot.journal_digest != expected_digest:
        raise JournalIntegrityError("snapshot does not match the journal chain")
    # Schema 22 only adds an explicit future rule; schema-21 checkpoints
    # remain authoritative, including operator-imported profiles.
    if snapshot.source_schema < 21:
        return replay_records(records)
    return replay_records(
        records,
        initial_state=snapshot.state,
        after_sequence=snapshot.journal_sequence,
        initial_digest=snapshot.journal_digest,
    )


def snapshot_from_result(result: ReplayResult) -> Snapshot:
    return Snapshot(result.last_sequence, result.last_digest, result.state)
