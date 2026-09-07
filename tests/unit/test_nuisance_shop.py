from __future__ import annotations

import unittest

from pyduckhunt.game.model import GameState, OutcomeKind, PlayerState
from pyduckhunt.game.shop import purchase


def funded_state(*, target_confiscated: bool = False) -> GameState:
    return GameState(
        players=(
            PlayerState("actor", "Actor", level=30, experience=300),
            PlayerState(
                "target",
                "Target",
                level=30,
                experience=300,
                confiscated=target_confiscated,
            ),
        )
    )


def immune_state(level: int) -> GameState:
    return GameState(
        players=(
            PlayerState("actor", "Actor", level=30, experience=300),
            PlayerState("target", "Target", level=level),
        )
    )


def targeted(state: GameState, item_id: int, now_ns: int, *, present: bool = True):
    return purchase(
        state,
        "Actor",
        item_id,
        now_ns,
        target_nickname="Target",
        target_present=present,
    )


class NuisanceShopTests(unittest.TestCase):
    def test_target_identity_is_required_and_must_be_known(self) -> None:
        missing = purchase(funded_state(), "Actor", 14, 100)
        self.assertEqual(missing.outcomes[-1].kind, OutcomeKind.SHOP_TARGET_REQUIRED)
        unknown = purchase(
            funded_state(),
            "Actor",
            14,
            100,
            target_nickname="Unknown",
            target_present=True,
        )
        self.assertEqual(unknown.outcomes[-1].kind, OutcomeKind.SHOP_TARGET_UNKNOWN)
        self.assertEqual(unknown.state.player("actor").experience, 300)

    def test_presence_bound_nuisances_reject_an_absent_target(self) -> None:
        for item_id in (14, 16):
            with self.subTest(item_id=item_id):
                result = targeted(funded_state(), item_id, 100, present=False)
                self.assertEqual(
                    result.outcomes[-1].kind,
                    OutcomeKind.SHOP_TARGET_ABSENT,
                )
                self.assertEqual(result.state.effects, ())

    def test_weapon_nuisances_allow_an_absent_but_armed_target(self) -> None:
        for item_id in (15, 17):
            with self.subTest(item_id=item_id):
                result = targeted(funded_state(), item_id, 100, present=False)
                self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_PURCHASED)
                self.assertEqual(result.state.effects[0].owner_key, "target")
                self.assertEqual(result.state.effects[0].source_key, "actor")

    def test_weapon_nuisance_rejects_a_confiscated_target(self) -> None:
        result = targeted(funded_state(target_confiscated=True), 17, 100)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_TARGET_UNARMED)
        self.assertEqual(result.state.player("actor").experience, 300)

    def test_bow_and_crossbow_reject_sand_and_sabotage_without_charge(self) -> None:
        for level in (40, 60):
            for item_id in (15, 17):
                with self.subTest(level=level, item_id=item_id):
                    result = targeted(
                        immune_state(level),
                        item_id,
                        100,
                        present=False,
                    )
                    self.assertEqual(
                        result.outcomes[-1].kind,
                        OutcomeKind.SHOP_TARGET_IMMUNE,
                    )
                    self.assertEqual(result.state.player("actor").experience, 300)
                    self.assertEqual(result.state.effects, ())

    def test_sunglasses_block_glare_without_being_consumed(self) -> None:
        protected = purchase(funded_state(), "Target", 11, 100)
        result = targeted(protected.state, 14, 200)
        outcome = result.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.SHOP_PURCHASED)
        self.assertTrue(outcome.effect_blocked)
        self.assertEqual(outcome.counter_item_id, 11)
        self.assertEqual(result.state.player("actor").experience, 295)
        self.assertEqual(tuple(effect.item_id for effect in result.state.effects), (11,))

    def test_grease_blocks_sand_and_is_consumed(self) -> None:
        protected = purchase(funded_state(), "Target", 6, 100)
        result = targeted(protected.state, 15, 200, present=False)
        outcome = result.outcomes[-1]
        self.assertTrue(outcome.effect_blocked)
        self.assertEqual(outcome.counter_item_id, 6)
        self.assertEqual(outcome.removed_item_ids, (6,))
        self.assertEqual(result.state.effects, ())
        self.assertEqual(result.state.player("actor").experience, 293)

    def test_raincoat_blocks_water_without_being_consumed(self) -> None:
        protected = purchase(funded_state(), "Target", 26, 100)
        result = targeted(protected.state, 16, 200)
        self.assertTrue(result.outcomes[-1].effect_blocked)
        self.assertEqual(result.outcomes[-1].counter_item_id, 26)
        self.assertEqual(tuple(effect.item_id for effect in result.state.effects), (26,))

    def test_duplicate_target_effect_is_rejected_without_charge(self) -> None:
        first = targeted(funded_state(), 17, 100)
        second = targeted(first.state, 17, 200)
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.SHOP_EFFECT_ACTIVE)
        self.assertEqual(second.state.player("actor").experience, 286)
        self.assertEqual(len(second.state.effects), 1)

    def test_bore_brush_removes_sand_and_sabotage_together(self) -> None:
        sanded = targeted(funded_state(), 15, 100, present=False)
        sabotaged = targeted(sanded.state, 17, 200, present=False)
        cleaned = purchase(sabotaged.state, "Target", 13, 300)
        self.assertEqual(cleaned.outcomes[-1].removed_item_ids, (15, 17))
        self.assertEqual(cleaned.state.effects, ())

    def test_dry_clothes_only_charge_when_soaked(self) -> None:
        dry = purchase(funded_state(), "Target", 12, 100)
        self.assertEqual(dry.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        wet = targeted(funded_state(), 16, 100)
        changed = purchase(wet.state, "Target", 12, 200)
        self.assertEqual(changed.outcomes[-1].removed_item_ids, (16,))
        self.assertEqual(changed.state.player("target").experience, 291)

    def test_raincoat_purchase_drains_an_existing_soaked_effect(self) -> None:
        wet = targeted(funded_state(), 16, 100)
        protected = purchase(wet.state, "Target", 26, 200)
        self.assertEqual(protected.outcomes[-1].removed_item_ids, (16,))
        self.assertEqual(tuple(effect.item_id for effect in protected.state.effects), (26,))

    def test_glare_can_target_the_buyer(self) -> None:
        result = purchase(
            funded_state(),
            "Actor",
            14,
            100,
            target_nickname="Actor",
            target_present=True,
        )
        self.assertEqual(result.state.effects[0].owner_key, "actor")
        self.assertEqual(result.state.effects[0].source_key, "actor")
        self.assertEqual(
            result.state.player("actor").karma_modifier_basis_points,
            -200,
        )

    def test_successful_nuisance_lowers_only_the_buyers_temporary_karma(self) -> None:
        result = targeted(funded_state(), 17, 100, present=False)
        self.assertEqual(
            result.state.player("actor").karma_modifier_basis_points,
            -200,
        )
        self.assertEqual(
            result.state.player("target").karma_modifier_basis_points,
            0,
        )


if __name__ == "__main__":
    unittest.main()
