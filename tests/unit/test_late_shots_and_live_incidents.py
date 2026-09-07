from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import LATE_SHOT_WINDOW_NS, apply_command, start_flight
from pyduckhunt.game.model import (
    GameState,
    Outcome,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.irc.message import parse_irc_line
from pyduckhunt.persistence.replay import apply_replay_event
from pyduckhunt.rendering.responses import render_outcome, render_outcomes
from pyduckhunt.runtime.application import IRCCommandContext
from pyduckhunt.runtime.incidents import (
    CalibratedIncidentSource,
    HISTORICAL_INCIDENT_BPS,
    IRCChannelRoster,
)
from pyduckhunt.runtime.settlement import CalibratedEventResolver


SECOND = 1_000_000_000
SHOT = Command(CommandKind.SHOT, "bang")


class SequenceSource:
    def __init__(self, *values: int) -> None:
        self.values = list(values)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, minimum: int, maximum: int) -> int:
        self.calls.append((minimum, maximum))
        if not self.values:
            raise AssertionError("integer sequence exhausted")
        return self.values.pop(0)


def killed_state() -> GameState:
    started = start_flight(
        GameState(players=(PlayerState("second", "Second", experience=10),)),
        SECOND,
        lifetime_ns=20 * SECOND,
    )
    return apply_command(started.state, "First", SHOT, 2 * SECOND).state


class LateShotTests(unittest.TestCase):
    def test_three_second_boundary_is_late_without_wild_penalty(self) -> None:
        result = apply_command(
            killed_state(),
            "Second",
            SHOT,
            2 * SECOND + LATE_SHOT_WINDOW_NS,
            shot_attempt=ShotAttempt(miss_penalty=2, wild_penalty=7),
        )
        outcome = result.outcomes[-1]
        assert outcome.player is not None
        self.assertEqual(outcome.kind, OutcomeKind.LATE_SHOT)
        self.assertEqual(outcome.late_by_ms, 3_000)
        self.assertEqual(outcome.player.misses, 1)
        self.assertEqual(outcome.player.wild_shots, 0)
        self.assertEqual(outcome.player.experience, 8)
        self.assertEqual(outcome.player.ammo, 5)
        self.assertEqual(result.state.player("second").shots_fired, 1)

    def test_first_nanosecond_after_window_is_a_true_wild_shot(self) -> None:
        result = apply_command(
            killed_state(),
            "Second",
            SHOT,
            2 * SECOND + LATE_SHOT_WINDOW_NS + 1,
            shot_attempt=ShotAttempt(miss_penalty=2, wild_penalty=7),
        )
        outcome = result.outcomes[-1]
        assert outcome.player is not None
        self.assertEqual(outcome.kind, OutcomeKind.MISS)
        self.assertEqual(outcome.player.wild_shots, 1)
        self.assertEqual(outcome.player.experience, 1)
        self.assertEqual(outcome.wild_penalty, 7)

    def test_late_and_wild_renderings_match_the_historical_contract(self) -> None:
        late = render_outcome(
            Outcome(
                OutcomeKind.LATE_SHOT,
                actor="Moonbeam",
                late_by_ms=393,
                miss_penalty=1,
            )
        )[0]
        self.assertIn("tu as tiré 0.393s trop tard", late)
        self.assertIn("[raté : -1 xp]", late)
        self.assertNotIn("tir sauvage", late)

        wild = apply_command(
            GameState(),
            "pierreafeu",
            SHOT,
            1,
            shot_attempt=ShotAttempt(miss_penalty=1, wild_penalty=1),
        ).outcomes[-1]
        line = render_outcome(wild)[0]
        self.assertIn("tu visais qui au juste", line)
        self.assertIn("[tir sauvage : -1 xp]", line)

    def test_runtime_resolver_never_requests_an_incident_for_late_or_wild(self) -> None:
        incident_calls: list[str] = []

        def incident_source(state, context, attempt):
            del state, attempt
            incident_calls.append(context.nickname)
            return None

        late_context = IRCCommandContext(
            2 * SECOND + 393_000_000,
            "Second",
            "#coin",
            SHOT,
        )
        late_event = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            incident_source=incident_source,
        )(killed_state(), late_context)
        self.assertIsNone(late_event.shot_attempt.incident)
        self.assertEqual(
            apply_replay_event(killed_state(), late_event).outcomes[-1].kind,
            OutcomeKind.LATE_SHOT,
        )

        wild_context = IRCCommandContext(1, "Wild", "#coin", SHOT)
        wild_event = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            incident_source=incident_source,
        )(GameState(), wild_context)
        self.assertIsNone(wild_event.shot_attempt.incident)
        self.assertEqual(incident_calls, [])


class LiveIncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.roster = IRCChannelRoster(("#Coin",), ("Coin", "Coin_"))
        self.roster.observe(parse_irc_line(":Coin!u@h JOIN #coin"))
        self.roster.observe(
            parse_irc_line(":server 353 Coin = #coin :@Coin +Alice Bob")
        )

    def test_roster_fails_closed_until_names_end_and_tracks_departures(self) -> None:
        self.assertEqual(self.roster.candidates("#coin", "Alice"), ())
        self.roster.observe(parse_irc_line(":server 366 Coin #coin :End of NAMES"))
        self.assertEqual(self.roster.candidates("#COIN", "Alice"), ("Bob",))
        self.assertTrue(self.roster.present("#coin", "bOB"))
        self.roster.observe(parse_irc_line(":Bob!u@h NICK Robert"))
        self.assertEqual(self.roster.candidates("#coin", "Alice"), ("Robert",))
        self.roster.observe(parse_irc_line(":Robert!u@h PART #coin :bye"))
        self.assertEqual(self.roster.candidates("#coin", "Alice"), ())

    def test_five_percent_draw_builds_replay_complete_level_policy_attempt(self) -> None:
        self.roster.observe(parse_irc_line(":server 366 Coin #coin :End of NAMES"))
        integers = SequenceSource(HISTORICAL_INCIDENT_BPS, 0, 10_000, 10_000)
        observed: list[str] = []
        source = CalibratedIncidentSource(integers, self.roster, observed.append)
        context = IRCCommandContext(1, "Alice", "#coin", SHOT)
        incident = source(GameState(), context, ShotAttempt())
        assert incident is not None
        self.assertEqual(incident.targets[0].nickname, "Bob")
        self.assertGreater(incident.incident_penalty, 0)
        self.assertEqual(integers.calls[0], (1, 10_000))
        self.assertEqual(len(observed), 1)
        self.assertIn("trigger=500/500", observed[0])
        self.assertIn("Bob:deflection=10000/", observed[0])

    def test_five_percent_incident_is_per_eligible_bang_and_forces_the_miss(self) -> None:
        self.roster.observe(parse_irc_line(":server 366 Coin #coin :End of NAMES"))
        integers = SequenceSource(1, 10_000, 500, 0, 10_000, 10_000)
        resolver = CalibratedEventResolver(
            integers,
            self.roster.present,
            incident_source=CalibratedIncidentSource(integers, self.roster),
        )
        state = start_flight(
            GameState(
                players=(
                    PlayerState("alice", "Alice"),
                    PlayerState("bob", "Bob"),
                )
            ),
            1,
            lifetime_ns=SECOND,
        ).state
        event = resolver(state, IRCCommandContext(2, "Alice", "#coin", SHOT))
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.accuracy_roll, 1)
        self.assertIsNotNone(event.shot_attempt.incident)
        transition = apply_replay_event(state, event)
        self.assertEqual(
            tuple(outcome.kind for outcome in transition.outcomes),
            (OutcomeKind.MISS, OutcomeKind.INCIDENT_FATAL),
        )
        self.assertIsNotNone(transition.state.flight)

    def test_draw_above_five_percent_and_unsynchronized_roster_are_safe(self) -> None:
        untouched = SequenceSource()
        source = CalibratedIncidentSource(untouched, self.roster)
        context = IRCCommandContext(1, "Alice", "#coin", SHOT)
        self.assertIsNone(source(GameState(), context, ShotAttempt()))
        self.assertEqual(untouched.calls, [])

        self.roster.observe(parse_irc_line(":server 366 Coin #coin :End of NAMES"))
        rejected = SequenceSource(HISTORICAL_INCIDENT_BPS + 1)
        self.assertIsNone(
            CalibratedIncidentSource(rejected, self.roster)(
                GameState(), context, ShotAttempt()
            )
        )

    def test_incident_rendering_replaces_plain_miss_with_visible_ricochet(self) -> None:
        from pyduckhunt.game.model import IncidentAttempt, IncidentTargetAttempt

        flight = start_flight(GameState(), 1, lifetime_ns=SECOND).state
        transition = apply_command(
            flight,
            "Alice",
            SHOT,
            2,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=0,
                accuracy_roll=10_000,
                miss_penalty=1,
                incident=IncidentAttempt(
                    (
                        IncidentTargetAttempt(
                            "Bob",
                            deflection_bps=4_900,
                            deflection_roll=1,
                        ),
                    ),
                    incident_penalty=4,
                ),
            ),
        )
        lines = render_outcomes(transition.outcomes)
        self.assertEqual(len(lines), 1)
        self.assertIn("*PIEWWW*", lines[0])
        self.assertIn("ricoche sur Bob", lines[0])
        self.assertIn("[raté : -1 xp]", lines[0])
        self.assertIn("[accident : -4 xp]", lines[0])
        self.assertIn("[ARME CONFISQUÉE : accident de chasse]", lines[0])
        self.assertNotIn("[fatigué]", lines[0])


if __name__ == "__main__":
    unittest.main()
