from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    GameState,
    LootAward,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.rewards import DAY_NS
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import CodecError, decode_game_state, encode_game_state
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


SHOT = Command(CommandKind.SHOT, "bang")


class UnusualReplayTests(unittest.TestCase):
    def test_shop_credit_and_reward_effect_round_trip(self) -> None:
        player = PlayerState("hunter", "Hunter", shop_credit=75)
        coupon = ActiveEffect(
            1,
            109,
            "promotion_25_7d",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=7 * DAY_NS,
            magnitude=25,
        )
        state = GameState(players=(player,), next_effect_id=2, effects=(coupon,))
        self.assertEqual(decode_game_state(encode_game_state(state)), state)

    def test_decoder_rejects_truth_value_shop_credit(self) -> None:
        payload = encode_game_state(
            GameState(players=(PlayerState("hunter", "Hunter"),))
        )
        payload["players"][0]["shop_credit"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_replay_matches_direct_voucher_acquisition(self) -> None:
        state = start_flight(GameState(), 100, lifetime_ns=10_000).state
        attempt = ShotAttempt(loot=LootAward("voucher_20"))
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        self.assertEqual(
            apply_replay_event(state, event),
            apply_command(state, "Hunter", SHOT, 200, shot_attempt=attempt),
        )

    def test_replay_matches_purchase_paid_from_credit(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            level=2,
            experience=5,
            shop_credit=10,
            ammo=0,
        )
        state = GameState(players=(player,))
        event = ReplayEvent.purchase(100, "Hunter", 1, 7)
        self.assertEqual(
            apply_replay_event(state, event),
            purchase(state, "Hunter", 1, 100, charged_cost=7),
        )


if __name__ == "__main__":
    unittest.main()
