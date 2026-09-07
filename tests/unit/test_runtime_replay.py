from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import GameState, OutcomeKind
from pyduckhunt.game.runtime import (
    apply_runtime_command,
    build_daily_schedule,
    install_daily_schedule,
    select_scheduled_flight,
    tick_daily_schedule,
)
from pyduckhunt.persistence.codec import (
    CodecError,
    decode_game_state,
    encode_game_state,
)
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


HOURS = tuple(range(18))
MINUTES = (0,) * 18
SCHEDULE = build_daily_schedule(0, HOURS, MINUTES)
STATS = Command(CommandKind.STATS, "duckstats")


class RuntimeReplayTests(unittest.TestCase):
    def test_schedule_installation_payload_round_trip(self) -> None:
        event = ReplayEvent.install_daily_schedule(0, 0, SCHEDULE)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_scheduled_tick_payload_round_trip_with_and_without_selection(self) -> None:
        due = ReplayEvent.schedule_tick(
            SCHEDULE[0],
            selection=select_scheduled_flight(1, golden_health_roll=5),
        )
        missed = ReplayEvent.schedule_tick(SCHEDULE[1] + 1)
        self.assertEqual(ReplayEvent.from_payload(due.to_payload()), due)
        self.assertEqual(ReplayEvent.from_payload(missed.to_payload()), missed)

    def test_replay_matches_direct_schedule_installation_and_dispatch(self) -> None:
        installed = install_daily_schedule(GameState(), 0, 0, SCHEDULE)
        selection = select_scheduled_flight(2)
        direct = tick_daily_schedule(
            installed.state,
            SCHEDULE[0],
            selection=selection,
        )
        replayed_install = apply_replay_event(
            GameState(),
            ReplayEvent.install_daily_schedule(0, 0, SCHEDULE),
        )
        replayed = apply_replay_event(
            replayed_install.state,
            ReplayEvent.schedule_tick(SCHEDULE[0], selection=selection),
        )
        self.assertEqual(replayed, direct)

    def test_runtime_command_replay_rebuilds_the_throttle_window(self) -> None:
        event = ReplayEvent.runtime_command(0, "Hunter", STATS)
        decoded = ReplayEvent.from_payload(event.to_payload())
        replayed = apply_replay_event(GameState(), decoded)
        direct = apply_runtime_command(GameState(), "Hunter", STATS, 0)
        self.assertEqual(replayed, direct)
        self.assertEqual(len(replayed.state.throttle_windows), 2)

    def test_runtime_purchase_payload_round_trip_and_throttle(self) -> None:
        event = ReplayEvent.runtime_purchase(0, "Hunter", 999, 0)
        decoded = ReplayEvent.from_payload(event.to_payload())
        replayed = apply_replay_event(GameState(), decoded)
        self.assertEqual(replayed.outcomes[-1].kind, OutcomeKind.SHOP_UNKNOWN_ITEM)
        self.assertEqual(len(replayed.state.throttle_windows), 2)

    def test_state_codec_preserves_schedule_cursor_and_throttle_deadlines(self) -> None:
        installed = install_daily_schedule(GameState(), 0, 0, SCHEDULE)
        skipped = tick_daily_schedule(installed.state, SCHEDULE[0])
        admitted = apply_runtime_command(skipped.state, "Hunter", STATS, SCHEDULE[0])
        decoded = decode_game_state(encode_game_state(admitted.state))
        self.assertEqual(decoded.daily_schedule.next_index, 1)
        self.assertEqual(decoded.throttle_windows, admitted.state.throttle_windows)

    def test_decoder_rejects_truth_value_schedule_deadline(self) -> None:
        payload = ReplayEvent.install_daily_schedule(0, 0, SCHEDULE).to_payload()
        payload["deadlines_ns"][0] = True
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_decoder_rejects_partial_schedule_tick_settlement(self) -> None:
        payload = ReplayEvent.schedule_tick(SCHEDULE[0]).to_payload()
        payload["health"] = 1
        with self.assertRaises(CodecError):
            ReplayEvent.from_payload(payload)

    def test_state_decoder_rejects_uncalibrated_personal_window(self) -> None:
        admitted = apply_runtime_command(GameState(), "Hunter", STATS, 0)
        payload = encode_game_state(admitted.state)
        personal = next(
            value for value in payload["throttle_windows"] if value["player_key"]
        )
        personal["command"] = CommandKind.INVENTORY.value
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_state_decoder_rejects_noncanonical_throttle_identity(self) -> None:
        admitted = apply_runtime_command(GameState(), "Hunter", STATS, 0)
        payload = encode_game_state(admitted.state)
        personal = next(
            value for value in payload["throttle_windows"] if value["player_key"]
        )
        personal["player_key"] = "HUNTER"
        with self.assertRaises(CodecError):
            decode_game_state(payload)


if __name__ == "__main__":
    unittest.main()
