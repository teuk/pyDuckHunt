from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyduckhunt.game.admin import apply_admin_channel_item, PlayerAdministrationError
from pyduckhunt.game.bread import active_channel_breads
from pyduckhunt.game.catalog import HOUR_NS
from pyduckhunt.game.engine import advance_time, start_flight
from pyduckhunt.game.model import DailySchedule, FlightKind, GameState, OutcomeKind, PlayerState
from pyduckhunt.game.runtime import enable_hourly_bread, install_daily_schedule, replan_bread_schedule
from pyduckhunt.game.shop import purchase
from pyduckhunt.partyline.runtime import PartylineController
from pyduckhunt.persistence.codec import canonical_json_bytes, encode_game_state, decode_game_state, CodecError
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.journal import GENESIS_DIGEST, JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, recover, replay_records
from pyduckhunt.persistence.snapshot import Snapshot, SnapshotStore
from pyduckhunt.rendering.responses import render_outcomes, render_inventory
from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator, DispatchStatus
from pyduckhunt.runtime.scheduling import CalibratedScheduleSource, RuntimeSchedulingAdapter

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
DAY = 24 * HOUR_NS


def funded(*, modern=True):
    state = GameState(players=(PlayerState('hunter', 'Hunter', experience=300, level=30),))
    return enable_hourly_bread(state, 0).state if modern else state


def plan(state, now):
    controller = SimpleNamespace(runtime=SimpleNamespace(state=state),
        _network_status=lambda: ('Coin', 'ready', True, ('#marsh',)))
    return '\n'.join(PartylineController._duckplanning_lines(controller, now))


class BreadRuleTests(unittest.TestCase):
    def test_bread_is_not_consumed_and_delays_each_new_flight(self):
        bought = purchase(funded(), 'Hunter', 21, SECOND)
        two = purchase(bought.state, 'Hunter', 21, 2 * SECOND)
        started = start_flight(two.state, 3 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(len(started.state.effects), 2)
        self.assertEqual(started.state.flight.expires_at_ns, 343 * SECOND)
        self.assertNotIn(OutcomeKind.EFFECT_CONSUMED, [o.kind for o in started.outcomes])
        again = start_flight(started.state, 344 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(len(again.state.effects), 2)
        self.assertEqual(again.state.flight.expires_at_ns, 684 * SECOND)
        self.assertNotIn('mange un morceau', ' '.join(render_outcomes(started.outcomes)))

    def test_each_piece_expires_independently_and_boundary_has_no_bonus(self):
        a = purchase(funded(), 'Hunter', 21, SECOND)
        b = purchase(a.state, 'Hunter', 21, 2 * SECOND)
        started = start_flight(b.state, HOUR_NS + SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual([e.effect_id for e in started.state.effects], [2])
        self.assertEqual(started.state.flight.expires_at_ns, HOUR_NS + 321 * SECOND)
        expired_bread = advance_time(started.state, HOUR_NS + 2 * SECOND)
        self.assertEqual(expired_bread.state.effects, ())
        self.assertEqual(expired_bread.state.flight, started.state.flight)

    def test_bread_added_during_flight_only_affects_later_flights(self):
        started = start_flight(funded(), SECOND, lifetime_ns=300 * SECOND)
        bought = purchase(started.state, 'Hunter', 21, 2 * SECOND)
        self.assertEqual(bought.state.flight.expires_at_ns, 301 * SECOND)
        refused = start_flight(bought.state, 3 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(len(refused.state.effects), 1)
        self.assertEqual(refused.outcomes[-1].kind, OutcomeKind.FLIGHT_ALREADY_ACTIVE)

    def test_all_flight_kinds_share_delay_and_owner_bread(self):
        for kind in FlightKind:
            with self.subTest(kind=kind):
                state = apply_admin_channel_item(funded(), 'Owner', 21, SECOND).state
                result = start_flight(state, 2 * SECOND, lifetime_ns=300 * SECOND,
                                      kind=kind, health=3 if kind is FlightKind.GOLDEN else 1)
                self.assertEqual(result.state.flight.expires_at_ns, 322 * SECOND)
                self.assertEqual(len(result.state.effects), 1)

    def test_reference_stack_limit_preserves_xp_and_owner_refusal(self):
        state = funded()
        for i in range(20):
            state = apply_admin_channel_item(state, 'Owner', 21, i + 1).state
        before = state.player('hunter').experience
        denied = purchase(state, 'Hunter', 21, 21)
        self.assertEqual(denied.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        self.assertEqual(denied.state.player('hunter').experience, before)
        with self.assertRaises(PlayerAdministrationError):
            apply_admin_channel_item(state, 'Owner', 21, 21)

    def test_legacy_flights_still_consume_one_and_keep_original_lifetime(self):
        state = purchase(funded(modern=False), 'Hunter', 21, SECOND).state
        result = start_flight(state, 2 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(result.state.flight.expires_at_ns, 302 * SECOND)
        self.assertEqual(result.state.effects, ())
        self.assertIn(OutcomeKind.EFFECT_CONSUMED, [o.kind for o in result.outcomes])
        self.assertNotIn('bread_plan_effect_ids', encode_game_state(result.state))

    def test_player_notice_explains_real_effect_without_flight_deadline(self):
        bought = purchase(funded(), 'Hunter', 21, SECOND)
        text = ' '.join(render_outcomes(bought.outcomes, channel='#marsh'))
        self.assertIn('4 points', text)
        self.assertIn('Pendant 1h', text)
        self.assertIn('20s par morceau', text)
        self.assertIn('reste en place', text)
        self.assertNotIn('prochain envol', text)
        inventory = ' '.join(render_inventory(bought.state, 'Hunter'))
        self.assertIn('+20s aux nouveaux vols', inventory)
        self.assertIn('première expiration', inventory)
        private = plan(bought.state, SECOND)
        self.assertIn('pain conservé', private)
        self.assertNotIn('consommé', private)

    def test_calls_survive_time_advance_and_launch_one_at_a_time(self):
        state = purchase(funded(), 'Hunter', 20, SECOND, scheduled_for_ns=3 * SECOND).state
        state = purchase(state, 'Hunter', 20, 2 * SECOND, scheduled_for_ns=4 * SECOND).state
        advanced = advance_time(state, 5 * SECOND)
        self.assertEqual(len(advanced.state.scheduled_actions), 2)
        first = start_flight(advanced.state, 5 * SECOND, lifetime_ns=100 * SECOND)
        self.assertEqual(len(first.state.scheduled_actions), 1)
        self.assertEqual([o.action_id for o in first.outcomes if o.kind is OutcomeKind.CHANNEL_ACTION_DUE], [1])
        second = start_flight(first.state, 105 * SECOND, lifetime_ns=100 * SECOND)
        self.assertEqual(second.state.scheduled_actions, ())
        self.assertEqual([o.action_id for o in second.outcomes if o.kind is OutcomeKind.CHANNEL_ACTION_DUE], [2])

    def test_new_state_round_trip_and_legacy_checkpoint_are_preserved(self):
        state = purchase(funded(), 'Hunter', 21, SECOND).state
        state = replace(state, bread_plan_effect_ids=(1,))
        self.assertEqual(decode_game_state(encode_game_state(state)), state)
        payload = encode_game_state(state)
        for bad in (None, [True], [0], [2, 1], [1, 1]):
            with self.subTest(bad=bad), self.assertRaises(CodecError):
                decode_game_state({**payload, 'bread_plan_effect_ids': bad})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);store = SnapshotStore(root/'snapshot.json')
            original = funded(modern=False)
            store.write(Snapshot(0, GENESIS_DIGEST, original))
            raw = json.loads(store.path.read_text());raw['schema'] = 21
            raw.pop('checksum');raw['checksum'] = hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
            store.path.write_bytes(canonical_json_bytes(raw) + b'\n')
            self.assertEqual(recover(store, JournalFile(root/'events.jsonl')).state, original)


class BreadSchedulingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name);self.journal = JournalFile(self.root/'events.jsonl')
        self.store = SnapshotStore(self.root/'snapshot.json')
        self.store.write(Snapshot(0, GENESIS_DIGEST, funded(modern=False)))
        self.wires = []
        self.runtime, _ = RuntimeOrchestrator.open(self.journal, self.store, self.wires.append, snapshot_interval=None)
        self.addCleanup(self.runtime.close, 2)
        self.draws = []
        def draw(a, b): self.draws.append((a,b));return a
        self.source = CalibratedScheduleSource(draw)
        self.adapter = RuntimeSchedulingAdapter(self.runtime, ('#marsh',), self.source)
        self.adapter.step(0)

    def buy(self, at=SECOND, item=21, due=None):
        return self.runtime.dispatch(ReplayEvent.purchase(at, 'Hunter', item, 4 if item == 21 else 8, scheduled_for_ns=due), lambda t: ())

    def test_purchase_replans_25_preserves_next_and_expiry_returns_to_24(self):
        next_before = self.runtime.state.daily_schedule.deadlines_ns[0]
        self.buy();before_xp = self.runtime.state.player('hunter').experience
        result = self.adapter.step(SECOND)
        self.assertTrue(result.plan_replanned)
        schedule = self.runtime.state.daily_schedule
        self.assertEqual(len(schedule.deadlines_ns), 25)
        self.assertIn(next_before, schedule.deadlines_ns)
        self.assertEqual(len(set(schedule.deadlines_ns)), 25)
        self.assertNotIn(0, schedule.deadlines_ns)
        self.assertEqual(self.runtime.state.player('hunter').experience, before_xp)
        self.assertTrue(all(not batch for batch in self.wires))
        self.adapter.step(HOUR_NS + SECOND)  # settle any elapsed daily slot first
        self.adapter.step(HOUR_NS + SECOND)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 24)
        self.assertEqual(self.runtime.state.effects, ())
        self.assertEqual(self.runtime.state.bread_plan_effect_ids, ())

    def test_two_pieces_change_26_to_25_and_keep_next_on_partial_expiry(self):
        self.buy();self.adapter.step(SECOND)
        self.buy(2 * SECOND);self.adapter.step(2 * SECOND)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 26)
        before = self.runtime.state.daily_schedule
        next_time = next(d for d in before.deadlines_ns if d > HOUR_NS + SECOND)
        self.adapter.step(HOUR_NS + SECOND);self.adapter.step(HOUR_NS + SECOND)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 25)
        self.assertIn(next_time, self.runtime.state.daily_schedule.deadlines_ns)

    def test_source_44_slots_has_bounded_draws_and_unique_times(self):
        state = self.runtime.state
        for i in range(20):state = apply_admin_channel_item(state, 'Owner', 21, i+1).state
        before = len(self.draws);deadlines = self.source.bread_schedule(state, SECOND)
        self.assertEqual(len(deadlines), 44)
        self.assertEqual(len(set(deadlines)), 44)
        self.assertLess(len(self.draws)-before, 150)

    def test_replan_event_round_trip_validates_count_and_next_slot(self):
        self.buy()
        state = self.runtime.state;deadlines = self.source.bread_schedule(state, SECOND)
        event = ReplayEvent.replan_bread_schedule(SECOND, 0, deadlines)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        with self.assertRaises(ValueError): replan_bread_schedule(state, SECOND, 0, deadlines[:-1])
        keep = state.daily_schedule.deadlines_ns[0]
        altered = tuple(sorted((set(deadlines) - {keep}) | {DAY-MINUTE}))
        with self.assertRaises(ValueError): replan_bread_schedule(state, SECOND, 0, altered)

    def test_backpressure_keeps_bread_and_plan_then_retries(self):
        self.buy();state = self.runtime.state
        with patch.object(self.runtime.persistence, 'reserve', return_value=None):
            result = self.adapter.step(SECOND)
        self.assertEqual(result.dispatches[-1].status, DispatchStatus.BACKPRESSURED)
        self.assertEqual(self.runtime.state, state)
        result = self.adapter.step(SECOND)
        self.assertTrue(result.plan_replanned)

    def test_restart_recovers_same_plan_without_redrawing(self):
        self.buy();self.adapter.step(SECOND);expected = self.runtime.state
        self.runtime.persistence.flush(2)
        recovered = recover(self.store, self.journal)
        self.assertEqual(recovered.state, expected)
        new_source = CalibratedScheduleSource(lambda a,b: (_ for _ in ()).throw(AssertionError('redraw')))
        adapter = RuntimeSchedulingAdapter(self.runtime, ('#marsh',), new_source)
        adapter.step(2*SECOND)
        self.assertEqual(self.runtime.state.daily_schedule, expected.daily_schedule)

    def test_day_rollover_with_bread_is_25_then_expires(self):
        self.adapter.step(DAY-10*SECOND)
        self.buy(DAY-9*SECOND);self.adapter.step(DAY-9*SECOND)
        self.adapter.step(DAY)
        self.assertEqual(self.runtime.state.daily_schedule.day_start_ns, DAY)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 25)
        self.assertEqual(self.runtime.state.bread_plan_effect_ids, (1,))

    def test_bread_expiry_does_not_lose_a_paid_call_blocked_by_flight(self):
        self.buy();self.adapter.step(SECOND)
        self.buy(2*SECOND,20,3*SECOND)
        self.runtime.dispatch(ReplayEvent.start_flight(2*SECOND, 2*HOUR_NS), lambda t: ())
        self.adapter.step(HOUR_NS+SECOND);self.adapter.step(HOUR_NS+SECOND)
        self.assertEqual(len(self.runtime.state.scheduled_actions), 1)
        end = self.runtime.state.flight.expires_at_ns
        self.adapter.step(end)
        self.assertEqual(self.runtime.state.scheduled_actions, ())
        self.assertIsNotNone(self.runtime.state.flight)
        self.assertEqual(self.runtime.state.flight.spawned_at_ns, end)


if __name__ == '__main__':
    unittest.main()
