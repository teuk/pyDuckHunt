from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command, start_flight
from pyduckhunt.game.model import (
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.shop import purchase


SHOT = Command(CommandKind.SHOT, "bang")
RELOAD = Command(CommandKind.RELOAD, "reload")


def hunter(nickname: str, **changes: object) -> PlayerState:
    values: dict[str, object] = {
        "key": nickname.lower(),
        "nickname": nickname,
        "ammo": 4,
        "capacity": 4,
        "level": 5,
        "experience": 40,
    }
    values.update(changes)
    return PlayerState(**values)


def miss_with(
    incident: IncidentAttempt | None = None,
    *,
    miss_penalty: int = 0,
    wild_penalty: int = 0,
) -> ShotAttempt:
    return ShotAttempt(
        base_accuracy_bps=0,
        accuracy_roll=1,
        miss_penalty=miss_penalty,
        wild_penalty=wild_penalty,
        incident=incident,
    )


class IncidentEngineTests(unittest.TestCase):
    def test_incident_contract_rejects_invalid_targets_and_penalties(self) -> None:
        with self.assertRaises(ValueError):
            IncidentAttempt(())
        with self.assertRaises(ValueError):
            IncidentAttempt([IncidentTargetAttempt("Victim")])
        with self.assertRaises(ValueError):
            IncidentTargetAttempt("Victim", deflection_roll=True)
        with self.assertRaises(ValueError):
            IncidentAttempt((IncidentTargetAttempt("Victim"),), incident_penalty=-1)

    def test_fatal_incident_is_atomic_and_confiscates_once(self) -> None:
        state = GameState(players=(hunter("Hunter"), hunter("Victim")))
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Victim"),),
            incident_penalty=6,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            100,
            shot_attempt=miss_with(incident, miss_penalty=2, wild_penalty=3),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.MISS, OutcomeKind.INCIDENT_FATAL),
        )
        shooter = result.state.player("hunter")
        victim = result.state.player("victim")
        self.assertEqual((shooter.experience, shooter.incidents_caused), (29, 1))
        self.assertTrue(shooter.confiscated)
        self.assertEqual(shooter.confiscations, 1)
        self.assertEqual((victim.shots_received, victim.deaths), (1, 1))
        self.assertTrue(result.outcomes[-1].weapon_confiscated)

    def test_ricochet_chain_charges_each_exposed_target(self) -> None:
        state = GameState(
            players=(hunter("First"), hunter("Hunter"), hunter("Second"))
        )
        incident = IncidentAttempt(
            (
                IncidentTargetAttempt(
                    "First",
                    deflection_bps=7_500,
                    deflection_roll=7_500,
                ),
                IncidentTargetAttempt(
                    "Second",
                    armor_bps=5_000,
                    armor_roll=5_000,
                ),
            ),
            incident_penalty=4,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            100,
            shot_attempt=miss_with(incident),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes[-2:]),
            (OutcomeKind.INCIDENT_DEFLECTED, OutcomeKind.INCIDENT_ABSORBED),
        )
        shooter = result.state.player("hunter")
        self.assertEqual((shooter.experience, shooter.incidents_caused), (32, 2))
        self.assertEqual(shooter.confiscations, 1)
        self.assertEqual(result.state.player("first").incidents_deflected, 1)
        self.assertEqual(result.state.player("second").incidents_absorbed, 1)
        self.assertFalse(result.outcomes[-1].weapon_confiscated)

    def test_safe_conduct_waives_incident_penalty_and_confiscation(self) -> None:
        state = GameState(players=(hunter("Hunter"), hunter("Victim")))
        state = purchase(state, "Hunter", 29, 100).state
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Victim"),),
            incident_penalty=12,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=miss_with(incident, miss_penalty=2),
        )
        shooter = result.state.player("hunter")
        self.assertEqual(shooter.experience, 23)
        self.assertFalse(shooter.confiscated)
        self.assertTrue(result.outcomes[-1].safe_conduct_applied)
        self.assertEqual(result.outcomes[-1].incident_penalty, 0)

    def test_safe_conduct_expires_at_its_exact_deadline(self) -> None:
        state = GameState(players=(hunter("Hunter"), hunter("Victim")))
        state = purchase(state, "Hunter", 29, 100).state
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Victim"),),
            incident_penalty=4,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            100 + 24 * 3_600_000_000_000,
            shot_attempt=miss_with(incident),
        )
        self.assertTrue(result.state.player("hunter").confiscated)
        self.assertFalse(result.outcomes[-1].safe_conduct_applied)
        self.assertEqual(result.outcomes[-1].incident_penalty, 4)

    def test_liability_insurance_divides_each_incident_penalty_by_three(self) -> None:
        state = GameState(players=(hunter("Hunter"), hunter("Victim")))
        state = purchase(state, "Hunter", 19, 100).state
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Victim"),),
            incident_penalty=10,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=miss_with(incident),
        )
        shooter = result.state.player("hunter")
        self.assertEqual(shooter.experience, 32)
        self.assertTrue(shooter.confiscated)
        self.assertTrue(result.outcomes[-1].liability_applied)
        self.assertEqual(result.outcomes[-1].incident_penalty, 3)

    def test_life_insurance_pays_three_times_shooter_level_and_is_consumed(self) -> None:
        state = GameState(
            players=(
                hunter("Hunter", level=7, experience=40),
                hunter("Victim", level=5, experience=40),
            )
        )
        state = purchase(state, "Victim", 18, 100).state
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Victim", armor_bps=10_000, armor_roll=1),),
            incident_penalty=0,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=miss_with(incident),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.INCIDENT_ABSORBED)
        self.assertEqual(result.outcomes[-1].insurance_award, 21)
        self.assertEqual(result.state.player("victim").experience, 53)
        self.assertFalse(any(effect.item_id == 18 for effect in result.state.effects))

    def test_miss_penalty_can_cross_a_level_boundary(self) -> None:
        state = GameState(players=(hunter("Hunter", level=3, experience=2),))
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            100,
            shot_attempt=miss_with(miss_penalty=7, wild_penalty=6),
        )
        shooter = result.state.player("hunter")
        self.assertEqual((shooter.level, shooter.experience), (2, 19))
        self.assertEqual(result.outcomes[-1].levels_lost, 1)

    def test_confiscated_weapon_blocks_shooting_and_reload(self) -> None:
        state = GameState(players=(hunter("Hunter", confiscated=True),))
        for command in (SHOT, RELOAD):
            result = apply_command(state, "Hunter", command, 100)
            self.assertEqual(result.outcomes[-1].kind, OutcomeKind.WEAPON_CONFISCATED)
            self.assertEqual(result.state.players[0].ammo, 4)

    def test_weapon_return_purchase_restores_access(self) -> None:
        state = GameState(players=(hunter("Hunter", confiscated=True),))
        restored = purchase(state, "Hunter", 5, 100)
        self.assertFalse(restored.state.player("hunter").confiscated)
        fired = apply_command(restored.state, "Hunter", SHOT, 200)
        self.assertEqual(fired.outcomes[-1].kind, OutcomeKind.MISS)

    def test_weapon_return_cannot_override_permanent_owner_confiscation(self) -> None:
        state = GameState(
            players=(
                hunter(
                    "Hunter",
                    confiscated=True,
                    permanently_confiscated=True,
                ),
            )
        )
        refused = purchase(state, "Hunter", 5, 100)
        self.assertEqual(refused.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        selected = refused.state.player("hunter")
        assert selected is not None
        self.assertTrue(selected.confiscated)
        self.assertTrue(selected.permanently_confiscated)

    def test_weapon_return_is_not_charged_when_weapon_is_present(self) -> None:
        state = GameState(players=(hunter("Hunter"),))
        result = purchase(state, "Hunter", 5, 100)
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_NOT_APPLICABLE)
        self.assertEqual(result.state.player("hunter").experience, 40)

    def test_incident_payload_forces_an_otherwise_successful_hit_to_miss(self) -> None:
        state = start_flight(
            GameState(players=(hunter("Hunter"), hunter("Victim"))),
            100,
            lifetime_ns=10_000,
        ).state
        incident = IncidentAttempt((IncidentTargetAttempt("Victim"),))
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            200,
            shot_attempt=ShotAttempt(incident=incident),
        )
        self.assertEqual(
            tuple(outcome.kind for outcome in result.outcomes),
            (OutcomeKind.MISS, OutcomeKind.INCIDENT_FATAL),
        )
        self.assertIsNotNone(result.state.flight)


if __name__ == "__main__":
    unittest.main()
