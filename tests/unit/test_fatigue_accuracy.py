from __future__ import annotations

from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from pyduckhunt.game.accuracy import fatigue_penalty_bps, shot_accuracy
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import start_flight
from pyduckhunt.game.karma import player_base_karma_basis_points, player_karma_basis_points
from pyduckhunt.game.model import ActiveEffect, EffectScope, FlightKind, GameState, OutcomeKind, PlayerState, ShotAttempt
from pyduckhunt.game.shop import purchase
from pyduckhunt.game.runtime import apply_runtime_command, apply_runtime_purchase, SECOND_NS
from pyduckhunt.persistence.codec import CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, replay_records
from pyduckhunt.rendering import render_inventory, render_outcomes, render_profile, render_wire_notice
from pyduckhunt.runtime import CalibratedEventResolver, IRCCommandContext, SettlementPolicy


SHOT = Command(CommandKind.SHOT, 'bang')


def state_for(fatigue: int = 1_800, *, effects=()) -> GameState:
    player = PlayerState('hunter', 'Hunter', level=9, experience=44,
                         fatigue_centi=fatigue, ammo=6, capacity=6)
    return GameState(players=(player,), effects=effects,
                     next_effect_id=1 + max((effect.effect_id for effect in effects), default=0))


def resolve(state: GameState, roll: int, *, now_ns: int = 200) -> ReplayEvent:
    draws = iter((roll, 10_000))
    resolver = CalibratedEventResolver(
        lambda minimum, maximum: next(draws), lambda channel, nickname: True,
        policy=SettlementPolicy(frighten_on_miss=False),
    )
    return resolver(state, IRCCommandContext(now_ns, 'Hunter', '#pond', SHOT))


class FatigueAccuracyTests(unittest.TestCase):
    def test_observed_fractional_threshold_and_bounds(self) -> None:
        for centi, expected in ((0, 0), (672, 0), (1_200, 0), (1_201, 3),
                                (1_272, 216), (1_400, 600), (1_571, 1_113),
                                (1_800, 1_800), (2_700, 4_500), (3_400, 6_600),
                                (10_000, 10_000)):
            with self.subTest(fatigue=centi):
                state = state_for(centi)
                self.assertEqual(fatigue_penalty_bps(state, state.players[0]), expected)

    def test_live_threshold_is_49_percent_at_level_nine_and_fatigue_eighteen(self) -> None:
        state = start_flight(state_for(), 100, lifetime_ns=10_000,
                             kind=FlightKind.GOLDEN, health=4).state
        for roll, expected in ((4_900, OutcomeKind.FLIGHT_SURVIVED), (4_901, OutcomeKind.MISS)):
            with self.subTest(roll=roll):
                event = resolve(state, roll)
                self.assertEqual(event.shot_attempt.fatigue_penalty_bps, 1_800)
                transition = apply_replay_event(state, event)
                outcome = next(o for o in transition.outcomes if o.kind is expected)
                self.assertEqual(outcome.effective_accuracy_bps, 4_900)
                self.assertEqual(outcome.fatigue_penalty_bps, 1_800)
                self.assertIn('[fatigué]', ' '.join(render_outcomes(transition.outcomes)))

    def test_scope_bonus_and_fatigue_are_used_once_in_both_profile_and_shot(self) -> None:
        bought = purchase(state_for(), 'Hunter', 7, 10, magnitude=11).state
        state = start_flight(bought, 100, lifetime_ns=10_000,
                             kind=FlightKind.GOLDEN, health=4).state
        before = render_profile(state, 'Hunter')[0]
        self.assertIn('67% +11 pts lunette -18 pts fatigue = 60%', before)
        event = resolve(state, 6_000)
        transition = apply_replay_event(state, event)
        outcome = next(o for o in transition.outcomes if o.kind is OutcomeKind.FLIGHT_SURVIVED)
        self.assertEqual(outcome.effective_accuracy_bps, 6_000)
        self.assertEqual(next(e for e in transition.state.effects if e.item_id == 7).remaining_uses, 5)

    def test_legacy_shot_remains_a_hit_without_retroactive_penalty(self) -> None:
        state = start_flight(state_for(), 100, lifetime_ns=10_000).state
        old = ReplayEvent.command(200, 'Hunter', SHOT,
                                  shot_attempt=ShotAttempt(base_accuracy_bps=6_700, accuracy_roll=6_000))
        payload = old.to_payload()
        self.assertNotIn('fatigue_penalty_bps', payload['shot_attempt'])
        decoded = ReplayEvent.from_payload(payload)
        self.assertEqual(decoded.to_payload(), payload)
        transition = apply_replay_event(state, decoded)
        self.assertTrue(any(o.kind is OutcomeKind.HIT for o in transition.outcomes))
        self.assertNotIn('[fatigué]', ' '.join(render_outcomes(transition.outcomes)))

    def test_new_shot_round_trip_and_digest_chain_replay(self) -> None:
        initial = state_for()
        spawn = ReplayEvent.start_flight(100, 10_000, kind=FlightKind.GOLDEN, health=4)
        state = apply_replay_event(initial, spawn).state
        event = resolve(state, 5_000)
        payload = event.to_payload()
        self.assertEqual(payload['shot_attempt']['fatigue_penalty_bps'], 1_800)
        self.assertEqual(ReplayEvent.from_payload(payload), event)
        with tempfile.TemporaryDirectory() as directory:
            journal = JournalFile(Path(directory)/'events.jsonl')
            journal.append(spawn)
            journal.append(event)
            before = journal.path.read_bytes()
            replayed = replay_records(journal.read_records(), initial_state=initial)
            self.assertEqual(replayed.state, apply_replay_event(state, event).state)
            self.assertEqual(journal.path.read_bytes(), before)

    def test_invalid_penalties_are_rejected(self) -> None:
        for value in (True, -1, 10_001, 1.5):
            with self.subTest(value=value):
                payload = ReplayEvent.command(200, 'Hunter', SHOT, shot_attempt=ShotAttempt()).to_payload()
                payload['shot_attempt']['fatigue_penalty_bps'] = value
                with self.assertRaises(CodecError):
                    ReplayEvent.from_payload(payload)

    def test_endurance_suppresses_penalty_until_exact_expiration(self) -> None:
        endurance = ActiveEffect(1, 102, 'endurance_amulet', EffectScope.PLAYER,
                                  'hunter', None, 0, expires_at_ns=300)
        state = start_flight(state_for(effects=(endurance,)), 100, lifetime_ns=10_000,
                             kind=FlightKind.GOLDEN, health=4).state
        self.assertEqual(resolve(state, 6_000).shot_attempt.fatigue_penalty_bps, 0)
        self.assertNotIn('[fatigué]', render_profile(state, 'Hunter')[0])
        self.assertEqual(resolve(state, 6_000, now_ns=300).shot_attempt.fatigue_penalty_bps, 1_800)

    def test_espresso_relief_restores_accuracy_immediately(self) -> None:
        before = state_for()
        after = purchase(before, 'Hunter', 24, 10, fatigue_relief_centi=500).state
        self.assertEqual(after.players[0].fatigue_centi, 1_300)
        self.assertIn('67% -3 pts fatigue = 64%', render_profile(after, 'Hunter')[0])

    def test_tag_uses_fatigue_before_the_shot_not_the_new_gain(self) -> None:
        state = start_flight(state_for(1_200), 100, lifetime_ns=10_000,
                             kind=FlightKind.GOLDEN, health=4).state
        transition = apply_replay_event(state, resolve(state, 6_000))
        self.assertEqual(transition.state.players[0].fatigue_centi, 1_300)
        self.assertNotIn('[fatigué]', ' '.join(render_outcomes(transition.outcomes)))
        self.assertIn('[fatigué]', render_profile(transition.state, 'Hunter')[0])

    def test_jam_has_no_fatigue_tag_or_additional_fatigue(self) -> None:
        state = start_flight(state_for(), 100, lifetime_ns=10_000).state
        event = ReplayEvent.command(200, 'Hunter', SHOT, shot_attempt=ShotAttempt(
            base_jam_bps=10_000, fatigue_penalty_bps=1_800))
        transition = apply_replay_event(state, event)
        self.assertEqual(transition.state.players[0].fatigue_centi, 1_800)
        self.assertNotIn('[fatigué]', ' '.join(render_outcomes(transition.outcomes)))

    def test_successful_kill_reports_the_settled_fatigue_status(self) -> None:
        state = start_flight(state_for(), 100, lifetime_ns=10_000).state
        event = ReplayEvent.command(200, 'Hunter', SHOT, shot_attempt=ShotAttempt(
            base_accuracy_bps=6_700, accuracy_roll=4_900, fatigue_penalty_bps=1_800))
        transition = apply_replay_event(state, event)
        self.assertTrue(any(o.kind is OutcomeKind.HIT for o in transition.outcomes))
        self.assertIn('[fatigué]', ' '.join(render_outcomes(transition.outcomes)))

    def test_shop_wait_of_four_minutes_seven_seconds_matches_an_earlier_request(self) -> None:
        # Relative to a prior catalog request at 17:37:07, the next requests
        # are 17:41:00, 17:42:00 and 17:43:00. No live history is assumed.
        state = apply_runtime_command(state_for(), 'Hunter', Command(CommandKind.SHOP, 'shop'), 0).state
        for seconds in (233, 293):
            state = apply_runtime_purchase(state, 'Hunter', 21, seconds * SECOND_NS, charged_cost=4).state
        spent = state.players[0].experience_spent
        blocked = apply_runtime_purchase(state, 'Hunter', 7, 353 * SECOND_NS,
                                         charged_cost=5, magnitude=11)
        outcome = blocked.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.COMMAND_THROTTLED)
        self.assertEqual(outcome.defer_until_ns - blocked.state.now_ns, 247 * SECOND_NS)
        self.assertEqual(blocked.state.players[0].experience_spent, spent)
        self.assertFalse(any(e.item_id == 7 for e in blocked.state.effects))

    def test_profile_inventory_and_notice_remain_clear_and_bounded(self) -> None:
        state = state_for()
        profile = render_profile(state, 'Hunter')
        self.assertIn('67% -18 pts fatigue = 49%', profile[0])
        self.assertIn('[fatigué]', profile[0])
        self.assertIn('[fatigué]', ' '.join(render_inventory(state, 'Hunter')))
        for wire in render_wire_notice('Hunter', profile):
            self.assertTrue(wire.startswith(b'NOTICE Hunter :'))
            self.assertLessEqual(len(wire), 512)

    def test_accuracy_is_clamped_even_with_scope_and_extreme_fatigue(self) -> None:
        state = purchase(state_for(10_000), 'Hunter', 7, 10, magnitude=15).state
        self.assertEqual(shot_accuracy(state, state.players[0], 6_700,
                         settled_fatigue_penalty_bps=10_000).effective_bps, 0)
        self.assertEqual(shot_accuracy(state, state.players[0], 9_900).effective_bps, 10_000)

    def test_reported_net_profitability_and_karma_do_not_depend_on_fatigue(self) -> None:
        hunter = replace(state_for().players[0], hits=47, misses=26, shots_fired=73,
                         incidents_caused=2, empty_shots=5, compulsive_reloads=4,
                         experience_spent=248)
        state = GameState(players=(hunter,))
        self.assertIn('484 xp', render_profile(state, 'Hunter')[0])
        self.assertIn('rentab.: 10.30 xp/canard', render_profile(state, 'Hunter')[0])
        rested = replace(hunter, fatigue_centi=0)
        self.assertEqual(player_base_karma_basis_points(hunter), 8_386)
        self.assertEqual(player_karma_basis_points(hunter), player_karma_basis_points(rested))
