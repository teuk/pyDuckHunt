from __future__ import annotations

import unittest

from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    FlightKind,
    GameState,
    LootAward,
    PlayerState,
)
from pyduckhunt.game.runtime import (
    BOOTSTRAP_DAILY_FLIGHT_COUNT,
    DAILY_FLIGHT_COUNT,
    DAY_NS,
    FLIGHT_LIFETIME_NS,
    GROWTH_DAILY_FLIGHT_COUNT,
    adaptive_daily_flight_count,
    community_hunt_progress,
    loot_chance_multiplier,
    select_runtime_loot,
    select_scheduled_flight,
    validate_daily_schedule,
)


class RuntimePolicyTests(unittest.TestCase):
    def test_daily_schedule_requires_one_supported_unique_ordered_count(self) -> None:
        for count in (DAILY_FLIGHT_COUNT, GROWTH_DAILY_FLIGHT_COUNT, BOOTSTRAP_DAILY_FLIGHT_COUNT):
            with self.subTest(count=count):
                validate_daily_schedule(0, tuple(range(count)))
        schedule = tuple(range(DAILY_FLIGHT_COUNT))
        with self.assertRaises(ValueError):
            validate_daily_schedule(0, schedule[:-1])
        with self.assertRaises(ValueError):
            validate_daily_schedule(0, (*schedule[:-1], schedule[-2]))
        with self.assertRaises(ValueError):
            validate_daily_schedule(0, (*schedule[:-1], DAY_NS))

    def test_community_progress_selects_bootstrap_growth_and_mature_counts(self) -> None:
        for hits, expected in (
            (0, BOOTSTRAP_DAILY_FLIGHT_COUNT),
            (24, BOOTSTRAP_DAILY_FLIGHT_COUNT),
            (25, GROWTH_DAILY_FLIGHT_COUNT),
            (99, GROWTH_DAILY_FLIGHT_COUNT),
            (100, DAILY_FLIGHT_COUNT),
        ):
            with self.subTest(hits=hits):
                state = GameState(players=(PlayerState("hunter", "Hunter", hits=hits),))
                self.assertEqual(community_hunt_progress(state), hits)
                self.assertEqual(adaptive_daily_flight_count(state), expected)
        combined = GameState(
            players=(
                PlayerState("alice", "Alice", hits=12),
                PlayerState("bob", "Bob", hits=13),
            )
        )
        self.assertEqual(community_hunt_progress(combined), 25)
        self.assertEqual(adaptive_daily_flight_count(combined), GROWTH_DAILY_FLIGHT_COUNT)

    def test_one_in_eighteen_kind_weight_and_golden_health_are_explicit(self) -> None:
        golden = select_scheduled_flight(1, golden_health_roll=5)
        self.assertEqual(golden.kind, FlightKind.GOLDEN)
        self.assertEqual(golden.health, 5)
        self.assertEqual(golden.reward_experience, 60)
        self.assertEqual(golden.lifetime_ns, FLIGHT_LIFETIME_NS)
        standard = select_scheduled_flight(2)
        self.assertEqual(standard.kind, FlightKind.STANDARD)
        self.assertEqual(standard.health, 1)

    def test_runtime_rejects_truth_values_and_unpaired_golden_health(self) -> None:
        with self.assertRaises(ValueError):
            select_scheduled_flight(True, golden_health_roll=3)
        with self.assertRaises(ValueError):
            select_scheduled_flight(1)
        with self.assertRaises(ValueError):
            select_scheduled_flight(18, golden_health_roll=3)

    def test_abundance_doubles_only_the_bounded_standard_thresholds(self) -> None:
        player = PlayerState("hunter", "Hunter")
        abundance = ActiveEffect(
            1,
            101,
            "abundance_amulet",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=DAY_NS,
        )
        ordinary = GameState(players=(player,))
        boosted = GameState(players=(player,), next_effect_id=2, effects=(abundance,))
        rolls = (21, *(1_000 for _ in range(17)))
        self.assertEqual(loot_chance_multiplier(ordinary, "Hunter"), 1)
        self.assertEqual(loot_chance_multiplier(boosted, "Hunter"), 2)
        self.assertIsNone(select_runtime_loot(ordinary, "Hunter", rolls))
        self.assertEqual(
            select_runtime_loot(boosted, "Hunter", rolls),
            LootAward("junk_item"),
        )

    def test_uncalibrated_unusual_frequency_stays_an_injected_boundary(self) -> None:
        rolls = tuple(1_000 for _ in range(18))
        award = LootAward("voucher_75")
        self.assertEqual(
            select_runtime_loot(
                GameState(),
                "Hunter",
                rolls,
                unusual_award=award,
            ),
            award,
        )
        with self.assertRaises(ValueError):
            select_runtime_loot(
                GameState(),
                "Hunter",
                rolls,
                unusual_award=LootAward("xp_10"),
            )


if __name__ == "__main__":
    unittest.main()
