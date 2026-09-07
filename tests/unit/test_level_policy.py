from __future__ import annotations

import unittest

from pyduckhunt.game.level_policy import MAX_CALIBRATED_LEVEL, level_policy


class LevelPolicyTests(unittest.TestCase):
    def test_level_one_matches_the_current_v3_table(self) -> None:
        policy = level_policy(1)
        self.assertEqual(policy.weapon_label, "mitraillette")
        self.assertEqual(policy.accuracy_bps, 5_500)
        self.assertEqual(policy.jam_bps, 1_500)
        self.assertEqual((policy.ammo_capacity, policy.magazine_capacity), (6, 2))
        self.assertEqual((policy.miss_penalty, policy.wild_penalty), (1, 1))
        self.assertFalse(policy.silent)

    def test_weapon_boundaries_are_exact(self) -> None:
        expected = {
            9: ("mitraillette", 6, 2),
            10: ("fusil d'assaut", 4, 3),
            20: ("fusil de chasse", 2, 4),
            30: ("fusil de précision", 1, 6),
            40: ("arc", 1, 5),
            60: ("arbalète", 1, 5),
        }
        self.assertEqual(
            {
                level: (
                    level_policy(level).weapon_label,
                    level_policy(level).ammo_capacity,
                    level_policy(level).magazine_capacity,
                )
                for level in expected
            },
            expected,
        )

    def test_high_level_accuracy_reliability_and_penalties_are_exact(self) -> None:
        expected = {
            70: (9_600, 900, 7, 12, 26),
            80: (9_800, 800, 8, 14, 27),
            93: (9_900, 700, 9, 16, 28),
            95: (9_900, 600, 9, 16, 28),
            100: (9_900, 500, 10, 18, 30),
        }
        self.assertEqual(
            {
                level: (
                    level_policy(level).accuracy_bps,
                    level_policy(level).jam_bps,
                    level_policy(level).miss_penalty,
                    level_policy(level).wild_penalty,
                    level_policy(level).incident_penalty,
                )
                for level in expected
            },
            expected,
        )

    def test_bow_and_crossbow_are_silent_and_nuisance_immune(self) -> None:
        self.assertFalse(level_policy(39).silent)
        for level in (40, 60, MAX_CALIBRATED_LEVEL):
            self.assertTrue(level_policy(level).silent)
            self.assertTrue(level_policy(level).nuisance_immune)

    def test_post_table_levels_are_clamped_and_cross_types_rejected(self) -> None:
        self.assertEqual(level_policy(101), level_policy(MAX_CALIBRATED_LEVEL))
        for value in (0, True, 1.0):
            with self.assertRaises(ValueError):
                level_policy(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
