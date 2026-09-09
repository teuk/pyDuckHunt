"""Standalone, responsive HTML ranking generated from one immutable state."""

from __future__ import annotations

import html
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pyduckhunt.game.karma import player_karma_basis_points
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import FATIGUE_SCALE, GameState, PlayerState
from pyduckhunt.game.progression import available_experience
from pyduckhunt.game.ranking import ranked_players
from pyduckhunt.publishing.ranking_style import DH051_REFINEMENT_STYLE
from pyduckhunt.rendering.responses import render_inventory
from pyduckhunt.time_format import format_duration_ms


MAX_RANKING_PAGE_BYTES = 4 * 1024 * 1024


class RankingPagePublisher:
    """Commit one generated page through an fsync-backed atomic replacement."""

    def __init__(
        self,
        path: str | Path,
        *,
        excluded_nicknames: tuple[str, ...] = (),
    ) -> None:
        target = Path(path)
        if (
            not target.is_absolute()
            or target == Path("/")
            or target.name in ("", ".", "..")
            or target.suffix.casefold() != ".html"
            or ".." in target.parts
        ):
            raise ValueError("ranking page target must be a safe absolute HTML path")
        self.path = target
        self.excluded_nicknames = excluded_nicknames

    def publish(self, state: GameState) -> None:
        """Render and atomically replace the configured page."""

        encoded = render_ranking_page(
            state,
            excluded_nicknames=self.excluded_nicknames,
        )
        if len(encoded) > MAX_RANKING_PAGE_BYTES:
            raise ValueError("ranking page exceeds the bounded size")
        parent = self.path.parent
        _validate_publish_directory(parent)
        _validate_existing_target(self.path)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.fchmod(handle.fileno(), 0o644)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def render_ranking_page(
    state: GameState,
    *,
    excluded_nicknames: tuple[str, ...] = (),
) -> bytes:
    """Render one deterministic UTF-8 page without scripts or external input."""

    if not isinstance(state, GameState):
        raise ValueError("ranking page requires a game state")
    players = ranked_players(state, excluded_nicknames=excluded_nicknames)
    summary = _summary(state, players)
    podium = _podium(players)
    table = _table(state, players)
    updated = _updated_at(state.now_ns)
    document = f"""<!doctype html>
<html lang="fr" data-pyduckhunt-ranking="1">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="generator" content="Coin / pyDuckHunt">
  <meta name="color-scheme" content="dark">
  <meta name="theme-color" content="#071013">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'">
  <title>Classement pyDuckHunt — i/o</title>
  <meta name="description" content="Classement public et statistiques des chasseurs pyDuckHunt sur i/o.">
  <style>{_STYLE}{DH051_REFINEMENT_STYLE}{_INVENTORY_STYLE}</style>
</head>
<body>
  <!-- PYDUCKHUNT_RANKING_PAGE_V1 -->
  <div class="site-noise" aria-hidden="true"></div>
  <header class="site-header">
    <div class="site-container header-inner">
      <a class="brand" href="/" aria-label="i/o — accueil"><span class="brand-mark">i/o</span><span class="brand-copy">Epiknet<br>mediabot_v3</span></a>
      <nav class="primary-nav" aria-label="Navigation principale"><a href="/">Accueil</a><a href="/#mediabot">Mediabot</a><a href="/DuckHunt/">DuckHunt</a><a href="/#connexion">Connexion</a></nav>
      <div class="header-status"><i></i><span>Coin en ligne</span></div>
    </div>
  </header>
  <div class="duckhunt-subnav">
    <div class="site-container duckhunt-subnav-inner">
      <a class="duckhunt-subbrand" href="/DuckHunt/"><span class="target-mark" aria-hidden="true">◎</span> Coin / pyDuckHunt</a>
      <nav aria-label="Navigation pyDuckHunt"><a href="/DuckHunt/">Vue d’ensemble</a><a href="/DuckHunt/shop/">Boutique</a><a href="/DuckHunt/levels/">Niveaux</a><a href="/DuckHunt/commands/">Commandes</a><a href="/DuckHunt/rankings/" aria-current="page">Classement</a></nav>
    </div>
  </div>
  <main>
    <section class="ranking-hero">
      <div class="site-container hero-grid">
        <div>
          <div class="eyebrow"><span></span>TABLEAU DE CHASSE · DONNÉES DURABLES</div>
          <h1>Classement des <em>chasseurs.</em></h1>
          <p>Les places suivent le nombre de canards touchés, puis le meilleur temps et l’identité IRC canonique pour départager les égalités.</p>
        </div>
        <div class="hero-signal" aria-hidden="true"><span>RANK</span><b>01</b><i>\\_O&lt;</i></div>
      </div>
    </section>
    <section class="site-container summary-grid" aria-label="Résumé du classement">{summary}</section>
    <section class="site-container ranking-section">
      <div class="section-heading"><div><span>LE PODIUM</span><h2>Les fines gâchettes du canal.</h2></div><p>Actualisé automatiquement par Coin après chaque changement durable.</p></div>
      {podium}
      <div class="table-heading"><div><span>TABLEAU COMPLET</span><h2>Tous les chasseurs</h2></div><time datetime="{_datetime_attribute(state.now_ns)}">Mise à jour : {updated}</time></div>
      {table}
      <p class="ranking-note">XP désigne le solde actuellement disponible. La précision affichée est celle de l’arme au niveau courant.</p>
    </section>
  </main>
  <footer class="site-footer"><div class="site-container footer-inner"><span>io.teuk.org · Coin / pyDuckHunt</span><span>Classement généré depuis l’état durable du jeu.</span></div></footer>
</body>
</html>
"""
    return document.encode("utf-8")


def _summary(state: GameState, players: tuple[PlayerState, ...]) -> str:
    total_hits = sum(player.hits for player in players)
    total_golden = sum(player.golden_hits for player in players)
    best = min(
        (player.best_time_ms for player in players if player.best_time_ms is not None),
        default=None,
    )
    facts = (
        ("Chasseurs", str(len(players))),
        ("Canards touchés", _integer(total_hits)),
        ("Canards dorés", _integer(total_golden)),
        ("Meilleur temps", _time(best)),
    )
    return "".join(
        f'<article><span>{label}</span><strong>{value}</strong></article>'
        for label, value in facts
    )


def _podium(players: tuple[PlayerState, ...]) -> str:
    if not players:
        return '<div class="empty-state"><b>\\_O&lt;</b><strong>Aucun chasseur classé.</strong><span>Le premier tir réussi ouvrira le tableau.</span></div>'
    cards = []
    for place, player in enumerate(players[:3], start=1):
        policy = level_policy(player.level)
        cards.append(
            f'<article class="podium-card place-{place}"><span class="place">#{place:02d}</span>'
            f'<div class="podium-name">{_escape(player.nickname)}</div>'
            f'<div class="podium-score"><strong>{_integer(player.hits)}</strong><span>canards</span></div>'
            f'<div class="podium-meta"><span>Niv. {player.level}</span><span>{_escape(policy.weapon_label)}</span><span>{_time(player.best_time_ms)}</span></div></article>'
        )
    return '<div class="podium-grid">' + "".join(cards) + "</div>"


def _table(state: GameState, players: tuple[PlayerState, ...]) -> str:
    if not players:
        return '<div class="table-empty">En attente du premier chasseur.</div>'
    rows = []
    for place, player in enumerate(players, start=1):
        policy = level_policy(player.level)
        values = (
            ("Place", f'<span class="rank-badge">{place}</span>', "place-cell"),
            (
                "Chasseur",
                f'<strong class="hunter">{_escape(player.nickname)}</strong>',
                "hunter-cell",
            ),
            (
                "Chasse",
                _fact_group(
                    (
                        ("Canards", "can.", _integer(player.hits)),
                        ("Canards dorés", "dorés", _integer(player.golden_hits)),
                    )
                ),
                "hunt-cell",
            ),
            ("Meilleur temps", _time(player.best_time_ms), "time-cell"),
            (
                "Progression",
                _fact_group(
                    (
                        ("Niveau", "niv.", str(player.level)),
                        ("XP disponible", "xp", _integer(available_experience(player))),
                    )
                ),
                "progress-cell",
            ),
            ("Arme", _escape(policy.weapon_label), "weapon-cell"),
            (
                "État",
                _fact_group(
                    (
                        ("Précision", "préc.", _percent(policy.accuracy_bps)),
                        (
                            "Karma",
                            "karma",
                            _signed_percent(player_karma_basis_points(player)),
                        ),
                        ("Fatigue", "fat.", _decimal(player.fatigue_centi)),
                    )
                ),
                "condition-cell",
            ),
            (
                "Charge",
                _fact_group(
                    (
                        ("Munitions", "mun.", f"{player.ammo}/{player.capacity}"),
                        (
                            "Chargeurs",
                            "charg.",
                            f"{player.magazines}/{player.magazine_capacity}",
                        ),
                    )
                ),
                "ammunition-cell",
            ),
            (
                "Tirs",
                _fact_group(
                    (
                        ("Tirs ratés", "ratés", _integer(player.misses)),
                        ("Tirs sauvages", "sauv.", _integer(player.wild_shots)),
                        ("Tirs à vide", "vide", _integer(player.empty_shots)),
                        ("Arme enrayée", "enray.", _integer(player.jammed_shots)),
                        (
                            "Rechargements compulsifs",
                            "recharg.",
                            _integer(player.compulsive_reloads),
                        ),
                        (
                            "Confiscations",
                            "confisq.",
                            _integer(player.confiscations),
                        ),
                    ),
                    columns=3,
                ),
                "shots-cell",
            ),
            (
                "Accidents",
                _fact_group(
                    (
                        ("Tirs reçus", "reçus", _integer(player.shots_received)),
                        (
                            "Tirs déviés",
                            "déviés",
                            _integer(player.incidents_deflected),
                        ),
                        (
                            "Tirs absorbés",
                            "absorb.",
                            _integer(player.incidents_absorbed),
                        ),
                        ("Décès", "décès", _integer(player.deaths)),
                    )
                ),
                "incidents-cell",
            ),
            ("Inventaire", _inventory_details(state, player), "inventory-cell"),
        )
        cells = "".join(
            _table_cell(label, value, class_name=class_name)
            for label, value, class_name in values
        )
        rows.append(f'<tr class="rank-{place}">{cells}</tr>')
    headings = (
        "Place",
        "Chasseur",
        "Chasse",
        "Meilleur temps",
        "Progression",
        "Arme",
        "État",
        "Charge",
        "Tirs",
        "Accidents",
        "Inventaire",
    )
    header = "".join(f'<th scope="col">{heading}</th>' for heading in headings)
    return (
        '<div class="ranking-table-shell" aria-label="Tableau complet du classement">'
        '<table><caption>Classement complet des chasseurs pyDuckHunt</caption>'
        '<colgroup><col class="col-place"><col class="col-hunter"><col class="col-hunt">'
        '<col class="col-time"><col class="col-progress"><col class="col-weapon">'
        '<col class="col-condition"><col class="col-ammunition"><col class="col-shots">'
        '<col class="col-incidents"><col class="col-inventory"></colgroup>'
        f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _table_cell(label: str, value: str, *, class_name: str) -> str:
    return f'<td class="{class_name}" data-label="{label}">{value}</td>'


def _fact_group(
    facts: tuple[tuple[str, str, str], ...],
    *,
    columns: int = 2,
) -> str:
    if columns not in (2, 3):
        raise ValueError("fact group must use two or three columns")
    items = "".join(
        f'<span title="{_escape_attribute(label)} : {_escape_attribute(value)}" '
        f'aria-label="{_escape_attribute(label)} : {_escape_attribute(value)}">'
        f"<b>{value}</b><small>{_escape(short_label)}</small></span>"
        for label, short_label, value in facts
    )
    return f'<div class="cell-facts facts-{columns}">{items}</div>'


def _inventory_details(state: GameState, player: PlayerState) -> str:
    lines = tuple(
        cleaned
        for raw_line in render_inventory(state, player.nickname, channel="#i/o")
        for cleaned in (_plain_inventory_line(raw_line),)
        if cleaned
    )
    items = tuple(
        item.strip()
        for line in lines
        for item in line.split(" | ")
        if item.strip()
    )
    label = f"Inventaire de {player.nickname}"
    tooltip = label + "\n" + "\n".join(lines)
    contents = "".join(f"<li>{_escape(item)}</li>" for item in items)
    return (
        '<details class="inventory-details" data-inventory="1">'
        f'<summary title="{_escape_attribute(tooltip)}" '
        f'aria-label="Afficher l’inventaire de {_escape_attribute(player.nickname)}">'
        '<span class="inventory-icon" aria-hidden="true">🎒</span>'
        '<span class="sr-only">Afficher l’inventaire</span></summary>'
        f'<div class="inventory-panel"><strong>{_escape(label)}</strong>'
        f'<ul>{contents}</ul></div></details>'
    )


def _plain_inventory_line(value: str) -> str:
    cleaned = _IRC_FORMATTING.sub("", value).strip()
    if cleaned.startswith("[Inventaire] "):
        cleaned = cleaned.removeprefix("[Inventaire] ")
    return cleaned.removeprefix("| ").strip()


def _updated_at(value_ns: int) -> str:
    if value_ns == 0:
        return "initialisation"
    try:
        return datetime.fromtimestamp(value_ns / 1_000_000_000, UTC).strftime(
            "%d/%m/%Y %H:%M:%S UTC"
        )
    except (OSError, OverflowError, ValueError):
        return f"horodatage durable {value_ns} ns"


def _datetime_attribute(value_ns: int) -> str:
    if value_ns == 0:
        return ""
    try:
        return datetime.fromtimestamp(value_ns / 1_000_000_000, UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _escape_attribute(value: str) -> str:
    return _escape(value).replace("\n", "&#10;")


def _integer(value: int) -> str:
    return f"{value:,}".replace(",", "\u202f")


def _time(value_ms: int | None) -> str:
    if value_ms is None:
        return "—"
    return _escape(format_duration_ms(value_ms))


def _percent(value_bps: int) -> str:
    whole, fraction = divmod(value_bps, 100)
    return f"{whole}%" if fraction == 0 else f"{whole}.{fraction:02d}%"


def _signed_percent(value_bps: int) -> str:
    sign = "+" if value_bps > 0 else ""
    return sign + _percent(value_bps)


def _decimal(value_centi: int) -> str:
    sign = "-" if value_centi < 0 else ""
    whole, fraction = divmod(abs(value_centi), FATIGUE_SCALE)
    return sign + (str(whole) if fraction == 0 else f"{whole}.{fraction:02d}".rstrip("0"))


def _validate_publish_directory(path: Path) -> None:
    if not path.exists() or not path.is_dir() or path.is_symlink():
        raise ValueError("ranking page directory must be one real existing directory")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("ranking page directory cannot cross a symbolic link")


def _validate_existing_target(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("ranking page target must be one regular file")


_STYLE = r"""
:root{--background:#071013;--foreground:#edf6f3;--card:#0b171a;--card-2:#0e1e21;--line:#1b3033;--text-soft:#9bb0ae;--amber:#f4b740;--amber-soft:#ffd878;--cyan:#62dfd1;--cyan-dark:#0f3535;--danger:#ff6b55;color-scheme:dark}*{box-sizing:border-box}html{background:var(--background);scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 76% 16%,#0f35354f 0,transparent 30%),var(--background);color:var(--foreground);font-family:"Avenir Next",Avenir,"Segoe UI",sans-serif;line-height:1.5}.site-noise{position:fixed;inset:0;pointer-events:none;opacity:.03;background-image:repeating-linear-gradient(0deg,#fff 0,#fff 1px,transparent 1px,transparent 3px);z-index:10}.site-container{width:min(100% - 48px,1180px);margin-inline:auto}.site-header{position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);background:#071013ed;backdrop-filter:blur(18px)}.header-inner{height:74px;display:flex;align-items:center;justify-content:space-between;gap:28px}.brand,.duckhunt-subbrand{color:inherit;text-decoration:none}.brand{display:flex;align-items:center;gap:12px}.brand-mark{color:var(--amber);font:800 24px/1 ui-monospace,monospace;letter-spacing:-.08em}.brand-copy{color:#6e8986;font:9px/1.35 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.12em}.primary-nav{display:flex;gap:28px}.primary-nav a,.duckhunt-subnav nav a{color:#90a5a3;text-decoration:none;font:10px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}.primary-nav a:hover,.duckhunt-subnav nav a:hover,.duckhunt-subnav nav a[aria-current=page]{color:var(--amber)}.header-status{display:flex;align-items:center;gap:8px;color:var(--cyan);font:9px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.header-status i,.eyebrow span{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 10px var(--cyan)}.duckhunt-subnav{position:sticky;top:74px;z-index:4;border-bottom:1px solid var(--line);background:#0b171af2}.duckhunt-subnav-inner{min-height:52px;display:flex;align-items:center;justify-content:space-between;gap:24px}.duckhunt-subbrand{display:flex;align-items:center;gap:8px;font:600 11px/1 ui-monospace,monospace}.target-mark{color:var(--amber);font-size:20px}.duckhunt-subnav nav{display:flex;gap:20px;align-items:center}.ranking-hero{border-bottom:1px solid var(--line);background:linear-gradient(115deg,#0f353564,#071013 55%,#f4b7400d)}.hero-grid{min-height:310px;display:grid;grid-template-columns:1fr 250px;align-items:center;gap:70px;padding-block:48px}.eyebrow{display:flex;align-items:center;gap:10px;color:var(--cyan);font:9px/1 ui-monospace,monospace;letter-spacing:.13em}.hero-grid h1{margin:18px 0 14px;font-size:clamp(32px,4.1vw,54px);line-height:1.03;letter-spacing:-.05em}.hero-grid h1 em{color:var(--amber);font-style:normal}.hero-grid p{max-width:720px;margin:0;color:var(--text-soft);font-size:14px;line-height:1.75}.hero-signal{position:relative;height:190px;border:1px solid #29484a;border-radius:50%;display:grid;place-items:center;background:repeating-radial-gradient(circle,#62dfd10d 0 1px,transparent 1px 34px);box-shadow:inset 0 0 60px #62dfd10c}.hero-signal:after{content:"";position:absolute;inset:50% 0 auto;border-top:1px solid #62dfd133;transform:rotate(-28deg)}.hero-signal span{position:absolute;top:24px;color:#58726f;font:8px/1 ui-monospace,monospace;letter-spacing:.15em}.hero-signal b{color:var(--amber);font:700 44px/1 ui-monospace,monospace}.hero-signal i{position:absolute;bottom:24px;color:var(--cyan);font:14px/1 ui-monospace,monospace;font-style:normal}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);margin-top:14px;border:1px solid var(--line);border-radius:10px;overflow:hidden}.summary-grid article{min-height:92px;padding:20px 24px;background:linear-gradient(145deg,#0e1e21eb,#071013f5);border-right:1px solid var(--line);display:flex;flex-direction:column;justify-content:center}.summary-grid article:last-child{border-right:0}.summary-grid span{color:#6f8784;font:8px/1.2 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.12em}.summary-grid strong{margin-top:10px;color:var(--foreground);font:600 21px/1 ui-monospace,monospace}.ranking-section{padding-block:70px 90px}.section-heading,.table-heading{display:flex;align-items:end;justify-content:space-between;gap:32px}.section-heading>div>span,.table-heading>div>span{color:var(--amber);font:8px/1 ui-monospace,monospace;letter-spacing:.14em}.section-heading h2,.table-heading h2{margin:10px 0 0;font-size:30px;letter-spacing:-.035em}.section-heading p{max-width:390px;margin:0;color:var(--text-soft);font-size:12px;text-align:right}.podium-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:28px}.podium-card{position:relative;min-height:220px;padding:25px;border:1px solid var(--line);border-radius:11px;overflow:hidden;background:linear-gradient(145deg,#0e1e21,#071013)}.podium-card:after{content:"";position:absolute;width:170px;height:170px;right:-76px;top:-70px;border:1px solid #62dfd116;border-radius:50%;box-shadow:0 0 0 32px #62dfd108,0 0 0 64px #62dfd105}.podium-card.place-1{border-color:#f4b74070;background:linear-gradient(145deg,#f4b74018,#071013)}.podium-card .place{position:relative;z-index:1;color:var(--amber);font:700 11px/1 ui-monospace,monospace;letter-spacing:.13em}.podium-name{position:relative;z-index:1;margin-top:42px;font-size:24px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.podium-score{position:relative;z-index:1;display:flex;align-items:baseline;gap:8px;margin-top:10px}.podium-score strong{color:var(--cyan);font:650 28px/1 ui-monospace,monospace}.podium-score span{color:#6e8784;font:8px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.podium-meta{position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:7px;margin-top:25px}.podium-meta span{padding:6px 8px;border:1px solid #284346;border-radius:4px;color:#93aaa7;font:8px/1 ui-monospace,monospace}.empty-state,.table-empty{margin-top:28px;border:1px dashed #365355;border-radius:11px;background:#0b171a;padding:42px;text-align:center}.empty-state b{display:block;color:var(--cyan);font:24px/1 ui-monospace,monospace}.empty-state strong{display:block;margin-top:16px;font-size:21px}.empty-state span,.table-empty{color:var(--text-soft);font-size:12px}.table-heading{margin-top:68px;padding-bottom:20px;border-bottom:1px solid var(--line)}.table-heading time{color:#728a87;font:8px/1.5 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}.ranking-table-shell{margin-top:16px;border:1px solid var(--line);border-radius:10px;background:#091316;overflow:auto;box-shadow:0 25px 80px #0005}.ranking-table-shell:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}table{width:100%;min-width:2200px;border-collapse:collapse}caption{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}th{position:sticky;top:0;z-index:1;padding:15px 12px;border-bottom:1px solid #2b4548;background:#0e1e21;color:#78918e;font:7px/1.25 ui-monospace,monospace;text-align:left;text-transform:uppercase;letter-spacing:.1em;white-space:nowrap}td{padding:14px 12px;border-bottom:1px solid #17292c;color:#bfd0cd;font:10px/1.3 ui-monospace,monospace;white-space:nowrap}tbody tr:nth-child(even){background:#0c191b}tbody tr:hover{background:#0f2426}tbody tr:last-child td{border-bottom:0}.rank-badge{display:inline-grid;place-items:center;width:27px;height:27px;border:1px solid #315052;border-radius:50%;color:#7d9794}.rank-1 .rank-badge{border-color:var(--amber);color:var(--amber);box-shadow:0 0 16px #f4b74026}.rank-2 .rank-badge,.rank-3 .rank-badge{border-color:#62dfd166;color:var(--cyan)}.hunter{color:var(--foreground);font-size:11px}.ranking-note{margin:14px 0 0;color:#667e7b;font:8px/1.6 ui-monospace,monospace;letter-spacing:.04em}.site-footer{border-top:1px solid var(--line);background:#050c0e}.footer-inner{min-height:90px;display:flex;align-items:center;justify-content:space-between;gap:24px;color:#5e7774;font:8px/1.5 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}@media(max-width:980px){.primary-nav{display:none}.hero-grid{grid-template-columns:1fr}.hero-signal{display:none}.summary-grid{grid-template-columns:repeat(2,1fr)}.summary-grid article:nth-child(2){border-right:0}.summary-grid article:nth-child(-n+2){border-bottom:1px solid var(--line)}.podium-grid{grid-template-columns:1fr}.podium-card{min-height:170px}.podium-name{margin-top:25px}.section-heading{align-items:start}.section-heading p{max-width:300px}}@media(max-width:700px){.site-container{width:min(100% - 28px,1180px)}.header-inner{height:66px}.header-status span{display:none}.duckhunt-subnav{top:66px}.duckhunt-subnav-inner{align-items:flex-start;flex-direction:column;gap:8px;padding-block:10px}.duckhunt-subnav nav{width:100%;padding-bottom:3px;overflow-x:auto}.duckhunt-subnav nav a{white-space:nowrap}.hero-grid{min-height:auto;padding-block:38px 32px}.hero-grid h1{font-size:30px}.summary-grid{margin-top:8px}.summary-grid article{min-height:82px;padding:17px}.ranking-section{padding-block:52px 68px}.section-heading,.table-heading{align-items:flex-start;flex-direction:column}.section-heading p{text-align:left}.table-heading{margin-top:48px}.ranking-table-shell{border:0;background:transparent;box-shadow:none;overflow:visible}.ranking-table-shell table{min-width:0}.ranking-table-shell thead{display:none}.ranking-table-shell tbody{display:grid;gap:10px}.ranking-table-shell tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:16px;border:1px solid var(--line);border-radius:9px;background:linear-gradient(145deg,#0e1e21,#071013)}.ranking-table-shell td{display:block;padding:8px 9px;border:0;white-space:normal}.ranking-table-shell td:before{content:attr(data-label);display:block;margin-bottom:5px;color:#607a77;font:7px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.ranking-table-shell td:nth-child(1),.ranking-table-shell td:nth-child(2){grid-column:auto}.ranking-table-shell td:nth-child(2){align-self:center}.ranking-table-shell td:nth-child(8){grid-column:1/-1;border-block:1px solid var(--line);padding-block:12px}.footer-inner{align-items:flex-start;flex-direction:column;justify-content:center}.footer-inner span:last-child{display:none}}
"""

_IRC_FORMATTING = re.compile(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?|[\x02\x0f]")

_INVENTORY_STYLE = r"""
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.ranking-table-shell{overflow:visible}.ranking-table-shell table{width:100%;min-width:0;table-layout:fixed}.ranking-table-shell th,.ranking-table-shell td{padding-inline:9px;white-space:normal;vertical-align:middle}.ranking-table-shell th{text-align:center}.ranking-table-shell th:nth-child(2){text-align:left}.col-place{width:5%}.col-hunter{width:11%}.col-hunt{width:8%}.col-time{width:8%}.col-progress{width:8%}.col-weapon{width:10%}.col-condition{width:11%}.col-ammunition{width:8%}.col-shots{width:14%}.col-incidents{width:12%}.col-inventory{width:5%}.cell-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 6px}.cell-facts.facts-3{grid-template-columns:repeat(3,minmax(0,1fr))}.cell-facts span{display:flex;min-width:0;align-items:baseline;gap:4px}.cell-facts b{color:var(--foreground);font:650 9px/1 ui-monospace,monospace}.cell-facts small{overflow:hidden;color:#66817e;font:7px/1 ui-monospace,monospace;text-overflow:ellipsis;white-space:nowrap}.place-cell,.hunt-cell,.time-cell,.progress-cell,.condition-cell,.ammunition-cell,.inventory-cell{text-align:center}.hunter-cell,.weapon-cell{overflow-wrap:anywhere}.inventory-cell{position:relative;overflow:visible}.inventory-details{position:relative;display:inline-block}.inventory-details summary{display:grid;place-items:center;width:31px;height:31px;margin:auto;border:1px solid #315052;border-radius:7px;background:#0e1e21;color:var(--amber);cursor:help;list-style:none;transition:border-color .15s ease,background .15s ease,transform .15s ease}.inventory-details summary::-webkit-details-marker{display:none}.inventory-details summary::marker{content:""}.inventory-details summary:hover,.inventory-details summary:focus-visible{border-color:var(--amber);background:#142427;outline:none;transform:translateY(-1px)}.inventory-icon{font-size:15px;line-height:1}.inventory-panel{display:none;position:absolute;z-index:6;right:calc(100% + 10px);top:50%;width:390px;max-width:70vw;padding:16px 17px;border:1px solid #3b595b;border-radius:9px;background:#071013f7;box-shadow:0 18px 55px #000b;color:var(--foreground);text-align:left;white-space:normal;transform:translateY(-50%)}.inventory-details:hover .inventory-panel,.inventory-details:focus-within .inventory-panel,.inventory-details[open] .inventory-panel{display:block}.inventory-panel strong{display:block;padding-bottom:10px;border-bottom:1px solid var(--line);color:var(--amber);font:650 11px/1.3 ui-monospace,monospace}.inventory-panel ul{display:flex;flex-wrap:wrap;gap:6px;margin:11px 0 0;padding:0;list-style:none}.inventory-panel li{padding:6px 8px;border:1px solid #284346;border-radius:5px;background:#0d191b;color:#b8cac7;font:9px/1.35 ui-monospace,monospace}tbody tr:first-child:not(:only-child) .inventory-panel{top:0;transform:none}tbody tr:last-child:not(:only-child) .inventory-panel{top:auto;bottom:0;transform:none}tbody tr:only-child .inventory-panel{position:static;width:min(390px,70vw);margin-top:8px;transform:none}@media(max-width:1180px){.ranking-table-shell{border:0;background:transparent;box-shadow:none}.ranking-table-shell table{table-layout:auto}.ranking-table-shell colgroup,.ranking-table-shell thead{display:none}.ranking-table-shell tbody{display:grid;gap:10px}.ranking-table-shell tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:16px;border:1px solid var(--line);border-radius:9px;background:linear-gradient(145deg,#0e1e21,#071013)}.ranking-table-shell td{display:block;padding:8px 9px;border:0}.ranking-table-shell td:nth-child(8){grid-column:auto;padding-block:8px;border-block:0}.ranking-table-shell td:before{content:attr(data-label);display:block;margin-bottom:5px;color:#607a77;font:7px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.hunter-cell,.weapon-cell,.shots-cell,.incidents-cell,.inventory-cell{grid-column:1/-1}.hunter-cell,.weapon-cell{overflow-wrap:normal}.cell-facts{max-width:300px}.shots-cell .cell-facts,.incidents-cell .cell-facts{max-width:none}.inventory-details{display:block}.inventory-details summary{margin:0}.inventory-panel,tbody tr:first-child:not(:only-child) .inventory-panel,tbody tr:last-child:not(:only-child) .inventory-panel{position:static;width:100%;max-width:none;margin-top:9px;transform:none}.inventory-panel ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:430px){.inventory-panel ul,.ranking-table-shell tr{grid-template-columns:1fr}.hunter-cell,.weapon-cell,.shots-cell,.incidents-cell,.inventory-cell{grid-column:auto}}
"""
