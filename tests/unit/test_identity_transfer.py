from __future__ import annotations

from dataclasses import replace
import unittest

from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.engine import advance_time
from pyduckhunt.game.identity_transfer import (
    PENDING_IDENTITY_TRANSFER_TTL_NS,
    cancel_pending_identity_transfer,
    resolve_pending_identity_transfer,
    track_nick_change,
)
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    GameState,
    InventoryStack,
    PendingIdentityTransfer,
    PlayerState,
    ScheduledAction,
    ThrottleWindow,
)
from pyduckhunt.game.progression import available_experience, grant_experience
from pyduckhunt.persistence.codec import decode_game_state, encode_game_state
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


def player(nickname: str, *, experience: int = 0, hits: int = 0) -> PlayerState:
    base = PlayerState(nickname.casefold(), nickname, hits=hits)
    return grant_experience(base, experience).player


class IdentityTransferTests(unittest.TestCase):
    def test_nick_change_is_deferred_until_participation(self) -> None:
        state = GameState(now_ns=10, players=(player("Hunter", experience=37),))
        tracked = track_nick_change(state, "Hunter", "Wizard", 10).state
        self.assertIsNotNone(tracked.player("hunter"))
        self.assertIsNone(tracked.player("wizard"))
        self.assertEqual(tracked.pending_identity_transfers[0].source_key, "hunter")

        resolved = resolve_pending_identity_transfer(tracked, "Wizard").state
        self.assertIsNone(resolved.player("hunter"))
        self.assertEqual(resolved.player("wizard").nickname, "Wizard")
        self.assertEqual(available_experience(resolved.player("wizard")), 37)
        self.assertEqual(resolved.pending_identity_transfers, ())

    def test_reverse_and_departure_cancel_unconsumed_transfer(self) -> None:
        state = GameState(now_ns=10, players=(player("Hunter"),))
        tracked = track_nick_change(state, "Hunter", "Wizard", 10).state
        reversed_state = track_nick_change(tracked, "Wizard", "Hunter", 10).state
        self.assertEqual(reversed_state.pending_identity_transfers, ())

        tracked = track_nick_change(state, "Hunter", "Wizard", 10).state
        cancelled = cancel_pending_identity_transfer(tracked, "Wizard").state
        self.assertEqual(cancelled.pending_identity_transfers, ())
        self.assertIsNotNone(cancelled.player("hunter"))

    def test_chain_keeps_original_source_and_latest_destination(self) -> None:
        state = GameState(now_ns=10, players=(player("Hunter"),))
        first = track_nick_change(state, "Hunter", "Wizard", 10).state
        second = track_nick_change(first, "Wizard", "Seeker", 10).state
        self.assertEqual(len(second.pending_identity_transfers), 1)
        transfer = second.pending_identity_transfers[0]
        self.assertEqual(
            (transfer.source_key, transfer.destination_key),
            ("hunter", "seeker"),
        )

    def test_transfer_expires_after_reference_window(self) -> None:
        state = GameState(now_ns=10, players=(player("Hunter"),))
        tracked = track_nick_change(state, "Hunter", "Wizard", 10).state
        deadline = 10 + PENDING_IDENTITY_TRANSFER_TTL_NS
        expired = advance_time(tracked, deadline).state
        self.assertEqual(expired.pending_identity_transfers, ())
        self.assertIsNotNone(expired.player("hunter"))

    def test_collision_merges_reference_stats_and_runtime_identity(self) -> None:
        source = replace(
            player("Hunter", experience=37, hits=2),
            misses=3,
            best_time_ms=900,
            inventory=(InventoryStack("lucky_token", 1),),
        )
        destination = replace(
            player("Wizard", experience=28, hits=4),
            misses=5,
            best_time_ms=700,
            inventory=(
                InventoryStack("lucky_token", 2),
                InventoryStack("target_lens", 1),
            ),
        )
        state = GameState(
            now_ns=10,
            last_shooter_key="hunter",
            players=tuple(sorted((source, destination), key=lambda item: item.key)),
            next_effect_id=3,
            effects=(
                ActiveEffect(
                    1,
                    21,
                    "channel_bread",
                    EffectScope.CHANNEL,
                    None,
                    "hunter",
                    1,
                    expires_at_ns=500,
                    magnitude=100,
                ),
                ActiveEffect(
                    2,
                    21,
                    "channel_bread",
                    EffectScope.CHANNEL,
                    None,
                    "wizard",
                    2,
                    expires_at_ns=600,
                    magnitude=200,
                ),
            ),
            next_action_id=3,
            scheduled_actions=(
                ScheduledAction(1, 20, "duck_call", "hunter", 1, 300),
                ScheduledAction(2, 20, "duck_call", "wizard", 2, 400),
            ),
            throttle_windows=(
                ThrottleWindow("hunter", CommandKind.SHOT, (100,)),
                ThrottleWindow("wizard", CommandKind.SHOT, (200,)),
            ),
        )
        tracked = track_nick_change(state, "Hunter", "Wizard", 10).state
        merged = resolve_pending_identity_transfer(tracked, "Wizard").state
        self.assertEqual(tuple(item.key for item in merged.players), ("wizard",))
        profile = merged.players[0]
        self.assertEqual(available_experience(profile), 65)
        self.assertEqual((profile.hits, profile.misses), (6, 8))
        self.assertEqual(profile.best_time_ms, 700)
        self.assertEqual(
            profile.inventory,
            (
                InventoryStack("lucky_token", 2),
                InventoryStack("target_lens", 1),
            ),
        )
        self.assertEqual(merged.last_shooter_key, "wizard")
        self.assertEqual(len(merged.throttle_windows), 1)
        self.assertEqual(merged.throttle_windows[0].expires_at_ns, (100, 200))
        self.assertEqual(len(merged.effects), 2)
        self.assertEqual({effect.source_key for effect in merged.effects}, {"wizard"})
        self.assertEqual(len(merged.scheduled_actions), 2)
        self.assertEqual(
            {action.source_key for action in merged.scheduled_actions},
            {"wizard"},
        )

    def test_replay_events_and_schema_round_trip(self) -> None:
        initial = GameState(players=(player("Hunter"),))
        track = ReplayEvent.track_nick_change(10, "Hunter", "Wizard")
        self.assertEqual(track.kind, EventKind.TRACK_NICK_CHANGE)
        self.assertEqual(ReplayEvent.from_payload(track.to_payload()), track)
        tracked = apply_replay_event(initial, track).state

        payload = encode_game_state(tracked)
        self.assertEqual(decode_game_state(payload), tracked)
        legacy = dict(payload)
        del legacy["pending_identity_transfers"]
        self.assertEqual(
            decode_game_state(legacy, schema_version=24).pending_identity_transfers,
            (),
        )

        resolve = ReplayEvent.resolve_nick_transfer(11, "Wizard")
        self.assertEqual(ReplayEvent.from_payload(resolve.to_payload()), resolve)
        resolved = apply_replay_event(tracked, resolve).state
        self.assertIsNotNone(resolved.player("wizard"))

        cancel = ReplayEvent.cancel_nick_transfer(11, "Wizard")
        self.assertEqual(ReplayEvent.from_payload(cancel.to_payload()), cancel)

    def test_invalid_identity_event_payloads_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReplayEvent.track_nick_change(10, "Hunter", "HUNTER")
        with self.assertRaises(ValueError):
            PendingIdentityTransfer("hunter", "Hunter", "hunter", "HUNTER", 10)


if __name__ == "__main__":
    unittest.main()
