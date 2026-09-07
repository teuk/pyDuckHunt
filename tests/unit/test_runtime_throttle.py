from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import GameState, OutcomeKind
from pyduckhunt.game.runtime import (
    COMMAND_RATE_LIMITS,
    GLOBAL_RATE_LIMIT,
    SECOND_NS,
    apply_runtime_command,
    apply_runtime_purchase,
)


def command(kind: CommandKind) -> Command:
    return Command(kind, kind.value)


class RuntimeThrottleTests(unittest.TestCase):
    def test_calibrated_command_and_global_windows_are_exact(self) -> None:
        observed = {
            CommandKind.SHOT: (30, 600),
            CommandKind.RELOAD: (15, 120),
            CommandKind.STATS: (2, 120),
            CommandKind.LAST_FLIGHT: (1, 300),
            CommandKind.SHOP: (3, 600),
        }
        self.assertEqual(
            {
                kind: (limit.maximum, limit.window_ns // SECOND_NS)
                for kind, limit in COMMAND_RATE_LIMITS.items()
            },
            observed,
        )
        self.assertEqual(
            (GLOBAL_RATE_LIMIT.maximum, GLOBAL_RATE_LIMIT.window_ns // SECOND_NS),
            (30, 600),
        )

    def test_third_stats_request_is_blocked_without_applying_the_query(self) -> None:
        state = GameState()
        first = apply_runtime_command(state, "Hunter", command(CommandKind.STATS), 0)
        second = apply_runtime_command(
            first.state,
            "Hunter",
            command(CommandKind.STATS),
            1,
        )
        blocked = apply_runtime_command(
            second.state,
            "Hunter",
            command(CommandKind.STATS),
            2,
        )
        self.assertEqual(blocked.outcomes[-1].kind, OutcomeKind.COMMAND_THROTTLED)
        self.assertTrue(blocked.outcomes[-1].notice_emitted)
        self.assertNotIn(OutcomeKind.QUERY, tuple(value.kind for value in blocked.outcomes))

    def test_personal_window_reopens_at_the_exact_first_expiration(self) -> None:
        state = GameState()
        state = apply_runtime_command(state, "Hunter", command(CommandKind.STATS), 0).state
        state = apply_runtime_command(state, "Hunter", command(CommandKind.STATS), 1).state
        blocked = apply_runtime_command(state, "Hunter", command(CommandKind.STATS), 2)
        reopened = apply_runtime_command(
            blocked.state,
            "Hunter",
            command(CommandKind.STATS),
            120 * SECOND_NS,
        )
        self.assertEqual(reopened.outcomes[-1].kind, OutcomeKind.QUERY)

    def test_global_window_blocks_the_thirty_first_public_command(self) -> None:
        state = GameState()
        inventory = command(CommandKind.INVENTORY)
        for index in range(30):
            state = apply_runtime_command(state, f"Hunter{index}", inventory, index).state
        blocked = apply_runtime_command(state, "Overflow", inventory, 30)
        self.assertEqual(blocked.outcomes[-1].kind, OutcomeKind.COMMAND_THROTTLED)
        self.assertIsNone(blocked.state.player("overflow"))

    def test_throttle_notice_is_emitted_at_most_once_per_minute(self) -> None:
        last = command(CommandKind.LAST_FLIGHT)
        accepted = apply_runtime_command(GameState(), "Hunter", last, 0)
        first = apply_runtime_command(accepted.state, "Hunter", last, 1)
        quiet = apply_runtime_command(first.state, "Hunter", last, 2)
        repeated = apply_runtime_command(
            quiet.state,
            "Hunter",
            last,
            60 * SECOND_NS + 1,
        )
        self.assertTrue(first.outcomes[-1].notice_emitted)
        self.assertFalse(quiet.outcomes[-1].notice_emitted)
        self.assertTrue(repeated.outcomes[-1].notice_emitted)

    def test_rfc1459_case_variants_share_the_personal_window(self) -> None:
        last = command(CommandKind.LAST_FLIGHT)
        accepted = apply_runtime_command(GameState(), "Hunter", last, 0)
        blocked = apply_runtime_command(accepted.state, "HUNTER", last, 1)
        self.assertEqual(blocked.outcomes[-1].kind, OutcomeKind.COMMAND_THROTTLED)

    def test_inventory_and_ranking_use_only_the_global_safety_window(self) -> None:
        inventory = apply_runtime_command(
            GameState(),
            "Hunter",
            command(CommandKind.INVENTORY),
            0,
        )
        self.assertEqual(len(inventory.state.throttle_windows), 1)
        ranking = apply_runtime_command(
            inventory.state,
            "Hunter",
            command(CommandKind.RANK),
            1,
        )
        self.assertEqual(len(ranking.state.throttle_windows), 1)

    def test_fourth_shop_purchase_is_rejected_atomically(self) -> None:
        state = GameState()
        for now_ns in range(3):
            state = apply_runtime_purchase(
                state,
                "Hunter",
                999,
                now_ns,
                charged_cost=0,
            ).state
        blocked = apply_runtime_purchase(
            state,
            "Hunter",
            999,
            3,
            charged_cost=0,
        )
        self.assertEqual(blocked.outcomes[-1].kind, OutcomeKind.COMMAND_THROTTLED)
        self.assertNotIn(
            OutcomeKind.SHOP_UNKNOWN_ITEM,
            tuple(value.kind for value in blocked.outcomes),
        )

    def test_truth_value_timestamp_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_runtime_command(
                GameState(),
                "Hunter",
                command(CommandKind.STATS),
                True,
            )


if __name__ == "__main__":
    unittest.main()
