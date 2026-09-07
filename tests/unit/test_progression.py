from __future__ import annotations

import unittest

from pyduckhunt.game.model import PlayerState
from pyduckhunt.game.progression import (
    available_experience,
    debit_experience,
    experience_required,
    grant_experience,
    spend_experience,
)


def player(**changes: object) -> PlayerState:
    values: dict[str, object] = {"key": "hunter", "nickname": "Hunter"}
    values.update(changes)
    return PlayerState(**values)


class ProgressionTests(unittest.TestCase):
    def test_observed_level_targets(self) -> None:
        expected = {
            1: 20,
            30: 310,
            60: 610,
            61: 1240,
            69: 1400,
            70: 2130,
            71: 2160,
            79: 2400,
            80: 3240,
            89: 3600,
            90: 4550,
            94: 4750,
        }
        self.assertEqual(
            {level: experience_required(level) for level in expected},
            expected,
        )

    def test_grant_stays_inside_level(self) -> None:
        change = grant_experience(player(), 10)
        self.assertEqual((change.player.level, change.player.experience), (1, 10))
        self.assertEqual(change.levels_gained, 0)

    def test_grant_carries_over_to_next_level(self) -> None:
        change = grant_experience(player(experience=15), 10)
        self.assertEqual((change.player.level, change.player.experience), (2, 5))
        self.assertEqual(change.levels_gained, 1)

    def test_grant_crosses_multiple_levels(self) -> None:
        change = grant_experience(player(), 55)
        self.assertEqual((change.player.level, change.player.experience), (3, 5))
        self.assertEqual(change.levels_gained, 2)

    def test_high_level_boundary_uses_calibrated_target(self) -> None:
        change = grant_experience(player(level=60, experience=600), 20)
        self.assertEqual((change.player.level, change.player.experience), (61, 10))

    def test_rankings_page_total_matches_level_ninety_three_progress(self) -> None:
        teuk = player(level=93, experience=1_445)
        self.assertEqual(available_experience(teuk), 102_875)

    def test_level_change_applies_weapon_capacity_and_preserves_bag_bonus(self) -> None:
        promoted = grant_experience(
            player(
                level=9,
                experience=99,
                ammo=6,
                capacity=6,
                magazines=3,
                magazine_capacity=3,
            ),
            1,
        ).player
        self.assertEqual((promoted.level, promoted.ammo, promoted.capacity), (10, 4, 4))
        self.assertEqual((promoted.magazines, promoted.magazine_capacity), (3, 4))

    def test_spend_preserves_earned_level(self) -> None:
        change = spend_experience(player(level=30, experience=100), 13)
        self.assertEqual((change.player.level, change.player.experience), (30, 87))
        self.assertEqual(change.amount, -13)

    def test_spend_crosses_downward_level_boundary(self) -> None:
        change = spend_experience(player(level=3, experience=2), 13)
        self.assertEqual((change.player.level, change.player.experience), (2, 19))
        self.assertEqual(change.levels_lost, 1)

    def test_total_balance_includes_completed_levels(self) -> None:
        self.assertEqual(available_experience(player(level=3, experience=2)), 52)

    def test_penalty_is_bounded_at_zero_balance(self) -> None:
        change = debit_experience(player(level=2, experience=3), 99)
        self.assertEqual((change.player.level, change.player.experience), (1, 0))
        self.assertEqual(change.amount, -23)

    def test_spend_rejects_insufficient_balance(self) -> None:
        with self.assertRaises(ValueError):
            spend_experience(player(experience=3), 4)

    def test_truth_values_are_not_amounts_or_levels(self) -> None:
        with self.assertRaises(ValueError):
            grant_experience(player(), True)
        with self.assertRaises(ValueError):
            experience_required(True)


if __name__ == "__main__":
    unittest.main()
