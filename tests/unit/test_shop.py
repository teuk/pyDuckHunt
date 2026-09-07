from __future__ import annotations

import unittest

from pyduckhunt.game.catalog import HOUR_NS
from pyduckhunt.game.engine import advance_time
from pyduckhunt.game.model import GameState, OutcomeKind, PlayerState
from pyduckhunt.game.shop import consume_effect_use, purchase


def funded_player(**changes: object) -> PlayerState:
    values: dict[str, object] = {
        "key": "hunter",
        "nickname": "Hunter",
        "level": 30,
        "experience": 300,
        "ammo": 1,
        "capacity": 1,
        "magazines": 6,
        "magazine_capacity": 6,
    }
    values.update(changes)
    return PlayerState(**values)


class ShopTests(unittest.TestCase):
    def test_ammunition_purchase_is_atomic(self) -> None:
        state = GameState(players=(funded_player(ammo=0),))
        result = purchase(state, "Hunter", 1, 100)
        player = result.outcomes[-1].player
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_PURCHASED)
        self.assertEqual((player.ammo, player.experience), (1, 293))
        self.assertEqual(result.outcomes[-1].charged_experience, 7)
        self.assertEqual(player.experience_spent, 7)

    def test_magazine_purchase_is_atomic(self) -> None:
        state = GameState(players=(funded_player(magazines=4),))
        result = purchase(state, "Hunter", 2, 100)
        player = result.outcomes[-1].player
        self.assertEqual((player.magazines, player.experience), (5, 284))

    def test_full_direct_grant_does_not_charge(self) -> None:
        state = GameState(players=(funded_player(),))
        result = purchase(state, "Hunter", 1, 100)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        self.assertEqual(result.outcomes[-1].player.experience, 300)
        self.assertEqual(result.outcomes[-1].player.experience_spent, 0)

    def test_unknown_item_does_not_create_or_charge_profile(self) -> None:
        result = purchase(GameState(), "Hunter", 999, 100)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_UNKNOWN_ITEM)
        self.assertEqual(result.state.players, ())

    def test_insufficient_experience_does_not_create_effect(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", experience=4),))
        result = purchase(state, "Hunter", 3, 100)
        self.assertEqual(
            result.outcomes[-1].kind,
            OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
        )
        self.assertEqual(result.state.effects, ())
        self.assertEqual(result.state.player("hunter").experience_spent, 0)

    def test_settled_discount_is_recorded_exactly(self) -> None:
        state = GameState(players=(funded_player(),))
        result = purchase(state, "Hunter", 3, 100, charged_cost=11)
        self.assertEqual(result.outcomes[-1].charged_experience, 11)
        self.assertEqual(result.outcomes[-1].player.experience, 289)
        self.assertEqual(result.outcomes[-1].player.experience_spent, 11)

    def test_timed_effect_expires_at_exact_deadline(self) -> None:
        state = GameState(players=(funded_player(),))
        bought = purchase(state, "Hunter", 3, 100)
        deadline = 100 + 24 * HOUR_NS
        before = advance_time(bought.state, deadline - 1)
        self.assertEqual(len(before.state.effects), 1)
        expired = advance_time(before.state, deadline)
        self.assertEqual(expired.state.effects, ())
        self.assertEqual(expired.outcomes[-1].kind, OutcomeKind.EFFECT_EXPIRED)

    def test_duplicate_effect_is_rejected_without_charge(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 6, 100)
        second = purchase(first.state, "Hunter", 6, 101)
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.SHOP_EFFECT_ACTIVE)
        self.assertEqual(second.outcomes[-1].player.experience, 295)
        self.assertEqual(len(second.state.effects), 1)

    def test_ammunition_type_replaces_its_exclusive_group(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 3, 100)
        second = purchase(first.state, "Hunter", 4, 101)
        self.assertEqual(tuple(effect.item_id for effect in second.state.effects), (4,))
        self.assertEqual(second.state.next_effect_id, 3)

    def test_channel_effect_stacks_with_independent_deadlines(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 21, 100)
        second = purchase(first.state, "Hunter", 21, 200)
        self.assertEqual(len(second.state.effects), 2)
        self.assertTrue(all(effect.owner_key is None for effect in second.state.effects))
        self.assertNotEqual(
            second.state.effects[0].expires_at_ns,
            second.state.effects[1].expires_at_ns,
        )
        player = second.state.player("hunter")
        self.assertEqual(player.karma_modifier_basis_points, 400)
        self.assertEqual(second.outcomes[-1].channel_effect_count, 2)
        decayed = advance_time(second.state, 100 + 2 * HOUR_NS)
        self.assertEqual(
            decayed.state.player("hunter").karma_modifier_basis_points,
            388,
        )

    def test_failed_altruistic_purchase_does_not_change_karma(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter"),))
        result = purchase(state, "Hunter", 21, 100)
        self.assertEqual(
            result.outcomes[-1].kind,
            OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
        )
        self.assertEqual(result.state.player("hunter").karma_modifier_basis_points, 0)

    def test_variable_effect_requires_injected_magnitude(self) -> None:
        state = GameState(players=(funded_player(),))
        with self.assertRaises(ValueError):
            purchase(state, "Hunter", 10, 100)
        with self.assertRaises(ValueError):
            purchase(state, "Hunter", 10, 100, magnitude=11)
        result = purchase(state, "Hunter", 10, 100, magnitude=7)
        self.assertEqual(result.state.effects[0].magnitude, 7)

    def test_use_bounded_effect_is_decremented_then_removed(self) -> None:
        state = GameState(players=(funded_player(),))
        bought = purchase(state, "Hunter", 7, 100, magnitude=12)
        self.assertEqual(bought.outcomes[-1].effect_magnitude, 12)
        effect_id = bought.state.effects[0].effect_id
        current = consume_effect_use(bought.state, effect_id, 101)
        self.assertEqual(current.state.effects[0].remaining_uses, 5)
        for now_ns in range(102, 107):
            current = consume_effect_use(current.state, effect_id, now_ns)
        self.assertEqual(current.state.effects, ())
        self.assertEqual(current.outcomes[-1].kind, OutcomeKind.EFFECT_CONSUMED)

    def test_purchase_outcome_preserves_lucky_charm_magnitude(self) -> None:
        result = purchase(
            GameState(players=(funded_player(),)),
            "Hunter",
            10,
            100,
            magnitude=2,
        )
        self.assertEqual(result.outcomes[-1].effect_magnitude, 2)
        self.assertEqual(result.state.effects[0].magnitude, 2)

    def test_lucky_charm_reroll_replaces_value_deadline_and_charges_again(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 10, 100, magnitude=2)
        second = purchase(
            first.state,
            "Hunter",
            10,
            200,
            magnitude=9,
            replace_active_effect=True,
        )
        player = second.state.player("hunter")
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.SHOP_PURCHASED)
        self.assertEqual(second.outcomes[-1].effect_magnitude, 9)
        self.assertEqual(player.experience, 274)
        self.assertEqual(len(second.state.effects), 1)
        self.assertEqual(second.state.effects[0].effect_id, 2)
        self.assertEqual(second.state.effects[0].magnitude, 9)
        self.assertEqual(
            second.state.effects[0].expires_at_ns,
            200 + 24 * HOUR_NS,
        )

        underfunded = purchase(
            first.state.with_player(
                funded_player(level=1, experience=0),
            ),
            "Hunter",
            10,
            200,
            magnitude=10,
            replace_active_effect=True,
        )
        self.assertEqual(
            underfunded.outcomes[-1].kind,
            OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
        )
        self.assertEqual(underfunded.state.effects, first.state.effects)

    def test_lucky_charm_reroll_requires_the_replayed_decision(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 10, 100, magnitude=2)
        legacy_repeat = purchase(first.state, "Hunter", 10, 200, magnitude=9)
        self.assertEqual(
            legacy_repeat.outcomes[-1].kind,
            OutcomeKind.SHOP_EFFECT_ACTIVE,
        )
        self.assertEqual(
            legacy_repeat.state.player("hunter"),
            first.state.player("hunter"),
        )
        self.assertEqual(legacy_repeat.state.effects, first.state.effects)

        with self.assertRaises(ValueError):
            purchase(
                first.state,
                "Hunter",
                9,
                200,
                replace_active_effect=True,
            )

    def test_purchase_at_expiration_reaps_then_recreates_effect(self) -> None:
        state = GameState(players=(funded_player(),))
        first = purchase(state, "Hunter", 9, 100)
        deadline = 100 + 24 * HOUR_NS
        second = purchase(first.state, "Hunter", 9, deadline)
        self.assertEqual(
            tuple(outcome.kind for outcome in second.outcomes),
            (OutcomeKind.EFFECT_EXPIRED, OutcomeKind.SHOP_PURCHASED),
        )
        self.assertEqual(second.state.effects[0].effect_id, 2)

    def test_purchase_can_cross_a_level_boundary(self) -> None:
        state = GameState(
            players=(funded_player(level=3, experience=2, ammo=0),)
        )
        result = purchase(state, "Hunter", 1, 100)
        player = result.state.player("hunter")
        self.assertEqual((player.level, player.experience), (2, 25))
        self.assertEqual(result.outcomes[-1].levels_lost, 1)


if __name__ == "__main__":
    unittest.main()
