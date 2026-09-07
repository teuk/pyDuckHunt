from __future__ import annotations

import unittest

from pyduckhunt.game.catalog import MINUTE_NS
from pyduckhunt.game.engine import advance_time, start_flight
from pyduckhunt.game.model import GameState, OutcomeKind, PlayerState
from pyduckhunt.game.shop import purchase


def funded_state() -> GameState:
    return GameState(
        players=(PlayerState("hunter", "Hunter", level=30, experience=300),)
    )


class ChannelActionTests(unittest.TestCase):
    def test_call_requires_injected_deadline(self) -> None:
        with self.assertRaises(ValueError):
            purchase(funded_state(), "Hunter", 20, 100)

    def test_call_accepts_entire_ten_minute_window(self) -> None:
        deadline = 100 + 10 * MINUTE_NS
        bought = purchase(
            funded_state(),
            "Hunter",
            20,
            100,
            scheduled_for_ns=deadline,
        )
        action = bought.state.scheduled_actions[0]
        self.assertEqual((action.action_id, action.item_id, action.due_at_ns), (1, 20, deadline))
        self.assertEqual(bought.state.next_action_id, 2)
        self.assertEqual(
            bought.state.player("hunter").karma_modifier_basis_points,
            200,
        )

    def test_call_rejects_deadline_outside_window(self) -> None:
        with self.assertRaises(ValueError):
            purchase(
                funded_state(),
                "Hunter",
                20,
                100,
                scheduled_for_ns=100 + 10 * MINUTE_NS + 1,
            )

    def test_mechanical_duck_uses_exact_ten_minute_deadline(self) -> None:
        bought = purchase(funded_state(), "Hunter", 23, 100)
        self.assertEqual(
            bought.state.scheduled_actions[0].due_at_ns,
            100 + 10 * MINUTE_NS,
        )

    def test_due_action_is_emitted_at_exact_deadline(self) -> None:
        deadline = 100 + MINUTE_NS
        bought = purchase(
            funded_state(),
            "Hunter",
            20,
            100,
            scheduled_for_ns=deadline,
        )
        before = advance_time(bought.state, deadline - 1)
        self.assertEqual(len(before.state.scheduled_actions), 1)
        due = advance_time(before.state, deadline)
        self.assertEqual(due.state.scheduled_actions, ())
        self.assertEqual(due.outcomes[-1].kind, OutcomeKind.CHANNEL_ACTION_DUE)
        self.assertEqual(due.outcomes[-1].action_id, 1)

    def test_detector_is_consumed_by_next_flight(self) -> None:
        bought = purchase(funded_state(), "Hunter", 22, 100)
        started = start_flight(bought.state, 101, lifetime_ns=1_000)
        self.assertEqual(started.state.effects, ())
        self.assertEqual(
            tuple(outcome.kind for outcome in started.outcomes),
            (OutcomeKind.FLIGHT_STARTED, OutcomeKind.DUCK_ALERT),
        )
        self.assertEqual(started.outcomes[-1].actor, "Hunter")

    def test_active_flight_does_not_consume_detector(self) -> None:
        started = start_flight(funded_state(), 100, lifetime_ns=1_000)
        bought = purchase(started.state, "Hunter", 22, 101)
        rejected = start_flight(bought.state, 102, lifetime_ns=1_000)
        self.assertEqual(rejected.outcomes[-1].kind, OutcomeKind.FLIGHT_ALREADY_ACTIVE)
        self.assertEqual(len(rejected.state.effects), 1)

    def test_next_successful_flight_consumes_exactly_one_oldest_bread(self) -> None:
        first = purchase(funded_state(), "Hunter", 21, 100)
        second = purchase(first.state, "Hunter", 21, 200)
        started = start_flight(second.state, 201, lifetime_ns=1_000)
        self.assertEqual(
            tuple(effect.effect_id for effect in started.state.effects),
            (2,),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in started.outcomes),
            (OutcomeKind.FLIGHT_STARTED, OutcomeKind.EFFECT_CONSUMED),
        )
        self.assertEqual(started.outcomes[-1].effect_id, 1)

    def test_refused_flight_does_not_consume_bread(self) -> None:
        started = start_flight(funded_state(), 100, lifetime_ns=1_000)
        bought = purchase(started.state, "Hunter", 21, 101)
        rejected = start_flight(bought.state, 102, lifetime_ns=1_000)
        self.assertEqual(rejected.outcomes[-1].kind, OutcomeKind.FLIGHT_ALREADY_ACTIVE)
        self.assertEqual(
            tuple(effect.effect_id for effect in rejected.state.effects),
            (1,),
        )


if __name__ == "__main__":
    unittest.main()
