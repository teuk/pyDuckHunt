from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import GameState, OutcomeKind, PlayerState


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")
SECOND = 1_000_000_000


class ProfileEngineTests(unittest.TestCase):
    def test_hit_grants_base_experience_in_the_priority_transition(self) -> None:
        flight = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        hit = apply_command(flight.state, "Hunter", SHOT, 2 * SECOND)
        outcome = hit.outcomes[-1]
        self.assertEqual(outcome.experience_awarded, 10)
        self.assertEqual((outcome.player.level, outcome.player.experience), (1, 10))

    def test_hit_reports_a_level_gain(self) -> None:
        state = GameState(
            players=(PlayerState("hunter", "Hunter", experience=15),),
        )
        flight = start_flight(state, SECOND, lifetime_ns=5 * SECOND)
        hit = apply_command(flight.state, "Hunter", SHOT, 2 * SECOND)
        outcome = hit.outcomes[-1]
        self.assertEqual(outcome.levels_gained, 1)
        self.assertEqual((outcome.player.level, outcome.player.experience), (2, 5))

    def test_reload_consumes_one_reserve_magazine(self) -> None:
        state = GameState(
            players=(PlayerState("hunter", "Hunter", ammo=0, magazines=2),),
        )
        reloaded = apply_command(state, "Hunter", RELOAD, SECOND)
        self.assertEqual(reloaded.outcomes[-1].kind, OutcomeKind.RELOADED)
        self.assertEqual((reloaded.outcomes[-1].player.ammo, reloaded.outcomes[-1].player.magazines), (6, 1))

    def test_empty_weapon_reloads_to_its_profile_capacity(self) -> None:
        state = GameState(
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=0,
                    capacity=4,
                    magazines=2,
                ),
            ),
        )
        reloaded = apply_command(state, "Hunter", RELOAD, SECOND)
        self.assertEqual((reloaded.outcomes[-1].player.ammo, reloaded.outcomes[-1].player.magazines), (4, 1))

    def test_remaining_round_refuses_reload_without_spending_a_magazine(self) -> None:
        state = GameState(
            players=(PlayerState("hunter", "Hunter", ammo=5, magazines=2),),
        )
        refused = apply_command(state, "Hunter", RELOAD, SECOND)
        self.assertEqual(refused.outcomes[-1].kind, OutcomeKind.ALREADY_LOADED)
        self.assertEqual(
            (refused.outcomes[-1].player.ammo, refused.outcomes[-1].player.magazines),
            (5, 2),
        )
        self.assertEqual(refused.outcomes[-1].player.compulsive_reloads, 1)

    def test_empty_reserve_cannot_reload(self) -> None:
        state = GameState(
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=0,
                    magazines=0,
                ),
            ),
        )
        result = apply_command(state, "Hunter", RELOAD, SECOND)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.NO_RESERVE)
        self.assertEqual(result.outcomes[-1].player.ammo, 0)

    def test_full_weapon_does_not_consume_reserve(self) -> None:
        result = apply_command(GameState(), "Hunter", RELOAD, SECOND)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.ALREADY_LOADED)
        self.assertEqual(result.outcomes[-1].player.magazines, 2)


if __name__ == "__main__":
    unittest.main()
