from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.model import FlightKind, GameState
from pyduckhunt.game.model import ActiveCurse, PlayerState, ScheduledAction
from pyduckhunt.persistence.codec import CodecError, decode_game_state, encode_game_state


class StateCodecTests(unittest.TestCase):
    def test_round_trip_preserves_active_flight_and_player(self) -> None:
        started = start_flight(GameState(), 1_000, lifetime_ns=10_000)
        missed = apply_command(
            GameState(),
            "H[unter",
            Command(CommandKind.SHOT, "bang"),
            500,
        )
        combined = started.state.with_player(missed.state.players[0])
        self.assertEqual(decode_game_state(encode_game_state(combined)), combined)

    def test_round_trip_preserves_last_flight(self) -> None:
        started = start_flight(GameState(), 1_000, lifetime_ns=10_000)
        expired = advance_time(started.state, 11_000).state
        self.assertEqual(decode_game_state(encode_game_state(expired)), expired)
        self.assertIsNotNone(encode_game_state(expired)["last_flight"])

    def test_encoded_player_order_is_stable(self) -> None:
        first = apply_command(
            GameState(), "Zulu", Command(CommandKind.STATS, "duckstats"), 1
        )
        second = apply_command(
            first.state, "Alpha", Command(CommandKind.STATS, "duckstats"), 2
        )
        payload = encode_game_state(second.state)
        self.assertEqual([player["key"] for player in payload["players"]], ["alpha", "zulu"])

    def test_flight_health_is_explicit_in_canonical_payload(self) -> None:
        state = start_flight(GameState(), 1, lifetime_ns=10, health=7).state
        payload = encode_game_state(state)
        self.assertEqual(payload["flight"]["health"], 7)
        self.assertEqual(payload["flight"]["max_health"], 7)
        self.assertEqual(payload["flight"]["kind"], "standard")
        self.assertEqual(payload["flight"]["reward_experience"], 10)

    def test_decoder_rejects_mismatched_golden_reward(self) -> None:
        state = start_flight(
            GameState(),
            1,
            lifetime_ns=10,
            health=4,
            kind=FlightKind.GOLDEN,
        ).state
        payload = encode_game_state(state)
        payload["flight"]["reward_experience"] = 47
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_round_trip_preserves_fatigue_action_and_curse(self) -> None:
        player = PlayerState("hunter", "Hunter", fatigue_centi=1_772)
        state = GameState(
            players=(player,),
            next_action_id=2,
            scheduled_actions=(
                ScheduledAction(1, 20, "duck_call", "hunter", 1, 2),
            ),
            next_curse_id=2,
            curses=(
                ActiveCurse(
                    1,
                    "confusion",
                    "hunter",
                    0,
                    86_400_000_000_000,
                    2,
                ),
            ),
        )
        self.assertEqual(decode_game_state(encode_game_state(state)), state)

    def test_decoder_rejects_action_outside_catalog_window(self) -> None:
        player = PlayerState("hunter", "Hunter")
        state = GameState(
            players=(player,),
            next_action_id=2,
            scheduled_actions=(
                ScheduledAction(1, 20, "duck_call", "hunter", 1, 2),
            ),
        )
        payload = encode_game_state(state)
        payload["scheduled_actions"][0]["due_at_ns"] = 700_000_000_002
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_unknown_curse(self) -> None:
        player = PlayerState("hunter", "Hunter")
        state = GameState(
            players=(player,),
            next_curse_id=2,
            curses=(
                ActiveCurse(
                    1,
                    "confusion",
                    "hunter",
                    0,
                    86_400_000_000_000,
                    2,
                ),
            ),
        )
        payload = encode_game_state(state)
        payload["curses"][0]["key"] = "unknown"
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_truth_value_as_integer(self) -> None:
        payload = encode_game_state(GameState())
        payload["now_ns"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_unknown_field(self) -> None:
        payload = encode_game_state(GameState())
        payload["unexpected"] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_unsorted_players(self) -> None:
        state = apply_command(
            apply_command(
                GameState(), "Alpha", Command(CommandKind.STATS, "duckstats"), 1
            ).state,
            "Zulu",
            Command(CommandKind.STATS, "duckstats"),
            2,
        ).state
        payload = encode_game_state(state)
        payload["players"] = list(reversed(payload["players"]))
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_mismatched_identity_key(self) -> None:
        state = apply_command(
            GameState(), "Hunter", Command(CommandKind.STATS, "duckstats"), 1
        ).state
        payload = encode_game_state(state)
        payload["players"][0]["key"] = "another"
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_expired_active_flight(self) -> None:
        state = start_flight(GameState(), 1, lifetime_ns=10).state
        payload = encode_game_state(state)
        payload["now_ns"] = 11
        with self.assertRaises(CodecError):
            decode_game_state(payload)


if __name__ == "__main__":
    unittest.main()
