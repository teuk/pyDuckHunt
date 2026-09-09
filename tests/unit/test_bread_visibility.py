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
    return int(datetime.fromisoformat("2026-09-09T" + clock + "+02:00").timestamp()) * 1_000_000_000


def planning(state: GameState, now: int) -> str:
    controller = SimpleNamespace(runtime=SimpleNamespace(state=state),
        _network_status=lambda: ("Coin", "ready", True, ("#marsh",)))
    return "\n".join(PartylineController._duckplanning_lines(controller, now))


def remaining_bread() -> GameState:
    state = GameState(players=(PlayerState("hunter", "Hunter", level=30, experience=300),))
    first = purchase(state, "Hunter", 21, at("10:43:20"))
    second = purchase(first.state, "Hunter", 21, at("10:43:22"))
    started = start_flight(second.state, at("11:06:00"), lifetime_ns=300_000_000_000)
    return replace(advance_time(started.state, at("11:42:00")).state,
        daily_schedule=DailySchedule(day_start_ns=at("02:00:00"),
            deadlines_ns=(at("11:06:00"), at("12:18:00")), next_index=1))


class BreadVisibilityTests(unittest.TestCase):
    def test_two_purchases_one_consumption_then_normal_one_hour_expiry(self):
        state = remaining_bread()
        self.assertEqual([effect.effect_id for effect in state.effects], [2])
        self.assertEqual(state.effects[0].expires_at_ns, at("11:43:22"))
        before = planning(state, at("11:43:21"))
        self.assertIn("Pains=1", before)
        self.assertIn("Attention : 1/1 pain(s) expirent", before)
        self.assertIn("09/09 12:18:00 CEST", before)
        after = planning(state, at("11:43:22"))
        self.assertIn("Pains=0", after)
        self.assertIn("aucun pain disponible", after)
        self.assertNotIn("sera consommé", after)
        self.assertNotIn("Expiration des pains:", after)
        self.assertEqual(len(state.effects), 1)  # projections do not rewrite state
        expired = advance_time(state, at("11:43:22"))
        self.assertEqual(expired.state.effects, ())
        self.assertIn(OutcomeKind.EFFECT_EXPIRED, [o.kind for o in expired.outcomes])
        later = start_flight(expired.state, at("12:18:00"), lifetime_ns=100)
        self.assertNotIn(OutcomeKind.EFFECT_CONSUMED, [o.kind for o in later.outcomes])

    def test_inventory_shows_relative_expiry_without_flight_schedule(self):
        state = replace(remaining_bread(), now_ns=at("11:43:20"))
        text = " ".join(render_inventory(state, "Hunter", channel="#marsh"))
        self.assertIn("1 morceau de pain", text)
        self.assertIn("première expiration dans 2s", text)
        self.assertNotIn("12:18", text)
        after = " ".join(render_inventory(advance_time(state, at("11:43:22")).state, "Hunter"))
        self.assertNotIn("morceau de pain", after)

    def test_earlier_call_may_consume_bread_without_moving_daily_slot(self):
        state = remaining_bread()
        action = ScheduledAction(1, 20, "duck_call", "hunter", at("11:42:00"), at("11:43:00"))
        state = replace(state, scheduled_actions=(action,), next_action_id=2)
        text = planning(state, at("11:42:00"))
        self.assertNotIn("Attention :", text)
        self.assertIn("Prochain quotidien=09/09 12:18:00 CEST", text)
        self.assertIn("réveil effectif=09/09 11:43:00 CEST", text)

    def test_expiry_at_flight_deadline_is_too_late(self):
        state = remaining_bread()
        schedule = replace(state.daily_schedule, deadlines_ns=(at("11:06:00"), at("11:43:22")))
        self.assertIn("Attention : 1/1", planning(replace(state, daily_schedule=schedule), at("11:42:00")))

    def test_active_flight_delays_call_past_bread_expiry(self):
        state = start_flight(remaining_bread(), at("11:42:00"), lifetime_ns=300_000_000_000).state
        bread = remaining_bread().effects
        action = ScheduledAction(1, 20, "duck_call", "hunter", at("11:42:00"), at("11:43:00"))
        state = replace(state, effects=bread, scheduled_actions=(action,), next_action_id=2)
        self.assertIn("Attention : 1/1", planning(state, at("11:42:00")))

    def test_day_rollover_is_not_a_promised_flight(self):
        state = remaining_bread()
        state = replace(state, daily_schedule=replace(state.daily_schedule, next_index=2))
        self.assertIn("Aucun prochain envol connu", planning(state, at("11:42:00")))


if __name__ == "__main__":
    unittest.main()
