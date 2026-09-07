from __future__ import annotations

from dataclasses import replace
import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.curses import HOUR_NS
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.model import ActiveCurse, GameState, OutcomeKind, PlayerState, ShotAttempt
from pyduckhunt.game.shop import purchase
from pyduckhunt.persistence.codec import decode_game_state, encode_game_state


def player(key: str, nickname: str, **changes: object) -> PlayerState:
    values: dict[str, object] = {
        "key": key,
        "nickname": nickname,
        "level": 30,
        "experience": 300,
        "ammo": 1,
        "capacity": 1,
        "magazines": 6,
        "magazine_capacity": 6,
    }
    values.update(changes)
    return PlayerState(**values)


class RemainingShopTests(unittest.TestCase):
    def test_espresso_applies_settled_relief(self) -> None:
        state = GameState(players=(player("hunter", "Hunter", fatigue_centi=872),))
        bought = purchase(state, "Hunter", 24, 100, fatigue_relief_centi=500)
        self.assertEqual(bought.state.player("hunter").fatigue_centi, 372)
        self.assertEqual(bought.outcomes[-1].fatigue_changed_centi, -500)

    def test_thermos_sets_a_replayed_bounded_target(self) -> None:
        state = GameState(players=(player("hunter", "Hunter", fatigue_centi=872),))
        with self.assertRaises(ValueError):
            purchase(state, "Hunter", 25, 100, fatigue_target_centi=1_001)
        bought = purchase(state, "Hunter", 25, 100, fatigue_target_centi=644)
        self.assertEqual(bought.state.player("hunter").fatigue_centi, 644)
        self.assertEqual(bought.outcomes[-1].fatigue_changed_centi, -228)

    def test_tonic_relieves_target_and_applies_one_hour_penalty(self) -> None:
        state = GameState(
            players=tuple(
                sorted(
                    (
                        player("buyer", "Buyer"),
                        player("target", "Target", fatigue_centi=1_772),
                    ),
                    key=lambda value: value.key,
                )
            )
        )
        bought = purchase(
            state,
            "Buyer",
            27,
            100,
            target_nickname="Target",
            target_present=True,
            fatigue_relief_centi=1_772,
        )
        self.assertEqual(bought.state.player("target").fatigue_centi, 0)
        effect = bought.state.effects[0]
        self.assertEqual((effect.item_id, effect.owner_key), (27, "target"))
        self.assertEqual(effect.expires_at_ns, 100 + HOUR_NS)

    def test_tonic_reduces_shot_accuracy_by_ten_percent(self) -> None:
        state = GameState(
            players=tuple(
                sorted(
                    (
                        player("buyer", "Buyer"),
                        player("target", "Target"),
                    ),
                    key=lambda value: value.key,
                )
            )
        )
        bought = purchase(
            state,
            "Buyer",
            27,
            100,
            target_nickname="Target",
            target_present=True,
            fatigue_relief_centi=0,
        )
        started = start_flight(bought.state, 101, lifetime_ns=1_000)
        fired = apply_command(
            started.state,
            "Target",
            Command(CommandKind.SHOT, "bang"),
            102,
            shot_attempt=ShotAttempt(base_accuracy_bps=10_000, accuracy_roll=9_001),
        )
        self.assertEqual(fired.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertEqual(fired.outcomes[-1].effective_accuracy_bps, 9_000)

    def test_self_targeted_tonic_keeps_charge_and_relief(self) -> None:
        state = GameState(players=(player("hunter", "Hunter", fatigue_centi=1_272),))
        bought = purchase(
            state,
            "Hunter",
            27,
            100,
            target_nickname="Hunter",
            target_present=True,
            fatigue_relief_centi=1_272,
        )
        hunter = bought.state.player("hunter")
        self.assertEqual((hunter.fatigue_centi, hunter.experience), (0, 290))

    def test_infusion_is_a_one_hour_target_effect(self) -> None:
        state = GameState(
            players=tuple(
                sorted(
                    (player("buyer", "Buyer"), player("target", "Target")),
                    key=lambda value: value.key,
                )
            )
        )
        bought = purchase(
            state,
            "Buyer",
            28,
            100,
            target_nickname="Target",
            target_present=True,
        )
        effect = bought.state.effects[0]
        self.assertEqual((effect.item_id, effect.expires_at_ns), (28, 100 + HOUR_NS))
        self.assertEqual(effect.magnitude, 600)
        self.assertEqual(decode_game_state(encode_game_state(bought.state)), bought.state)
        self.assertEqual(bought.state.player("target").fatigue_centi, 600)
        expired = advance_time(bought.state, 100 + HOUR_NS)
        self.assertEqual(expired.state.player("target").fatigue_centi, 0)
        self.assertEqual(expired.outcomes[-1].fatigue_changed_centi, -600)

    def test_infusion_expiration_never_crosses_below_zero(self) -> None:
        state = GameState(
            players=tuple(
                sorted(
                    (player("buyer", "Buyer"), player("target", "Target")),
                    key=lambda value: value.key,
                )
            )
        )
        bought = purchase(
            state,
            "Buyer",
            28,
            100,
            target_nickname="Target",
            target_present=True,
        )
        target = bought.state.player("target")
        lowered = bought.state.with_player(replace(target, fatigue_centi=250))
        expired = advance_time(lowered, 100 + HOUR_NS)
        self.assertEqual(expired.state.player("target").fatigue_centi, 0)
        self.assertEqual(expired.outcomes[-1].fatigue_changed_centi, -250)

    def test_infusion_removes_only_its_bounded_contribution(self) -> None:
        state = GameState(
            players=tuple(
                sorted(
                    (
                        player("buyer", "Buyer"),
                        player("target", "Target", fatigue_centi=9_750),
                    ),
                    key=lambda value: value.key,
                )
            )
        )
        bought = purchase(
            state,
            "Buyer",
            28,
            100,
            target_nickname="Target",
            target_present=True,
        )
        self.assertEqual(bought.state.player("target").fatigue_centi, 10_000)
        self.assertEqual(bought.state.effects[0].magnitude, 250)
        expired = advance_time(bought.state, 100 + HOUR_NS)
        self.assertEqual(expired.state.player("target").fatigue_centi, 9_750)

    def test_automatic_reloader_settles_after_fired_shot(self) -> None:
        state = GameState(players=(player("hunter", "Hunter", magazines=2),))
        bought = purchase(state, "Hunter", 30, 100)
        started = start_flight(bought.state, 101, lifetime_ns=1_000)
        fired = apply_command(
            started.state,
            "Hunter",
            Command(CommandKind.SHOT, "bang"),
            102,
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in fired.outcomes),
            (OutcomeKind.HIT, OutcomeKind.RELOADED),
        )
        self.assertTrue(fired.outcomes[-1].automatic)
        self.assertEqual(
            (
                fired.state.player("hunter").ammo,
                fired.state.player("hunter").magazines,
            ),
            (1, 1),
        )

    def test_automatic_reloader_does_not_create_reserves(self) -> None:
        state = GameState(players=(player("hunter", "Hunter", magazines=0),))
        bought = purchase(state, "Hunter", 30, 100)
        started = start_flight(bought.state, 101, lifetime_ns=1_000)
        fired = apply_command(
            started.state,
            "Hunter",
            Command(CommandKind.SHOT, "bang"),
            102,
        )
        self.assertEqual(tuple(outcome.kind for outcome in fired.outcomes), (OutcomeKind.HIT,))
        self.assertEqual(fired.state.player("hunter").ammo, 0)

    def test_purification_removes_every_owned_curse(self) -> None:
        hunter = player("hunter", "Hunter")
        curses = (
            ActiveCurse(1, "confusion", "hunter", 0, 24 * HOUR_NS, 2),
            ActiveCurse(2, "tremor", "hunter", 0, 24 * HOUR_NS, 25),
        )
        state = GameState(players=(hunter,), next_curse_id=3, curses=curses)
        cleansed = purchase(state, "Hunter", 31, 100)
        self.assertEqual(cleansed.state.curses, ())
        self.assertEqual(cleansed.outcomes[-1].removed_curse_keys, ("confusion", "tremor"))

    def test_purification_without_curse_does_not_charge(self) -> None:
        state = GameState(players=(player("hunter", "Hunter"),))
        result = purchase(state, "Hunter", 31, 100)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        self.assertEqual(result.state.player("hunter").experience, 300)

    def test_curse_expires_at_exact_deadline(self) -> None:
        hunter = player("hunter", "Hunter")
        deadline = 24 * HOUR_NS
        state = GameState(
            players=(hunter,),
            next_curse_id=2,
            curses=(ActiveCurse(1, "confusion", "hunter", 0, deadline, 2),),
        )
        before = advance_time(state, deadline - 1)
        self.assertEqual(len(before.state.curses), 1)
        expired = advance_time(before.state, deadline)
        self.assertEqual(expired.state.curses, ())
        self.assertEqual(expired.outcomes[-1].kind, OutcomeKind.CURSE_EXPIRED)


if __name__ == "__main__":
    unittest.main()
