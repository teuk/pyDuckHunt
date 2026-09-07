from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.curses import curse_spec
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.replay import apply_replay_event


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")


def player(
    key: str = "hunter",
    nickname: str = "Hunter",
    **changes: object,
) -> PlayerState:
    values: dict[str, object] = {
        "key": key,
        "nickname": nickname,
        "ammo": 3,
        "capacity": 3,
        "magazines": 2,
    }
    values.update(changes)
    return PlayerState(**values)


def curse(identifier: int, key: str, owner_key: str = "hunter") -> ActiveCurse:
    spec = curse_spec(key)
    assert spec is not None
    return ActiveCurse(
        identifier,
        key,
        owner_key,
        0,
        spec.duration_ns,
        spec.magnitude,
    )


def state_with_curses(*keys: str, hunter: PlayerState | None = None) -> GameState:
    curses = tuple(curse(index, key) for index, key in enumerate(keys, start=1))
    return GameState(
        players=(hunter if hunter is not None else player(),),
        next_curse_id=len(curses) + 1,
        curses=curses,
    )


class CurseModifierTests(unittest.TestCase):
    def test_slowness_defers_then_replays_the_same_shot(self) -> None:
        state = start_flight(
            state_with_curses("slowness"),
            1,
            lifetime_ns=10_000_000_000,
        ).state
        delayed = apply_command(state, "Hunter", SHOT, 2)
        self.assertEqual(delayed.outcomes[-1].kind, OutcomeKind.COMMAND_DELAYED)
        self.assertEqual(delayed.outcomes[-1].defer_until_ns, 5_000_000_002)
        self.assertEqual(delayed.state.player("hunter").ammo, 3)
        self.assertEqual(delayed.state.player("hunter").fatigue_centi, 0)

        event = ReplayEvent.command(
            5_000_000_002,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(fatigue_gain_centi=172),
            delay_settled=True,
        )
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)
        replayed = apply_replay_event(delayed.state, event)
        direct = apply_command(
            delayed.state,
            "Hunter",
            SHOT,
            5_000_000_002,
            shot_attempt=ShotAttempt(fatigue_gain_centi=172),
            delay_settled=True,
        )
        self.assertEqual(replayed, direct)
        self.assertEqual(replayed.outcomes[-1].kind, OutcomeKind.HIT)
        self.assertEqual(replayed.state.player("hunter").fatigue_centi, 172)

    def test_slowness_defers_reload_without_spending_a_magazine(self) -> None:
        state = state_with_curses("slowness", hunter=player(ammo=0))
        delayed = apply_command(state, "Hunter", RELOAD, 10)
        self.assertEqual(delayed.outcomes[-1].kind, OutcomeKind.COMMAND_DELAYED)
        self.assertEqual(delayed.state.player("hunter").magazines, 2)
        settled = apply_command(
            delayed.state,
            "Hunter",
            RELOAD,
            5_000_000_010,
            delay_settled=True,
        )
        self.assertEqual(settled.outcomes[-1].kind, OutcomeKind.RELOADED)
        self.assertEqual(settled.state.player("hunter").magazines, 1)

    def test_one_armed_blocks_reload_without_changing_reserves(self) -> None:
        hunter = player(ammo=0)
        state = state_with_curses("one_armed", hunter=hunter)
        blocked = apply_command(state, "Hunter", RELOAD, 1)
        self.assertEqual(blocked.outcomes[-1].kind, OutcomeKind.CURSE_BLOCKED)
        self.assertEqual(
            (
                blocked.state.player("hunter").ammo,
                blocked.state.player("hunter").magazines,
            ),
            (0, 2),
        )

    def test_decay_reduces_reliability_by_thirty_three_percent(self) -> None:
        state = state_with_curses("decay")
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(base_jam_bps=0, jam_roll=3_300),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.JAMMED)
        self.assertEqual(result.outcomes[-1].effective_jam_bps, 3_300)
        self.assertEqual(result.state.player("hunter").fatigue_centi, 0)

    def test_tremor_composes_with_tonic_glare_and_scope(self) -> None:
        hunter = player()
        effects = (
            ActiveEffect(
                1,
                7,
                "scope",
                EffectScope.PLAYER,
                "hunter",
                None,
                0,
                remaining_uses=1,
                magnitude=10,
            ),
            ActiveEffect(
                2,
                14,
                "glare",
                EffectScope.PLAYER,
                "hunter",
                "source",
                0,
                remaining_uses=1,
            ),
            ActiveEffect(
                3,
                27,
                "strong_tonic",
                EffectScope.PLAYER,
                "hunter",
                "source",
                0,
                expires_at_ns=3_600_000_000_000,
            ),
        )
        source = player("source", "Source")
        state = GameState(
            players=tuple(sorted((hunter, source), key=lambda value: value.key)),
            next_effect_id=4,
            effects=effects,
            next_curse_id=2,
            curses=(curse(1, "tremor"),),
        )
        state = start_flight(state, 1, lifetime_ns=1_000).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            2,
            shot_attempt=ShotAttempt(accuracy_roll=4_376),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertEqual(result.outcomes[-1].effective_accuracy_bps, 4_375)

    def test_confusion_halves_charm_augmented_hit_experience(self) -> None:
        charm = ActiveEffect(
            1,
            10,
            "lucky_charm",
            EffectScope.PLAYER,
            "hunter",
            None,
            0,
            expires_at_ns=10_000,
            magnitude=6,
        )
        state = GameState(
            players=(player(),),
            next_effect_id=2,
            effects=(charm,),
            next_curse_id=2,
            curses=(curse(1, "confusion"),),
        )
        state = start_flight(state, 1, lifetime_ns=1_000).state
        result = apply_command(state, "Hunter", SHOT, 2)
        self.assertEqual(result.outcomes[-1].experience_awarded, 8)
        self.assertEqual(result.state.player("hunter").experience, 8)

    def test_frenzy_and_burden_compose_damage_rounds_and_fatigue(self) -> None:
        state = state_with_curses("burden", "frenzy")
        state = start_flight(state, 1, lifetime_ns=1_000, health=5).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            2,
            shot_attempt=ShotAttempt(fatigue_gain_centi=123),
        )
        outcome = result.outcomes[-1]
        self.assertEqual(outcome.kind, OutcomeKind.FLIGHT_SURVIVED)
        self.assertEqual((outcome.damage_dealt, outcome.rounds_consumed), (2, 2))
        self.assertEqual(outcome.fatigue_changed_centi, 492)
        self.assertEqual(result.state.player("hunter").fatigue_centi, 492)

    def test_frenzy_uses_the_single_available_round(self) -> None:
        state = state_with_curses("frenzy", hunter=player(ammo=1))
        state = start_flight(state, 1, lifetime_ns=1_000, health=3).state
        result = apply_command(state, "Hunter", SHOT, 2)
        self.assertEqual(result.outcomes[-1].rounds_consumed, 1)
        self.assertEqual(result.state.player("hunter").ammo, 0)

    def test_composed_fatigue_is_bounded_at_one_hundred(self) -> None:
        hunter = player(fatigue_centi=9_950)
        state = state_with_curses("burden", "frenzy", hunter=hunter)
        state = start_flight(state, 1, lifetime_ns=1_000).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            2,
            shot_attempt=ShotAttempt(fatigue_gain_centi=123),
        )
        self.assertEqual(result.outcomes[-1].fatigue_changed_centi, 50)
        self.assertEqual(result.state.player("hunter").fatigue_centi, 10_000)

    def test_unerring_miss_requires_and_settles_an_incident(self) -> None:
        hunter = player()
        victim = player("victim", "Victim")
        state = GameState(
            players=tuple(sorted((hunter, victim), key=lambda value: value.key)),
            next_curse_id=2,
            curses=(curse(1, "unerring_miss"),),
        )
        with self.assertRaises(ValueError):
            apply_command(state, "Hunter", SHOT, 1)
        self.assertEqual(state.player("hunter").ammo, 3)

        incident = IncidentAttempt((IncidentTargetAttempt("Victim"),), 0)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(incident=incident),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.MISS, OutcomeKind.INCIDENT_FATAL),
        )
        self.assertEqual(result.state.player("victim").deaths, 1)

    def test_unerring_miss_ignores_preinjected_incident_on_a_hit(self) -> None:
        hunter = player()
        victim = player("victim", "Victim")
        state = GameState(
            players=tuple(sorted((hunter, victim), key=lambda value: value.key)),
            next_curse_id=2,
            curses=(curse(1, "unerring_miss"),),
        )
        state = start_flight(state, 1, lifetime_ns=1_000).state
        incident = IncidentAttempt((IncidentTargetAttempt("Victim"),), 0)
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            2,
            shot_attempt=ShotAttempt(incident=incident),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.HIT,),
        )
        self.assertEqual(result.state.player("victim").deaths, 0)

    def test_truth_values_are_not_fatigue_or_delay_settlements(self) -> None:
        with self.assertRaises(ValueError):
            ShotAttempt(fatigue_gain_centi=True)
        with self.assertRaises(ValueError):
            PlayerState("hunter", "Hunter", fatigue_centi=True)
        with self.assertRaises(ValueError):
            ReplayEvent.command(1, "Hunter", SHOT, delay_settled=1)

    def test_expired_tremor_is_reaped_before_accuracy_settlement(self) -> None:
        state = state_with_curses("tremor")
        spec = curse_spec("tremor")
        assert spec is not None
        state = start_flight(state, 1, lifetime_ns=spec.duration_ns + 1_000).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            spec.duration_ns,
            shot_attempt=ShotAttempt(accuracy_roll=10_000),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.CURSE_EXPIRED, OutcomeKind.HIT),
        )
        self.assertEqual(result.outcomes[-1].effective_accuracy_bps, 10_000)


if __name__ == "__main__":
    unittest.main()
