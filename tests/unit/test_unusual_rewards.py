from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.loot import acquire_loot
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    GameState,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.rewards import (
    DAY_NS,
    REWARD_EFFECT_CATALOG,
    milestone_credit,
    settled_shop_cost,
)
from pyduckhunt.game.shop import purchase


SHOT = Command(CommandKind.SHOT, "bang")


class UnusualRewardTests(unittest.TestCase):
    def test_observed_reward_effect_catalog_is_exact_and_bounded(self) -> None:
        self.assertEqual(
            tuple(spec.item_id for spec in REWARD_EFFECT_CATALOG),
            tuple(range(101, 119)),
        )
        self.assertEqual(REWARD_EFFECT_CATALOG[0].duration_ns, DAY_NS)
        self.assertEqual(REWARD_EFFECT_CATALOG[2].uses, 1)
        self.assertEqual(
            tuple(
                spec.magnitude
                for spec in REWARD_EFFECT_CATALOG
                if spec.exclusive_group == "promotion_coupon"
            ),
            (10, 10, 10, 25, 25, 25, 50, 50),
        )

    def test_voucher_loot_credits_the_killing_player_atomically(self) -> None:
        state = start_flight(GameState(), 0, lifetime_ns=100).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(loot=LootAward("voucher_50")),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.HIT, OutcomeKind.LOOT_ACQUIRED),
        )
        self.assertEqual(result.state.players[0].shop_credit, 50)
        self.assertEqual(result.outcomes[-1].shop_credit_awarded, 50)

    def test_shop_credit_is_spent_before_durable_experience(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            level=2,
            experience=7,
            shop_credit=10,
            ammo=0,
        )
        result = purchase(GameState(players=(player,)), "Hunter", 1, 1)
        bought = result.outcomes[-1]
        self.assertEqual(bought.kind, OutcomeKind.SHOP_PURCHASED)
        self.assertEqual(bought.charged_experience, 7)
        self.assertEqual(bought.shop_credit_spent, 7)
        self.assertEqual(bought.experience_spent, 0)
        self.assertEqual(result.state.players[0].shop_credit, 3)
        self.assertEqual(result.state.players[0].experience, 7)
        self.assertEqual(result.state.players[0].experience_spent, 0)

    def test_failed_purchase_preserves_partial_shop_credit(self) -> None:
        player = PlayerState("hunter", "Hunter", shop_credit=5, ammo=0)
        result = purchase(GameState(players=(player,)), "Hunter", 1, 1)
        self.assertEqual(
            result.outcomes[-1].kind,
            OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
        )
        self.assertEqual(result.state.players[0].shop_credit, 5)
        self.assertEqual(result.state.players[0].ammo, 0)

    def test_promotion_rounding_matches_observed_half_up_prices(self) -> None:
        self.assertEqual(settled_shop_cost(15, 10), 14)
        self.assertEqual(settled_shop_cost(7, 25), 5)
        self.assertEqual(settled_shop_cost(7, 50), 4)
        self.assertEqual(settled_shop_cost(4, 25), 3)

    def test_default_purchase_applies_active_promotion(self) -> None:
        player = PlayerState("hunter", "Hunter", level=2, experience=7, ammo=0)
        coupon = ActiveEffect(
            1,
            107,
            "promotion_25_24h",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=DAY_NS,
            magnitude=25,
        )
        state = GameState(players=(player,), next_effect_id=2, effects=(coupon,))
        result = purchase(state, "Hunter", 1, 1)
        bought = result.outcomes[-1]
        self.assertEqual(bought.charged_experience, 5)
        self.assertEqual(bought.experience_spent, 5)
        self.assertEqual(bought.discount_percent, 25)
        self.assertEqual(result.state.players[0].experience, 2)
        self.assertEqual(result.state.players[0].experience_spent, 5)

    def test_promotion_expires_at_its_exact_deadline(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            level=2,
            experience=15,
            ammo=0,
            carried_day_start_ns=DAY_NS,
        )
        coupon = ActiveEffect(
            1,
            104,
            "promotion_10_24h",
            EffectScope.PLAYER,
            "hunter",
            None,
            1,
            expires_at_ns=DAY_NS + 1,
            magnitude=10,
        )
        state = GameState(
            now_ns=DAY_NS,
            players=(player,),
            next_effect_id=2,
            effects=(coupon,),
        )
        result = purchase(state, "Hunter", 1, DAY_NS + 1)
        bought = result.outcomes[-1]
        self.assertEqual(bought.charged_experience, 7)
        self.assertEqual(bought.discount_percent, 0)
        self.assertEqual(result.state.effects, ())

    def test_new_promotion_replaces_the_existing_coupon_group(self) -> None:
        player = PlayerState("hunter", "Hunter")
        state = acquire_loot(
            GameState(players=(player,)),
            "Hunter",
            LootAward("promotion_10_24h"),
            0,
        ).state
        result = acquire_loot(
            state,
            "Hunter",
            LootAward("promotion_50_48h"),
            0,
        )
        self.assertEqual(tuple(effect.item_id for effect in result.state.effects), (111,))
        self.assertEqual(result.outcomes[0].removed_item_ids, (104,))

    def test_endurance_prevents_shot_fatigue_for_its_full_window(self) -> None:
        player = PlayerState("hunter", "Hunter")
        endurance = ActiveEffect(
            1,
            102,
            "endurance_amulet",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=DAY_NS,
        )
        state = GameState(players=(player,), next_effect_id=2, effects=(endurance,))
        state = start_flight(state, 0, lifetime_ns=100).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(fatigue_gain_centi=900),
        )
        self.assertEqual(result.state.players[0].fatigue_centi, 0)
        self.assertEqual(result.outcomes[0].fatigue_changed_centi, 0)

    def test_blessing_consumes_itself_and_neutralizes_the_next_curse(self) -> None:
        player = PlayerState("hunter", "Hunter", level=5)
        state = acquire_loot(
            GameState(players=(player,)),
            "Hunter",
            LootAward("blessing_amulet"),
            0,
        ).state
        result = acquire_loot(
            state,
            "Hunter",
            LootAward("curse_scroll", curse_key="tremor"),
            0,
        )
        self.assertEqual(result.outcomes[0].kind, OutcomeKind.CURSE_NEUTRALIZED)
        self.assertEqual(result.state.effects, ())
        self.assertEqual(result.state.curses, ())

        second = acquire_loot(
            result.state,
            "Hunter",
            LootAward("curse_scroll", curse_key="tremor"),
            0,
        )
        self.assertEqual(second.outcomes[0].kind, OutcomeKind.LOOT_ACQUIRED)
        self.assertEqual(tuple(curse.key for curse in second.state.curses), ("tremor",))

    def test_baker_and_prankster_trigger_after_each_later_kill(self) -> None:
        player = PlayerState("hunter", "Hunter")
        state = GameState(players=(player,))
        for key in ("baker_amulet", "prankster_amulet"):
            state = acquire_loot(state, "Hunter", LootAward(key), 0).state
        state = start_flight(state, 1, lifetime_ns=100).state
        result = apply_command(state, "Hunter", SHOT, 2)
        triggered = tuple(
            outcome
            for outcome in result.outcomes
            if outcome.kind is OutcomeKind.REWARD_TRIGGERED
        )
        self.assertEqual(tuple(outcome.item_id for outcome in triggered), (112, 113))
        self.assertEqual(result.state.effects[-1].item_id, 21)
        self.assertEqual(result.state.effects[-1].expires_at_ns, 2 + 3_600_000_000_000)
        self.assertEqual(result.state.scheduled_actions[0].item_id, 23)
        self.assertEqual(
            result.state.scheduled_actions[0].due_at_ns,
            2 + 600_000_000_000,
        )

    def test_reward_acquired_on_a_kill_starts_with_the_next_kill(self) -> None:
        state = start_flight(GameState(), 0, lifetime_ns=100).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(loot=LootAward("baker_amulet")),
        )
        self.assertFalse(
            any(effect.item_id == 21 for effect in result.state.effects)
        )

    def test_hundred_hit_milestones_grant_observed_vouchers(self) -> None:
        self.assertEqual(
            tuple(milestone_credit(value) for value in (100, 200, 300, 400, 500)),
            (50, 75, 100, 125, 150),
        )
        player = PlayerState("hunter", "Hunter", hits=99)
        state = start_flight(GameState(players=(player,)), 0, lifetime_ns=100).state
        result = apply_command(state, "Hunter", SHOT, 1)
        self.assertEqual(result.state.players[0].shop_credit, 50)
        self.assertEqual(result.outcomes[1].kind, OutcomeKind.MILESTONE_CREDIT)


if __name__ == "__main__":
    unittest.main()
