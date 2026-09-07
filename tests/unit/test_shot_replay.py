from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import GameState, PlayerState, ShotAttempt
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


SHOT = Command(CommandKind.SHOT, "bang")


class ShotReplayTests(unittest.TestCase):
    def test_shot_attempt_payload_round_trip(self) -> None:
        attempt = ShotAttempt(
            base_accuracy_bps=6_500,
            base_jam_bps=400,
            accuracy_roll=6_000,
            jam_roll=900,
            recycler_roll=17,
            frighten_on_miss=True,
        )
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_shot_attempt_decoder_rejects_truth_value_roll(self) -> None:
        payload = ReplayEvent.command(200, "Hunter", SHOT).to_payload()
        payload["shot_attempt"] = {
            "accuracy_roll": True,
            "base_accuracy_bps": 5_000,
            "base_jam_bps": 100,
            "fatigue_gain_centi": 100,
            "frighten_on_miss": False,
            "incident": None,
            "jam_roll": 1_000,
            "loot": None,
            "miss_penalty": 0,
            "wild_penalty": 0,
        }
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_legacy_shot_payload_defaults_the_recycler_roll_to_none(self) -> None:
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=ShotAttempt())
        payload = event.to_payload()
        del payload["shot_attempt"]["recycler_roll"]
        decoded = ReplayEvent.from_payload(payload)
        assert decoded.shot_attempt is not None
        self.assertIsNone(decoded.shot_attempt.recycler_roll)

    def test_recycler_roll_rejects_truth_values(self) -> None:
        payload = ReplayEvent.command(
            200,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(),
        ).to_payload()
        payload["shot_attempt"]["recycler_roll"] = True
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_start_flight_payload_preserves_health(self) -> None:
        event = ReplayEvent.start_flight(100, 10_000, health=7)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        self.assertEqual(apply_replay_event(GameState(), event).state.flight.health, 7)

    def test_replay_matches_direct_jam_decision(self) -> None:
        state = GameState(
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=2,
                    capacity=2,
                ),
            )
        )
        attempt = ShotAttempt(base_jam_bps=500, jam_roll=250)
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        direct = apply_command(state, "Hunter", SHOT, 200, shot_attempt=attempt)
        self.assertEqual(apply_replay_event(state, event), direct)

    def test_replay_matches_resistant_flight_damage(self) -> None:
        state = start_flight(GameState(), 100, lifetime_ns=10_000, health=4).state
        attempt = ShotAttempt(base_accuracy_bps=10_000, accuracy_roll=9_999)
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        replayed = apply_replay_event(state, event)
        direct = apply_command(state, "Hunter", SHOT, 200, shot_attempt=attempt)
        self.assertEqual(replayed, direct)
        self.assertEqual(replayed.state.flight.health, 3)


if __name__ == "__main__":
    unittest.main()
