from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    FlightKind,
    GameState,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.targets import flight_reward


SHOT = Command(CommandKind.SHOT, "bang")
DAY_NS = 86_400_000_000_000


class RareFlightTests(unittest.TestCase):
    def test_calibrated_rewards_and_health_boundaries(self) -> None:
        self.assertEqual(flight_reward(FlightKind.STANDARD, 7), 10)
        self.assertEqual(flight_reward(FlightKind.GOLDEN, 3), 36)
        self.assertEqual(flight_reward(FlightKind.GOLDEN, 5), 60)
        self.assertEqual(flight_reward(FlightKind.MECHANICAL, 1), 0)
        with self.assertRaises(ValueError):
            flight_reward(FlightKind.GOLDEN, 2)
        with self.assertRaises(ValueError):
            flight_reward(FlightKind.MECHANICAL, 2)

    def test_golden_kill_awards_health_scaled_experience_and_counter(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", ammo=3, capacity=3),))
        state = start_flight(
            state,
            0,
            lifetime_ns=100,
            health=3,
            kind=FlightKind.GOLDEN,
        ).state
        for now_ns in (1, 2):
            transition = apply_command(state, "Hunter", SHOT, now_ns)
            state = transition.state
            self.assertEqual(transition.outcomes[-1].kind, OutcomeKind.FLIGHT_SURVIVED)
        killed = apply_command(state, "Hunter", SHOT, 3)
        hit = killed.outcomes[-1]
        self.assertEqual(hit.kind, OutcomeKind.HIT)
        self.assertEqual(hit.flight_kind, FlightKind.GOLDEN)
        self.assertEqual(hit.experience_awarded, 36)
        self.assertEqual(killed.state.players[0].golden_hits, 1)

    def test_mechanical_target_has_no_base_reward(self) -> None:
        state = start_flight(
            GameState(),
            0,
            lifetime_ns=100,
            kind=FlightKind.MECHANICAL,
        ).state
        killed = apply_command(state, "Hunter", SHOT, 1)
        self.assertEqual(killed.outcomes[-1].experience_awarded, 0)
        self.assertEqual(killed.state.players[0].experience, 0)

    def test_frenzy_burden_confusion_and_explosive_compose_on_golden_kill(self) -> None:
        player = PlayerState("hunter", "Hunter", ammo=2, capacity=2)
        explosive = ActiveEffect(
            1,
            4,
            "explosive_ammunition",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=DAY_NS,
        )
        curses = (
            ActiveCurse(1, "burden", "hunter", 0, DAY_NS, 2),
            ActiveCurse(2, "confusion", "hunter", 0, DAY_NS, 2),
            ActiveCurse(3, "frenzy", "hunter", 0, 14_400_000_000_000, 2),
        )
        state = GameState(
            players=(player,),
            next_effect_id=2,
            effects=(explosive,),
            next_curse_id=4,
            curses=curses,
        )
        state = start_flight(
            state,
            0,
            lifetime_ns=100,
            health=5,
            kind=FlightKind.GOLDEN,
        ).state
        killed = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(fatigue_gain_centi=100),
        )
        hit = killed.outcomes[-1]
        self.assertEqual(hit.damage_dealt, 6)
        self.assertEqual(hit.rounds_consumed, 2)
        self.assertEqual(hit.fatigue_changed_centi, 400)
        self.assertEqual(hit.experience_awarded, 30)
        self.assertEqual(killed.state.players[0].golden_hits, 1)


if __name__ == "__main__":
    unittest.main()
