from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
import unittest

from pyduckhunt.game.engine import advance_time, start_flight
from pyduckhunt.game.model import DailySchedule, GameState, OutcomeKind, PlayerState, ScheduledAction
from pyduckhunt.game.shop import purchase
from pyduckhunt.partyline.runtime import PartylineController
from pyduckhunt.rendering.responses import render_inventory


def at(clock: str) -> int:
    return int(datetime.fromisoformat('2026-09-09T' + clock + '+02:00').timestamp()) * 1_000_000_000


def planning(state: GameState, now: int) -> str:
    controller = SimpleNamespace(
        runtime=SimpleNamespace(state=state),
        _network_status=lambda: ('Coin', 'ready', True, ('#marsh',)),
    )
    return '\n'.join(PartylineController._duckplanning_lines(controller, now))


def remaining_bread() -> GameState:
    state = GameState(
        players=(PlayerState('hunter', 'Hunter', level=30, experience=300),),
    )
    first = purchase(
        state,
        'Hunter',
        21,
        at('10:43:20'),
        scheduled_for_ns=at('11:20:00'),
    )
    second = purchase(
        first.state,
        'Hunter',
        21,
        at('10:43:22'),
        scheduled_for_ns=at('11:43:21'),
    )
    started = start_flight(
        second.state,
        at('11:06:00'),
        lifetime_ns=300_000_000_000,
    )
    return replace(
        advance_time(started.state, at('11:42:00')).state,
        daily_schedule=DailySchedule(
            day_start_ns=at('02:00:00'),
            deadlines_ns=(at('11:06:00'), at('12:18:00')),
            next_index=1,
        ),
    )


class BreadVisibilityTests(unittest.TestCase):
    def test_one_consumed_piece_leaves_one_attraction_until_normal_expiry(self):
        state = remaining_bread()
        self.assertEqual([effect.effect_id for effect in state.effects], [2])
        self.assertEqual(state.effects[0].expires_at_ns, at('11:43:22'))
        before = planning(state, at('11:43:20'))
        self.assertIn('Pains=1', before)
        self.assertIn('Attractions des pains: 09/09 11:43:21 CEST', before)
        self.assertIn('Expiration des pains: 09/09 11:43:22 CEST', before)
        after = planning(state, at('11:43:22'))
        self.assertIn('Pains=0', after)
        self.assertIn('aucun pain disponible', after)
        self.assertNotIn('Attractions des pains:', after)
        self.assertNotIn('Expiration des pains:', after)
        self.assertEqual(len(state.effects), 1)  # projections do not rewrite state
        expired = advance_time(state, at('11:43:22'))
        self.assertEqual(expired.state.effects, ())
        self.assertIn(OutcomeKind.EFFECT_EXPIRED, [outcome.kind for outcome in expired.outcomes])
        later = start_flight(expired.state, at('12:18:00'), lifetime_ns=100)
        self.assertNotIn(OutcomeKind.EFFECT_CONSUMED, [outcome.kind for outcome in later.outcomes])

    def test_inventory_shows_relative_expiry_without_daily_schedule(self):
        state = replace(remaining_bread(), now_ns=at('11:43:20'))
        text = ' '.join(render_inventory(state, 'Hunter', channel='#marsh'))
        self.assertIn('1 morceau de pain', text)
        self.assertNotIn('première expiration', text)
        self.assertIn('un morceau par envol', text)
        self.assertNotIn('12:18', text)
        after = ' '.join(render_inventory(advance_time(state, at('11:43:22')).state, 'Hunter'))
        self.assertNotIn('morceau de pain', after)

    def test_earlier_call_is_the_next_event_without_moving_daily_slot(self):
        state = remaining_bread()
        action = ScheduledAction(
            1,
            20,
            'duck_call',
            'hunter',
            at('11:42:00'),
            at('11:43:00'),
        )
        state = replace(state, scheduled_actions=(action,), next_action_id=2)
        text = planning(state, at('11:42:00'))
        self.assertIn('Prochain quotidien=09/09 12:18:00 CEST', text)
        self.assertIn('prochain événement=09/09 11:43:00 CEST', text)
        self.assertIn('Attractions des pains: 09/09 11:43:21 CEST', text)

    def test_bread_attraction_can_precede_the_daily_flight(self):
        state = remaining_bread()
        text = planning(state, at('11:42:00'))
        self.assertIn('Prochain quotidien=09/09 12:18:00 CEST', text)
        self.assertIn('prochain événement=09/09 11:43:21 CEST', text)

    def test_active_flight_defers_calls_and_attractions_to_its_end(self):
        state = start_flight(
            remaining_bread(),
            at('11:42:00'),
            lifetime_ns=300_000_000_000,
        ).state
        # Restore one independent bread to model a piece bought during the active flight.
        state = purchase(
            state,
            'Hunter',
            21,
            at('11:42:01'),
            scheduled_for_ns=at('11:43:21'),
        ).state
        action = ScheduledAction(
            1,
            20,
            'duck_call',
            'hunter',
            at('11:42:01'),
            at('11:43:00'),
        )
        state = replace(state, scheduled_actions=(action,), next_action_id=2)
        text = planning(state, at('11:42:01'))
        self.assertIn('prochain événement=09/09 11:47:20 CEST', text)
        self.assertIn('vol=#2 fin=09/09 11:47:20 CEST', text)

    def test_attraction_remains_visible_after_daily_plan_is_exhausted(self):
        state = remaining_bread()
        state = replace(state, daily_schedule=replace(state.daily_schedule, next_index=2))
        text = planning(state, at('11:42:00'))
        self.assertIn('Prochain quotidien=10/09 02:00:00 CEST', text)
        self.assertIn('prochain événement=09/09 11:43:21 CEST', text)
        self.assertIn('Attractions des pains:', text)


if __name__ == '__main__':
    unittest.main()
