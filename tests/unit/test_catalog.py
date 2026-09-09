from __future__ import annotations

import unittest

from pyduckhunt.game.catalog import (
    HOUR_NS,
    MINUTE_NS,
    SHOP_CATALOG,
    DuplicatePolicy,
    GrantKind,
    ShopItem,
    shop_item,
)
from pyduckhunt.game.model import EffectScope


class CatalogTests(unittest.TestCase):
    def test_supported_identifiers_are_sorted_and_exact(self) -> None:
        self.assertEqual(
            tuple(item.item_id for item in SHOP_CATALOG),
            tuple(range(1, 32)),
        )

    def test_nominal_costs_match_the_calibrated_slice(self) -> None:
        self.assertEqual(
            {item.item_id: item.base_cost for item in SHOP_CATALOG},
            {
                1: 7,
                2: 16,
                3: 15,
                4: 25,
                5: 40,
                6: 5,
                7: 5,
                8: 15,
                9: 5,
                10: 13,
                11: 5,
                12: 9,
                13: 6,
                14: 5,
                15: 7,
                16: 10,
                17: 14,
                18: 8,
                19: 5,
                20: 8,
                21: 4,
                22: 4,
                23: 20,
                24: 5,
                25: 10,
                26: 15,
                27: 10,
                28: 9,
                29: 15,
                30: 20,
                31: 30,
            },
        )

    def test_timed_and_limited_effect_boundaries(self) -> None:
        self.assertEqual(shop_item(3).duration_ns, 24 * HOUR_NS)
        self.assertEqual(shop_item(7).uses, 6)
        self.assertEqual(
            (shop_item(7).magnitude_min, shop_item(7).magnitude_max),
            (0, 15),
        )
        self.assertEqual(
            (shop_item(10).magnitude_min, shop_item(10).magnitude_max),
            (1, 10),
        )
        self.assertEqual(shop_item(18).duration_ns, 7 * 24 * HOUR_NS)
        self.assertEqual(shop_item(18).uses, 1)
        self.assertEqual(shop_item(19).duration_ns, 2 * 24 * HOUR_NS)
        self.assertEqual(shop_item(21).duration_ns, HOUR_NS)
        self.assertEqual(shop_item(29).duration_ns, 24 * HOUR_NS)
        self.assertEqual(shop_item(30).duration_ns, 24 * HOUR_NS)

    def test_channel_actions_have_exact_windows(self) -> None:
        self.assertEqual(shop_item(20).grant_kind, GrantKind.CHANNEL_ACTION)
        self.assertEqual(
            (shop_item(20).schedule_min_ns, shop_item(20).schedule_max_ns),
            (1, 10 * MINUTE_NS),
        )
        self.assertEqual(
            (shop_item(23).schedule_min_ns, shop_item(23).schedule_max_ns),
            (10 * MINUTE_NS, 10 * MINUTE_NS),
        )
        self.assertEqual(shop_item(20).scope, EffectScope.CHANNEL)

    def test_fatigue_and_purification_grants_are_explicit(self) -> None:
        self.assertEqual(shop_item(24).fatigue_relief_max, 5)
        self.assertEqual(shop_item(25).fatigue_relief_max, 10)
        self.assertEqual(shop_item(27).fatigue_relief_max, 100)
        self.assertEqual(shop_item(31).grant_kind, GrantKind.PURIFICATION)

    def test_targeted_nuisance_policies_are_explicit(self) -> None:
        self.assertEqual(shop_item(12).grant_kind, GrantKind.REMEDY)
        self.assertEqual(shop_item(13).removes_item_ids, (15, 17))
        self.assertEqual(shop_item(14).counter_item_id, 11)
        self.assertTrue(shop_item(14).target_presence_required)
        self.assertEqual(shop_item(15).counter_item_id, 6)
        self.assertTrue(shop_item(15).consume_counter)
        self.assertEqual(shop_item(16).duration_ns, HOUR_NS)
        self.assertEqual(shop_item(16).counter_item_id, 26)
        self.assertTrue(shop_item(17).target_weapon_required)

    def test_channel_item_is_the_only_stackable_effect(self) -> None:
        stackable = tuple(
            item.item_id
            for item in SHOP_CATALOG
            if item.duplicate_policy is DuplicatePolicy.STACK
        )
        self.assertEqual(stackable, (21,))
        self.assertEqual(shop_item(21).scope, EffectScope.CHANNEL)

    def test_direct_grant_rejects_effect_metadata(self) -> None:
        with self.assertRaises(ValueError):
            ShopItem(
                99,
                "bad_round",
                1,
                GrantKind.AMMUNITION,
                duration_ns=HOUR_NS,
            )


if __name__ == "__main__":
    unittest.main()
