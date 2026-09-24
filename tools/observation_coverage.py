#!/usr/bin/env python3
"""Summarize private observation coverage from a verified event journal.

The report contains aggregate counters only. It never prints nicknames, raw
commands, IRC text, inventory contents or exact timestamps.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.day_boundary import paris_calendar_day_marker_ns
from pyduckhunt.game.model import (
    FlightKind,
    GameState,
    LastFlightConclusion,
    OutcomeKind,
    Transition,
)
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.persistence.journal import GENESIS_DIGEST, JournalFile, JournalRecord
from pyduckhunt.persistence.replay import apply_replay_event
from pyduckhunt.persistence.snapshot import SnapshotStore


MAX_JOURNAL_BYTES = 64 * 1024 * 1024
SHOP_ITEM_DUCK_CALL = 20
SHOP_ITEM_BREAD = 21
SHOP_ITEM_MECHANICAL = 23


@dataclass(frozen=True, slots=True)
class ScenarioRule:
    identifier: str
    summary: str
    requirements: tuple[tuple[str, int], ...] = ()
    evidence_keys: tuple[str, ...] = ()
    external_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    identifier: str
    summary: str
    status: str
    evidence: tuple[tuple[str, int], ...]
    note: str


@dataclass(frozen=True, slots=True)
class CoverageReport:
    records_in_journal: int
    records_in_scope: int
    replay_boundary_sequence: int
    first_sequence: int | None
    last_sequence: int | None
    last_digest: str | None
    scenarios: tuple[ScenarioResult, ...]


RULES = (
    ScenarioRule(
        "IO-001",
        "Ordinary flight appears and expires",
        (("ordinary_started", 1), ("ordinary_expired", 1)),
        ("ordinary_started", "ordinary_expired"),
    ),
    ScenarioRule(
        "IO-002",
        "Successful ordinary kill",
        (("ordinary_hit", 1),),
        ("ordinary_hit",),
    ),
    ScenarioRule(
        "IO-003",
        "Miss during flight",
        (("flight_miss", 1),),
        ("flight_miss",),
    ),
    ScenarioRule(
        "IO-004",
        "Wild shot",
        (("wild_shot", 1),),
        ("wild_shot",),
    ),
    ScenarioRule(
        "IO-005",
        "Late shot grace",
        (("late_shot", 1),),
        ("late_shot",),
    ),
    ScenarioRule(
        "IO-006",
        "Empty, jammed and unjam paths",
        (("empty", 1), ("jammed", 1), ("unjammed", 1)),
        ("empty", "jammed", "unjammed"),
    ),
    ScenarioRule(
        "IO-007",
        "Manual reload",
        (("manual_reload", 1),),
        ("manual_reload",),
    ),
    ScenarioRule(
        "IO-008",
        "Duckstats self and target",
        (("stats_self", 1), ("stats_target", 1)),
        ("stats_self", "stats_target"),
    ),
    ScenarioRule(
        "IO-009",
        "Inventory self and target",
        (("inventory_self", 1), ("inventory_target", 1)),
        ("inventory_self", "inventory_target"),
    ),
    ScenarioRule(
        "IO-010",
        "Lastduck after kill and escape",
        (("last_after_hit", 1), ("last_after_escape", 1)),
        ("last_after_hit", "last_after_escape"),
    ),
    ScenarioRule(
        "IO-011",
        "Bare shop and one safe purchase",
        (("bare_shop", 1), ("shop_purchase", 1)),
        ("bare_shop", "shop_purchase", "shop_refusal"),
    ),
    ScenarioRule(
        "IO-012",
        "Duck call",
        (("duck_call_purchase", 1), ("duck_call_takeoff", 1)),
        ("duck_call_purchase", "duck_call_due", "duck_call_takeoff"),
    ),
    ScenarioRule(
        "IO-013",
        "Two bread pieces",
        (("bread_purchase", 2), ("bread_consumed", 2), ("bread_extended_takeoff", 2)),
        ("bread_purchase", "bread_consumed", "bread_extended_takeoff"),
    ),
    ScenarioRule(
        "IO-014",
        "Mechanical duck",
        (("mechanical_purchase", 1), ("mechanical_takeoff_zero_xp", 1)),
        ("mechanical_purchase", "mechanical_due", "mechanical_takeoff_zero_xp"),
    ),
    ScenarioRule(
        "IO-015",
        "Paris midnight",
        (("exact_midnight_reset", 2),),
        ("midnight_boundary", "exact_midnight_reset"),
    ),
    ScenarioRule(
        "IO-016",
        "Service restart",
        external_reason="requires service-manager evidence outside the event journal",
    ),
    ScenarioRule(
        "IO-017",
        "Host reboot",
        external_reason="requires boot and service evidence outside the event journal",
    ),
    ScenarioRule(
        "IO-018",
        "IRC reconnect",
        external_reason="requires transport-generation evidence outside the event journal",
    ),
    ScenarioRule(
        "IO-019",
        "Visible NICK change",
        external_reason="nickname changes are not represented by the current event schema",
    ),
    ScenarioRule(
        "IO-020",
        "Owner planning",
        external_reason="private presentation evidence is intentionally absent from the journal",
    ),
)


SHOP_REFUSALS = {
    OutcomeKind.SHOP_UNKNOWN_ITEM,
    OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
    OutcomeKind.SHOP_NOT_APPLICABLE,
    OutcomeKind.SHOP_EFFECT_ACTIVE,
    OutcomeKind.SHOP_TARGET_REQUIRED,
    OutcomeKind.SHOP_TARGET_UNKNOWN,
    OutcomeKind.SHOP_TARGET_ABSENT,
    OutcomeKind.SHOP_TARGET_UNARMED,
    OutcomeKind.SHOP_TARGET_IMMUNE,
}


def _command_succeeded(event: ReplayEvent, transition: Transition) -> bool:
    return event.command_kind is not None and any(
        outcome.kind is OutcomeKind.QUERY and outcome.command is event.command_kind
        for outcome in transition.outcomes
    )


def _record_query(counter: Counter[str], event: ReplayEvent, transition: Transition) -> None:
    if not _command_succeeded(event, transition):
        return
    if event.command_kind is CommandKind.STATS:
        counter["stats_target" if event.arguments else "stats_self"] += 1
    elif event.command_kind is CommandKind.INVENTORY:
        counter["inventory_target" if event.arguments else "inventory_self"] += 1
    elif event.command_kind is CommandKind.SHOP and not event.arguments:
        counter["bare_shop"] += 1


def _record_last_flight(
    counter: Counter[str],
    event: ReplayEvent,
    before: GameState,
    transition: Transition,
) -> None:
    if (
        event.command_kind is not CommandKind.LAST_FLIGHT
        or before.last_flight is None
        or not _command_succeeded(event, transition)
    ):
        return
    if before.last_flight.conclusion is LastFlightConclusion.HIT:
        counter["last_after_hit"] += 1
    elif before.last_flight.conclusion in (
        LastFlightConclusion.ESCAPED,
        LastFlightConclusion.FRIGHTENED,
    ):
        counter["last_after_escape"] += 1


def _exact_daily_reset(before: GameState, after: GameState) -> bool:
    if not before.players:
        return False
    before_marker = paris_calendar_day_marker_ns(before.now_ns)
    after_marker = paris_calendar_day_marker_ns(after.now_ns)
    if before_marker == after_marker:
        return False
    for player in before.players:
        reset = after.player(player.key)
        if reset is None or (
            reset.ammo != reset.capacity
            or reset.magazines != reset.magazine_capacity
            or reset.confiscated != reset.permanently_confiscated
            or reset.carried_ducks != 0
            or reset.carried_day_start_ns != after_marker
            or reset.fatigue_centi != 0
        ):
            return False
    return True


def observe_transition(
    counter: Counter[str],
    event: ReplayEvent,
    before: GameState,
    transition: Transition,
) -> None:
    """Collect privacy-safe facts from one already-verified transition."""

    after = transition.state
    before_marker = paris_calendar_day_marker_ns(before.now_ns)
    after_marker = paris_calendar_day_marker_ns(after.now_ns)
    if before.players and before_marker != after_marker:
        counter["midnight_boundary"] += 1
        if _exact_daily_reset(before, after):
            counter["exact_midnight_reset"] += 1

    _record_query(counter, event, transition)
    _record_last_flight(counter, event, before, transition)

    if event.command_kind is CommandKind.RELOAD and any(
        outcome.kind is OutcomeKind.RELOADED for outcome in transition.outcomes
    ):
        counter["manual_reload"] += 1

    due_items = {
        outcome.item_id
        for outcome in transition.outcomes
        if outcome.kind is OutcomeKind.CHANNEL_ACTION_DUE
    }
    started_kinds = {
        outcome.flight_kind
        for outcome in transition.outcomes
        if outcome.kind is OutcomeKind.FLIGHT_STARTED
    }

    if SHOP_ITEM_DUCK_CALL in due_items:
        counter["duck_call_due"] += 1
        if FlightKind.STANDARD in started_kinds:
            counter["duck_call_takeoff"] += 1
    if SHOP_ITEM_MECHANICAL in due_items:
        counter["mechanical_due"] += 1
        if (
            FlightKind.MECHANICAL in started_kinds
            and event.flight_reward_experience == 0
        ):
            counter["mechanical_takeoff_zero_xp"] += 1

    for outcome in transition.outcomes:
        kind = outcome.kind
        if kind is OutcomeKind.FLIGHT_STARTED:
            if outcome.flight_kind is FlightKind.STANDARD:
                counter["ordinary_started"] += 1
            if outcome.effect_magnitude == 20 and outcome.channel_effect_count == 1:
                counter["bread_extended_takeoff"] += 1
        elif kind is OutcomeKind.FLIGHT_EXPIRED and outcome.flight_kind is FlightKind.STANDARD:
            counter["ordinary_expired"] += 1
        elif kind is OutcomeKind.HIT and outcome.flight_kind is FlightKind.STANDARD:
            counter["ordinary_hit"] += 1
        elif kind is OutcomeKind.MISS:
            counter["flight_miss" if before.flight is not None else "wild_shot"] += 1
        elif kind is OutcomeKind.LATE_SHOT:
            counter["late_shot"] += 1
        elif kind is OutcomeKind.EMPTY:
            counter["empty"] += 1
        elif kind is OutcomeKind.JAMMED:
            counter["jammed"] += 1
        elif kind is OutcomeKind.UNJAMMED:
            counter["unjammed"] += 1
        elif kind is OutcomeKind.SHOP_PURCHASED:
            counter["shop_purchase"] += 1
            if outcome.item_id == SHOP_ITEM_DUCK_CALL:
                counter["duck_call_purchase"] += 1
            elif outcome.item_id == SHOP_ITEM_BREAD:
                counter["bread_purchase"] += 1
            elif outcome.item_id == SHOP_ITEM_MECHANICAL:
                counter["mechanical_purchase"] += 1
        elif kind in SHOP_REFUSALS:
            counter["shop_refusal"] += 1
        elif kind is OutcomeKind.EFFECT_CONSUMED and outcome.item_id == SHOP_ITEM_BREAD:
            counter["bread_consumed"] += 1


def _scenario_results(counter: Counter[str]) -> tuple[ScenarioResult, ...]:
    results = []
    for rule in RULES:
        if rule.external_reason is not None:
            results.append(
                ScenarioResult(
                    rule.identifier,
                    rule.summary,
                    "EXTERNAL-EVIDENCE",
                    (),
                    rule.external_reason,
                )
            )
            continue
        evidence = tuple((key, counter[key]) for key in rule.evidence_keys)
        complete = all(counter[key] >= minimum for key, minimum in rule.requirements)
        present = any(value for _, value in evidence)
        status = "OBSERVED" if complete else "PARTIAL" if present else "NOT-OBSERVED"
        note = "journal evidence threshold met" if complete else "journal evidence incomplete"
        results.append(ScenarioResult(rule.identifier, rule.summary, status, evidence, note))
    return tuple(results)


def build_report(
    records: tuple[JournalRecord, ...],
    *,
    after_sequence: int = 0,
    through_sequence: int | None = None,
    initial_state: GameState | None = None,
    replay_after_sequence: int = 0,
    initial_digest: str = GENESIS_DIGEST,
) -> CoverageReport:
    """Replay the complete chain and count only the selected sequence range."""

    if after_sequence < 0:
        raise ValueError("after_sequence must not be negative")
    if through_sequence is not None and through_sequence <= after_sequence:
        raise ValueError("through_sequence must be greater than after_sequence")
    if replay_after_sequence < 0 or replay_after_sequence > after_sequence:
        raise ValueError("replay boundary must be between zero and after_sequence")
    if replay_after_sequence > len(records):
        raise ValueError("replay boundary is ahead of the journal")
    expected_digest = (
        GENESIS_DIGEST
        if replay_after_sequence == 0
        else records[replay_after_sequence - 1].digest
    )
    if initial_digest != expected_digest:
        raise ValueError("replay boundary digest does not match the journal")

    state = initial_state if initial_state is not None else GameState()
    counter: Counter[str] = Counter()
    scoped: list[JournalRecord] = []
    for record in records:
        if record.sequence <= replay_after_sequence:
            continue
        before = state
        transition = apply_replay_event(state, record.event)
        state = transition.state
        if record.sequence <= after_sequence:
            continue
        if through_sequence is not None and record.sequence > through_sequence:
            continue
        scoped.append(record)
        observe_transition(counter, record.event, before, transition)

    return CoverageReport(
        records_in_journal=len(records),
        records_in_scope=len(scoped),
        replay_boundary_sequence=replay_after_sequence,
        first_sequence=None if not scoped else scoped[0].sequence,
        last_sequence=None if not scoped else scoped[-1].sequence,
        last_digest=None if not scoped else scoped[-1].digest,
        scenarios=_scenario_results(counter),
    )


def render_markdown(report: CoverageReport) -> str:
    lines = [
        "# pyDuckHunt private observation coverage",
        "",
        f"- Journal records validated: {report.records_in_journal}",
        f"- Replay boundary sequence: {report.replay_boundary_sequence}",
        f"- Records inside selected range: {report.records_in_scope}",
        f"- First selected sequence: {report.first_sequence if report.first_sequence is not None else '-'}",
        f"- Last selected sequence: {report.last_sequence if report.last_sequence is not None else '-'}",
        f"- Last selected digest: `{report.last_digest if report.last_digest is not None else '-'}`",
        "- Privacy: aggregate counters only; no nickname, IRC text, inventory or exact timestamp.",
        "",
        "| Scenario | Status | Aggregate evidence | Scope note |",
        "| --- | --- | --- | --- |",
    ]
    for scenario in report.scenarios:
        evidence = ", ".join(f"{key}={value}" for key, value in scenario.evidence) or "-"
        lines.append(
            f"| {scenario.identifier} — {scenario.summary} | {scenario.status} | "
            f"{evidence} | {scenario.note} |"
        )
    lines.extend(
        (
            "",
            "`OBSERVED` means the journal evidence threshold was met, not that the full",
            "fourteen-day protocol passed. External lifecycle and presentation scenarios",
            "must be joined from their separate private receipts before any final conclusion.",
        )
    )
    return "\n".join(lines) + "\n"


def render_tsv(report: CoverageReport) -> str:
    lines = ["scenario_id\tstatus\tevidence\tnote"]
    for scenario in report.scenarios:
        evidence = ",".join(f"{key}={value}" for key, value in scenario.evidence) or "-"
        lines.append(
            "\t".join((scenario.identifier, scenario.status, evidence, scenario.note))
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--after-sequence", type=int, default=0)
    parser.add_argument("--through-sequence", type=int)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--require-events", action="store_true")
    return parser.parse_args(argv)


def validate_journal_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("journal path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("journal must be an existing regular non-symlink file")
    size = path.stat().st_size
    if size > MAX_JOURNAL_BYTES:
        raise ValueError(f"journal exceeds the {MAX_JOURNAL_BYTES}-byte analysis limit")
    return path


def validate_snapshot_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("snapshot path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("snapshot must be an existing regular non-symlink file")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("snapshot exceeds the 16 MiB analysis limit")
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        journal_path = validate_journal_path(args.journal)
        records = JournalFile(journal_path).read_records()
        snapshot = None
        if args.snapshot is not None:
            snapshot_path = validate_snapshot_path(args.snapshot)
            snapshot = SnapshotStore(snapshot_path).read()
            if snapshot is None:
                raise ValueError("snapshot file is empty")
        report = build_report(
            records,
            after_sequence=args.after_sequence,
            through_sequence=args.through_sequence,
            initial_state=None if snapshot is None else snapshot.state,
            replay_after_sequence=0 if snapshot is None else snapshot.journal_sequence,
            initial_digest=GENESIS_DIGEST if snapshot is None else snapshot.journal_digest,
        )
        if args.require_events and report.records_in_scope == 0:
            raise ValueError("selected journal range contains no event")
    except (OSError, ValueError) as error:
        print(f"[KO] {error}", file=sys.stderr)
        return 1

    output = render_markdown(report) if args.format == "markdown" else render_tsv(report)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
