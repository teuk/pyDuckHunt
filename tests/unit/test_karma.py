from __future__ import annotations

import unittest

from pyduckhunt.game.karma import (
    KARMA_DECAY_PERIOD_NS,
    adjust_karma_modifier,
    calculate_karma_basis_points,
    decay_karma_modifier,
    karma_adjusted_jam_basis_points,
    player_base_karma_basis_points,
    player_karma_basis_points,
)
from pyduckhunt.game.model import PlayerState


class KarmaTests(unittest.TestCase):
    def test_historical_weighting_and_neutral_profile_are_exact(self) -> None:
        self.assertEqual(calculate_karma_basis_points(0, 0, 0), 0)
        self.assertEqual(calculate_karma_basis_points(1, 0, 0), 10_000)
        self.assertEqual(calculate_karma_basis_points(0, 1, 0), -10_000)
        self.assertEqual(calculate_karma_basis_points(1, 1, 0), 3_333)
        self.assertEqual(calculate_karma_basis_points(1, 0, 1), -2_000)

    def test_player_karma_uses_only_historical_moral_counters(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            hits=10,
            misses=40,
            wild_shots=1,
            incidents_caused=1,
        )
        self.assertEqual(player_karma_basis_points(player), 6_667)

    def test_complete_observed_formula_uses_quarter_weight_mistakes(self) -> None:
        self.assertEqual(
            calculate_karma_basis_points(8_023, 137, 65, 465, 3, 270),
            9_376,
        )
        player = PlayerState(
            "hunter",
            "Hunter",
            hits=8_023,
            wild_shots=137,
            incidents_caused=65,
            empty_shots=465,
            jammed_shots=3,
            compulsive_reloads=270,
        )
        self.assertEqual(player_base_karma_basis_points(player), 9_376)

    def test_temporary_modifier_decays_point_twelve_every_two_hours(self) -> None:
        player = adjust_karma_modifier(
            PlayerState("hunter", "Hunter", hits=1),
            200,
            10,
        )
        self.assertEqual(player_karma_basis_points(player), 10_000)
        self.assertEqual(player.karma_modifier_basis_points, 200)
        self.assertEqual(player.karma_decay_at_ns, 10 + KARMA_DECAY_PERIOD_NS)
        before = decay_karma_modifier(player, 9 + KARMA_DECAY_PERIOD_NS)
        self.assertEqual(before, player)
        first = decay_karma_modifier(player, 10 + KARMA_DECAY_PERIOD_NS)
        self.assertEqual(first.karma_modifier_basis_points, 188)
        later = decay_karma_modifier(first, 10 + 20 * KARMA_DECAY_PERIOD_NS)
        self.assertEqual(later.karma_modifier_basis_points, 0)
        self.assertIsNone(later.karma_decay_at_ns)

    def test_karma_changes_jam_risk_without_leaving_bounds(self) -> None:
        self.assertEqual(karma_adjusted_jam_basis_points(1_000, 10_000), 500)
        self.assertEqual(karma_adjusted_jam_basis_points(1_000, 0), 1_000)
        self.assertEqual(karma_adjusted_jam_basis_points(6_000, -10_000), 10_000)

    def test_truth_values_and_negative_counters_are_rejected(self) -> None:
        for values in (
            (True, 0, 0),
            (0, -1, 0),
            (0, 0, -1),
            (0, 0, 0, -1, 0, 0),
            (0, 0, 0, 0, True, 0),
        ):
            with self.assertRaises(ValueError):
                calculate_karma_basis_points(*values)


if __name__ == "__main__":
    unittest.main()
