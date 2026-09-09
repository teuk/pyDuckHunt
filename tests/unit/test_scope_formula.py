from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from pyduckhunt.game.accuracy import scope_bonus_points, live_scope_bonus_points
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import start_flight
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import FlightKind, GameState, PlayerState, ShotAttempt, OutcomeKind
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import CodecError, encode_game_state, decode_game_state
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, replay_records
from pyduckhunt.rendering import render_profile, render_inventory, render_outcomes
from pyduckhunt.runtime import CalibratedEventResolver, IRCCommandContext, SettlementPolicy

SHOT = Command(CommandKind.SHOT, 'bang')


def state_for(level=9, experience=45, fatigue=400, **values):
    return GameState(players=(PlayerState('hunter', 'Hunter', level=level, experience=experience,
                                         fatigue_centi=fatigue, **values),))


def resolve(state, command, *, now=100, draws=()):
    entropy = iter(draws)
    calls = []
    def draw(low, high):
        calls.append((low, high))
        return next(entropy)
    resolver = CalibratedEventResolver(draw, lambda channel, nick: True,
                                      policy=SettlementPolicy(frighten_on_miss=False))
    event = resolver(state, IRCCommandContext(now, 'Hunter', '#pond', command))
    return event, calls


def equipped(level=9, magnitude=2, **values):
    return purchase(state_for(level=level, **values), 'Hunter', 7, 10, magnitude=magnitude).state


def flight(state):
    return start_flight(state, 20, lifetime_ns=10000, kind=FlightKind.GOLDEN, health=4).state


class ScopeFormulaTests(unittest.TestCase):
    def test_reference_curve_uses_integer_floor(self):
        for base, expected in ((5500, 15), (6700, 11), (7000, 10), (7200, 9),
                               (8900, 3), (9700, 1), (9800, 0), (9900, 0), (10000, 0)):
            with self.subTest(base=base):
                self.assertEqual(scope_bonus_points(base), expected)
        for bad in (-1, 10001, True, 6700.0):
            with self.assertRaises(ValueError):
                scope_bonus_points(bad)

    def test_same_level_purchase_always_grants_eleven_without_entropy(self):
        for fatigue in (-300, 0, 400, 1800, 9000):
            state = state_for(fatigue=fatigue)
            event, calls = resolve(state, Command(CommandKind.SHOP, 'shop', ('7',)))
            self.assertEqual(calls, [])
            self.assertEqual(event.magnitude, 11)
            result = apply_replay_event(state, event)
            self.assertEqual(result.state.effects[0].remaining_uses, 6)
            self.assertEqual(result.state.player('hunter').experience, 40)
            self.assertIn('+11 points de précision', ' '.join(render_outcomes(result.outcomes)))

    def test_purchase_crossing_a_level_uses_the_paid_profile(self):
        state = state_for(level=11, experience=0)
        event, _ = resolve(state, Command(CommandKind.SHOP, 'shop', ('7',)))
        result = apply_replay_event(state, event)
        self.assertEqual(result.state.player('hunter').level, 10)
        self.assertEqual(event.magnitude, 10)
        self.assertIn('70% +10 pts lunette', ' '.join(render_profile(result.state, 'Hunter')))

    def test_credit_prevents_level_drop_and_bonus_uses_that_level(self):
        state = state_for(level=11, experience=0, shop_credit=5)
        event, _ = resolve(state, Command(CommandKind.SHOP, 'shop', ('7',)))
        result = apply_replay_event(state, event)
        self.assertEqual(result.state.player('hunter').level, 11)
        self.assertEqual(event.magnitude, 9)
        self.assertEqual(result.state.player('hunter').shop_credit, 0)

    def test_existing_two_point_scope_is_corrected_without_mutating_state(self):
        state = equipped()
        before = encode_game_state(state)
        self.assertIn('67% +11 pts lunette = 78%', ' '.join(render_profile(state, 'Hunter')))
        self.assertIn('+11 pts précision', ' '.join(render_inventory(state, 'Hunter')))
        self.assertEqual(encode_game_state(state), before)
        self.assertEqual(state.effects[0].magnitude, 2)
        self.assertEqual(state.effects[0].remaining_uses, 6)

    def test_new_hit_boundary_is_78_percent_and_consumes_one_use(self):
        state = flight(equipped())
        for roll, kind in ((7800, OutcomeKind.FLIGHT_SURVIVED), (7801, OutcomeKind.MISS)):
            with self.subTest(roll=roll):
                event, calls = resolve(state, SHOT, draws=(roll, 10000))
                self.assertEqual(calls, [(1, 10000), (1, 10000)])
                self.assertEqual(event.shot_attempt.scope_bonus_points, 11)
                result = apply_replay_event(state, event)
                outcome = next(o for o in result.outcomes if o.kind is kind)
                self.assertEqual(outcome.effective_accuracy_bps, 7800)
                self.assertEqual(outcome.accuracy_bonus_percent, 11)
                self.assertEqual(result.state.effects[0].remaining_uses, 5)

    def test_fatigue_does_not_increase_scope_bonus(self):
        state = flight(equipped(fatigue=1800))
        event, _ = resolve(state, SHOT, draws=(6001, 10000))
        result = apply_replay_event(state, event)
        miss = next(o for o in result.outcomes if o.kind is OutcomeKind.MISS)
        self.assertEqual(event.shot_attempt.scope_bonus_points, 11)
        self.assertEqual(miss.effective_accuracy_bps, 6000)
        self.assertIn('67% +11 pts lunette -18 pts fatigue = 60%', ' '.join(render_profile(state, 'Hunter')))

    def test_level_change_updates_scope_without_restoring_uses(self):
        state = equipped()
        state = replace(state, players=(replace(state.players[0], level=11),),
                        effects=(replace(state.effects[0], remaining_uses=3),))
        self.assertEqual(live_scope_bonus_points(state, state.players[0]), 9)
        self.assertIn('3 util., +9 pts précision', ' '.join(render_inventory(state, 'Hunter')))

    def test_zero_bonus_is_preserved_as_an_explicit_replay_value(self):
        state = flight(equipped(level=100, magnitude=2))
        event, _ = resolve(state, SHOT, draws=(9901, 10000))
        self.assertEqual(event.shot_attempt.scope_bonus_points, 0)
        self.assertEqual(event.to_payload()['shot_attempt']['scope_bonus_points'], 0)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        result = apply_replay_event(state, event)
        self.assertTrue(any(o.kind is OutcomeKind.MISS for o in result.outcomes))
        self.assertIn('99% +0 pts lunette = 99%', ' '.join(render_profile(state, 'Hunter')))

    def test_old_scope_and_old_shot_keep_the_old_69_percent(self):
        state = flight(equipped())
        event = ReplayEvent.command(100, 'Hunter', SHOT,
                                    shot_attempt=ShotAttempt(base_accuracy_bps=6700, accuracy_roll=7000))
        payload = event.to_payload()
        self.assertNotIn('scope_bonus_points', payload['shot_attempt'])
        self.assertEqual(ReplayEvent.from_payload(payload).to_payload(), payload)
        result = apply_replay_event(state, event)
        miss = next(o for o in result.outcomes if o.kind is OutcomeKind.MISS)
        self.assertEqual(miss.effective_accuracy_bps, 6900)
        self.assertEqual(miss.accuracy_bonus_percent, 2)

    def test_no_scope_means_no_bonus_even_with_a_settled_value(self):
        state = flight(state_for())
        live, _ = resolve(state, SHOT, draws=(6701, 10000))
        self.assertIsNone(live.shot_attempt.scope_bonus_points)
        explicit = replace(live, shot_attempt=replace(live.shot_attempt, scope_bonus_points=11))
        result = apply_replay_event(state, explicit)
        miss = next(o for o in result.outcomes if o.kind is OutcomeKind.MISS)
        self.assertEqual(miss.effective_accuracy_bps, 6700)

    def test_invalid_settled_bonus_is_rejected(self):
        for value in (-1, 34, True, 1.1, None):
            with self.subTest(value=value), self.assertRaises(CodecError):
                payload = ReplayEvent.command(100, 'Hunter', SHOT, shot_attempt=ShotAttempt()).to_payload()
                payload['shot_attempt']['scope_bonus_points'] = value
                ReplayEvent.from_payload(payload)

    def test_journal_chain_mixes_legacy_and_new_scope_rules(self):
        initial = state_for()
        events = [ReplayEvent.purchase(10, 'Hunter', 7, 5, magnitude=2),
                  ReplayEvent.start_flight(20, 10000, kind=FlightKind.GOLDEN, health=4),
                  ReplayEvent.command(30, 'Hunter', SHOT,
                    shot_attempt=ShotAttempt(base_accuracy_bps=6700, accuracy_roll=7000))]
        state = initial
        with tempfile.TemporaryDirectory() as directory:
            journal = JournalFile(Path(directory)/'events.jsonl')
            for event in events:
                journal.append(event)
                state = apply_replay_event(state, event).state
            event, _ = resolve(state, SHOT, draws=(7000, 10000))
            journal.append(event)
            expected = apply_replay_event(state, event).state
            before = journal.path.read_bytes()
            self.assertEqual(replay_records(journal.read_records(), initial_state=initial).state, expected)
            self.assertEqual(journal.path.read_bytes(), before)
            self.assertEqual(decode_game_state(encode_game_state(expected)), expected)
            self.assertEqual(expected.effects[0].remaining_uses, 4)
