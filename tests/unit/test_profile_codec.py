from __future__ import annotations

import unittest

from pyduckhunt.game.model import GameState, InventoryStack, PlayerState
from pyduckhunt.persistence.codec import CodecError, decode_game_state, encode_game_state


def state_with_profile() -> GameState:
    return GameState(
        last_shooter_key="hunter",
        players=(
            PlayerState(
                "hunter",
                "Hunter",
                ammo=2,
                capacity=4,
                magazines=3,
                magazine_capacity=7,
                hits=12,
                misses=3,
                wild_shots=2,
                empty_shots=5,
                jammed_shots=3,
                compulsive_reloads=4,
                shots_fired=19,
                jams=5,
                best_time_ms=842,
                level=9,
                experience=44,
                experience_spent=123,
                jammed=True,
                confiscated=True,
                permanently_confiscated=True,
                confiscations=2,
                incidents_caused=7,
                shots_received=6,
                incidents_deflected=3,
                incidents_absorbed=2,
                deaths=1,
                golden_hits=4,
                fatigue_centi=1_772,
                karma_modifier_basis_points=200,
                karma_decay_at_ns=7_200_000_000_100,
                inventory=(
                    InventoryStack("lucky_token", 2),
                    InventoryStack("target_lens", 1),
                ),
            ),
        ),
    )


class ProfileCodecTests(unittest.TestCase):
    def test_round_trip_preserves_profile_weapon_and_inventory(self) -> None:
        state = state_with_profile()
        self.assertEqual(decode_game_state(encode_game_state(state)), state)

    def test_profile_fields_are_explicit_in_canonical_payload(self) -> None:
        player = encode_game_state(state_with_profile())["players"][0]
        self.assertEqual(player["level"], 9)
        self.assertEqual(player["experience"], 44)
        self.assertEqual(player["magazines"], 3)
        self.assertEqual(player["magazine_capacity"], 7)
        self.assertIs(player["jammed"], True)
        self.assertIs(player["confiscated"], True)
        self.assertIs(player["permanently_confiscated"], True)
        self.assertEqual(player["confiscations"], 2)
        self.assertEqual(player["incidents_caused"], 7)
        self.assertEqual(player["wild_shots"], 2)
        self.assertEqual(player["empty_shots"], 5)
        self.assertEqual(player["jammed_shots"], 3)
        self.assertEqual(player["compulsive_reloads"], 4)
        self.assertEqual(player["shots_fired"], 19)
        self.assertEqual(player["jams"], 5)
        self.assertEqual(player["experience_spent"], 123)
        self.assertEqual(player["karma_modifier_basis_points"], 200)
        self.assertEqual(player["shots_received"], 6)
        self.assertEqual(player["incidents_deflected"], 3)
        self.assertEqual(player["incidents_absorbed"], 2)
        self.assertEqual(player["deaths"], 1)
        self.assertEqual(player["golden_hits"], 4)
        self.assertEqual(player["fatigue_centi"], 1_772)
        self.assertEqual(player["inventory"][0], {"key": "lucky_token", "quantity": 2})
        self.assertEqual(
            encode_game_state(state_with_profile())["last_shooter_key"],
            "hunter",
        )

    def test_decoder_rejects_unsorted_inventory(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["inventory"] = list(reversed(payload["players"][0]["inventory"]))
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_duplicate_inventory_keys(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["inventory"].append({"key": "target_lens", "quantity": 2})
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_experience_outside_current_level(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["experience"] = 100
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_truth_value_inventory_quantity(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["inventory"][0]["quantity"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_non_truth_value_jammed_state(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["jammed"] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_non_truth_value_confiscated_state(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["confiscated"] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_negative_incident_counter(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["incidents_caused"] = -1
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_truth_value_wild_shot_counter(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["wild_shots"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_schema_11_profile_defaults_the_new_counter_for_migration(self) -> None:
        payload = encode_game_state(state_with_profile())
        del payload["last_flight"]
        del payload["last_shooter_key"]
        for field in (
            "compulsive_reloads",
            "empty_shots",
            "jammed_shots",
            "karma_decay_at_ns",
            "karma_modifier_basis_points",
            "wild_shots",
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "permanently_confiscated",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del payload["players"][0][field]
        migrated = decode_game_state(payload, schema_version=11)
        self.assertEqual(migrated.players[0].wild_shots, 0)
        self.assertEqual(migrated.players[0].empty_shots, 0)

    def test_schema_12_profile_defaults_complete_karma_state(self) -> None:
        payload = encode_game_state(state_with_profile())
        del payload["last_flight"]
        del payload["last_shooter_key"]
        for field in (
            "compulsive_reloads",
            "empty_shots",
            "jammed_shots",
            "karma_decay_at_ns",
            "karma_modifier_basis_points",
            "carried_day_start_ns",
            "carried_ducks",
            "letter_slots",
            "permanently_confiscated",
            "experience_spent",
            "jams",
            "shots_fired",
        ):
            del payload["players"][0][field]
        migrated = decode_game_state(payload, schema_version=12)
        self.assertEqual(migrated.players[0].wild_shots, 2)
        self.assertEqual(migrated.players[0].compulsive_reloads, 0)
        self.assertEqual(migrated.players[0].karma_modifier_basis_points, 0)
        self.assertFalse(migrated.players[0].permanently_confiscated)

    def test_schema_19_profile_defaults_reference_counters_for_full_replay(self) -> None:
        payload = encode_game_state(state_with_profile())
        for field in ("experience_spent", "jams", "shots_fired"):
            del payload["players"][0][field]
        migrated = decode_game_state(payload, schema_version=19)
        self.assertEqual(migrated.players[0].experience_spent, 0)
        self.assertEqual(migrated.players[0].jams, 0)
        self.assertEqual(migrated.players[0].shots_fired, 0)

    def test_decoder_rejects_invalid_reference_counters(self) -> None:
        for field in ("experience_spent", "jams", "shots_fired"):
            with self.subTest(field=field):
                payload = encode_game_state(state_with_profile())
                payload["players"][0][field] = -1
                with self.assertRaises(CodecError):
                    decode_game_state(payload)

    def test_decoder_rejects_ambiguous_permanent_confiscation(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["permanently_confiscated"] = 1
        with self.assertRaises(CodecError):
            decode_game_state(payload)
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["confiscated"] = False
        with self.assertRaises(CodecError):
            decode_game_state(payload)

    def test_decoder_rejects_invalid_fatigue(self) -> None:
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["fatigue_centi"] = True
        with self.assertRaises(CodecError):
            decode_game_state(payload)
        payload = encode_game_state(state_with_profile())
        payload["players"][0]["fatigue_centi"] = 10_001
        with self.assertRaises(CodecError):
            decode_game_state(payload)


if __name__ == "__main__":
    unittest.main()
