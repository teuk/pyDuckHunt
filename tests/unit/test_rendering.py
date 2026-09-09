from __future__ import annotations

import unittest

from pyduckhunt.game.catalog import GrantKind, SHOP_CATALOG
from pyduckhunt.game.commands import CommandSyntaxError, parse_command
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    GameState,
    InventoryStack,
    LastFlight,
    LastFlightConclusion,
    FlightKind,
    Outcome,
    OutcomeKind,
    PlayerState,
)
from pyduckhunt.game.rewards import REWARD_EFFECT_CATALOG
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.message import IRCProtocolError, MAX_WIRE_BYTES
from pyduckhunt.rendering import (
    MAX_RESPONSE_LINES,
    render_detector_notice,
    render_inventory,
    render_last_flight,
    render_outcome,
    render_outcomes,
    render_profile,
    render_query,
    render_ranking,
    render_shop,
    render_wire_notice,
    render_wire_response,
)
from pyduckhunt.time_format import format_duration_ns


def player(nickname: str, **changes: object) -> PlayerState:
    values: dict[str, object] = {
        "key": rfc1459_casefold(nickname),
        "nickname": nickname,
    }
    values.update(changes)
    return PlayerState(**values)


class ResponseRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.alice = player(
            "Alice",
            ammo=0,
            magazines=1,
            hits=12,
            golden_hits=2,
            misses=3,
            best_time_ms=1234,
            level=2,
            experience=5,
            incidents_caused=2,
            shots_received=1,
            fatigue_centi=672,
        )
        self.bob = player("Bob", hits=20, best_time_ms=2500)
        self.state = GameState(players=(self.alice, self.bob))

    def test_profile_is_the_complete_two_line_hunting_sheet(self) -> None:
        lines = render_profile(self.state, "alice")
        self.assertEqual(len(lines), 2)
        joined = " ".join(lines)
        for fact in ("12 canards", "1.234s", "niv. 2"):
            self.assertIn(fact, joined)
        self.assertIn("fatigue: 6.72", joined)
        self.assertIn("karma: 60", joined)
        self.assertIn("dont 2 super-canards", joined)
        self.assertIn("[Arme]", joined)
        self.assertIn("[Tableau de chasse]", joined)
        self.assertNotIn("mun.", joined)
        self.assertNotIn("charg.:", joined)

    def test_profile_includes_the_temporary_modifier_in_effective_karma(self) -> None:
        boosted = player(
            "Boosted",
            hits=10,
            karma_modifier_basis_points=200,
            karma_decay_at_ns=1,
        )
        rendered = render_profile(GameState(players=(boosted,)), "Boosted")[0]
        self.assertIn("karma: 100", rendered)

    def test_profile_matches_the_reference_values_and_labels(self) -> None:
        reference = player(
            "ReferenceHunter",
            ammo=1,
            capacity=1,
            magazines=5,
            magazine_capacity=5,
            hits=8_460,
            golden_hits=391,
            misses=768,
            wild_shots=138,
            empty_shots=489,
            jammed_shots=3,
            compulsive_reloads=294,
            shots_fired=9_825,
            jams=98,
            best_time_ms=634,
            level=94,
            experience=785,
            experience_spent=29_387,
            confiscations=26,
            incidents_caused=68,
            shots_received=69,
            incidents_deflected=47,
            incidents_absorbed=14,
            deaths=8,
        )
        first, second = render_profile(
            GameState(players=(reference,)),
            "ReferenceHunter",
        )
        self.assertEqual(
            first,
            "\x0307[Profil]\x0f 106915 xp | niv. 94 "
            "(chasseur d'élite émérite) +3965 xp = niv. sup. | fatigue: 0 | "
            "karma: 93.83 | rentab.: 12.64 xp/canard | dépensé: 29387 xp  "
            "\x0307[Stats]\x0f préc. théor.: 99% | effic. tirs: 92.18% | "
            "fiab. arme: 93+3% | armure: 100% | déflex.: 75%  "
            "\x0307[Arme]\x0f enray.: non (98 fois) | confisq.: non (26 fois)",
        )
        self.assertEqual(
            second,
            "\x0307[Tableau de chasse]\x0f meill. tps.: 0.634s | "
            "8460 canards (dont 391 super-canards) | 768 tirs ratés | "
            "489 tirs à vide | 3 tirs enray. | 294 recharg. compulsifs | "
            "138 tirs sauvages | 68 accidents | 9825 coups tirés  "
            "\x0307[Accidents]\x0f reçu 69 balles perdues dont 8 mortelles, "
            "47 ont ricoché et 14 ont été encaissées.",
        )
        self.assertEqual(
            len(render_wire_notice("ReferenceHunter", (first, second))),
            2,
        )

    def test_loot_acquisition_has_a_player_response(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                loot_key="xp_20",
                experience_awarded=20,
            )
        )[0]
        self.assertIn("fouillant les buissons", line)
        self.assertIn("20 xp", line)

    def test_loot_rarity_tags_use_the_observed_labels_and_tier_colors(self) -> None:
        for key, tag in (
            ("xp_10", "\x0303[item inhabituel]\x0f"),
            ("voucher_50", "\x0312[item rare]\x0f"),
            ("voucher_75", "\x0306[item très rare]\x0f"),
            ("large_ammo_bag", "\x0307[item légendaire]\x0f"),
        ):
            with self.subTest(key=key):
                line = render_outcome(
                    Outcome(OutcomeKind.LOOT_ACQUIRED, actor="Alice", loot_key=key)
                )[0]
                self.assertIn(f"   {tag}", line)
                self.assertEqual(line.count("[item "), 1)

        ordinary = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                loot_key="duck_detector",
            )
        )[0]
        self.assertNotIn("[item ", ordinary)

    def test_every_equipment_drop_explains_its_bound_or_permanent_effect(self) -> None:
        cases = (
            ("penetrating_ammunition", None, "doublés pendant 24h"),
            ("explosive_ammunition", None, "triplés pendant 24h"),
            ("weapon_grease", None, "réduit de moitié pendant 24h"),
            ("targeting_scope", 7, "6 tirs : +7 points de précision"),
            ("infrared_lock", None, "Dure 24h pour 6 utilisations"),
            ("suppressor", None, "effrayer les canards pendant 24h"),
            ("sunglasses", None, "éblouissement pendant 24h"),
            ("duck_detector", None, "prochain canard"),
            ("lucky_charm", 4, "4 points d'xp supplémentaires pendant 24h"),
            ("abundance_amulet", None, "doublées pendant 24h"),
            ("endurance_amulet", None, "fatigue pendant 24h"),
            ("blessing_amulet", None, "prochaine malédiction"),
            ("promotion_10_24h", None, "10% de réduction dans le shop pendant 24h"),
            ("promotion_10_48h", None, "10% de réduction dans le shop pendant 48h"),
            ("promotion_10_7d", None, "10% de réduction dans le shop pendant 1 semaine"),
            ("promotion_25_24h", None, "25% de réduction dans le shop pendant 24h"),
            ("promotion_25_48h", None, "25% de réduction dans le shop pendant 48h"),
            ("promotion_25_7d", None, "25% de réduction dans le shop pendant 1 semaine"),
            ("promotion_50_24h", None, "50% de réduction dans le shop pendant 24h"),
            ("promotion_50_48h", None, "50% de réduction dans le shop pendant 48h"),
            ("baker_amulet", None, "chaque canard abattu fait apparaître un morceau"),
            ("prankster_amulet", None, "canard mécanique 10mn après"),
            ("ammo_recycler", None, "Pendant 24h, il y a 1 chance sur 3"),
            ("premium_ammo_recycler", None, "Pendant 48h, il y a 1 chance sur 2"),
            ("warrior_amulet", None, "chargeurs illimitée pendant 24h"),
            ("eternal_warrior_amulet", None, "chargeurs illimitée pendant 48h"),
            ("tardis_bag", None, "sans être encombré pendant 24h"),
            ("large_ammo_bag", None, "transporter un chargeur supplémentaire"),
            ("extended_magazine", None, "charger une munition supplémentaire"),
            ("military_ammo_recycler", None, "désormais 1 chance sur 10"),
            ("indestructible_sunglasses", None, "manière permanente"),
            ("tearproof_raincoat", None, "manière permanente"),
            ("military_self_lubricating_system", None, "manière permanente"),
            ("permanent_killing_license", None, "accident de chasse"),
        )
        for key, magnitude, expected in cases:
            with self.subTest(key=key):
                line = render_outcome(
                    Outcome(
                        OutcomeKind.LOOT_ACQUIRED,
                        actor="Alice",
                        loot_key=key,
                        loot_magnitude=magnitude,
                    )
                )[0]
                self.assertIn(expected, line)
                self.assertIn("tu trouves ", line)
                self.assertNotIn("tu trouves...", line)
                self.assertEqual(len(render_wire_response("#canal", (line,))), 1)

    def test_variable_equipment_drop_requires_the_settled_magnitude(self) -> None:
        for key in ("targeting_scope", "lucky_charm"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                render_outcome(
                    Outcome(OutcomeKind.LOOT_ACQUIRED, actor="Alice", loot_key=key)
                )

    def test_letter_and_completion_keep_the_unusual_marker(self) -> None:
        hunter = player(
            "Alice",
            letter_slots=(True, False, False, False, False, False, False, False),
        )
        letter = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                player=hunter,
                loot_key="letter_d",
            )
        )[0]
        completed = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                player=hunter,
                loot_key="letter_d",
                letter_collection_completed=True,
            )
        )[0]
        tag = "\x0303[item inhabituel]\x0f"
        self.assertIn(tag, letter)
        self.assertIn(tag, completed)

    def test_carry_warning_is_red_in_hits_and_inventory(self) -> None:
        for multiplier, label, carried in (
            (2, "encombré", 6),
            (3, "surchargé", 11),
        ):
            with self.subTest(label=label):
                tag = f"\x0304[{label}]\x0f"
                hit = render_outcome(
                    Outcome(
                        OutcomeKind.HIT,
                        actor="Alice",
                        player=player("Alice", hits=carried),
                        experience_awarded=10,
                        carry_fatigue_multiplier=multiplier,
                    )
                )[0]
                inventory = render_inventory(
                    GameState(players=(player("Alice", carried_ducks=carried),)),
                    "Alice",
                )[0]
                self.assertIn(tag, hit)
                self.assertIn(tag, inventory)
                self.assertNotIn(f" [{label}]", hit)
                self.assertNotIn(f" [{label}]", inventory)

    def test_detector_discovery_explains_the_next_flight_notice(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                loot_key="duck_detector",
            )
        )[0]
        self.assertIn("un détecteur de canards", line)
        self.assertIn(
            "Tu seras averti par une notice lors de l'envol du prochain canard.",
            line,
        )

    def test_detector_alert_has_one_private_notice_text(self) -> None:
        alert = Outcome(OutcomeKind.DUCK_ALERT, actor="Alice", flight_id=1)
        self.assertEqual(
            render_detector_notice(alert),
            ("Ton détecteur de canards t'avertit : un canard vient de s'envoler.",),
        )
        self.assertEqual(
            render_detector_notice(Outcome(OutcomeKind.DUCK_ALERT, flight_id=1)),
            (),
        )

    def test_unusual_outcomes_and_shop_tags_have_player_responses(self) -> None:
        unusual = render_outcome(
            Outcome(
                OutcomeKind.LOOT_ACQUIRED,
                actor="Alice",
                loot_key="abundance_amulet",
            )
        )[0]
        self.assertIn("abondance", unusual)
        purchased = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=1,
                charged_experience=5,
                shop_credit_spent=5,
                discount_percent=25,
            )
        )[0]
        self.assertIn("bon d'achat", purchased)
        self.assertIn("coupon promo", purchased)

    def test_variable_shop_purchase_announces_the_settled_value(self) -> None:
        scope = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=7,
                charged_experience=5,
                effect_magnitude=14,
            )
        )[0]
        self.assertIn("6 tirs", scope)
        self.assertIn("+14 points de précision", scope)

        charm = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=10,
                charged_experience=13,
                effect_magnitude=2,
                shop_credit_spent=13,
            )
        )[0]
        self.assertIn("2 points d'xp supplémentaires", charm)
        self.assertIn("pendant 24h", charm)
        self.assertIn("bon d'achat", charm)

    def test_single_point_lucky_charm_uses_singular_words(self) -> None:
        charm = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=10,
                charged_experience=13,
                effect_magnitude=1,
            )
        )[0]
        self.assertIn("1 point d'xp supplémentaire", charm)

    def test_variable_shop_purchase_rejects_missing_magnitude(self) -> None:
        for item_id in (7, 10):
            with self.subTest(item_id=item_id), self.assertRaises(ValueError):
                render_outcome(
                    Outcome(
                        OutcomeKind.SHOP_PURCHASED,
                        actor="Alice",
                        item_id=item_id,
                        charged_experience=5,
                    )
                )

    def test_scheduled_reward_uses_the_canonical_duration(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.REWARD_TRIGGERED,
                actor="Alice",
                triggered_item_id=113,
            )
        )[0]
        self.assertIn("dans 10mn00s", line)

    def test_unknown_profile_has_one_clear_response(self) -> None:
        self.assertIn("aucun chasseur", render_profile(self.state, "Nobody")[0])

    def test_inventory_uses_the_reference_single_section_layout(self) -> None:
        lines = render_inventory(self.state, "Alice")
        self.assertEqual(len(lines), 1)
        self.assertIn("[Inventaire]", lines[0])
        self.assertIn("arme: mitraillette", lines[0])
        self.assertIn("mun.: 0/6", lines[0])
        self.assertIn("charg.: 1/2", lines[0])
        self.assertIn("gibecière: 0 canard", lines[0])
        self.assertNotIn("[Malédictions]", lines[0])

    def test_inventory_matches_the_reference_values_labels_and_wire_line(self) -> None:
        reference = player(
            "ReferenceHunter",
            level=94,
            ammo=1,
            capacity=1,
            magazines=5,
            magazine_capacity=5,
            inventory=(
                InventoryStack("indestructible_sunglasses", 1),
                InventoryStack("military_ammo_recycler", 1),
                InventoryStack("permanent_killing_license", 1),
            ),
            letter_slots=(True, False, False, False, False, False, False, False),
        )
        suppressor = ActiveEffect(
            effect_id=1,
            item_id=9,
            key="suppressor",
            scope=EffectScope.PLAYER,
            owner_key=reference.key,
            source_key=None,
            activated_at_ns=0,
            expires_at_ns=86_400_000_000_000,
        )
        lines = render_inventory(
            GameState(
                now_ns=1,
                players=(reference,),
                next_effect_id=2,
                effects=(suppressor,),
            ),
            "ReferenceHunter",
        )
        self.assertEqual(
            lines,
            (
                "\x0307[Inventaire]\x0f arme: arbalète | mun.: 1/1 | "
                "charg.: 5/5 | gibecière: 0 canard | "
                "lettres: D _ _ _   _ _ _ _",
                "| silencieux (23h59mn59s) | lunettes soleil | "
                "recycl. mun. (10%) | permis de tuer",
            ),
        )
        self.assertEqual(len(render_wire_notice("ReferenceHunter", lines)), 1)

    def test_inventory_reports_jammed_and_confiscated_weapon_states(self) -> None:
        jammed = GameState(players=(player("Jammed", jammed=True),))
        confiscated = GameState(players=(player("Gone", confiscated=True),))
        permanent = GameState(
            players=(
                player(
                    "Banned",
                    confiscated=True,
                    permanently_confiscated=True,
                ),
            )
        )
        self.assertIn("enrayée", render_inventory(jammed, "Jammed")[0])
        self.assertIn("confisquée", render_inventory(confiscated, "Gone")[0])
        self.assertIn(
            "confisquée définitivement",
            render_inventory(permanent, "Banned")[0],
        )

    def test_inventory_reports_shop_credit_and_reward_effect(self) -> None:
        credited = player("Credit", shop_credit=25)
        effect = ActiveEffect(
            1,
            101,
            "abundance_amulet",
            EffectScope.PLAYER,
            credited.key,
            None,
            0,
            expires_at_ns=86_400_000_000_000,
        )
        state = GameState(players=(credited,), next_effect_id=2, effects=(effect,))
        rendered = " ".join(render_inventory(state, "Credit"))
        self.assertIn("bon d'achat 25 xp", rendered)
        self.assertIn("abondance", rendered)

    def test_inventory_compacts_permanent_ammo_rewards_and_unlimited_reserve(self) -> None:
        equipped = player(
            "Equipped",
            inventory=(
                InventoryStack("extended_magazine", 1),
                InventoryStack("large_ammo_bag", 1),
                InventoryStack("military_ammo_recycler", 1),
            ),
        )
        warrior = ActiveEffect(
            1,
            116,
            "warrior_amulet",
            EffectScope.PLAYER,
            equipped.key,
            None,
            0,
            expires_at_ns=86_400_000_000_000,
        )
        state = GameState(players=(equipped,), next_effect_id=2, effects=(warrior,))
        rendered = " ".join(render_inventory(state, "Equipped"))
        self.assertIn("charg.: ∞", rendered)
        self.assertIn("chargeur étendu", rendered)
        self.assertIn("grande gibecière", rendered)
        self.assertIn("recycl. mun. (10%)", rendered)

    def test_inventory_reports_effect_deadline_uses_and_magnitude(self) -> None:
        effect = ActiveEffect(
            effect_id=1,
            item_id=10,
            key="lucky_charm",
            scope=EffectScope.PLAYER,
            owner_key=self.alice.key,
            source_key=None,
            activated_at_ns=0,
            expires_at_ns=86_400_000_000_000,
            magnitude=4,
        )
        state = GameState(players=(self.alice, self.bob), next_effect_id=2, effects=(effect,))
        rendered = " ".join(render_inventory(state, "Alice"))
        self.assertIn("trèfle", rendered)
        self.assertIn("24h00mn00s", rendered)
        self.assertIn("+4", rendered)

    def test_inventory_displays_the_remaining_bound_for_every_active_equipment(self) -> None:
        shop_effects = tuple(
            (
                item.item_id,
                item.key,
                item.scope,
                item.duration_ns,
                item.uses,
                item.magnitude_min,
                item.grant_kind is GrantKind.TARGET_EFFECT,
            )
            for item in SHOP_CATALOG
            if item.duration_ns is not None and item.scope is EffectScope.PLAYER
        )
        reward_effects = tuple(
            (
                item.item_id,
                item.key,
                EffectScope.PLAYER,
                item.duration_ns,
                item.uses,
                item.magnitude,
                False,
            )
            for item in REWARD_EFFECT_CATALOG
            if item.duration_ns is not None
        )
        for (
            item_id,
            key,
            scope,
            duration_ns,
            uses,
            magnitude,
            targeted,
        ) in (*shop_effects, *reward_effects):
            with self.subTest(key=key):
                assert duration_ns is not None
                effect = ActiveEffect(
                    effect_id=1,
                    item_id=item_id,
                    key=key,
                    scope=scope,
                    owner_key=self.alice.key,
                    source_key=self.bob.key if targeted else None,
                    activated_at_ns=0,
                    expires_at_ns=duration_ns,
                    remaining_uses=uses,
                    magnitude=magnitude,
                )
                rendered = " ".join(
                    render_inventory(
                        GameState(
                            players=(self.alice, self.bob),
                            next_effect_id=2,
                            effects=(effect,),
                        ),
                        "Alice",
                    )
                )
                remaining = format_duration_ns(duration_ns)
                self.assertIn(remaining, rendered)
                self.assertEqual(rendered.count(remaining), 1)

    def test_inventory_displays_remaining_uses_for_use_bounded_equipment(self) -> None:
        shop_effects = tuple(
            (item.item_id, item.key, item.uses, item.grant_kind is GrantKind.TARGET_EFFECT)
            for item in SHOP_CATALOG
            if item.duration_ns is None
            and item.uses is not None
            and item.scope is EffectScope.PLAYER
        )
        reward_effects = tuple(
            (item.item_id, item.key, item.uses, False)
            for item in REWARD_EFFECT_CATALOG
            if item.duration_ns is None and item.uses is not None
        )
        for item_id, key, uses, targeted in (*shop_effects, *reward_effects):
            with self.subTest(key=key):
                assert uses is not None
                effect = ActiveEffect(
                    effect_id=1,
                    item_id=item_id,
                    key=key,
                    scope=EffectScope.PLAYER,
                    owner_key=self.alice.key,
                    source_key=self.bob.key if targeted else None,
                    activated_at_ns=0,
                    remaining_uses=uses,
                )
                rendered = " ".join(
                    render_inventory(
                        GameState(
                            players=(self.alice, self.bob),
                            next_effect_id=2,
                            effects=(effect,),
                        ),
                        "Alice",
                    )
                )
                self.assertIn(f"{uses} util.", rendered)

    def test_inventory_lists_the_suppressor_once_before_other_items(self) -> None:
        suppressor = ActiveEffect(
            effect_id=1,
            item_id=9,
            key="suppressor",
            scope=EffectScope.PLAYER,
            owner_key=self.alice.key,
            source_key=None,
            activated_at_ns=0,
            expires_at_ns=86_400_000_000_000,
        )
        charm = ActiveEffect(
            effect_id=2,
            item_id=10,
            key="lucky_charm",
            scope=EffectScope.PLAYER,
            owner_key=self.alice.key,
            source_key=None,
            activated_at_ns=0,
            expires_at_ns=86_400_000_000_000,
            magnitude=2,
        )
        state = GameState(
            players=(self.alice, self.bob),
            next_effect_id=3,
            effects=(suppressor, charm),
        )
        lines = render_inventory(state, "Alice")
        rendered = " ".join(lines)
        self.assertIn("arme: mitraillette", lines[0])
        self.assertIn(
            "| silencieux (24h00mn00s) | trèfle à quatre feuilles",
            rendered,
        )
        self.assertEqual(rendered.count("silencieux"), 1)

    def test_bread_purchase_reports_cost_duration_channel_and_stack(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=21,
                charged_experience=4,
                channel_effect_count=2,
            ),
            channel="#pond",
        )[0]
        self.assertIn("4 points d'xp", line)
        self.assertIn("pendant 1h", line)
        self.assertIn("prochain envol", line)
        self.assertIn("karma temporaire", line)
        self.assertIn("2 morceaux de pain sur #pond", line)

    def test_duck_call_purchase_preserves_the_surprise_and_purchase_tags(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.SHOP_PURCHASED,
                actor="Alice",
                item_id=20,
                charged_experience=8,
                shop_credit_spent=8,
                discount_percent=10,
                due_at_ns=1_788_867_281_000_000_000,
            ),
            channel="#pond",
        )[0]
        self.assertIn("8 points d'xp", line)
        self.assertIn("achètes et utilises un appeau", line)
        self.assertIn("10 prochaines minutes", line)
        self.assertIn("[bon d'achat]", line)
        self.assertIn("[coupon promo.]", line)
        self.assertNotIn("quotidien", line)
        self.assertNotRegex(line, r"\d{2}:\d{2}|\d{4}-\d{2}-\d{2}|1788867281")

    def test_consumed_bread_is_visible_on_the_channel(self) -> None:
        self.assertEqual(
            render_outcome(
                Outcome(OutcomeKind.EFFECT_CONSUMED, item_id=21)
            ),
            ("Le canard mange un morceau de pain posé sur le canal.",),
        )

    def test_shop_is_one_flood_safe_optional_catalog_link(self) -> None:
        self.assertEqual(render_shop(), ("Boutique: !shop [id [cible]]",))
        lines = render_shop("https://games.example/duckhunt/shop/")
        self.assertEqual(len(lines), 1)
        self.assertIn("https://games.example/duckhunt/shop/", lines[0])
        self.assertIn("!shop [id [cible]]", lines[0])
        self.assertLessEqual(len(f"NOTICE {'X' * 30} :{lines[0]}\r\n".encode()), 512)
        longest = render_shop("https://games.example/" + "a" * 218)[0]
        self.assertLessEqual(len(f"NOTICE {'X' * 30} :{longest}\r\n".encode()), 512)
        with self.assertRaises(ValueError):
            render_shop("http://games.example/shop/")

    def test_query_receives_the_injected_shop_url(self) -> None:
        command = parse_command("!shop")
        assert command is not None
        line = render_query(
            self.state,
            "Alice",
            command,
            shop_url="https://games.example/duckhunt/shop/",
        )[0]
        self.assertIn("https://games.example/duckhunt/shop/", line)

    def test_ranking_orders_hits_then_best_time_then_identity(self) -> None:
        tied = player("Aaron", hits=20, best_time_ms=2000)
        state = GameState(
            players=tuple(
                sorted((self.alice, self.bob, tied), key=lambda item: item.key)
            )
        )
        line = render_ranking(state, limit=3)[0]
        self.assertLess(line.index("Aaron"), line.index("Bob"))
        self.assertLess(line.index("Bob"), line.index("Alice"))
        self.assertIn("\x0307[TOP 3]\x0f", line)
        self.assertIn("🥇", line)
        self.assertIn("🥈", line)
        self.assertIn("🥉", line)

    def test_ranking_defaults_to_five_and_appends_configured_page(self) -> None:
        players = tuple(
            player(f"Hunter{index}", hits=10 - index)
            for index in range(1, 8)
        )
        lines = render_ranking(
            GameState(players=players),
            ranking_url="https://io.teuk.org/DuckHunt/rankings",
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("\x0307[TOP 5]\x0f", lines[0])
        for index in range(1, 6):
            self.assertIn(f"Hunter{index}", lines[0])
        self.assertNotIn("Hunter6", lines[0])
        self.assertEqual(
            lines[1],
            "\x0312[Classement complet]\x0f "
            "https://io.teuk.org/DuckHunt/rankings",
        )

    def test_empty_ranking_is_explicit(self) -> None:
        self.assertIn("Aucun", render_ranking(GameState())[0])
        self.assertEqual(len(render_ranking(GameState())), 1)

    def test_ranking_rejects_unbounded_limit(self) -> None:
        with self.assertRaises(ValueError):
            render_ranking(self.state, limit=21)

    def test_last_flight_formats_injected_duration(self) -> None:
        self.assertIn("1h01mn01s", render_last_flight(3_661_000_000_000)[0])
        self.assertIn("Aucun", render_last_flight(None)[0])

    def test_last_flight_reports_a_durable_escape(self) -> None:
        record = LastFlight(
            4,
            FlightKind.STANDARD,
            1_000_000_000,
            301_000_000_000,
            LastFlightConclusion.ESCAPED,
        )
        line = render_last_flight(record, now_ns=361_000_000_000)[0]
        self.assertIn("envolé sans être touché", line)
        self.assertIn("5mn00s", line)
        self.assertIn("1mn00s", line)

    def test_query_defaults_profile_target_to_actor(self) -> None:
        command = parse_command("!duckstats")
        assert command is not None
        self.assertEqual(
            render_query(self.state, "Alice", command),
            render_profile(self.state, "Alice"),
        )

    def test_query_accepts_explicit_inventory_target(self) -> None:
        command = parse_command("!inventory Bob")
        assert command is not None
        self.assertIn("[Inventaire]", render_query(self.state, "Alice", command)[0])

    def test_query_renders_bounded_rank_request(self) -> None:
        command = parse_command("!duckrank 1")
        assert command is not None
        line = render_query(self.state, "Alice", command)[0]
        self.assertIn("Bob", line)
        self.assertNotIn("Alice", line)

    def test_query_omits_configured_non_playing_admin_from_ranking(self) -> None:
        command = parse_command("!duckrank")
        assert command is not None
        line = render_query(
            self.state,
            "Alice",
            command,
            statistics_excluded_nicknames=("Bob",),
        )[0]
        self.assertNotIn("Bob", line)
        self.assertIn("Alice", line)

    def test_query_hides_configured_non_playing_admin_profile(self) -> None:
        command = parse_command("!duckstats Bob")
        assert command is not None
        line = render_query(
            self.state,
            "Alice",
            command,
            statistics_excluded_nicknames=("Bob",),
        )[0]
        self.assertIn("aucun chasseur", line)
        self.assertNotIn("[Profil]", line)

    def test_query_injects_the_ranking_page_without_hard_coding_it(self) -> None:
        command = parse_command("!duckrank")
        assert command is not None
        lines = render_query(
            self.state,
            "Alice",
            command,
            ranking_url="https://rankings.example/duckhunt",
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("[TOP 5]", lines[0])
        self.assertIn("https://rankings.example/duckhunt", lines[1])

    def test_query_rejects_bad_public_syntax(self) -> None:
        command = parse_command("!duckrank all")
        assert command is not None
        with self.assertRaises(CommandSyntaxError):
            render_query(self.state, "Alice", command)

    def test_shop_purchase_is_not_a_read_only_query(self) -> None:
        command = parse_command("!shop 1")
        assert command is not None
        with self.assertRaises(ValueError):
            render_query(self.state, "Alice", command)

    def test_wire_response_is_utf8_valid_and_bounded(self) -> None:
        wires = render_wire_response("#pond", ("🦆" * 200,))
        self.assertEqual(len(wires), 1)
        self.assertLessEqual(len(wires[0]), MAX_WIRE_BYTES)
        wires[0].decode("utf-8")

    def test_wire_response_packs_adjacent_fragments_into_one_line(self) -> None:
        wires = render_wire_response("#pond", ("premier", "deuxième", "troisième"))
        self.assertEqual(
            wires,
            ("PRIVMSG #pond :premier  deuxième  troisième\r\n".encode(),),
        )

    def test_wire_notice_keeps_only_the_lines_required_by_the_byte_budget(self) -> None:
        short = render_wire_notice("Alice", ("un", "deux"))
        self.assertEqual(short, (b"NOTICE Alice :un  deux\r\n",))

        long = "x" * 494
        separated = render_wire_notice("Alice", (long, "fin"))
        self.assertEqual(len(separated), 2)
        self.assertLessEqual(max(map(len, separated)), MAX_WIRE_BYTES)

    def test_wire_response_rejects_too_many_lines(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_wire_response("#pond", ("x",) * (MAX_RESPONSE_LINES + 1))

    def test_wire_response_rejects_empty_line(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_wire_response("#pond", ("",))

    def test_hit_response_contains_priority_facts(self) -> None:
        outcome = Outcome(
            OutcomeKind.HIT,
            actor="Alice",
            player=self.alice,
            elapsed_ms=1234,
            experience_awarded=10,
        )
        line = render_outcome(outcome, channel="#pond")[0]
        for fact in ("Alice", "*BANG*", "1.234s", "12", "#pond", "10 xp", "niv. 2", "progression"):
            self.assertIn(fact, line)

    def test_hit_response_formats_long_elapsed_time_compactly(self) -> None:
        outcome = Outcome(
            OutcomeKind.HIT,
            actor="Alice",
            player=self.alice,
            elapsed_ms=154_200,
            experience_awarded=10,
        )
        line = render_outcome(outcome, channel="#pond")[0]
        self.assertIn("canard en 2mn34.2s", line)
        self.assertNotIn("154.2s", line)

    def test_explosive_hit_uses_the_reference_boum_sound(self) -> None:
        outcome = Outcome(
            OutcomeKind.HIT,
            actor="Alice",
            player=self.alice,
            elapsed_ms=1234,
            experience_awarded=10,
            ammunition_item_id=4,
        )
        line = render_outcome(outcome, channel="#pond")[0]
        self.assertIn("*BOUM*", line)
        self.assertNotIn("*BANG*", line)
        self.assertNotIn("[mun. expl.]", line)

    def test_golden_ammunition_identity_matches_the_reference_labels(self) -> None:
        explosive = Outcome(
            OutcomeKind.HIT,
            actor="Alice",
            player=self.alice,
            flight_kind=FlightKind.GOLDEN,
            elapsed_ms=1234,
            experience_awarded=36,
            ammunition_item_id=4,
        )
        penetrating = Outcome(
            OutcomeKind.HIT,
            actor="Alice",
            player=self.alice,
            flight_kind=FlightKind.GOLDEN,
            elapsed_ms=1234,
            experience_awarded=36,
            ammunition_item_id=3,
        )
        explosive_line = render_outcome(explosive, channel="#pond")[0]
        penetrating_line = render_outcome(penetrating, channel="#pond")[0]
        self.assertIn("*BOUM*", explosive_line)
        self.assertIn("[mun. expl.]", explosive_line)
        self.assertIn("*BANG*", penetrating_line)
        self.assertIn("[mun. AP]", penetrating_line)

    def test_explosive_golden_survivor_uses_boum_without_inventing_a_tag(self) -> None:
        outcome = Outcome(
            OutcomeKind.FLIGHT_SURVIVED,
            actor="Alice",
            flight_kind=FlightKind.GOLDEN,
            damage_dealt=3,
            ammunition_item_id=4,
        )
        line = render_outcome(outcome)[0]
        self.assertIn("*BOUM*", line)
        self.assertNotIn("*BANG*", line)
        self.assertNotIn("[mun. expl.]", line)

    def test_reload_response_contains_current_reserves(self) -> None:
        line = render_outcome(
            Outcome(OutcomeKind.RELOADED, actor="Alice", player=self.alice)
        )[0]
        self.assertIn("0/6", line)
        self.assertIn("1/2", line)

    def test_refused_partial_reload_keeps_ammunition_and_reserves_visible(self) -> None:
        current = player("Alice", ammo=5, magazines=2)
        line = render_outcome(
            Outcome(OutcomeKind.ALREADY_LOADED, actor="Alice", player=current)
        )[0]
        self.assertIn("Ton arme n'a pas besoin d'être rechargée.", line)
        self.assertIn("Mun. : 5/6", line)
        self.assertIn("Charg. : 2/2", line)

    def test_automatic_reload_is_labeled(self) -> None:
        line = render_outcome(
            Outcome(
                OutcomeKind.RELOADED,
                actor="Alice",
                player=self.alice,
                item_id=30,
                automatic=True,
            )
        )[0]
        self.assertIn("rechargement auto", line)

    def test_curse_delay_and_block_have_player_responses(self) -> None:
        self.assertIn(
            "retardée de 5s",
            render_outcome(Outcome(OutcomeKind.COMMAND_DELAYED, actor="Alice"))[0],
        )
        self.assertIn(
            "empêche de recharger",
            render_outcome(Outcome(OutcomeKind.CURSE_BLOCKED, actor="Alice"))[0],
        )

    def test_throttle_notice_is_rendered_and_quiet_repeats_are_silent(self) -> None:
        notice = Outcome(
            OutcomeKind.COMMAND_THROTTLED,
            actor="Alice",
            due_at_ns=1_000_000_000,
            defer_until_ns=31_000_000_000,
            notice_emitted=True,
        )
        self.assertIn("30s", render_outcome(notice)[0])
        self.assertEqual(
            render_outcome(
                Outcome(OutcomeKind.COMMAND_THROTTLED, actor="Alice")
            ),
            (),
        )

    def test_bookkeeping_outcomes_are_silent(self) -> None:
        for kind in (
            OutcomeKind.EFFECT_EXPIRED,
            OutcomeKind.CHANNEL_ACTION_DUE,
            OutcomeKind.DUCK_ALERT,
            OutcomeKind.CURSE_EXPIRED,
            OutcomeKind.QUERY,
        ):
            self.assertEqual(render_outcome(Outcome(kind)), ())

    def test_outcome_flattening_preserves_order(self) -> None:
        lines = render_outcomes(
            (
                Outcome(OutcomeKind.EMPTY, actor="Alice"),
                Outcome(OutcomeKind.JAMMED, actor="Bob"),
            )
        )
        self.assertTrue(lines[0].startswith("Alice"))
        self.assertTrue(lines[1].startswith("Bob"))

    def test_outcome_flattening_summarizes_overflow(self) -> None:
        lines = render_outcomes(
            tuple(Outcome(OutcomeKind.EMPTY, actor=str(index)) for index in range(5))
        )
        self.assertEqual(len(lines), MAX_RESPONSE_LINES)
        self.assertIn("+2 événements", lines[-1])

    def test_every_outcome_kind_has_a_renderer(self) -> None:
        for kind in OutcomeKind:
            rendered = render_outcome(Outcome(kind, actor="Alice", target="Bob"))
            self.assertIsInstance(rendered, tuple, kind)


if __name__ == "__main__":
    unittest.main()
