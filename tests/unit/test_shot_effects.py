from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import (
    GameState,
    Outcome,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.shop import purchase
from pyduckhunt.rendering import render_outcome


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")


def player_state() -> GameState:
    return GameState(
        players=(
            PlayerState(
                "hunter",
                "Hunter",
                ammo=6,
                capacity=6,
                magazines=5,
                magazine_capacity=5,
                level=30,
                experience=300,
            ),
        )
    )


def equipped(item_id: int, *, magnitude: int | None = None) -> GameState:
    return purchase(
        player_state(),
        "Hunter",
        item_id,
        100,
        magnitude=magnitude,
    ).state


class ShotEffectTests(unittest.TestCase):
    def test_shot_attempt_rejects_out_of_range_or_truth_value_rolls(self) -> None:
        with self.assertRaises(ValueError):
            ShotAttempt(accuracy_roll=0)
        with self.assertRaises(ValueError):
            ShotAttempt(base_jam_bps=True)

    def test_engine_rejects_non_contract_shot_attempt(self) -> None:
        with self.assertRaises(ValueError):
            apply_command(
                player_state(),
                "Hunter",
                SHOT,
                100,
                shot_attempt={"accuracy_roll": 1},
            )

    def test_scope_adds_accuracy_and_consumes_one_use_after_firing(self) -> None:
        state = equipped(7, magnitude=15)
        flight = start_flight(state, 200, lifetime_ns=10_000)
        result = apply_command(
            flight.state,
            "Hunter",
            SHOT,
            300,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=4_000,
                accuracy_roll=5_000,
            ),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.HIT)
        self.assertEqual(result.outcomes[-1].effective_accuracy_bps, 5_500)
        self.assertEqual(result.state.effects[0].remaining_uses, 5)

    def test_scope_is_not_consumed_when_weapon_jams(self) -> None:
        state = equipped(7, magnitude=9)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=500),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.JAMMED)
        self.assertEqual(result.state.effects[0].remaining_uses, 6)

    def test_grease_halves_the_injected_jam_risk(self) -> None:
        state = equipped(6)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=750),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertEqual(result.outcomes[-1].effective_jam_bps, 500)

    def test_same_roll_without_grease_jams_the_weapon(self) -> None:
        result = apply_command(
            player_state(),
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=750),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.JAMMED)
        self.assertTrue(result.state.players[0].jammed)
        self.assertEqual(result.state.players[0].ammo, 6)
        self.assertEqual(result.state.players[0].jams, 1)
        self.assertEqual(result.state.players[0].shots_fired, 0)

    def test_reload_unjams_without_spending_a_magazine(self) -> None:
        jammed = apply_command(
            player_state(),
            "Hunter",
            SHOT,
            100,
            shot_attempt=ShotAttempt(base_jam_bps=10_000, jam_roll=1),
        )
        cleared = apply_command(jammed.state, "Hunter", RELOAD, 200)
        self.assertEqual(cleared.outcomes[-1].kind, OutcomeKind.UNJAMMED)
        self.assertFalse(cleared.state.players[0].jammed)
        self.assertEqual(cleared.state.players[0].magazines, 5)
        self.assertEqual(cleared.state.players[0].ammo, 6)

    def test_infrared_lock_blocks_wild_shot_and_consumes_one_use(self) -> None:
        state = equipped(8)
        result = apply_command(state, "Hunter", SHOT, 200)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.TRIGGER_LOCKED)
        self.assertEqual(result.state.players[0].ammo, 6)
        self.assertEqual(result.state.players[0].misses, 0)
        self.assertEqual(result.state.effects[0].remaining_uses, 5)

    def test_penetrating_ammunition_deals_two_damage(self) -> None:
        state = equipped(3)
        flight = start_flight(state, 200, lifetime_ns=10_000, health=4)
        result = apply_command(flight.state, "Hunter", SHOT, 300)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.FLIGHT_SURVIVED)
        self.assertEqual(result.outcomes[-1].damage_dealt, 2)
        self.assertEqual(result.outcomes[-1].ammunition_item_id, 3)
        self.assertEqual(result.state.flight.health, 2)

    def test_explosive_ammunition_deals_three_damage(self) -> None:
        state = equipped(4)
        flight = start_flight(state, 200, lifetime_ns=10_000, health=3)
        result = apply_command(flight.state, "Hunter", SHOT, 300)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.HIT)
        self.assertEqual(result.outcomes[-1].damage_dealt, 3)
        self.assertEqual(result.outcomes[-1].ammunition_item_id, 4)
        self.assertIsNone(result.state.flight)
        rendered = render_outcome(result.outcomes[-1])[0]
        self.assertIn("*BOUM*", rendered)
        self.assertNotIn("*BANG*", rendered)

    def test_standard_ammunition_is_explicitly_absent_from_the_outcome(self) -> None:
        flight = start_flight(player_state(), 200, lifetime_ns=10_000)
        result = apply_command(flight.state, "Hunter", SHOT, 300)
        self.assertIsNone(result.outcomes[-1].ammunition_item_id)

    def test_outcome_rejects_a_non_ammunition_item_identifier(self) -> None:
        with self.assertRaises(ValueError):
            Outcome(OutcomeKind.HIT, ammunition_item_id=2)

    def test_lucky_charm_adds_its_magnitude_to_hit_experience(self) -> None:
        state = equipped(10, magnitude=7)
        flight = start_flight(state, 200, lifetime_ns=10_000)
        result = apply_command(flight.state, "Hunter", SHOT, 300)
        self.assertEqual(result.outcomes[-1].experience_awarded, 17)
        self.assertEqual(result.state.players[0].experience, 304)

    def test_suppressor_prevents_noise_escape(self) -> None:
        state = equipped(9)
        flight = start_flight(state, 200, lifetime_ns=10_000)
        result = apply_command(
            flight.state,
            "Hunter",
            SHOT,
            300,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=0,
                accuracy_roll=1,
                frighten_on_miss=True,
            ),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertTrue(result.outcomes[-1].noise_suppressed)
        self.assertIsNotNone(result.state.flight)

    def test_unsuppressed_noisy_miss_ends_the_flight(self) -> None:
        flight = start_flight(player_state(), 200, lifetime_ns=10_000)
        result = apply_command(
            flight.state,
            "Hunter",
            SHOT,
            300,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=0,
                accuracy_roll=1,
                frighten_on_miss=True,
            ),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.MISS, OutcomeKind.FLIGHT_FRIGHTENED),
        )
        self.assertIsNone(result.state.flight)


if __name__ == "__main__":
    unittest.main()
