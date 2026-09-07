from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.level_policy import level_policy
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
    ammunition_recycler_successes_per_thirty,
    has_unlimited_magazines,
)


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")


def player_at(level: int, *, ammo: int | None = None, magazines: int | None = None) -> PlayerState:
    policy = level_policy(level)
    return PlayerState(
        "hunter",
        "Hunter",
        level=level,
        ammo=policy.ammo_capacity if ammo is None else ammo,
        capacity=policy.ammo_capacity,
        magazines=policy.magazine_capacity if magazines is None else magazines,
        magazine_capacity=policy.magazine_capacity,
    )


class AmmunitionRewardTests(unittest.TestCase):
    def test_ammunition_reward_catalog_has_exact_observed_durations_and_odds(self) -> None:
        by_id = {spec.item_id: spec for spec in REWARD_EFFECT_CATALOG}
        self.assertEqual(tuple(by_id), tuple(range(101, 119)))
        self.assertEqual(
            (
                by_id[114].duration_ns,
                by_id[114].recycle_successes_per_thirty,
                by_id[115].duration_ns,
                by_id[115].recycle_successes_per_thirty,
            ),
            (DAY_NS, 10, 2 * DAY_NS, 15),
        )
        self.assertTrue(by_id[116].unlimited_magazines)
        self.assertTrue(by_id[117].unlimited_magazines)
        self.assertEqual((by_id[116].duration_ns, by_id[117].duration_ns), (DAY_NS, 2 * DAY_NS))

    def test_permanent_capacity_upgrades_are_level_gated_unique_and_durable(self) -> None:
        level_twenty = player_at(20)
        state = GameState(players=(level_twenty,))
        bagged = acquire_loot(state, "Hunter", LootAward("large_ammo_bag"), 0)
        player = bagged.state.player("hunter")
        assert player is not None
        self.assertEqual((player.magazines, player.magazine_capacity), (4, 5))
        self.assertEqual(tuple(stack.key for stack in player.inventory), ("large_ammo_bag",))
        duplicate = acquire_loot(
            bagged.state,
            "Hunter",
            LootAward("large_ammo_bag"),
            0,
        ).state.player("hunter")
        assert duplicate is not None
        self.assertEqual(duplicate.magazine_capacity, 5)
        self.assertEqual(duplicate.inventory[0].quantity, 1)

        level_ten = player_at(10)
        extended = acquire_loot(
            GameState(players=(level_ten,)),
            "Hunter",
            LootAward("extended_magazine"),
            0,
        ).state.player("hunter")
        assert extended is not None
        self.assertEqual((extended.ammo, extended.capacity), (4, 5))
        with self.assertRaises(ValueError):
            acquire_loot(
                GameState(players=(PlayerState("novice", "Novice"),)),
                "Novice",
                LootAward("extended_magazine"),
                0,
            )

    def test_three_recyclers_settle_exact_thirtieths_and_strongest_wins(self) -> None:
        ordinary = acquire_loot(
            GameState(players=(PlayerState("hunter", "Hunter"),)),
            "Hunter",
            LootAward("ammo_recycler"),
            0,
        ).state
        self.assertEqual(ammunition_recycler_successes_per_thirty(ordinary, "hunter"), 10)
        premium = acquire_loot(
            ordinary,
            "Hunter",
            LootAward("premium_ammo_recycler"),
            0,
        ).state
        self.assertEqual(ammunition_recycler_successes_per_thirty(premium, "hunter"), 15)
        self.assertEqual(tuple(effect.item_id for effect in premium.effects), (115,))

        veteran = player_at(20)
        military = acquire_loot(
            GameState(players=(veteran,)),
            "Hunter",
            LootAward("military_ammo_recycler"),
            0,
        ).state
        self.assertEqual(ammunition_recycler_successes_per_thirty(military, "hunter"), 3)
        combined = acquire_loot(
            military,
            "Hunter",
            LootAward("ammo_recycler"),
            0,
        ).state
        self.assertEqual(ammunition_recycler_successes_per_thirty(combined, "hunter"), 10)

    def test_recycled_shot_consumes_no_round_and_requires_replayed_roll(self) -> None:
        state = acquire_loot(
            GameState(players=(PlayerState("hunter", "Hunter"),)),
            "Hunter",
            LootAward("ammo_recycler"),
            0,
        ).state
        state = start_flight(state, 1, lifetime_ns=100).state
        recycled = apply_command(
            state,
            "Hunter",
            SHOT,
            2,
            shot_attempt=ShotAttempt(recycler_roll=10),
        )
        player = recycled.state.player("hunter")
        assert player is not None
        self.assertEqual(player.ammo, 6)
        self.assertTrue(recycled.outcomes[0].ammunition_recycled)
        self.assertEqual(recycled.outcomes[0].rounds_consumed, 0)

        state = start_flight(recycled.state, 3, lifetime_ns=100).state
        consumed = apply_command(
            state,
            "Hunter",
            SHOT,
            4,
            shot_attempt=ShotAttempt(recycler_roll=11),
        )
        player = consumed.state.player("hunter")
        assert player is not None
        self.assertEqual(player.ammo, 5)
        self.assertFalse(consumed.outcomes[0].ammunition_recycled)
        self.assertEqual(consumed.outcomes[0].rounds_consumed, 1)

        with self.assertRaises(ValueError):
            apply_command(
                start_flight(consumed.state, 5, lifetime_ns=100).state,
                "Hunter",
                SHOT,
                6,
                shot_attempt=ShotAttempt(),
            )
        with self.assertRaises(ValueError):
            apply_command(
                start_flight(GameState(), 0, lifetime_ns=100).state,
                "Hunter",
                SHOT,
                1,
                shot_attempt=ShotAttempt(recycler_roll=1),
            )

    def test_warrior_amulet_reloads_without_spending_a_reserve(self) -> None:
        state = acquire_loot(
            GameState(
                now_ns=1,
                players=(PlayerState("hunter", "Hunter", ammo=0, magazines=0),),
            ),
            "Hunter",
            LootAward("warrior_amulet"),
            1,
        ).state
        self.assertTrue(has_unlimited_magazines(state, "hunter"))
        loaded = apply_command(state, "Hunter", RELOAD, 2)
        player = loaded.state.player("hunter")
        assert player is not None
        self.assertEqual((player.ammo, player.magazines), (6, 0))
        self.assertEqual(loaded.outcomes[-1].kind, OutcomeKind.RELOADED)
        self.assertTrue(loaded.outcomes[-1].unlimited_magazines)

        expired = apply_command(
            GameState(
                now_ns=DAY_NS,
                players=(
                    PlayerState(
                        "hunter",
                        "Hunter",
                        ammo=0,
                        magazines=0,
                        carried_day_start_ns=DAY_NS,
                    ),
                ),
                next_effect_id=loaded.state.next_effect_id,
                effects=loaded.state.effects,
            ),
            "Hunter",
            RELOAD,
            DAY_NS + 1,
        )
        self.assertEqual(expired.outcomes[-1].kind, OutcomeKind.NO_RESERVE)

    def test_warrior_composes_with_automatic_reload_at_zero_reserve(self) -> None:
        player = PlayerState("hunter", "Hunter", ammo=1, magazines=0)
        automatic = ActiveEffect(
            1,
            30,
            "automatic_reloader",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=DAY_NS,
        )
        state = GameState(players=(player,), next_effect_id=2, effects=(automatic,))
        state = acquire_loot(state, "Hunter", LootAward("warrior_amulet"), 0).state
        state = start_flight(state, 1, lifetime_ns=100).state
        result = apply_command(state, "Hunter", SHOT, 2)
        player = result.state.player("hunter")
        assert player is not None
        self.assertEqual((player.ammo, player.magazines), (6, 0))
        self.assertTrue(result.outcomes[-1].automatic)
        self.assertTrue(result.outcomes[-1].unlimited_magazines)


if __name__ == "__main__":
    unittest.main()
