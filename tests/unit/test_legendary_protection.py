from __future__ import annotations

import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import apply_command
from pyduckhunt.game.loot import UNUSUAL_LOOT_CATALOG, acquire_loot
from pyduckhunt.game.model import (
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.shop import purchase
from pyduckhunt.rendering import render_inventory


SHOT = Command(CommandKind.SHOT, "bang")
LEGENDARY_PROTECTION = {
    "indestructible_sunglasses": (20, (14,)),
    "tearproof_raincoat": (20, (16,)),
    "military_self_lubricating_system": (20, (15,)),
    "permanent_killing_license": (30, ()),
}


def protected_state() -> GameState:
    return GameState(
        players=(
            PlayerState("actor", "Actor", level=30),
            PlayerState("hunter", "Hunter", level=30),
        )
    )


class LegendaryProtectionTests(unittest.TestCase):
    def test_catalog_preserves_exact_levels_and_counter_boundaries(self) -> None:
        catalog = {spec.key: spec for spec in UNUSUAL_LOOT_CATALOG}
        self.assertEqual(
            {
                key: (catalog[key].minimum_level, catalog[key].removes_item_ids)
                for key in LEGENDARY_PROTECTION
            },
            LEGENDARY_PROTECTION,
        )

    def test_every_permanent_protection_is_level_gated_exactly(self) -> None:
        for key, (minimum_level, _) in LEGENDARY_PROTECTION.items():
            with self.subTest(key=key):
                below = PlayerState("hunter", "Hunter", level=minimum_level - 1)
                with self.assertRaises(ValueError):
                    acquire_loot(
                        GameState(players=(below,)),
                        "Hunter",
                        LootAward(key),
                        0,
                    )
                exact = PlayerState("hunter", "Hunter", level=minimum_level)
                acquired = acquire_loot(
                    GameState(players=(exact,)),
                    "Hunter",
                    LootAward(key),
                    0,
                )
                self.assertEqual(acquired.state.players[0].inventory[0].key, key)

    def test_permanent_protections_are_unique_inventory_facts(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", level=30),))
        for key in LEGENDARY_PROTECTION:
            state = acquire_loot(state, "Hunter", LootAward(key), 0).state
            state = acquire_loot(state, "Hunter", LootAward(key), 0).state
        player = state.player("hunter")
        assert player is not None
        self.assertEqual(
            tuple((stack.key, stack.quantity) for stack in player.inventory),
            tuple((key, 1) for key in sorted(LEGENDARY_PROTECTION)),
        )

    def test_acquisition_drains_the_matching_pending_nuisance(self) -> None:
        for nuisance_id, key in (
            (14, "indestructible_sunglasses"),
            (15, "military_self_lubricating_system"),
            (16, "tearproof_raincoat"),
        ):
            with self.subTest(key=key):
                nuisance = purchase(
                    protected_state(),
                    "Actor",
                    nuisance_id,
                    100,
                    target_nickname="Hunter",
                    target_present=True,
                )
                acquired = acquire_loot(
                    nuisance.state,
                    "Hunter",
                    LootAward(key),
                    100,
                )
                self.assertEqual(acquired.state.effects, ())
                self.assertEqual(acquired.outcomes[0].removed_item_ids, (nuisance_id,))

    def test_permanent_equipment_blocks_matching_nuisances_without_consumption(self) -> None:
        for nuisance_id, key in (
            (14, "indestructible_sunglasses"),
            (15, "military_self_lubricating_system"),
            (16, "tearproof_raincoat"),
        ):
            with self.subTest(key=key):
                state = acquire_loot(
                    protected_state(),
                    "Hunter",
                    LootAward(key),
                    0,
                ).state
                result = purchase(
                    state,
                    "Actor",
                    nuisance_id,
                    100,
                    target_nickname="Hunter",
                    target_present=True,
                )
                self.assertEqual(result.outcomes[-1].kind, OutcomeKind.SHOP_PURCHASED)
                self.assertTrue(result.outcomes[-1].effect_blocked)
                self.assertEqual(result.state.effects, ())
                self.assertEqual(result.state.player("hunter").inventory[0].key, key)

    def test_military_self_lubrication_halves_jam_risk_permanently(self) -> None:
        state = acquire_loot(
            GameState(players=(PlayerState("hunter", "Hunter", level=20),)),
            "Hunter",
            LootAward("military_self_lubricating_system"),
            0,
        ).state
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=750),
        )
        self.assertEqual(result.outcomes[-1].kind, OutcomeKind.MISS)
        self.assertEqual(result.outcomes[-1].effective_jam_bps, 500)
        self.assertFalse(result.state.player("hunter").jammed)

    def test_military_self_lubrication_neither_stacks_nor_spends_grease(self) -> None:
        state = acquire_loot(
            protected_state(),
            "Hunter",
            LootAward("military_self_lubricating_system"),
            0,
        ).state
        state = purchase(state, "Hunter", 6, 100).state
        blocked = purchase(
            state,
            "Actor",
            15,
            200,
            target_nickname="Hunter",
            target_present=True,
        )
        self.assertTrue(blocked.outcomes[-1].effect_blocked)
        self.assertEqual(tuple(effect.item_id for effect in blocked.state.effects), (6,))
        fired = apply_command(
            blocked.state,
            "Hunter",
            SHOT,
            300,
            shot_attempt=ShotAttempt(base_jam_bps=1_000, jam_roll=750),
        )
        self.assertEqual(fired.outcomes[-1].effective_jam_bps, 500)
        self.assertEqual(tuple(effect.item_id for effect in fired.state.effects), (6,))

    def test_permanent_killing_license_waives_penalty_and_confiscation(self) -> None:
        state = acquire_loot(
            protected_state(),
            "Hunter",
            LootAward("permanent_killing_license"),
            0,
        ).state
        incident = IncidentAttempt(
            (IncidentTargetAttempt("Actor"),),
            incident_penalty=12,
        )
        result = apply_command(
            state,
            "Hunter",
            SHOT,
            1,
            shot_attempt=ShotAttempt(
                base_accuracy_bps=0,
                accuracy_roll=1,
                incident=incident,
            ),
        )
        hunter = result.state.player("hunter")
        assert hunter is not None
        self.assertFalse(hunter.confiscated)
        self.assertEqual(hunter.incidents_caused, 1)
        self.assertTrue(result.outcomes[-1].safe_conduct_applied)
        self.assertEqual(result.outcomes[-1].incident_penalty, 0)

    def test_inventory_uses_compact_french_legendary_labels(self) -> None:
        state = GameState(players=(PlayerState("hunter", "Hunter", level=30),))
        for key in LEGENDARY_PROTECTION:
            state = acquire_loot(state, "Hunter", LootAward(key), 0).state
        rendered = " ".join(render_inventory(state, "Hunter"))
        for label in (
            "lunettes soleil",
            "imperméable",
            "syst. autolubrifiant",
            "permis de tuer",
        ):
            self.assertIn(label, rendered)


if __name__ == "__main__":
    unittest.main()
