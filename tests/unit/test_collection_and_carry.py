from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.day_boundary import paris_calendar_day_marker_ns
from pyduckhunt.game.engine import advance_time, apply_command, start_flight
from pyduckhunt.game.loot import LETTER_SEQUENCE, acquire_loot
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    GameState,
    LootAward,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
)
from pyduckhunt.game.rewards import DAY_NS, reward_effect_by_key
from pyduckhunt.persistence.codec import (
    CodecError,
    decode_game_state,
    encode_game_state,
)
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.rendering.responses import render_inventory, render_outcome


SHOT = Command(CommandKind.SHOT, "bang")


def _utc_ns(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    instant = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return int(instant.timestamp()) * 1_000_000_000


def _kill(state: GameState, spawn_ns: int, *, loot: LootAward | None = None):
    started = start_flight(state, spawn_ns, lifetime_ns=100).state
    return apply_command(
        started,
        "Hunter",
        SHOT,
        spawn_ns + 1,
        shot_attempt=ShotAttempt(
            base_jam_bps=0,
            accuracy_roll=1,
            jam_roll=10_000,
            loot=loot,
        ),
    )


class CollectionAndCarryTests(unittest.TestCase):
    def test_player_contract_rejects_ambiguous_collection_and_carry_values(self) -> None:
        with self.assertRaises(ValueError):
            PlayerState("hunter", "Hunter", carried_ducks=True)
        with self.assertRaises(ValueError):
            PlayerState("hunter", "Hunter", carried_day_start_ns=1)
        with self.assertRaises(ValueError):
            PlayerState("hunter", "Hunter", letter_slots=(False,) * 7)
        with self.assertRaises(ValueError):
            PlayerState(
                "hunter",
                "Hunter",
                letter_slots=(False, False, False, False, False, False, False, 0),
            )

    def test_schema_15_defaults_new_profile_state_and_schema_17_round_trips(self) -> None:
        state = GameState(
            now_ns=DAY_NS + 7,
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    carried_ducks=9,
                    carried_day_start_ns=DAY_NS,
                    letter_slots=(True, False, True, False, True, False, True, False),
                ),
            ),
        )
        payload = encode_game_state(state)
        self.assertEqual(decode_game_state(payload), state)
        del payload["last_flight"]
        del payload["last_shooter_key"]
        for field in (
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del payload["players"][0][field]
        del payload["players"][0]["permanently_confiscated"]
        migrated = decode_game_state(payload, schema_version=15)
        self.assertEqual(migrated.players[0].carried_ducks, 0)
        self.assertEqual(migrated.players[0].carried_day_start_ns, DAY_NS)
        self.assertEqual(migrated.players[0].letter_slots, (False,) * 8)

    def test_decoder_rejects_noncanonical_letter_and_carry_payloads(self) -> None:
        payload = encode_game_state(
            GameState(players=(PlayerState("hunter", "Hunter"),))
        )
        payload["players"][0]["letter_slots"][0] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)
        payload = encode_game_state(
            GameState(players=(PlayerState("hunter", "Hunter"),))
        )
        payload["players"][0]["carried_ducks"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_two_u_slots_fill_in_phrase_order_and_duplicates_are_harmless(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            letter_slots=(False, False, False, False, False, True, False, False),
        )
        state = GameState(players=(player,))
        first = acquire_loot(state, "Hunter", LootAward("letter_u"), 0)
        self.assertEqual(
            first.state.players[0].letter_slots,
            (False, True, False, False, False, True, False, False),
        )
        duplicate = acquire_loot(
            first.state,
            "Hunter",
            LootAward("letter_u"),
            0,
        )
        self.assertEqual(duplicate.state, first.state)
        self.assertEqual(tuple(LETTER_SEQUENCE), tuple("DUCKHUNT"))

    def test_completion_is_atomic_resets_letters_and_stays_one_public_outcome(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            ammo=0,
            magazines=0,
            level=10,
            shop_credit=4,
            letter_slots=(True, True, True, True, True, True, False, True),
        )
        award = LootAward(
            "letter_n",
            completion_loot=(
                LootAward("voucher_10"),
                LootAward("extended_magazine"),
            ),
        )
        completed = acquire_loot(
            GameState(players=(player,)),
            "Hunter",
            award,
            0,
        )
        settled = completed.state.players[0]
        self.assertEqual(settled.letter_slots, (False,) * 8)
        self.assertEqual((settled.ammo, settled.capacity), (7, 7))
        self.assertEqual(
            (settled.magazines, settled.magazine_capacity),
            (2, 2),
        )
        self.assertEqual(settled.shop_credit, 64)
        self.assertEqual(len(completed.outcomes), 1)
        self.assertIs(completed.outcomes[0].letter_collection_completed, True)
        self.assertIn("Collection complète", render_outcome(completed.outcomes[0])[0])

    def test_completion_entropy_is_required_only_for_the_final_letter(self) -> None:
        incomplete = GameState(players=(PlayerState("hunter", "Hunter"),))
        with self.assertRaises(ValueError):
            acquire_loot(
                incomplete,
                "Hunter",
                LootAward("letter_d", completion_loot=(LootAward("voucher_10"),)),
                0,
            )
        final = GameState(
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    letter_slots=(True, True, True, True, True, True, False, True),
                ),
            )
        )
        with self.assertRaises(ValueError):
            acquire_loot(final, "Hunter", LootAward("letter_n"), 0)

    def test_completion_bundle_round_trips_in_the_replay_event(self) -> None:
        event = ReplayEvent.runtime_command(
            3,
            "Hunter",
            SHOT,
            shot_attempt=ShotAttempt(
                loot=LootAward(
                    "letter_t",
                    completion_loot=(LootAward("voucher_20"),),
                )
            ),
        )
        self.assertEqual(ReplayEvent.from_payload(event.to_payload()), event)

    def test_bag_thresholds_multiply_following_shots_exactly(self) -> None:
        first = _kill(
            GameState(
                players=(
                    PlayerState(
                        "hunter",
                        "Hunter",
                        carried_ducks=5,
                        carried_day_start_ns=0,
                    ),
                )
            ),
            0,
        )
        self.assertEqual(first.state.players[0].carried_ducks, 6)
        self.assertEqual(first.state.players[0].fatigue_centi, 100)
        self.assertEqual(first.outcomes[0].carry_fatigue_multiplier, 2)
        second = _kill(first.state, 2)
        self.assertEqual(second.state.players[0].fatigue_centi, 300)
        overloaded = _kill(
            GameState(
                players=(
                    PlayerState(
                        "hunter",
                        "Hunter",
                        carried_ducks=11,
                        carried_day_start_ns=0,
                    ),
                )
            ),
            0,
        )
        self.assertEqual(overloaded.state.players[0].fatigue_centi, 300)
        self.assertEqual(overloaded.outcomes[0].carry_fatigue_multiplier, 3)

    def test_tardis_is_a_24_hour_reward_and_prevents_carry_fatigue(self) -> None:
        spec = reward_effect_by_key("tardis_bag")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.duration_ns, DAY_NS)
        state = acquire_loot(
            GameState(
                players=(
                    PlayerState(
                        "hunter",
                        "Hunter",
                        carried_ducks=11,
                        carried_day_start_ns=0,
                    ),
                )
            ),
            "Hunter",
            LootAward("tardis_bag"),
            0,
        ).state
        killed = _kill(state, 0)
        self.assertEqual(killed.state.players[0].carried_ducks, 12)
        self.assertEqual(killed.state.players[0].fatigue_centi, 100)
        self.assertEqual(killed.outcomes[0].carry_fatigue_multiplier, 1)

    def test_paris_midnight_restocks_and_restores_the_daily_profile(self) -> None:
        before_midnight = _utc_ns(2026, 1, 1, 22, 59)
        paris_midnight = _utc_ns(2026, 1, 1, 23)
        state = GameState(
            now_ns=before_midnight,
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=1,
                    capacity=8,
                    magazines=0,
                    magazine_capacity=4,
                    jammed=True,
                    confiscated=True,
                    carried_ducks=12,
                    carried_day_start_ns=paris_calendar_day_marker_ns(before_midnight),
                    fatigue_centi=700,
                ),
            ),
        )
        advanced = advance_time(state, paris_midnight).state.players[0]
        self.assertEqual((advanced.ammo, advanced.magazines), (8, 4))
        self.assertFalse(advanced.confiscated)
        self.assertTrue(advanced.jammed)
        self.assertEqual(advanced.carried_ducks, 0)
        self.assertEqual(advanced.fatigue_centi, 0)
        self.assertEqual(
            advanced.carried_day_start_ns,
            paris_calendar_day_marker_ns(paris_midnight),
        )

    def test_daily_restock_does_not_run_again_at_utc_midnight(self) -> None:
        before_midnight = _utc_ns(2026, 1, 1, 22, 59)
        paris_midnight = _utc_ns(2026, 1, 1, 23)
        utc_midnight = _utc_ns(2026, 1, 2, 0)
        state = GameState(
            now_ns=before_midnight,
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=0,
                    magazines=0,
                    confiscated=True,
                    carried_day_start_ns=paris_calendar_day_marker_ns(before_midnight),
                    fatigue_centi=500,
                ),
            ),
        )
        stocked = advance_time(state, paris_midnight).state
        player = replace(
            stocked.players[0],
            ammo=2,
            magazines=1,
            confiscated=True,
            fatigue_centi=300,
        )
        later = advance_time(
            replace(stocked, players=(player,)),
            utc_midnight,
        ).state.players[0]
        self.assertEqual((later.ammo, later.magazines), (2, 1))
        self.assertTrue(later.confiscated)
        self.assertEqual(later.fatigue_centi, 300)

    def test_paris_day_marker_follows_cest_midnight_in_summer(self) -> None:
        before_midnight = _utc_ns(2026, 7, 1, 21, 59)
        paris_midnight = _utc_ns(2026, 7, 1, 22)
        before = paris_calendar_day_marker_ns(before_midnight)
        after = paris_calendar_day_marker_ns(paris_midnight)
        self.assertEqual(after - before, DAY_NS)

    def test_permanent_confiscation_survives_midnight_until_owner_rearm(self) -> None:
        state = GameState(
            now_ns=DAY_NS - 1,
            players=(
                PlayerState(
                    "hunter",
                    "Hunter",
                    ammo=0,
                    magazines=0,
                    confiscated=True,
                    permanently_confiscated=True,
                    carried_day_start_ns=0,
                    fatigue_centi=500,
                ),
            ),
        )
        advanced = advance_time(state, DAY_NS).state.players[0]
        self.assertEqual((advanced.ammo, advanced.magazines), (6, 2))
        self.assertTrue(advanced.confiscated)
        self.assertTrue(advanced.permanently_confiscated)
        self.assertEqual(advanced.fatigue_centi, 0)

    def test_inventory_compacts_bag_letters_and_tardis_on_existing_lines(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            carried_ducks=7,
            carried_day_start_ns=0,
            letter_slots=(True, True, False, True, True, False, True, True),
        )
        effect = ActiveEffect(
            effect_id=1,
            item_id=118,
            key="tardis_bag",
            scope=EffectScope.PLAYER,
            owner_key="hunter",
            source_key=None,
            activated_at_ns=0,
            expires_at_ns=DAY_NS,
        )
        lines = render_inventory(
            GameState(
                now_ns=1,
                players=(player,),
                effects=(effect,),
                next_effect_id=2,
            ),
            "Hunter",
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("gibecière TARDIS: 7 canards", lines[0])
        self.assertIn("lettres: D U _ K   H _ N T", lines[0])

    def test_inventory_counts_active_bread_on_the_current_channel(self) -> None:
        breads = tuple(
            ActiveEffect(
                effect_id=index,
                item_id=21,
                key="channel_bread",
                scope=EffectScope.CHANNEL,
                owner_key=None,
                source_key=None,
                activated_at_ns=1,
                expires_at_ns=DAY_NS,
            )
            for index in (1, 2)
        )
        lines = render_inventory(
            GameState(
                now_ns=2,
                players=(PlayerState("hunter", "Hunter"),),
                effects=breads,
                next_effect_id=3,
            ),
            "Hunter",
            channel="#pond",
        )
        self.assertIn("2 morceaux de pain sur #pond", " ".join(lines))
        self.assertNotIn("[Effets]", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
