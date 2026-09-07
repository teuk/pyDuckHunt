from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import (
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


SHOT = Command(CommandKind.SHOT, "bang")


def replay_attempt() -> ShotAttempt:
    return ShotAttempt(
        base_accuracy_bps=0,
        accuracy_roll=9_999,
        miss_penalty=2,
        wild_penalty=4,
        incident=IncidentAttempt(
            (
                IncidentTargetAttempt(
                    "First",
                    deflection_bps=7_500,
                    armor_bps=2_000,
                    deflection_roll=5_000,
                    armor_roll=9_000,
                ),
                IncidentTargetAttempt(
                    "Second",
                    armor_bps=8_000,
                    armor_roll=1_000,
                ),
            ),
            incident_penalty=6,
        ),
    )


class IncidentReplayTests(unittest.TestCase):
    def test_nested_incident_payload_round_trip(self) -> None:
        event = ReplayEvent.command(100, "Hunter", SHOT, shot_attempt=replay_attempt())
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_decoder_rejects_extra_incident_target_field(self) -> None:
        payload = ReplayEvent.command(
            100,
            "Hunter",
            SHOT,
            shot_attempt=replay_attempt(),
        ).to_payload()
        payload["shot_attempt"]["incident"]["targets"][0]["extra"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_decoder_rejects_truth_value_incident_roll(self) -> None:
        payload = ReplayEvent.command(
            100,
            "Hunter",
            SHOT,
            shot_attempt=replay_attempt(),
        ).to_payload()
        payload["shot_attempt"]["incident"]["targets"][0]["armor_roll"] = True
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_replay_matches_direct_incident_chain(self) -> None:
        state = GameState(
            players=(
                PlayerState("first", "First"),
                PlayerState("hunter", "Hunter", ammo=3, capacity=3, level=5, experience=40),
                PlayerState("second", "Second"),
            )
        )
        event = ReplayEvent.command(100, "Hunter", SHOT, shot_attempt=replay_attempt())
        direct = apply_replay_event(state, event)
        decoded = ReplayEvent.from_payload(event.to_payload())
        replayed = apply_replay_event(state, decoded)
        self.assertEqual(replayed, direct)


if __name__ == "__main__":
    unittest.main()
