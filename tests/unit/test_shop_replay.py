from __future__ import annotations

import unittest

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.replay import apply_replay_event
from pyduckhunt.rendering import render_outcome


STATE = GameState(
    players=(PlayerState("hunter", "Hunter", level=30, experience=300),),
)


class ShopReplayTests(unittest.TestCase):
    def test_purchase_event_payload_round_trip(self) -> None:
        event = ReplayEvent.purchase(
            100,
            "Hunter",
            10,
            12,
            magnitude=7,
            replace_active_effect=True,
        )
        self.assertEqual(event.to_payload()["target_nickname"], None)
        self.assertEqual(event.to_payload()["target_present"], None)
        self.assertIs(event.to_payload()["replace_active_effect"], True)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_scheduled_action_and_fatigue_relief_round_trip(self) -> None:
        action = ReplayEvent.purchase(
            100,
            "Hunter",
            20,
            8,
            scheduled_for_ns=200,
        )
        relief = ReplayEvent.purchase(
            100,
            "Hunter",
            24,
            5,
            fatigue_relief_centi=400,
        )
        target = ReplayEvent.purchase(
            100,
            "Hunter",
            25,
            10,
            fatigue_target_centi=644,
        )
        self.assertEqual(ReplayEvent.from_payload(action.to_payload()), action)
        self.assertEqual(ReplayEvent.from_payload(relief.to_payload()), relief)
        self.assertEqual(ReplayEvent.from_payload(target.to_payload()), target)

    def test_replay_matches_scheduled_action(self) -> None:
        event = ReplayEvent.purchase(
            100,
            "Hunter",
            20,
            8,
            scheduled_for_ns=200,
        )
        replayed = apply_replay_event(STATE, event)
        direct = purchase(
            STATE,
            "Hunter",
            20,
            100,
            charged_cost=8,
            scheduled_for_ns=200,
        )
        self.assertEqual(replayed, direct)

    def test_replay_matches_direct_discounted_purchase(self) -> None:
        event = ReplayEvent.purchase(100, "Hunter", 3, 11)
        replayed = apply_replay_event(STATE, event)
        direct = purchase(STATE, "Hunter", 3, 100, charged_cost=11)
        self.assertEqual(replayed, direct)

    def test_replay_preserves_injected_magnitude(self) -> None:
        event = ReplayEvent.purchase(100, "Hunter", 10, 13, magnitude=9)
        replayed = apply_replay_event(STATE, event)
        self.assertEqual(replayed.state.effects[0].magnitude, 9)
        self.assertEqual(replayed.outcomes[-1].effect_magnitude, 9)
        self.assertIn(
            "9 points d'xp supplémentaires",
            render_outcome(replayed.outcomes[-1])[0],
        )

    def test_replay_replaces_lucky_charm_with_the_second_paid_roll(self) -> None:
        first_event = ReplayEvent.purchase(100, "Hunter", 10, 13, magnitude=2)
        second_event = ReplayEvent.purchase(
            200,
            "Hunter",
            10,
            13,
            magnitude=9,
            replace_active_effect=True,
        )
        first = apply_replay_event(STATE, first_event)
        second = apply_replay_event(first.state, second_event)
        direct_first = purchase(STATE, "Hunter", 10, 100, magnitude=2)
        direct_second = purchase(
            direct_first.state,
            "Hunter",
            10,
            200,
            magnitude=9,
            replace_active_effect=True,
        )
        self.assertEqual(second, direct_second)
        self.assertEqual(len(second.state.effects), 1)
        self.assertEqual(second.state.effects[0].magnitude, 9)
        self.assertEqual(second.state.player("hunter").experience, 274)

    def test_legacy_repeat_payload_keeps_its_original_rejection(self) -> None:
        first = apply_replay_event(
            STATE,
            ReplayEvent.purchase(100, "Hunter", 10, 13, magnitude=2),
        )
        legacy_payload = ReplayEvent.purchase(
            200,
            "Hunter",
            10,
            13,
            magnitude=9,
        ).to_payload()
        self.assertNotIn("replace_active_effect", legacy_payload)
        legacy_event = ReplayEvent.from_payload(legacy_payload)
        self.assertFalse(legacy_event.replace_active_effect)
        repeated = apply_replay_event(first.state, legacy_event)
        self.assertEqual(
            repeated.outcomes[-1].kind.value,
            "shop_effect_active",
        )
        self.assertEqual(
            repeated.state.player("hunter"),
            first.state.player("hunter"),
        )
        self.assertEqual(repeated.state.effects, first.state.effects)

    def test_purchase_event_rejects_unbounded_replacement(self) -> None:
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(
                100,
                "Hunter",
                9,
                5,
                replace_active_effect=True,
            )
        payload = ReplayEvent.purchase(100, "Hunter", 9, 5).to_payload()
        payload["replace_active_effect"] = True
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)
        payload["replace_active_effect"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_purchase_event_rejects_truth_values(self) -> None:
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Hunter", True, 1)
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Hunter", 1, True)
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Hunter", 20, 8, scheduled_for_ns=True)
        with self.assertRaises(ValueError):
            ReplayEvent.purchase(100, "Hunter", 24, 5, fatigue_relief_centi=True)

    def test_purchase_decoder_rejects_extra_field(self) -> None:
        payload = ReplayEvent.purchase(100, "Hunter", 3, 15).to_payload()
        payload["unexpected"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
