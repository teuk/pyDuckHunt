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
from pyduckhunt.game.bread import active_channel_breads, bread_attraction_deadline
from pyduckhunt.game.catalog import HOUR_NS
from pyduckhunt.game.engine import advance_time, start_flight
from pyduckhunt.game.model import DailySchedule, FlightKind, GameState, OutcomeKind, PlayerState
from pyduckhunt.game.runtime import migrate_bread_policy
from pyduckhunt.game.shop import purchase
from pyduckhunt.partyline.runtime import PartylineController
from pyduckhunt.persistence.codec import canonical_json_bytes, encode_game_state, decode_game_state, CodecError
from pyduckhunt.persistence.event import EventKind, ReplayEvent
from pyduckhunt.persistence.journal import GENESIS_DIGEST, JournalFile
from pyduckhunt.persistence.replay import apply_replay_event, recover
from pyduckhunt.persistence.snapshot import Snapshot, SnapshotStore
from pyduckhunt.rendering.responses import render_outcomes, render_inventory
from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator, DispatchStatus
from pyduckhunt.runtime.scheduling import CalibratedScheduleSource, RuntimeSchedulingAdapter

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
DAY = 24 * HOUR_NS


def funded(*, legacy: bool = False) -> GameState:
    return GameState(
        players=(PlayerState('hunter', 'Hunter', experience=300, level=30),),
        bread_policy_version=1 if legacy else 2,
        bread_plan_effect_ids=() if legacy else None,
    )


def plan(state: GameState, now: int) -> str:
    controller = SimpleNamespace(
        runtime=SimpleNamespace(state=state),
        _network_status=lambda: ('Coin', 'ready', True, ('#marsh',)),
    )
    return '\n'.join(PartylineController._duckplanning_lines(controller, now))


class BreadRuleTests(unittest.TestCase):
    def test_two_breads_are_consumed_by_two_flights_and_each_add_twenty_seconds(self):
        first = purchase(funded(), 'Hunter', 21, SECOND, scheduled_for_ns=10 * MINUTE)
        second = purchase(first.state, 'Hunter', 21, 2 * SECOND, scheduled_for_ns=20 * MINUTE)

        started = start_flight(second.state, 3 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual([effect.effect_id for effect in started.state.effects], [2])
        self.assertEqual(started.state.flight.expires_at_ns, 323 * SECOND)
        self.assertEqual(
            [outcome.effect_id for outcome in started.outcomes if outcome.kind is OutcomeKind.EFFECT_CONSUMED],
            [1],
        )
        flight_outcome = next(
            outcome for outcome in started.outcomes
            if outcome.kind is OutcomeKind.FLIGHT_STARTED
        )
        self.assertEqual(flight_outcome.channel_effect_count, 1)
        self.assertEqual(flight_outcome.effect_magnitude, 20)

        again = start_flight(started.state, 324 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(again.state.effects, ())
        self.assertEqual(again.state.flight.expires_at_ns, 644 * SECOND)
        self.assertEqual(
            [outcome.effect_id for outcome in again.outcomes if outcome.kind is OutcomeKind.EFFECT_CONSUMED],
            [2],
        )
        self.assertIn('mange un morceau', ' '.join(render_outcomes(started.outcomes)))

    def test_expired_piece_is_not_consumed_and_boundary_has_no_bonus(self):
        first = purchase(funded(), 'Hunter', 21, SECOND, scheduled_for_ns=100 * SECOND)
        second = purchase(first.state, 'Hunter', 21, 2 * SECOND, scheduled_for_ns=200 * SECOND)
        started = start_flight(second.state, HOUR_NS + SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(started.state.effects, ())
        self.assertEqual(started.state.flight.expires_at_ns, HOUR_NS + 321 * SECOND)
        self.assertEqual(
            [outcome.effect_id for outcome in started.outcomes if outcome.kind is OutcomeKind.EFFECT_CONSUMED],
            [2],
        )
        self.assertEqual(
            [outcome.effect_id for outcome in started.outcomes if outcome.kind is OutcomeKind.EFFECT_EXPIRED],
            [1],
        )

    def test_bread_added_during_flight_only_affects_later_flights(self):
        started = start_flight(funded(), SECOND, lifetime_ns=300 * SECOND)
        bought = purchase(started.state, 'Hunter', 21, 2 * SECOND, scheduled_for_ns=10 * MINUTE)
        self.assertEqual(bought.state.flight.expires_at_ns, 301 * SECOND)
        refused = start_flight(bought.state, 3 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(len(refused.state.effects), 1)
        self.assertEqual(refused.outcomes[-1].kind, OutcomeKind.FLIGHT_ALREADY_ACTIVE)

    def test_all_flight_kinds_consume_owner_bread_and_share_delay(self):
        for kind in FlightKind:
            with self.subTest(kind=kind):
                state = apply_admin_channel_item(
                    funded(), 'Owner', 21, SECOND, scheduled_for_ns=10 * MINUTE,
                ).state
                result = start_flight(
                    state,
                    2 * SECOND,
                    lifetime_ns=300 * SECOND,
                    kind=kind,
                    health=3 if kind is FlightKind.GOLDEN else 1,
                )
                self.assertEqual(result.state.flight.expires_at_ns, 322 * SECOND)
                self.assertEqual(result.state.effects, ())

    def test_stack_limit_preserves_xp_and_owner_refusal(self):
        state = funded()
        for index in range(20):
            state = apply_admin_channel_item(
                state,
                'Owner',
                21,
                index + 1,
                scheduled_for_ns=10 * MINUTE + index,
            ).state
        before = state.player('hunter').experience
        denied = purchase(state, 'Hunter', 21, 21, scheduled_for_ns=11 * MINUTE)
        self.assertEqual(denied.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        self.assertEqual(denied.state.player('hunter').experience, before)
        with self.assertRaises(PlayerAdministrationError):
            apply_admin_channel_item(
                state,
                'Owner',
                21,
                21,
                scheduled_for_ns=11 * MINUTE,
            )

    def test_legacy_hourly_state_keeps_reference_additive_behaviour_until_migration(self):
        first = purchase(funded(legacy=True), 'Hunter', 21, SECOND)
        second = purchase(first.state, 'Hunter', 21, 2 * SECOND)
        result = start_flight(second.state, 3 * SECOND, lifetime_ns=300 * SECOND)
        self.assertEqual(result.state.flight.expires_at_ns, 343 * SECOND)
        self.assertEqual(len(result.state.effects), 2)
        self.assertNotIn(OutcomeKind.EFFECT_CONSUMED, [outcome.kind for outcome in result.outcomes])
        flight_outcome = next(
            outcome for outcome in result.outcomes
            if outcome.kind is OutcomeKind.FLIGHT_STARTED
        )
        self.assertEqual(flight_outcome.channel_effect_count, 2)
        self.assertEqual(flight_outcome.effect_magnitude, 40)

    def test_player_notice_inventory_and_planning_explain_the_same_rule(self):
        bought = purchase(
            funded(), 'Hunter', 21, SECOND, scheduled_for_ns=10 * MINUTE,
        )
        text = ' '.join(render_outcomes(bought.outcomes, channel='#marsh'))
        self.assertIn('4 points', text)
        self.assertIn('Pendant 1h au maximum', text)
        self.assertIn('il attire un canard', text)
        self.assertIn('premier envol consomme un morceau', text)
        inventory = ' '.join(render_inventory(bought.state, 'Hunter'))
        self.assertIn('un morceau par envol, +20s pour ce canard', inventory)
        self.assertIn('première expiration', inventory)
        private = plan(bought.state, SECOND)
        self.assertIn('le prochain envol consomme un morceau', private)
        self.assertIn('Attractions des pains:', private)
        self.assertNotIn('pain conservé', private)

    def test_calls_survive_time_advance_and_launch_one_at_a_time(self):
        state = purchase(
            funded(), 'Hunter', 20, SECOND, scheduled_for_ns=3 * SECOND,
        ).state
        state = purchase(
            state, 'Hunter', 20, 2 * SECOND, scheduled_for_ns=4 * SECOND,
        ).state
        advanced = advance_time(state, 5 * SECOND)
        self.assertEqual(len(advanced.state.scheduled_actions), 2)
        first = start_flight(advanced.state, 5 * SECOND, lifetime_ns=100 * SECOND)
        self.assertEqual(len(first.state.scheduled_actions), 1)
        self.assertEqual(
            [outcome.action_id for outcome in first.outcomes if outcome.kind is OutcomeKind.CHANNEL_ACTION_DUE],
            [1],
        )
        second = start_flight(first.state, 105 * SECOND, lifetime_ns=100 * SECOND)
        self.assertEqual(second.state.scheduled_actions, ())
        self.assertEqual(
            [outcome.action_id for outcome in second.outcomes if outcome.kind is OutcomeKind.CHANNEL_ACTION_DUE],
            [2],
        )

    def test_new_state_round_trip_and_schema_23_checkpoint_migrates_as_legacy(self):
        state = purchase(
            funded(), 'Hunter', 21, SECOND, scheduled_for_ns=10 * MINUTE,
        ).state
        self.assertEqual(decode_game_state(encode_game_state(state)), state)
        payload = encode_game_state(state)
        for bad in (None, 0, 3, True, '2'):
            with self.subTest(bad=bad), self.assertRaises(CodecError):
                decode_game_state({**payload, 'bread_policy_version': bad})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = SnapshotStore(root / 'snapshot.json')
            original = funded(legacy=True)
            store.write(Snapshot(0, GENESIS_DIGEST, original))
            raw = json.loads(store.path.read_text())
            raw['schema'] = 23
            raw['state'].pop('bread_policy_version')
            raw.pop('checksum')
            raw['checksum'] = hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
            store.path.write_bytes(canonical_json_bytes(raw) + b'\n')
            recovered = recover(store, JournalFile(root / 'events.jsonl')).state
            self.assertEqual(recovered.bread_policy_version, 1)
            self.assertEqual(recovered, original)

    def test_migration_keeps_bread_but_normalizes_expanded_daily_plan(self):
        first = purchase(funded(legacy=True), 'Hunter', 21, SECOND)
        second = purchase(first.state, 'Hunter', 21, 2 * SECOND)
        legacy = replace(
            second.state,
            bread_plan_effect_ids=(1, 2),
            daily_schedule=DailySchedule(
                0,
                tuple(index * MINUTE for index in range(1, 27)),
                5,
            ),
        )
        migrated = migrate_bread_policy(legacy, 10 * SECOND)
        self.assertEqual(migrated.state.bread_policy_version, 2)
        self.assertEqual(migrated.state.bread_plan_effect_ids, ())
        self.assertEqual(len(migrated.state.daily_schedule.deadlines_ns), 24)
        self.assertEqual(migrated.state.daily_schedule.next_index, 5)
        deadlines = tuple(
            bread_attraction_deadline(effect)
            for effect in active_channel_breads(migrated.state, 10 * SECOND)
        )
        self.assertEqual(len(deadlines), 2)
        self.assertTrue(all(10 * SECOND < value < HOUR_NS + SECOND for value in deadlines))
        event = ReplayEvent.migrate_bread_policy(10 * SECOND)
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        self.assertEqual(apply_replay_event(legacy, event), migrated)


class BreadSchedulingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journal = JournalFile(self.root / 'events.jsonl')
        self.store = SnapshotStore(self.root / 'snapshot.json')
        self.store.write(Snapshot(0, GENESIS_DIGEST, funded()))
        self.wires = []
        self.runtime, _ = RuntimeOrchestrator.open(
            self.journal,
            self.store,
            self.wires.append,
            snapshot_interval=None,
        )
        self.addCleanup(self.runtime.close, 2)
        self.draws = []

        def draw(minimum, maximum):
            self.draws.append((minimum, maximum))
            return minimum

        self.source = CalibratedScheduleSource(draw)
        self.adapter = RuntimeSchedulingAdapter(self.runtime, ('#marsh',), self.source)
        self.adapter.step(0)

    def buy(self, at=SECOND, item=21, due=None):
        if item == 21 and due is None:
            due = at + 10 * MINUTE
        return self.runtime.dispatch(
            ReplayEvent.purchase(
                at,
                'Hunter',
                item,
                4 if item == 21 else 8,
                scheduled_for_ns=due,
            ),
            lambda transition: (),
        )

    def test_purchase_keeps_exactly_twenty_four_daily_slots(self):
        schedule_before = self.runtime.state.daily_schedule
        self.buy()
        result = self.adapter.step(SECOND)
        self.assertFalse(result.plan_replanned)
        self.assertEqual(self.runtime.state.daily_schedule, schedule_before)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 24)
        self.assertEqual(len(active_channel_breads(self.runtime.state, SECOND)), 1)

    def test_bread_attraction_launches_and_consumes_one_piece(self):
        self.buy(due=5 * SECOND)
        result = self.adapter.step(5 * SECOND)
        self.assertTrue(result.dispatches)
        self.assertIsNotNone(self.runtime.state.flight)
        self.assertEqual(self.runtime.state.flight.expires_at_ns, 325 * SECOND)
        self.assertEqual(active_channel_breads(self.runtime.state, 5 * SECOND), ())

    def test_two_breads_and_two_attractions_leave_no_bread(self):
        self.buy(SECOND, due=5 * SECOND)
        self.buy(2 * SECOND, due=6 * SECOND)
        self.adapter.step(5 * SECOND)
        self.assertEqual(len(active_channel_breads(self.runtime.state, 5 * SECOND)), 1)
        first_expiry = self.runtime.state.flight.expires_at_ns
        self.adapter.step(first_expiry)
        self.assertIsNotNone(self.runtime.state.flight)
        self.assertEqual(self.runtime.state.flight.spawned_at_ns, first_expiry)
        self.assertEqual(active_channel_breads(self.runtime.state, first_expiry), ())

    def test_earlier_daily_flight_consumes_bread_and_cancels_its_attraction(self):
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        first_daily = schedule.deadlines_ns[0]
        self.buy(due=10 * MINUTE)
        self.adapter.step(first_daily)
        self.assertEqual(active_channel_breads(self.runtime.state, first_daily), ())
        self.assertEqual(self.runtime.state.effects, ())

    def test_attraction_backpressure_keeps_bread_then_retries(self):
        self.buy(due=5 * SECOND)
        state = self.runtime.state
        with patch.object(self.runtime.persistence, 'reserve', return_value=None):
            result = self.adapter.step(5 * SECOND)
        self.assertEqual(result.dispatches[-1].status, DispatchStatus.BACKPRESSURED)
        self.assertEqual(self.runtime.state, state)
        result = self.adapter.step(5 * SECOND)
        self.assertEqual(result.dispatches[-1].status, DispatchStatus.ACCEPTED)
        self.assertEqual(active_channel_breads(self.runtime.state, 5 * SECOND), ())

    def test_expired_backpressured_attraction_cannot_leave_a_past_wake_up(self):
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        self.runtime._state = replace(
            self.runtime.state,
            daily_schedule=replace(schedule, next_index=24),
        )
        self.buy(due=5 * SECOND)
        with patch.object(self.runtime.persistence, 'reserve', return_value=None):
            blocked = self.adapter.step(5 * SECOND)
        self.assertEqual(blocked.dispatches[-1].status, DispatchStatus.BACKPRESSURED)
        after_expiry = self.adapter.step(HOUR_NS + 2 * SECOND)
        self.assertEqual(after_expiry.next_deadline_ns, DAY)
        self.assertGreater(after_expiry.next_deadline_ns, HOUR_NS + 2 * SECOND)

    def test_restart_recovers_attraction_without_redrawing(self):
        self.buy(due=10 * MINUTE)
        expected = self.runtime.state
        self.runtime.persistence.flush(2)
        recovered = recover(self.store, self.journal)
        self.assertEqual(recovered.state, expected)
        self.assertEqual(
            bread_attraction_deadline(active_channel_breads(recovered.state, SECOND)[0]),
            10 * MINUTE,
        )

    def test_day_rollover_stays_at_twenty_four_with_active_bread(self):
        self.adapter.step(DAY - 10 * SECOND)
        self.buy(DAY - 9 * SECOND, due=DAY + 5 * SECOND)
        self.adapter.step(DAY)
        self.assertEqual(self.runtime.state.daily_schedule.day_start_ns, DAY)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 24)
        self.assertEqual(len(active_channel_breads(self.runtime.state, DAY)), 1)

    def test_legacy_state_is_migrated_once_before_scheduling(self):
        self.runtime.close(2)
        legacy_journal = JournalFile(self.root / 'legacy-events.jsonl')
        legacy_store = SnapshotStore(self.root / 'legacy-snapshot.json')
        legacy = purchase(funded(legacy=True), 'Hunter', 21, SECOND).state
        legacy = replace(
            legacy,
            daily_schedule=DailySchedule(
                0,
                tuple(index * MINUTE for index in range(1, 26)),
                0,
            ),
            bread_plan_effect_ids=(1,),
        )
        legacy_store.write(Snapshot(0, GENESIS_DIGEST, legacy))
        self.runtime, _ = RuntimeOrchestrator.open(
            legacy_journal,
            legacy_store,
            self.wires.append,
            snapshot_interval=None,
        )
        self.addCleanup(self.runtime.close, 2)
        adapter = RuntimeSchedulingAdapter(self.runtime, ('#marsh',), self.source)
        result = adapter.step(2 * SECOND)
        self.assertEqual(self.runtime.state.bread_policy_version, 2)
        self.assertEqual(len(self.runtime.state.daily_schedule.deadlines_ns), 24)
        self.assertEqual(result.dispatches[0].status, DispatchStatus.ACCEPTED)
        self.runtime.persistence.flush(2)
        self.assertEqual(
            legacy_journal.read_records()[-1].event.kind,
            EventKind.MIGRATE_BREAD_POLICY,
        )


if __name__ == '__main__':
    unittest.main()
