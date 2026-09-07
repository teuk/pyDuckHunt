from __future__ import annotations

import unittest

from pyduckhunt.game.catalog import HOUR_NS
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import GameState, OutcomeKind, PlayerState, ShotAttempt
from pyduckhunt.game.shop import purchase


SHOT = Command(CommandKind.SHOT, "bang")


def players() -> GameState:
    return GameState(
        players=(
            PlayerState("actor", "Actor", level=30, experience=300),
            PlayerState(
                "hunter",
                "Hunter",
                ammo=6,
                capacity=6,
                level=30,
                experience=300,
            ),
        )
    )


def nuisance(item_id: int, now_ns: int = 100) -> GameState:
    return purchase(
        players(),
        "Actor",
        item_id,
        now_ns,
        target_nickname="Hunter",
        target_present=True,
    ).state


class NuisanceShotTests(unittest.TestCase):
    def test_soaked_player_cannot_shoot_before_exact_expiration(self) -> None:
        state = nuisance(16)
        deadline = 100 + HOUR_NS
        blocked = apply_command(state, "Hunter", SHOT, deadline - 1)
        outcome = blocked.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.HUNT_BLOCKED)
        self.assertEqual(outcome.nuisance_source_key, "actor")
        self.assertEqual(blocked.state.player("hunter").ammo, 6)
        resumed = apply_command(blocked.state, "Hunter", SHOT, deadline)
        self.assertEqual(
            tuple(value.kind for value in resumed.outcomes),
            (OutcomeKind.EFFECT_EXPIRED, OutcomeKind.MISS),
        )
        self.assertEqual(resumed.state.player("hunter").ammo, 5)

    def test_glare_halves_next_fired_shot_accuracy(self) -> None:
        state = nuisance(14)
        flight = start_flight(state, 200, lifetime_ns=10_000)
        result = apply_command(
            flight.state,
            "Hunter",
            SHOT,
            300,
            shot_attempt=ShotAttempt(base_accuracy_bps=8_000, accuracy_roll=5_000),
        )
        outcome = result.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.MISS)
        self.assertEqual(outcome.effective_accuracy_bps, 4_000)
        self.assertEqual(outcome.nuisance_source_key, "actor")
        self.assertEqual(result.state.effects, ())

    def test_glare_waits_when_weapon_jams_before_firing(self) -> None:
        state = nuisance(14)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=1),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.JAMMED)
        self.assertEqual(result.state.effects[0].item_id, 14)

    def test_sand_doubles_jam_risk_and_is_consumed_on_trigger(self) -> None:
        state = nuisance(15)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=1_500),
        )
        outcome = result.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.JAMMED)
        self.assertEqual(outcome.effective_jam_bps, 2_000)
        self.assertEqual(outcome.nuisance_source_key, "actor")
        self.assertEqual(result.state.effects, ())
        self.assertEqual(result.state.player("hunter").ammo, 6)

    def test_sand_is_consumed_even_when_the_shot_does_not_jam(self) -> None:
        state = nuisance(15)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=2_500),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertEqual(result.outcomes[-1].effective_jam_bps, 2_000)
        self.assertEqual(result.state.effects, ())

    def test_sabotage_forces_jam_without_consuming_ammunition(self) -> None:
        state = nuisance(17)
        result = apply_command(state, "Hunter", SHOT, 200)
        outcome = result.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.SABOTAGE_TRIGGERED)
        self.assertEqual(outcome.nuisance_source_key, "actor")
        self.assertTrue(result.state.player("hunter").jammed)
        self.assertEqual(result.state.player("hunter").ammo, 6)
        self.assertEqual(result.state.effects, ())


if __name__ == "__main__":
    unittest.main()
