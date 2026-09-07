from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import FlightKind, GameState, LootAward, ShotAttempt
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


SHOT = Command(CommandKind.SHOT, "bang")


class RareReplayTests(unittest.TestCase):
    def test_golden_start_payload_preserves_target_settlement(self) -> None:
        event = ReplayEvent.start_flight(
            100,
            10_000,
            health=4,
            kind=FlightKind.GOLDEN,
        )
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        flight = apply_replay_event(GameState(), event).state.flight
        self.assertEqual(flight.kind, FlightKind.GOLDEN)
        self.assertEqual(flight.max_health, 4)
        self.assertEqual(flight.reward_experience, 48)

    def test_decoder_rejects_mismatched_golden_reward(self) -> None:
        payload = ReplayEvent.start_flight(
            100,
            10_000,
            health=4,
            kind=FlightKind.GOLDEN,
        ).to_payload()
        payload["reward_experience"] = 47
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_nested_loot_payload_round_trip(self) -> None:
        attempt = ShotAttempt(
            loot=LootAward("curse_scroll", curse_key="confusion")
        )
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_decoder_rejects_extra_loot_field(self) -> None:
        payload = ReplayEvent.command(
            200,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(loot=LootAward("xp_10")),
        ).to_payload()
        payload["shot_attempt"]["loot"]["unexpected"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_replay_matches_direct_loot_acquisition(self) -> None:
        state = start_flight(GameState(), 100, lifetime_ns=10_000).state
        attempt = ShotAttempt(loot=LootAward("targeting_scope", magnitude=8))
        event = ReplayEvent.command(200, "Hunter", SHOT, shot_attempt=attempt)
        self.assertEqual(
            apply_replay_event(state, event),
            apply_command(state, "Hunter", SHOT, 200, shot_attempt=attempt),
        )


if __name__ == "__main__":
    unittest.main()
