from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from pyduckhunt.game.accuracy import fatigue_penalty_bps, overexcitation_penalty_bps
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import advance_time, start_flight
from pyduckhunt.game.model import ActiveEffect, EffectScope, FlightKind, GameState, OutcomeKind, PlayerState, ShotAttempt
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import CodecError, canonical_json_bytes, decode_game_state, encode_game_state
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, replay_records
from pyduckhunt.publishing.ranking_page import _decimal
from pyduckhunt.rendering import render_inventory, render_profile, render_outcomes
from pyduckhunt.runtime import CalibratedEventResolver, IRCCommandContext, SettlementPolicy


def state_for(fatigue=3600, **values):
    return GameState(players=(PlayerState('hunter', 'Hunter', level=9, experience=44,
                                         fatigue_centi=fatigue, **values),))


def resolve(state, kind=CommandKind.SHOP, arguments=('25',), now=100, draws=()):
    source = iter(draws)
    resolver = CalibratedEventResolver(lambda low, high: next(source), lambda chan, nick: True,
                                      policy=SettlementPolicy(frighten_on_miss=False))
    return resolver(state, IRCCommandContext(now, 'Hunter', '#pond',
                    Command(kind, 'shop' if kind is CommandKind.SHOP else 'bang', arguments)))


class ThermosOverexcitationTests(unittest.TestCase):
    def test_live_thermos_sets_minus_three_without_randomness(self):
        for before in (-300, -1, 0, 828, 1800, 3600, 10000):
            with self.subTest(before=before):
                state = state_for(before)
                event = resolve(state)
                self.assertEqual(event.fatigue_target_centi, -300)
                result = apply_replay_event(state, event)
                player = result.state.player('hunter')
                self.assertEqual((player.fatigue_centi, player.experience, player.experience_spent), (-300, 34, 10))
                self.assertEqual(result.outcomes[-1].fatigue_changed_centi, -300-before)
                text = ' '.join(render_outcomes(result.outcomes))
                for part in ('→ -3', '[surexcité]', '10 points'):
                    self.assertIn(part, text)

    def test_negative_state_and_purchase_event_roundtrip(self):
        event = resolve(state_for())
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        state = apply_replay_event(state_for(), event).state
        payload = encode_game_state(state)
        self.assertEqual(decode_game_state(payload), state)
        self.assertEqual(canonical_json_bytes(encode_game_state(decode_game_state(payload))), canonical_json_bytes(payload))

    def test_historical_828_target_and_zero_fields_preserve_bytes(self):
        old = ReplayEvent.runtime_purchase(100, 'Hunter', 25, 10, fatigue_target_centi=828)
        payload = canonical_json_bytes(old.to_payload())
        self.assertEqual(canonical_json_bytes(ReplayEvent.from_payload(old.to_payload()).to_payload()), payload)
        result = apply_replay_event(state_for(), old)
        self.assertEqual((result.state.player('hunter').fatigue_centi, result.state.player('hunter').experience), (828, 34))
        self.assertNotIn('surexcité', ' '.join(render_outcomes(result.outcomes)))
        oldshot = ReplayEvent.command(101, 'Hunter', Command(CommandKind.SHOT, 'bang'), shot_attempt=ShotAttempt())
        self.assertNotIn('overexcitation_penalty_bps', oldshot.to_payload()['shot_attempt'])
        self.assertEqual(ReplayEvent.from_payload(oldshot.to_payload()).to_payload(), oldshot.to_payload())

    def test_invalid_bounds_and_penalty_fields_are_rejected(self):
        for value in (-301, True, 1.25, 10001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                state_for(value)
        for value in (-301, True, 1001):
            with self.subTest(target=value), self.assertRaises(ValueError):
                purchase(state_for(), 'Hunter', 25, 100, fatigue_target_centi=value)
        for value in (-1, True, 10001, 2.5):
            with self.subTest(penalty=value), self.assertRaises(CodecError):
                event = ReplayEvent.command(100, 'Hunter', Command(CommandKind.SHOT, 'bang'), shot_attempt=ShotAttempt()).to_payload()
                event['shot_attempt']['overexcitation_penalty_bps'] = value
                ReplayEvent.from_payload(event)

    def test_profile_inventory_and_negative_fraction_display(self):
        text = ' '.join(render_profile(state_for(-300), 'Hunter'))
        for part in ('fatigue: -3', '67% -9 pts surexcitation = 58%', '[surexcité]'):
            self.assertIn(part, text)
        self.assertNotIn('[fatigué]', text)
        self.assertIn('-9 pts précision', ' '.join(render_inventory(state_for(-300), 'Hunter')))
        for value, expected in ((-300, '-3'), (-172, '-1.72'), (-28, '-0.28'), (0, '0'), (828, '8.28')):
            self.assertEqual(_decimal(value), expected)
            self.assertIn('fatigue: '+expected, ' '.join(render_profile(state_for(value), 'Hunter')))

    def test_shot_threshold_uses_pre_trigger_fatigue_once(self):
        for before, roll, kind, expected in ((-300, 5800, OutcomeKind.FLIGHT_SURVIVED, 5800),
                                           (-300, 5801, OutcomeKind.MISS, 5800),
                                           (-100, 6401, OutcomeKind.MISS, 6400)):
            with self.subTest(before=before, roll=roll):
                state = start_flight(state_for(before), 10, lifetime_ns=10000, kind=FlightKind.GOLDEN, health=4).state
                event = resolve(state, CommandKind.SHOT, (), draws=(roll, 10000))
                self.assertEqual(event.shot_attempt.overexcitation_penalty_bps, -before*3)
                self.assertEqual(event.shot_attempt.fatigue_penalty_bps, 0)
                result = apply_replay_event(state, event)
                outcome = next(o for o in result.outcomes if o.kind is kind)
                self.assertEqual(outcome.effective_accuracy_bps, expected)
                self.assertEqual(result.state.player('hunter').fatigue_centi, before+100)
                self.assertIn('[surexcité]', ' '.join(render_outcomes(result.outcomes)))
                if before == -100:
                    self.assertNotIn('[surexcité]', ' '.join(render_profile(result.state, 'Hunter')))

    def test_endurance_suppresses_penalty(self):
        effect = ActiveEffect(1, 102, 'duck_endurance', EffectScope.PLAYER, 'hunter', 'hunter', 0, 10000)
        state = replace(state_for(-300), effects=(effect,), next_effect_id=2)
        self.assertEqual(overexcitation_penalty_bps(state, state.players[0]), 0)
        self.assertEqual(fatigue_penalty_bps(state, state.players[0]), 0)
        self.assertNotIn('[surexcité]', ' '.join(render_profile(state, 'Hunter')))

    def test_normal_relief_preserves_negative_fatigue(self):
        state = state_for(-300)
        for item, args in ((24, ()), (27, ('Hunter',))):
            event = resolve(state, arguments=(str(item), *args))
            self.assertEqual(event.fatigue_relief_centi, 0)
            self.assertEqual(apply_replay_event(state, event).state.player('hunter').fatigue_centi, -300)

    def test_infusion_expiry_preserves_negative_fatigue(self):
        effect = ActiveEffect(1, 28, 'herbal_infusion', EffectScope.PLAYER, 'hunter', 'hunter', 0, 1000, magnitude=600)
        state = replace(state_for(-300), effects=(effect,), next_effect_id=2)
        self.assertEqual(advance_time(state, 1001).state.player('hunter').fatigue_centi, -300)

    def test_credit_and_charge_remain_correct(self):
        result = purchase(state_for(3600, shop_credit=5), 'Hunter', 25, 100, charged_cost=8, fatigue_target_centi=-300)
        self.assertIn('[bon d\'achat]', ' '.join(render_outcomes(result.outcomes)))
        self.assertEqual((result.state.player('hunter').experience, result.state.player('hunter').shop_credit), (41, 0))

    def test_real_journal_recovers_mixed_targets_and_shot(self):
        initial = state_for()
        events = [ReplayEvent.runtime_purchase(10, 'Hunter', 25, 10, fatigue_target_centi=828),
                  ReplayEvent.purchase(20, 'Hunter', 25, 10, fatigue_target_centi=-300),
                  ReplayEvent.start_flight(30, 10000, kind=FlightKind.GOLDEN, health=4)]
        state = initial
        with tempfile.TemporaryDirectory() as directory:
            journal = JournalFile(Path(directory)/'events.jsonl')
            for event in events:
                journal.append(event)
                state = apply_replay_event(state, event).state
            event = resolve(state, CommandKind.SHOT, (), draws=(6000, 10000))
            journal.append(event)
            expected = apply_replay_event(state, event).state
            before = journal.path.read_bytes()
            self.assertEqual(replay_records(journal.read_records(), initial_state=initial).state, expected)
            self.assertEqual(journal.path.read_bytes(), before)
