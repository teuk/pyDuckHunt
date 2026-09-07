from __future__ import annotations

import unittest

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


STATE = GameState(
    players=(
        PlayerState("actor", "Actor", level=30, experience=300),
        PlayerState("target", "Target", level=30, experience=300),
    )
)


class NuisanceReplayTests(unittest.TestCase):
    def test_targeted_purchase_payload_round_trip(self) -> None:
        event = ReplayEvent.purchase(
            100,
            "Actor",
            14,
            5,
            target_nickname="Target",
            target_present=True,
        )
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_replay_matches_direct_absent_target_weapon_nuisance(self) -> None:
        event = ReplayEvent.purchase(
            100,
            "Actor",
            15,
            7,
            target_nickname="Target",
            target_present=False,
        )
        replayed = apply_replay_event(STATE, event)
        direct = purchase(
            STATE,
            "Actor",
            15,
            100,
            charged_cost=7,
            target_nickname="Target",
            target_present=False,
        )
        self.assertEqual(replayed, direct)
        self.assertEqual(replayed.state.effects[0].source_key, "actor")

    def test_purchase_constructor_rejects_unpaired_target_fields(self) -> None:
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Actor", 14, 5, target_nickname="Target")
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Actor", 14, 5, target_present=True)

    def test_decoder_rejects_non_truth_target_presence(self) -> None:
        payload = ReplayEvent.purchase(
            100,
            "Actor",
            14,
            5,
            target_nickname="Target",
            target_present=True,
        ).to_payload()
        payload["target_present"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
