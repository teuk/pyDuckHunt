from __future__ import annotations

import unittest

from pyduckhunt.game.engine import start_flight
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    FlightKind,
    GameState,
    OutcomeKind,
    PlayerState,
)
from pyduckhunt.game.runtime import (
    BOOTSTRAP_DAILY_FLIGHT_COUNT,
    DAY_NS,
    build_daily_schedule,
    install_daily_schedule,
    select_scheduled_flight,
    tick_daily_schedule,
)


HOURS = tuple(range(18))
MINUTES = (0,) * 18


def schedule(day_start_ns: int = 0) -> tuple[int, ...]:
    return build_daily_schedule(day_start_ns, HOURS, MINUTES)


class RuntimeSchedulerTests(unittest.TestCase):
    def test_builder_sorts_injected_hours_and_moves_midnight_to_0001(self) -> None:
        deadlines = build_daily_schedule(0, tuple(reversed(HOURS)), MINUTES)
        self.assertEqual(deadlines[0], 60_000_000_000)
        self.assertEqual(deadlines[1], 3_600_000_000_000)
        self.assertEqual(len(deadlines), 18)
        bootstrap = build_daily_schedule(
            0,
            tuple(range(BOOTSTRAP_DAILY_FLIGHT_COUNT)),
            (0,) * BOOTSTRAP_DAILY_FLIGHT_COUNT,
        )
        self.assertEqual(len(bootstrap), BOOTSTRAP_DAILY_FLIGHT_COUNT)

    def test_builder_rejects_duplicate_hours_and_truth_values(self) -> None:
        with self.assertRaises(ValueError):
            build_daily_schedule(0, (0,) * 18, MINUTES)
        with self.assertRaises(ValueError):
            build_daily_schedule(0, (True, *range(1, 18)), MINUTES)
        with self.assertRaises(ValueError):
            build_daily_schedule(1, HOURS, MINUTES)
        with self.assertRaises(ValueError):
            build_daily_schedule(0, tuple(range(20)), (0,) * 20)

    def test_exact_due_tick_dispatches_the_injected_golden_flight(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        ticked = tick_daily_schedule(
            installed.state,
            deadlines[0],
            selection=select_scheduled_flight(1, golden_health_roll=4),
        )
        self.assertEqual(ticked.state.daily_schedule.next_index, 1)
        self.assertEqual(ticked.state.flight.kind, FlightKind.GOLDEN)
        self.assertEqual(ticked.state.flight.health, 4)

    def test_restart_tick_skips_every_past_deadline_without_a_burst(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        recovered = tick_daily_schedule(installed.state, deadlines[2] + 1)
        self.assertIsNone(recovered.state.flight)
        self.assertEqual(recovered.state.daily_schedule.next_index, 3)
        skipped = next(
            outcome
            for outcome in recovered.outcomes
            if outcome.kind is OutcomeKind.SCHEDULED_FLIGHT_SKIPPED
        )
        self.assertEqual(skipped.skipped_deadlines_ns, deadlines[:3])

    def test_active_flight_causes_exact_scheduled_deadline_to_be_skipped(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        active = start_flight(
            installed.state,
            deadlines[0] - 1,
            lifetime_ns=10_000_000_000,
        )
        ticked = tick_daily_schedule(active.state, deadlines[0])
        self.assertEqual(ticked.state.daily_schedule.next_index, 1)
        self.assertEqual(ticked.state.flight.flight_id, 1)
        with self.assertRaises(ValueError):
            tick_daily_schedule(
                active.state,
                deadlines[0],
                selection=select_scheduled_flight(2),
            )

    def test_missing_selection_skips_an_exact_deadline(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        ticked = tick_daily_schedule(installed.state, deadlines[0])
        self.assertIsNone(ticked.state.flight)
        self.assertEqual(ticked.state.daily_schedule.next_index, 1)

    def test_selection_is_rejected_outside_an_exact_deadline(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        with self.assertRaises(ValueError):
            tick_daily_schedule(
                installed.state,
                deadlines[0] - 1,
                selection=select_scheduled_flight(2),
            )

    def test_same_day_install_is_idempotent_and_cannot_replace_entropy(self) -> None:
        deadlines = schedule()
        installed = install_daily_schedule(GameState(), 0, 0, deadlines)
        ticked = tick_daily_schedule(installed.state, deadlines[0])
        repeated = install_daily_schedule(ticked.state, deadlines[0], 0, deadlines)
        self.assertEqual(repeated.state.daily_schedule.next_index, 1)
        changed = (*deadlines[:-1], deadlines[-1] + 1)
        with self.assertRaises(ValueError):
            install_daily_schedule(ticked.state, deadlines[0], 0, changed)

    def test_next_utc_day_can_replace_the_previous_schedule(self) -> None:
        first = install_daily_schedule(GameState(), 0, 0, schedule())
        second_deadlines = schedule(DAY_NS)
        second = install_daily_schedule(
            first.state,
            DAY_NS,
            DAY_NS,
            second_deadlines,
        )
        self.assertEqual(second.state.daily_schedule.day_start_ns, DAY_NS)
        self.assertEqual(second.state.daily_schedule.next_index, 0)

    def test_recovered_schedule_composes_with_detector_and_golden_selection(self) -> None:
        deadlines = schedule()
        player = PlayerState("hunter", "Hunter")
        detector = ActiveEffect(
            1,
            22,
            "duck_detector",
            EffectScope.PLAYER,
            player.key,
            None,
            0,
            remaining_uses=1,
        )
        initial = GameState(
            players=(player,),
            next_effect_id=2,
            effects=(detector,),
        )
        installed = install_daily_schedule(initial, 0, 0, deadlines)
        recovered = tick_daily_schedule(installed.state, deadlines[1] + 1)
        launched = tick_daily_schedule(
            recovered.state,
            deadlines[2],
            selection=select_scheduled_flight(1, golden_health_roll=3),
        )
        kinds = tuple(outcome.kind for outcome in launched.outcomes)
        self.assertIn(OutcomeKind.DUCK_ALERT, kinds)
        self.assertEqual(launched.state.effects, ())
        self.assertEqual(launched.state.flight.kind, FlightKind.GOLDEN)


if __name__ == "__main__":
    unittest.main()
