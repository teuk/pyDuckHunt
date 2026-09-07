from __future__ import annotations

import unittest

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import CodecError, decode_game_state, encode_game_state


def effect_state() -> GameState:
    state = GameState(
        players=(
            PlayerState(
                "hunter",
                "Hunter",
                level=30,
                experience=300,
            ),
        ),
    )
    return purchase(state, "Hunter", 10, 100, magnitude=7).state


class EffectCodecTests(unittest.TestCase):
    def test_round_trip_preserves_active_effect(self) -> None:
        state = effect_state()
        self.assertEqual(decode_game_state(encode_game_state(state)), state)

    def test_effect_payload_is_explicit_and_canonical(self) -> None:
        payload = encode_game_state(effect_state())
        self.assertEqual(payload["next_effect_id"], 2)
        self.assertEqual(
            payload["effects"][0],
            {
                "activated_at_ns": 100,
                "effect_id": 1,
                "expires_at_ns": 86_400_000_000_100,
                "item_id": 10,
                "key": "lucky_charm",
                "magnitude": 7,
                "owner_key": "hunter",
                "remaining_uses": None,
                "scope": "player",
                "source_key": None,
            },
        )

    def test_target_effect_round_trip_preserves_source_identity(self) -> None:
        state = GameState(
            players=(
                PlayerState("actor", "Actor", level=30, experience=300),
                PlayerState("target", "Target"),
            )
        )
        bought = purchase(
            state,
            "Actor",
            14,
            100,
            target_nickname="Target",
            target_present=True,
        ).state
        payload = encode_game_state(bought)
        self.assertEqual(payload["effects"][0]["source_key"], "actor")
        self.assertEqual(decode_game_state(payload), bought)

    def test_decoder_rejects_target_effect_without_source(self) -> None:
        state = GameState(
            players=(
                PlayerState("actor", "Actor", level=30, experience=300),
                PlayerState("target", "Target"),
            )
        )
        payload = encode_game_state(
            purchase(
                state,
                "Actor",
                14,
                100,
                target_nickname="Target",
                target_present=True,
            ).state
        )
        payload["effects"][0]["source_key"] = None
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_unknown_effect_scope(self) -> None:
        payload = encode_game_state(effect_state())
        payload["effects"][0]["scope"] = "future_scope"
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_expired_effect(self) -> None:
        payload = encode_game_state(effect_state())
        payload["now_ns"] = payload["effects"][0]["expires_at_ns"]
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_nonadvancing_effect_sequence(self) -> None:
        payload = encode_game_state(effect_state())
        payload["next_effect_id"] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_magnitude_outside_catalog(self) -> None:
        payload = encode_game_state(effect_state())
        payload["effects"][0]["magnitude"] = 11
        with self.assertRaises(CodecError):
            decode_game_state(payload)


if __name__ == "__main__":
    unittest.main()
