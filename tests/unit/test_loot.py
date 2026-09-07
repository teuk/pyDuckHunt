from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.loot import (
    CURSE_LOOT_SPEC,
    LOOT_CATALOG,
    STANDARD_LOOT_CATALOG,
    LootRarity,
    select_standard_loot,
    standard_loot_threshold,
)
from pyduckhunt.game.model import (
    FlightKind,
    GameState,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)


SHOT = Command(CommandKind.SHOT, "bang")


class LootTests(unittest.TestCase):
    def test_every_loot_award_has_the_observed_rarity_tier(self) -> None:
        expected = {
            LootRarity.ORDINARY: {
                "curse_scroll",
                "duck_detector",
                "explosive_ammunition",
                "infrared_lock",
                "junk_item",
                "junk_letter_q",
                "lucky_charm",
                "penetrating_ammunition",
                "reserve_magazine",
                "single_round",
                "sunglasses",
                "suppressor",
                "targeting_scope",
                "weapon_grease",
            },
            LootRarity.UNUSUAL: {
                "blessing_amulet",
                "endurance_amulet",
                "letter_c",
                "letter_d",
                "letter_h",
                "letter_k",
                "letter_n",
                "letter_t",
                "letter_u",
                "promotion_10_24h",
                "promotion_10_48h",
                "promotion_10_7d",
                "promotion_25_24h",
                "tardis_bag",
                "voucher_10",
                "voucher_20",
                "xp_10",
                "xp_20",
            },
            LootRarity.RARE: {
                "abundance_amulet",
                "ammo_recycler",
                "baker_amulet",
                "promotion_25_48h",
                "promotion_50_24h",
                "voucher_50",
                "xp_30",
                "xp_40",
            },
            LootRarity.VERY_RARE: {
                "premium_ammo_recycler",
                "prankster_amulet",
                "promotion_25_7d",
                "promotion_50_48h",
                "voucher_75",
                "warrior_amulet",
                "xp_100",
                "xp_50",
            },
            LootRarity.LEGENDARY: {
                "eternal_warrior_amulet",
                "extended_magazine",
                "indestructible_sunglasses",
                "large_ammo_bag",
                "military_ammo_recycler",
                "military_self_lubricating_system",
                "permanent_killing_license",
                "tearproof_raincoat",
            },
        }
        actual = {
            rarity: {spec.key for spec in LOOT_CATALOG if spec.rarity is rarity}
            for rarity in LootRarity
        }
        self.assertEqual(actual, expected)
        self.assertIs(CURSE_LOOT_SPEC.rarity, LootRarity.ORDINARY)

    def test_standard_catalog_order_and_thresholds_are_exact(self) -> None:
        self.assertEqual(
            tuple((spec.key, spec.threshold_per_thousand) for spec in STANDARD_LOOT_CATALOG),
            (
                ("junk_item", 20),
                ("single_round", 20),
                ("reserve_magazine", 15),
                ("penetrating_ammunition", 7),
                ("explosive_ammunition", 5),
                ("weapon_grease", 7),
                ("targeting_scope", 12),
                ("infrared_lock", 7),
                ("suppressor", 12),
                ("sunglasses", 12),
                ("duck_detector", 12),
                ("lucky_charm", 7),
                ("xp_10", 3),
                ("xp_20", 2),
                ("xp_30", 1),
                ("xp_40", 1),
                ("xp_50", 1),
                ("xp_100", 1),
            ),
        )

    def test_selection_uses_first_success_and_bounded_multiplier(self) -> None:
        rolls = (21, 20, *(1_000 for _ in range(16)))
        self.assertEqual(select_standard_loot(rolls), LootAward("single_round"))
        doubled = (40, *(1_000 for _ in range(17)))
        self.assertEqual(
            select_standard_loot(doubled, chance_multiplier=2),
            LootAward("junk_item"),
        )

    def test_positive_karma_replaces_junk_with_more_interesting_drops(self) -> None:
        by_key = {spec.key: spec for spec in STANDARD_LOOT_CATALOG}
        self.assertEqual(
            standard_loot_threshold(by_key["junk_item"], karma_basis_points=10_000),
            0,
        )
        self.assertEqual(
            standard_loot_threshold(
                by_key["penetrating_ammunition"], karma_basis_points=10_000
            ),
            14,
        )
        self.assertEqual(
            standard_loot_threshold(by_key["xp_10"], karma_basis_points=10_000),
            6,
        )
        rolls = (1, 1_000, 1_000, 14, *(1_000 for _ in range(14)))
        self.assertEqual(
            select_standard_loot(rolls, karma_basis_points=10_000),
            LootAward("penetrating_ammunition"),
        )

    def test_negative_karma_only_increases_the_junk_threshold(self) -> None:
        by_key = {spec.key: spec for spec in STANDARD_LOOT_CATALOG}
        self.assertEqual(
            standard_loot_threshold(by_key["junk_item"], karma_basis_points=-10_000),
            40,
        )
        self.assertEqual(
            standard_loot_threshold(
                by_key["penetrating_ammunition"], karma_basis_points=-10_000
            ),
            7,
        )

    def test_variable_effect_selection_requires_injected_magnitude(self) -> None:
        rolls = (*(1_000 for _ in range(6)), 12, *(1_000 for _ in range(11)))
        with self.assertRaises(ValueError):
            select_standard_loot(rolls)
        self.assertEqual(
            select_standard_loot(rolls, magnitude=9),
            LootAward("targeting_scope", magnitude=9),
        )

    def test_selection_rejects_truth_value_rolls(self) -> None:
        with self.assertRaises(ValueError):
            select_standard_loot((True, *(1_000 for _ in range(17))))

    def test_experience_loot_is_atomic_with_the_killing_shot(self) -> None:
        state = start_flight(GameState(), 0, lifetime_ns=100).state
        killed = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(loot=LootAward("xp_20")),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in killed.outcomes),
            (OutcomeKind.HIT, OutcomeKind.LOOT_ACQUIRED),
        )
        self.assertEqual(killed.outcomes[0].experience_awarded, 10)
        self.assertEqual(killed.outcomes[1].experience_awarded, 20)

    def test_loot_rejects_non_kill_and_nonstandard_target(self) -> None:
        resistant = start_flight(GameState(), 0, lifetime_ns=100, health=2).state
        with self.assertRaises(ValueError):
            apply_command(
                resistant,
                "Hunter",
                SHOT,
                1,
                shot_attempt=ShotAttempt(loot=LootAward("single_round")),
            )
        golden = start_flight(
            GameState(),
            0,
            lifetime_ns=100,
            health=3,
            kind=FlightKind.GOLDEN,
        ).state
        with self.assertRaises(ValueError):
            apply_command(
                golden,
                "Hunter",
                SHOT,
                1,
                shot_attempt=ShotAttempt(loot=LootAward("xp_10")),
            )

    def test_curse_scroll_requires_level_five_and_creates_bounded_curse(self) -> None:
        novice = GameState(players=(PlayerState("hunter", "Hunter"),))
        novice = start_flight(novice, 0, lifetime_ns=100).state
        with self.assertRaises(ValueError):
            apply_command(
                novice,
                "Hunter",
                SHOT,
                1,
                shot_attempt=ShotAttempt(
                    loot=LootAward("curse_scroll", curse_key="tremor")
                ),
            )
        veteran = GameState(players=(PlayerState("hunter", "Hunter", level=5),))
        veteran = start_flight(veteran, 0, lifetime_ns=100).state
        cursed = apply_command(
            veteran,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(
                loot=LootAward("curse_scroll", curse_key="tremor")
            ),
        )
        self.assertEqual(cursed.state.curses[0].key, "tremor")
        self.assertEqual(cursed.state.curses[0].owner_key, "hunter")


if __name__ == "__main__":
    unittest.main()
