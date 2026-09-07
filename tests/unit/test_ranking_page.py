from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.model import GameState, PlayerState
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
            "Dorés",
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

    def test_long_best_times_use_the_same_compact_duration(self) -> None:
        rendered = render_ranking_page(
            GameState(players=(player("Hunter", hits=1, best_time_ms=3_903_000),))
        ).decode("utf-8")
        self.assertIn("1h05mn03s", rendered)

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
