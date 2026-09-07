from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.model import (
    GameState,
    LastFlightConclusion,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")
STATS = Command(CommandKind.STATS, "duckstats")
SECOND = 1_000_000_000


class DeterministicEngineTests(unittest.TestCase):
    def test_start_flight_allocates_monotonic_identifier(self) -> None:
        transition = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        self.assertEqual(transition.outcomes[-1].kind, OutcomeKind.FLIGHT_STARTED)
        self.assertEqual(transition.state.flight.flight_id, 1)
        self.assertEqual(transition.state.next_flight_id, 2)

    def test_second_spawn_is_rejected_while_active(self) -> None:
        first = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        second = start_flight(first.state, 2 * SECOND, lifetime_ns=5 * SECOND)
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.FLIGHT_ALREADY_ACTIVE)
        self.assertEqual(second.state.flight.flight_id, 1)

    def test_flight_expires_at_exact_deadline(self) -> None:
        started = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        expired = advance_time(started.state, 6 * SECOND)
        self.assertIsNone(expired.state.flight)
        self.assertEqual(expired.outcomes[-1].kind, OutcomeKind.FLIGHT_EXPIRED)
        assert expired.state.last_flight is not None
        self.assertEqual(expired.state.last_flight.ended_at_ns, 6 * SECOND)
        self.assertEqual(expired.state.last_flight.conclusion, LastFlightConclusion.ESCAPED)

    def test_first_loaded_shot_hits_and_closes_flight(self) -> None:
        started = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        hit = apply_command(started.state, "Hunter", SHOT, 2_463_000_000)
        self.assertEqual(hit.outcomes[-1].kind, OutcomeKind.HIT)
        self.assertEqual(hit.outcomes[-1].elapsed_ms, 1463)
        self.assertIsNone(hit.state.flight)
        self.assertEqual(hit.outcomes[-1].player.hits, 1)
        self.assertEqual(hit.outcomes[-1].player.ammo, 5)
        self.assertEqual(hit.outcomes[-1].experience_awarded, 10)
        self.assertEqual(hit.outcomes[-1].player.experience, 10)
        self.assertEqual(hit.state.players[0].shots_fired, 1)
        self.assertEqual(hit.state.last_shooter_key, "hunter")
        assert hit.state.last_flight is not None
        self.assertEqual(hit.state.last_flight.actor, "Hunter")
        self.assertEqual(hit.state.last_flight.conclusion, LastFlightConclusion.HIT)

    def test_second_shot_after_hit_is_late_for_another_player(self) -> None:
        started = start_flight(GameState(), SECOND, lifetime_ns=5 * SECOND)
        first = apply_command(started.state, "First", SHOT, 2 * SECOND)
        second = apply_command(first.state, "Second", SHOT, 2 * SECOND)
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.LATE_SHOT)
        self.assertEqual(second.outcomes[-1].late_by_ms, 0)
        self.assertEqual(second.outcomes[-1].player.misses, 1)
        self.assertEqual(second.outcomes[-1].player.wild_shots, 0)
        self.assertEqual(second.state.last_shooter_key, "second")

    def test_expired_flight_is_reported_before_miss(self) -> None:
        started = start_flight(GameState(), SECOND, lifetime_ns=SECOND)
        result = apply_command(started.state, "Late", SHOT, 2 * SECOND)
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.FLIGHT_EXPIRED, OutcomeKind.MISS),
        )

    def test_empty_weapon_does_not_increment_misses(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", ammo=1),))
        first = apply_command(state, "Hunter", SHOT, SECOND)
        second = apply_command(first.state, "Hunter", SHOT, 2 * SECOND)
        self.assertEqual(second.outcomes[-1].kind, OutcomeKind.EMPTY)
        self.assertEqual(second.outcomes[-1].player.misses, 1)
        self.assertEqual(second.outcomes[-1].player.empty_shots, 1)
        self.assertEqual(second.state.players[0].shots_fired, 1)
        self.assertEqual(second.state.last_shooter_key, "hunter")

    def test_shot_with_already_jammed_weapon_has_its_own_karma_counter(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", jammed=True),))
        result = apply_command(state, "Hunter", SHOT, SECOND)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.JAMMED)
        self.assertEqual(result.outcomes[-1].player.jammed_shots, 1)
        self.assertEqual(result.state.players[0].jams, 0)
        self.assertEqual(result.state.players[0].shots_fired, 0)

    def test_only_a_fired_shot_without_a_duck_increments_wild_shots(self) -> None:
        initial = GameState(
            players=(PlayerState("hunter", "Hunter", ammo=2, capacity=2),)
        )
        wild = apply_command(initial, "Hunter", SHOT, 1)
        self.assertEqual(wild.state.players[0].wild_shots, 1)
        flying = start_flight(wild.state, 2, lifetime_ns=100).state
        missed = apply_command(
            flying,
            "Hunter",
            SHOT,
            3,
            shot_attempt=ShotAttempt(accuracy_roll=10_000, base_accuracy_bps=0),
        )
        self.assertEqual(missed.state.players[0].wild_shots, 1)

    def test_reload_fills_weapon(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", ammo=1),))
        fired = apply_command(state, "Hunter", SHOT, SECOND)
        reloaded = apply_command(fired.state, "Hunter", RELOAD, 2 * SECOND)
        self.assertEqual(reloaded.outcomes[-1].kind, OutcomeKind.RELOADED)
        self.assertEqual(reloaded.outcomes[-1].player.ammo, 6)
        self.assertEqual(reloaded.outcomes[-1].player.magazines, 1)

    def test_reload_when_full_is_idempotent(self) -> None:
        result = apply_command(GameState(), "Hunter", RELOAD, SECOND)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.ALREADY_LOADED)
        self.assertEqual(result.outcomes[-1].player.ammo, 6)
        self.assertEqual(result.outcomes[-1].player.magazines, 2)
        self.assertEqual(result.outcomes[-1].player.compulsive_reloads, 1)

    def test_rfc1459_case_variants_share_player_state(self) -> None:
        fired = apply_command(GameState(), "H[unter", SHOT, SECOND)
        reloaded = apply_command(fired.state, "h{UNTER", RELOAD, 2 * SECOND)
        self.assertEqual(len(reloaded.state.players), 1)
        self.assertEqual(reloaded.outcomes[-1].player.misses, 1)

    def test_query_does_not_change_counters_or_ammo(self) -> None:
        result = apply_command(GameState(), "Hunter", STATS, SECOND)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.QUERY)
        self.assertEqual(result.outcomes[-1].player.hits, 0)
        self.assertEqual(result.outcomes[-1].player.misses, 0)
        self.assertEqual(result.outcomes[-1].player.ammo, 6)

    def test_best_time_only_improves(self) -> None:
        first_flight = start_flight(GameState(), SECOND, lifetime_ns=10 * SECOND)
        first_hit = apply_command(first_flight.state, "Hunter", SHOT, 4 * SECOND)
        reload_one = apply_command(first_hit.state, "Hunter", RELOAD, 5 * SECOND)
        second_flight = start_flight(reload_one.state, 6 * SECOND, lifetime_ns=10 * SECOND)
        second_hit = apply_command(second_flight.state, "Hunter", SHOT, 8 * SECOND)
        self.assertEqual(second_hit.outcomes[-1].player.best_time_ms, 2000)

    def test_clock_rejects_time_travel(self) -> None:
        state = advance_time(GameState(), 2 * SECOND).state
        with self.assertRaises(ValueError):
            advance_time(state, SECOND)


if __name__ == "__main__":
    unittest.main()
