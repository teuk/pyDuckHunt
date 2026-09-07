from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.karma import player_karma_basis_points
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    FlightKind,
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.rewards import DAY_NS
from pyduckhunt.game.runtime import build_daily_schedule, select_scheduled_flight
from pyduckhunt.persistence import (
    JournalFile,
    ReplayEvent,
    SnapshotStore,
    recover,
    replay_records,
)
from pyduckhunt.persistence.replay import apply_replay_event, snapshot_from_result
from pyduckhunt.rendering.responses import render_outcomes, render_wire_response


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")
STATS = Command(CommandKind.STATS, "duckstats")


@dataclass(frozen=True, slots=True)
class BehavioralScenario:
    name: str
    initial_state: GameState
    events: tuple[ReplayEvent, ...]


def _collection_day_events() -> tuple[ReplayEvent, ...]:
    events: list[ReplayEvent] = []
    start_ns = DAY_NS + 10
    events.append(
        ReplayEvent.start_flight(
            start_ns,
            1_000,
            health=5,
            kind=FlightKind.GOLDEN,
        )
    )
    for offset in range(1, 6):
        events.append(
            ReplayEvent.command(
                start_ns + offset,
                "Hunter",
                SHOT,
                shot_attempt=ShotAttempt(),
            )
        )
    events.append(ReplayEvent.command(start_ns + 6, "Hunter", RELOAD))

    letters = (
        "letter_d",
        "letter_u",
        "letter_c",
        "letter_k",
        "letter_h",
        "letter_u",
        "letter_n",
        "letter_t",
    )
    for index, key in enumerate(letters):
        spawn_ns = start_ns + 20 + index * 10
        award = LootAward(key)
        if key == "letter_t":
            award = LootAward(
                key,
                completion_loot=(
                    LootAward("voucher_20"),
                    LootAward("xp_100"),
                    LootAward("tardis_bag"),
                ),
            )
        events.append(ReplayEvent.start_flight(spawn_ns, 1_000))
        events.append(
            ReplayEvent.command(
                spawn_ns + 1,
                "Hunter",
                SHOT,
                shot_attempt=ShotAttempt(loot=award),
            )
        )
        if index in (0, 6):
            events.append(ReplayEvent.command(spawn_ns + 2, "Hunter", RELOAD))
    return tuple(events)


def _karma_events() -> tuple[ReplayEvent, ...]:
    events = [ReplayEvent.command(1, "Hunter", RELOAD)]
    events.extend(
        ReplayEvent.command(
            now_ns,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(),
        )
        for now_ns in range(2, 9)
    )
    events.extend(
        (
            ReplayEvent.command(9, "Hunter", RELOAD),
            ReplayEvent.command(
                10,
                "Hunter",
                SHOT,
                shot_attempt=ShotAttempt(base_jam_bps=10_000, jam_roll=1),
            ),
            ReplayEvent.command(
                11,
                "Hunter",
                SHOT,
                shot_attempt=ShotAttempt(),
            ),
            ReplayEvent.command(12, "Hunter", RELOAD),
        )
    )
    return tuple(events)


def _runtime_events() -> tuple[ReplayEvent, ...]:
    schedule = build_daily_schedule(0, tuple(range(18)), (0,) * 18)
    first = schedule[0]
    return (
        ReplayEvent.install_daily_schedule(0, 0, schedule),
        ReplayEvent.schedule_tick(
            first,
            selection=select_scheduled_flight(1, golden_health_roll=5),
        ),
        ReplayEvent.runtime_command(first, "Hunter", STATS),
        ReplayEvent.runtime_command(first + 1, "Hunter", STATS),
        ReplayEvent.runtime_command(first + 2, "Hunter", STATS),
    )


COLLECTION_DAY = BehavioralScenario(
    "collection_day",
    GameState(),
    _collection_day_events(),
)

CARRY_RESET = BehavioralScenario(
    "carry_reset",
    GameState(
        now_ns=DAY_NS + 101,
        players=(
            PlayerState(
                "hunter",
                "Hunter",
                ammo=1,
                capacity=8,
                magazines=0,
                magazine_capacity=4,
                confiscated=True,
                fatigue_centi=1_600,
                carried_ducks=9,
                carried_day_start_ns=DAY_NS,
            ),
        ),
        effects=(
            ActiveEffect(
                1,
                118,
                "tardis_bag",
                EffectScope.PLAYER,
                "hunter",
                None,
                DAY_NS + 101,
                expires_at_ns=2 * DAY_NS + 101,
            ),
        ),
        next_effect_id=2,
    ),
    (
        ReplayEvent.advance_time(2 * DAY_NS),
        ReplayEvent.advance_time(2 * DAY_NS + 101),
    ),
)

KARMA_BAD_ACTIONS = BehavioralScenario(
    "karma_bad_actions",
    GameState(),
    _karma_events(),
)

NUISANCE_GLARE = BehavioralScenario(
    "nuisance_glare",
    GameState(
        players=(
            PlayerState("actor", "Actor", level=30, experience=300),
            PlayerState("target", "Target", level=30, experience=300),
        ),
    ),
    (
        ReplayEvent.purchase(
            100,
            "Actor",
            14,
            5,
            target_nickname="Target",
            target_present=True,
        ),
        ReplayEvent.start_flight(200, 1_000),
        ReplayEvent.command(
            300,
            "Target",
            SHOT,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=8_000,
                accuracy_roll=5_000,
            ),
        ),
    ),
)

INCIDENT_CHAIN = BehavioralScenario(
    "incident_chain",
    GameState(
        players=(
            PlayerState("first", "First", ammo=4, capacity=4, level=5, experience=40),
            PlayerState("hunter", "Hunter", ammo=4, capacity=4, level=5, experience=40),
            PlayerState("second", "Second", ammo=4, capacity=4, level=5, experience=40),
        ),
    ),
    (
        ReplayEvent.start_flight(100, 1_000),
        ReplayEvent.command(
            200,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=0,
                accuracy_roll=9_999,
                incident=IncidentAttempt(
                    (
                        IncidentTargetAttempt(
                            "First",
                            deflection_bps=7_500,
                            armor_bps=2_000,
                            deflection_roll=5_000,
                            armor_roll=9_000,
                        ),
                        IncidentTargetAttempt(
                            "Second",
                            armor_bps=8_000,
                            armor_roll=1_000,
                        ),
                    ),
                    incident_penalty=4,
                ),
            ),
        ),
    ),
)

RUNTIME_SCHEDULE = BehavioralScenario(
    "runtime_schedule",
    GameState(),
    _runtime_events(),
)

SCENARIOS = (
    COLLECTION_DAY,
    CARRY_RESET,
    KARMA_BAD_ACTIONS,
    NUISANCE_GLARE,
    INCIDENT_CHAIN,
    RUNTIME_SCHEDULE,
)


def _apply_scenario(
    scenario: BehavioralScenario,
) -> tuple[GameState, tuple[tuple[OutcomeKind, ...], ...]]:
    state = scenario.initial_state
    outcome_kinds: list[tuple[OutcomeKind, ...]] = []
    for event in scenario.events:
        decoded = ReplayEvent.from_payload(event.to_payload())
        transition = apply_replay_event(state, decoded)
        state = transition.state
        outcome_kinds.append(tuple(outcome.kind for outcome in transition.outcomes))
    return state, tuple(outcome_kinds)


class CalibratedBehaviorReplayTests(unittest.TestCase):
    def test_scenario_catalog_and_event_payloads_are_canonical(self) -> None:
        self.assertEqual(
            tuple(scenario.name for scenario in SCENARIOS),
            (
                "collection_day",
                "carry_reset",
                "karma_bad_actions",
                "nuisance_glare",
                "incident_chain",
                "runtime_schedule",
            ),
        )
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.name):
                self.assertGreater(len(scenario.events), 0)
                for event in scenario.events:
                    self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_collection_day_matches_observed_profile_boundaries(self) -> None:
        state, outcomes = _apply_scenario(COLLECTION_DAY)
        player = state.player("hunter")
        assert player is not None
        self.assertEqual((player.hits, player.golden_hits), (9, 1))
        self.assertEqual((player.level, player.experience), (6, 40))
        self.assertEqual((player.ammo, player.magazines), (6, 2))
        self.assertEqual((player.carried_ducks, player.fatigue_centi), (9, 1_600))
        self.assertEqual(player.letter_slots, (False,) * 8)
        self.assertEqual(player.shop_credit, 70)
        self.assertEqual(tuple(effect.key for effect in state.effects), ("tardis_bag",))
        self.assertEqual(outcomes[-1], (OutcomeKind.HIT, OutcomeKind.LOOT_ACQUIRED))

    def test_daily_boundary_resets_carry_and_expires_tardis_exactly(self) -> None:
        state, outcomes = _apply_scenario(CARRY_RESET)
        player = state.player("hunter")
        assert player is not None
        self.assertEqual((player.ammo, player.magazines), (8, 4))
        self.assertFalse(player.confiscated)
        self.assertEqual((player.carried_ducks, player.fatigue_centi), (0, 0))
        self.assertEqual(player.carried_day_start_ns, 2 * DAY_NS)
        self.assertEqual(state.effects, ())
        self.assertEqual(outcomes[0], ())
        self.assertEqual(outcomes[1], (OutcomeKind.EFFECT_EXPIRED,))

    def test_karma_trace_preserves_distinct_bad_action_counters(self) -> None:
        state, outcomes = _apply_scenario(KARMA_BAD_ACTIONS)
        player = state.player("hunter")
        assert player is not None
        self.assertEqual(
            (
                player.wild_shots,
                player.empty_shots,
                player.jammed_shots,
                player.compulsive_reloads,
            ),
            (6, 1, 1, 1),
        )
        self.assertEqual((player.ammo, player.magazines, player.fatigue_centi), (6, 1, 600))
        self.assertFalse(player.jammed)
        self.assertEqual(player_karma_basis_points(player), -10_000)
        self.assertEqual(outcomes[-1], (OutcomeKind.UNJAMMED,))

    def test_targeted_glare_is_attributed_consumed_and_replayed(self) -> None:
        state, outcomes = _apply_scenario(NUISANCE_GLARE)
        actor = state.player("actor")
        target = state.player("target")
        assert actor is not None and target is not None
        self.assertEqual(actor.karma_modifier_basis_points, -200)
        self.assertEqual(target.misses, 1)
        self.assertEqual(state.effects, ())
        self.assertEqual(outcomes[-1], (OutcomeKind.MISS,))
        transition = apply_replay_event(
            apply_replay_event(
                apply_replay_event(
                    NUISANCE_GLARE.initial_state,
                    NUISANCE_GLARE.events[0],
                ).state,
                NUISANCE_GLARE.events[1],
            ).state,
            NUISANCE_GLARE.events[2],
        )
        self.assertEqual(transition.outcomes[-1].effective_accuracy_bps, 4_000)
        self.assertEqual(transition.outcomes[-1].nuisance_source_key, "actor")

    def test_incident_chain_preserves_deflection_absorption_and_costs(self) -> None:
        state, outcomes = _apply_scenario(INCIDENT_CHAIN)
        hunter = state.player("hunter")
        first = state.player("first")
        second = state.player("second")
        assert hunter is not None and first is not None and second is not None
        self.assertEqual(outcomes[-1][-3:], (
            OutcomeKind.MISS,
            OutcomeKind.INCIDENT_DEFLECTED,
            OutcomeKind.INCIDENT_ABSORBED,
        ))
        self.assertEqual((hunter.experience, hunter.incidents_caused), (32, 2))
        self.assertEqual(hunter.confiscations, 1)
        self.assertEqual(first.incidents_deflected, 1)
        self.assertEqual(second.incidents_absorbed, 1)

    def test_runtime_trace_keeps_schedule_and_throttle_decisions(self) -> None:
        state, outcomes = _apply_scenario(RUNTIME_SCHEDULE)
        assert state.daily_schedule is not None and state.flight is not None
        self.assertEqual(state.daily_schedule.next_index, 1)
        self.assertIs(state.flight.kind, FlightKind.GOLDEN)
        self.assertEqual((state.flight.health, state.flight.reward_experience), (5, 60))
        self.assertEqual(outcomes[-1][-1], OutcomeKind.COMMAND_THROTTLED)

    def test_every_snapshot_cut_recovers_the_same_terminal_state(self) -> None:
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    journal = JournalFile(root / "events.jsonl")
                    snapshots = SnapshotStore(root / "snapshot.json")
                    for event in scenario.events:
                        journal.append(event)
                    records = journal.read_records()
                    expected, _ = _apply_scenario(scenario)
                    for cut in range(len(records) + 1):
                        prefix = replay_records(
                            records[:cut],
                            initial_state=scenario.initial_state,
                        )
                        snapshots.write(snapshot_from_result(prefix))
                        recovered = recover(snapshots, journal)
                        self.assertEqual(recovered.state, expected, msg=f"cut={cut}")

    def test_rendered_trace_output_stays_inside_the_irc_boundary(self) -> None:
        for scenario in SCENARIOS:
            state = scenario.initial_state
            for index, event in enumerate(scenario.events):
                transition = apply_replay_event(state, event)
                state = transition.state
                lines = render_outcomes(transition.outcomes)
                with self.subTest(scenario=scenario.name, event=index):
                    self.assertLessEqual(len(lines), 4)
                    for wire_line in render_wire_response("#synthetic", lines):
                        self.assertLessEqual(len(wire_line), 512)


if __name__ == "__main__":
    unittest.main()
