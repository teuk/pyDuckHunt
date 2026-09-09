from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    GameState,
    InventoryStack,
    PlayerState,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.publishing import RankingPagePublisher, render_ranking_page


def player(nickname: str, **values: object) -> PlayerState:
    return PlayerState(
        key=rfc1459_casefold(nickname),
        nickname=nickname,
        **values,
    )


class RankingPageTests(unittest.TestCase):
    def test_empty_page_is_standalone_scriptless_and_responsive(self) -> None:
        rendered = render_ranking_page(GameState()).decode("utf-8")
        self.assertTrue(rendered.startswith("<!doctype html>"))
        self.assertIn("PYDUCKHUNT_RANKING_PAGE_V1", rendered)
        self.assertIn('data-pyduckhunt-ranking="1"', rendered)
        self.assertIn("Aucun chasseur classé", rendered)
        self.assertIn("@media(max-width:700px)", rendered)
        self.assertIn('href="/DuckHunt/rankings/" aria-current="page"', rendered)
        self.assertIn("DH051 — quiet technical editorial refinement", rendered)
        self.assertIn(".site-noise{display:none}", rendered)
        self.assertIn(".header-inner{height:64px", rendered)
        self.assertIn(".ranking-table-shell{margin-top:12px", rendered)
        self.assertNotIn("<script", rendered.casefold())

    def test_order_matches_hits_best_time_and_canonical_identity(self) -> None:
        hunters = tuple(
            sorted(
                (
                    player("Zulu", hits=9, best_time_ms=450),
                    player("A&B", hits=12, best_time_ms=700, golden_hits=2),
                    player("Alpha", hits=12, best_time_ms=500, level=2, experience=3),
                ),
                key=lambda candidate: candidate.key,
            )
        )
        rendered = render_ranking_page(
            GameState(now_ns=1_788_134_400_000_000_000, players=hunters)
        ).decode("utf-8")
        self.assertLess(rendered.index("Alpha"), rendered.index("A&amp;B"))
        self.assertLess(rendered.index("A&amp;B"), rendered.index("Zulu"))
        self.assertNotIn("A&B", rendered)
        self.assertIn("0.5s", rendered)
        self.assertIn("0.7s", rendered)
        self.assertIn("0.45s", rendered)
        for label in (
            "Canards",
            "Canards dorés",
            "Meilleur temps",
            "Niveau",
            "XP",
            "Arme",
            "Précision",
            "Karma",
            "Fatigue",
            "Munitions",
            "Chargeurs",
            "Confiscations",
            "Décès",
        ):
            self.assertIn(label, rendered)

    def test_compact_table_keeps_every_metric_inside_eleven_columns(self) -> None:
        hunter = player(
            "Hunter",
            hits=39,
            golden_hits=2,
            best_time_ms=1_514,
            level=9,
            experience=48,
            fatigue_centi=1_600,
            ammo=4,
            magazines=1,
            misses=18,
            wild_shots=2,
            empty_shots=3,
            jammed_shots=4,
            compulsive_reloads=5,
            confiscations=6,
            shots_received=7,
            incidents_deflected=8,
            incidents_absorbed=9,
            deaths=10,
        )
        rendered = render_ranking_page(GameState(players=(hunter,))).decode("utf-8")
        row = rendered.split('<tr class="rank-1">', 1)[1].split("</tr>", 1)[0]

        self.assertEqual(rendered.count('<th scope="col">'), 11)
        self.assertEqual(row.count("<td "), 11)
        self.assertIn('<colgroup><col class="col-place">', rendered)
        self.assertIn('<col class="col-inventory"></colgroup>', rendered)
        self.assertIn(
            ".ranking-table-shell table{width:100%;min-width:0;table-layout:fixed}",
            rendered,
        )
        self.assertIn("@media(max-width:1180px)", rendered)
        self.assertLess(row.index('data-label="Accidents"'), row.index('data-label="Inventaire"'))
        for fact in (
            "Canards : 39",
            "Canards dorés : 2",
            "Niveau : 9",
            "XP disponible : 48",
            "Fatigue : 16",
            "Munitions : 4/6",
            "Chargeurs : 1/2",
            "Tirs ratés : 18",
            "Tirs sauvages : 2",
            "Tirs à vide : 3",
            "Arme enrayée : 4",
            "Rechargements compulsifs : 5",
            "Confiscations : 6",
            "Tirs reçus : 7",
            "Tirs déviés : 8",
            "Tirs absorbés : 9",
            "Décès : 10",
        ):
            self.assertIn(fact, rendered)

    def test_long_best_times_use_the_same_compact_duration(self) -> None:
        rendered = render_ranking_page(
            GameState(players=(player("Hunter", hits=1, best_time_ms=3_903_000),))
        ).decode("utf-8")
        self.assertIn("1h05mn03s", rendered)

    def test_configured_admin_is_absent_from_page_and_summary_totals(self) -> None:
        hunters = tuple(
            sorted(
                (
                    player("Te[u]K", hits=99, golden_hits=4, best_time_ms=100),
                    player("gaby", hits=12, golden_hits=1, best_time_ms=500),
                ),
                key=lambda candidate: candidate.key,
            )
        )
        rendered = render_ranking_page(
            GameState(players=hunters),
            excluded_nicknames=("Te[u]K",),
        ).decode("utf-8")
        self.assertNotIn("Te[u]K", rendered)
        self.assertIn("gaby", rendered)
        self.assertIn("<strong>1</strong>", rendered)
        self.assertIn("<strong>12</strong>", rendered)

    def test_inventory_bag_matches_irc_facts_without_scripts_or_raw_formatting(self) -> None:
        hunter = player(
            "A&B",
            ammo=2,
            magazines=1,
            carried_ducks=2,
            letter_slots=(True, False, True, False, True, False, True, False),
            inventory=(InventoryStack("extended_magazine", 1),),
            shop_credit=12,
        )
        state = GameState(
            now_ns=1_000_000_000,
            players=(hunter,),
            next_effect_id=3,
            effects=(
                ActiveEffect(
                    effect_id=1,
                    item_id=9,
                    key="suppressor",
                    scope=EffectScope.PLAYER,
                    owner_key=hunter.key,
                    source_key=hunter.key,
                    activated_at_ns=1,
                    expires_at_ns=3_601_000_000_000,
                ),
                ActiveEffect(
                    effect_id=2,
                    item_id=21,
                    key="channel_bread",
                    scope=EffectScope.CHANNEL,
                    owner_key=None,
                    source_key=None,
                    activated_at_ns=1,
                    expires_at_ns=3_601_000_000_000,
                ),
            ),
            next_curse_id=2,
            curses=(
                ActiveCurse(
                    curse_id=1,
                    key="blinded",
                    owner_key=hunter.key,
                    activated_at_ns=1,
                    expires_at_ns=3_601_000_000_000,
                ),
            ),
        )

        rendered = render_ranking_page(state).decode("utf-8")

        self.assertIn('<th scope="col">Inventaire</th>', rendered)
        self.assertIn('<td class="inventory-cell" data-label="Inventaire">', rendered)
        self.assertIn('class="inventory-details" data-inventory="1"', rendered)
        self.assertIn('title="Inventaire de A&amp;B&#10;', rendered)
        self.assertIn('aria-label="Afficher l’inventaire de A&amp;B"', rendered)
        for fact in (
            "mun.: 2/6",
            "charg.: 1/2",
            "gibecière: 2 canards",
            "lettres: D _ C _   H _ N _",
            "chargeur étendu",
            "silencieux",
            "bon d&#x27;achat 12 xp",
            "1 morceau de pain sur #i/o",
            "malédiction: blinded",
        ):
            self.assertIn(fact, rendered)
        self.assertNotIn("A&B", rendered)
        self.assertNotIn("\x02", rendered)
        self.assertNotIn("\x03", rendered)
        self.assertNotIn("<script", rendered.casefold())

    def test_publisher_replaces_one_regular_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "player-rankings.html"
            publisher = RankingPagePublisher(target)
            publisher.publish(GameState())
            first = target.read_bytes()
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)
            self.assertEqual(
                tuple(root.glob(f".{target.name}.*")),
                (),
            )
            hunter = player("Hunter", hits=1, best_time_ms=321)
            publisher.publish(GameState(now_ns=1, players=(hunter,)))
            self.assertNotEqual(target.read_bytes(), first)
            self.assertIn(b"Hunter", target.read_bytes())

    def test_publisher_rejects_unsafe_paths_and_symlink_targets(self) -> None:
        for path in ("relative.html", "/", "/tmp/not-html.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                RankingPagePublisher(path)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real.html"
            real.write_text("safe", encoding="utf-8")
            linked = root / "ranking.html"
            linked.symlink_to(real)
            with self.assertRaises(ValueError):
                RankingPagePublisher(linked).publish(GameState())


if __name__ == "__main__":
    unittest.main()
