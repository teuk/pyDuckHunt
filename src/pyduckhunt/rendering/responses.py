"""Render deterministic game facts as localized IRC responses, with byte-compatible French defaults."""

from __future__ import annotations

from pyduckhunt.i18n import tr, localized, localized_method, LocalizedMapping

from collections.abc import Iterable

from pyduckhunt.game.bread import active_channel_breads
from pyduckhunt.game.accuracy import fatigue_penalty_bps, overexcitation_penalty_bps, shot_accuracy, live_scope_bonus_points
from pyduckhunt.game.catalog import SHOP_CATALOG, shop_item
from pyduckhunt.game.commands import (
    Command,
    CommandKind,
    command_usage,
    rank_limit,
    validate_command,
)
from pyduckhunt.game.karma import player_karma_basis_points
from pyduckhunt.game.karma import karma_adjusted_jam_basis_points
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.loot import (
    STANDARD_LOOT_CATALOG,
    UNUSUAL_LOOT_CATALOG,
    LootGrantKind,
    LootRarity,
    loot_spec,
)
from pyduckhunt.game.model import (
    ActiveEffect,
    FATIGUE_SCALE,
    FlightKind,
    FlightState,
    GameState,
    LastFlight,
    LastFlightConclusion,
    Outcome,
    OutcomeKind,
    PlayerState,
)
from pyduckhunt.game.progression import available_experience, experience_required
from pyduckhunt.game.ranking import is_statistically_excluded, ranked_players
from pyduckhunt.game.rewards import (
    has_unlimited_duck_carry,
    has_unlimited_magazines,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.message import (
    IRCProtocolError,
    notice_text_budget,
    privmsg_text_budget,
    render_notice_bounded,
    render_privmsg_bounded,
)
from pyduckhunt.time_format import format_duration_ms, format_duration_ns
from pyduckhunt.public_url import normalize_ranking_url, normalize_shop_url
from pyduckhunt.rendering.flight_appearance import FlightAppearance


MAX_RESPONSE_LINES = 4
_BOLD = "\x02"
_COLOR_GREEN = "\x0303"
_COLOR_RED = "\x0304"
_COLOR_PURPLE = "\x0306"
_COLOR_ORANGE = "\x0307"
_COLOR_BLUE = "\x0312"
_COLOR_GREY = "\x0314"
_RESET = "\x0f"

_RARITY_PRESENTATION = LocalizedMapping({
    LootRarity.UNUSUAL: (_COLOR_GREEN, "item inhabituel"),
    LootRarity.RARE: (_COLOR_BLUE, "item rare"),
    LootRarity.VERY_RARE: (_COLOR_PURPLE, "item très rare"),
    LootRarity.LEGENDARY: (_COLOR_ORANGE, "item légendaire"),
})

_ITEM_LABELS = LocalizedMapping({
    1: "balle supplémentaire",
    2: "chargeur supplémentaire",
    3: "munitions perforantes",
    4: "munitions explosives",
    5: "rachat de l'arme",
    6: "graisse",
    7: "lunette de visée",
    8: "détecteur infrarouge",
    9: "silencieux",
    10: "trèfle à quatre feuilles",
    11: "lunettes de soleil",
    12: "vêtements secs",
    13: "goupillon",
    14: "miroir",
    15: "poignée de sable",
    16: "seau d'eau",
    17: "sabotage",
    18: "assurance vie",
    19: "assurance responsabilité civile",
    20: "appeau",
    21: "morceau de pain",
    22: "détecteur de canards",
    23: "canard mécanique",
    24: "expresso",
    25: "thermos de café",
    26: "imperméable",
    27: "verre de gnôle",
    28: "infusion de camomille",
    29: "sauf-conduit",
    30: "rechargement automatique",
    31: "rituel de purification",
})

_LOOT_LABELS = LocalizedMapping({
    "junk_item": "un objet mystérieux",
    "single_round": "une balle supplémentaire",
    "reserve_magazine": "un chargeur supplémentaire",
    "penetrating_ammunition": "des munitions perforantes",
    "explosive_ammunition": "des munitions explosives",
    "weapon_grease": "de la graisse",
    "targeting_scope": "une lunette de visée",
    "infrared_lock": "un détecteur infrarouge",
    "suppressor": "un silencieux",
    "sunglasses": "des lunettes de soleil",
    "duck_detector": "un détecteur de canards",
    "lucky_charm": "un trèfle à quatre feuilles",
    "xp_10": "10 xp",
    "xp_20": "20 xp",
    "xp_30": "30 xp",
    "xp_40": "40 xp",
    "xp_50": "50 xp",
    "xp_100": "100 xp",
    "curse_scroll": "un parchemin maudit",
    "voucher_10": "un bon d'achat de 10 xp",
    "voucher_20": "un bon d'achat de 20 xp",
    "voucher_50": "un bon d'achat de 50 xp",
    "voucher_75": "un bon d'achat de 75 xp",
    "abundance_amulet": "une amulette d'abondance",
    "endurance_amulet": "une amulette d'endurance",
    "blessing_amulet": "une amulette de bénédiction",
    "promotion_10_24h": "un coupon promotionnel de 10% (24h)",
    "promotion_10_48h": "un coupon promotionnel de 10% (48h)",
    "promotion_10_7d": "un coupon promotionnel de 10% (7j)",
    "promotion_25_24h": "un coupon promotionnel de 25% (24h)",
    "promotion_25_48h": "un coupon promotionnel de 25% (48h)",
    "promotion_25_7d": "un coupon promotionnel de 25% (7j)",
    "promotion_50_24h": "un coupon promotionnel de 50% (24h)",
    "promotion_50_48h": "un coupon promotionnel de 50% (48h)",
    "baker_amulet": "une amulette du boulanger",
    "prankster_amulet": "une amulette du farceur",
    "ammo_recycler": "un recycleur de munitions (1/3, 24h)",
    "premium_ammo_recycler": "un recycleur de munitions haut de gamme (1/2, 48h)",
    "warrior_amulet": "une amulette du guerrier (24h)",
    "eternal_warrior_amulet": "une amulette du guerrier éternel (48h)",
    "large_ammo_bag": "un grand sac à munitions",
    "extended_magazine": "un chargeur étendu",
    "military_ammo_recycler": "un recycleur de munitions militaire (1/10)",
    "indestructible_sunglasses": "des lunettes de soleil incassables",
    "tearproof_raincoat": "un imperméable indéchirable",
    "military_self_lubricating_system": "un système autolubrifiant militaire",
    "permanent_killing_license": "un permis de tuer permanent",
    "tardis_bag": "une gibecière TARDIS (24h)",
    "letter_d": "une lettre D en bois",
    "letter_u": "une lettre U en bois",
    "letter_c": "une lettre C en bois",
    "letter_k": "une lettre K en bois",
    "letter_h": "une lettre H en bois",
    "letter_n": "une lettre N en bois",
    "letter_t": "une lettre T en bois",
    "junk_letter_q": "une lettre Q en bois",
})

_LOOT_EQUIPMENT_PRESENTATION = LocalizedMapping({
    "penetrating_ammunition": (
        "des munitions AP",
        "Les dégâts de ton arme sont doublés pendant 24h.",
    ),
    "explosive_ammunition": (
        "des munitions explosives",
        "Les dégâts de ton arme sont triplés pendant 24h.",
    ),
    "weapon_grease": (
        "de la graisse",
        "Le risque d'enrayage de ton arme est réduit de moitié pendant 24h.",
    ),
    "infrared_lock": (
        "un détecteur infrarouge",
        "La gâchette de ton arme sera bloquée s'il n'y a aucun canard dans les "
        "environs afin d'éviter le gaspillage de munitions. Dure 24h pour 6 "
        "utilisations.",
    ),
    "suppressor": (
        "un silencieux",
        "Tes tirs ne risquent plus d'effrayer les canards pendant 24h.",
    ),
    "sunglasses": (
        "des lunettes de soleil",
        "Tu es protégé contre l'éblouissement pendant 24h.",
    ),
    "duck_detector": (
        "un détecteur de canards",
        "Tu seras averti par une notice lors de l'envol du prochain canard.",
    ),
    "abundance_amulet": (
        "une amulette d'abondance",
        "Tes chances de trouver des objets intéressants en fouillant les buissons "
        "sont doublées pendant 24h.",
    ),
    "endurance_amulet": (
        "une Amulette d'Endurance",
        "Tu ne ressens plus les effets de la fatigue pendant 24h.",
    ),
    "blessing_amulet": (
        "une Amulette de Bénédiction",
        "Les effets de la prochaine malédiction seront neutralisés.",
    ),
    "promotion_10_24h": (
        "un coupon promotionnel",
        "Tu bénéficies de 10% de réduction dans le shop pendant 24h.",
    ),
    "promotion_10_48h": (
        "un coupon promotionnel",
        "Tu bénéficies de 10% de réduction dans le shop pendant 48h.",
    ),
    "promotion_10_7d": (
        "un coupon promotionnel",
        "Tu bénéficies de 10% de réduction dans le shop pendant 1 semaine.",
    ),
    "promotion_25_24h": (
        "un coupon promotionnel",
        "Tu bénéficies de 25% de réduction dans le shop pendant 24h.",
    ),
    "promotion_25_48h": (
        "un coupon promotionnel",
        "Tu bénéficies de 25% de réduction dans le shop pendant 48h.",
    ),
    "promotion_25_7d": (
        "un coupon promotionnel",
        "Tu bénéficies de 25% de réduction dans le shop pendant 1 semaine.",
    ),
    "promotion_50_24h": (
        "un coupon promotionnel",
        "Tu bénéficies de 50% de réduction dans le shop pendant 24h.",
    ),
    "promotion_50_48h": (
        "un coupon promotionnel",
        "Tu bénéficies de 50% de réduction dans le shop pendant 48h.",
    ),
    "baker_amulet": (
        "une Amulette du Boulanger",
        "Pendant 24h, chaque canard abattu fait apparaître un morceau de pain sur "
        "le canal.",
    ),
    "prankster_amulet": (
        "une Amulette du Farceur",
        "Pendant 24h, chaque canard abattu fera apparaître un canard mécanique "
        "10mn après.",
    ),
    "ammo_recycler": (
        "un recycleur de munitions",
        "Pendant 24h, il y a 1 chance sur 3 pour que les munitions utilisées soient "
        "recyclées et que tes tirs n'en consomment pas.",
    ),
    "premium_ammo_recycler": (
        "un recycleur de munitions haut de gamme",
        "Pendant 48h, il y a 1 chance sur 2 pour que les munitions utilisées soient "
        "recyclées et que tes tirs n'en consomment pas.",
    ),
    "warrior_amulet": (
        "une Amulette du Guerrier",
        "Tu disposes d'une réserve de chargeurs illimitée pendant 24h.",
    ),
    "eternal_warrior_amulet": (
        "une Amulette du Guerrier Éternel",
        "Tu disposes d'une réserve de chargeurs illimitée pendant 48h.",
    ),
    "tardis_bag": (
        "une gibecière TARDIS",
        "Tu peux transporter un nombre illimité de canards sans être encombré "
        "pendant 24h.",
    ),
    "large_ammo_bag": (
        "un grand sac à munitions",
        "Tu peux désormais transporter un chargeur supplémentaire.",
    ),
    "extended_magazine": (
        "un chargeur étendu",
        "Tu peux désormais charger une munition supplémentaire dans ton arme.",
    ),
    "military_ammo_recycler": (
        "un recycleur de munitions de grade militaire",
        "Il y a désormais 1 chance sur 10 pour que les munitions utilisées soient "
        "recyclées et que tes tirs n'en consomment pas.",
    ),
    "indestructible_sunglasses": (
        "des lunettes de soleil incassables",
        "Tu es maintenant protégé contre l'éblouissement de manière permanente.",
    ),
    "tearproof_raincoat": (
        "un imperméable indéchirable",
        "Tu es maintenant protégé contre les seaux d'eau de manière permanente.",
    ),
    "military_self_lubricating_system": (
        "un système autolubrifiant militaire pour ton arme",
        "Tu es maintenant protégé contre le sable et le risque d'enrayage de ton "
        "arme est réduit de moitié de manière permanente.",
    ),
    "permanent_killing_license": (
        "un permis de tuer permanent",
        "Désormais, tu n'encourras plus de pénalités en cas d'accident de chasse.",
    ),
})

_VARIABLE_LOOT_EQUIPMENT_KEYS = frozenset(("targeting_scope", "lucky_charm"))

_INVENTORY_LABELS = LocalizedMapping({
    "large_ammo_bag": "grande gibecière",
    "extended_magazine": "chargeur étendu",
    "military_ammo_recycler": "recycl. mun. (10%)",
    "indestructible_sunglasses": "lunettes soleil",
    "tearproof_raincoat": "imperméable",
    "military_self_lubricating_system": "syst. autolubrifiant",
    "permanent_killing_license": "permis de tuer",
})

_LEVEL_TITLES = LocalizedMapping({
    1: "touriste",
    2: "chasseur du dimanche",
    3: "végétarien armé",
    4: "promeneur armé",
    5: "noob",
    6: "stagiaire",
    7: "rateur de canards",
    8: "membre du CCC (Comité Contre les Canards)",
    9: "pointé du doigt par les canards",
    10: (
        "inscrit sur la liste noire de la CCCCC "
        "(Coalition Contre le Comité Contre les Canards)"
    ),
    11: "détesteur de canards",
    12: "haïsseur de canards",
    13: "anatidaephobe",
    14: "emmerdeur de canards",
    15: "harceleur de canards",
    17: "déplumeur de canards",
    18: "dépeceur de canards",
    19: "retourneur de canards",
    20: "expert en armes à feu",
    21: "assommeur de canards",
    22: "grignotteur de canards",
    23: "mâchouilleur de canards",
    24: "bouffeur de canards",
    25: "aplatisseur de canards",
    26: "déglingueur de canards",
    27: "déboîteur de canards",
    28: "démonteur de canards",
    29: "démolisseur de canards",
    30: "chasseur confirmé",
    31: "tueur de canards",
    33: "recherché dans 47 mares",
    34: "écorcheur de canards",
    35: "découpeur de canards",
    37: "décortiqueur de canards",
    38: "disséqueur de canards",
    42: "celui dont les canards ne prononcent pas le nom",
    43: "troueur de canards",
    46: "éclateur de canards",
    47: "déchiqueteur de canards",
    48: "défonceur de canards",
    51: "poutreur de canards",
    56: "dévastateur de canards",
    59: "désintégrateur de canards",
    61: "atomiseur de canards",
    63: "Lucky Luke",
    65: "vétéran",
    66: "serial duck killer",
    68: "grand inquisiteur des palmipèdes",
    77: "chasseur d'élite qui fout trop les jetons",
    78: "chasseur d'élite qui fout incroyablement les jetons",
    82: "chasseur d'élite professionnel",
    86: "chasseur d'élite de la mort qui tue",
    92: "chasseur d'élite de la mort qui tue même en dormant",
    93: "chasseur d'élite de la mort qui tue avant même de tirer",
    94: "chasseur d'élite émérite",
})

_REWARD_EFFECT_LABELS = LocalizedMapping({
    101: "amulette d'abondance",
    102: "amulette d'endurance",
    103: "amulette de bénédiction",
    104: "coupon promo. 10%",
    105: "coupon promo. 10%",
    106: "coupon promo. 10%",
    107: "coupon promo. 25%",
    108: "coupon promo. 25%",
    109: "coupon promo. 25%",
    110: "coupon promo. 50%",
    111: "coupon promo. 50%",
    112: "amulette du boulanger",
    113: "amulette du farceur",
    114: "recycleur (1/3)",
    115: "recycleur haut de gamme (1/2)",
    116: "amulette du guerrier",
    117: "amulette du guerrier éternel",
    118: "gibecière TARDIS",
})


def _player(state: GameState, nickname: str) -> PlayerState | None:
    return state.player(rfc1459_casefold(nickname))


def _player_name(outcome: Outcome) -> str:
    if outcome.actor:
        return outcome.actor
    if outcome.player:
        return outcome.player.nickname
    return tr('Chasseur')


def _item_label(item_id: int | None) -> str:
    if item_id is None:
        return tr('objet')
    return _ITEM_LABELS.get(
        item_id,
        _REWARD_EFFECT_LABELS.get(item_id, tr('objet {0}', item_id)),
    )


def _loot_rarity_tag(loot_key: str | None) -> str:
    spec = loot_spec(loot_key or "")
    presentation = None if spec is None else _RARITY_PRESENTATION.get(spec.rarity)
    if presentation is None:
        return ""
    color, label = presentation
    return f"   {color}[{label}]{_RESET}"


def _loot_equipment_presentation(outcome: Outcome) -> tuple[str, str] | None:
    key = outcome.loot_key or ""
    if key == "targeting_scope":
        magnitude = outcome.loot_magnitude
        if type(magnitude) is not int or not 0 <= magnitude <= 15:
            raise ValueError("targeting-scope loot magnitude is invalid")
        return (
            tr('une lunette de visée pour ton arme'),
            tr('Lunette pour 6 tirs : +{0} points de précision actuellement.', magnitude),
        )
    if key == "lucky_charm":
        magnitude = outcome.loot_magnitude
        if type(magnitude) is not int or not 1 <= magnitude <= 10:
            raise ValueError("lucky-charm loot magnitude is invalid")
        point = tr('point') if magnitude == 1 else tr('points')
        extra = tr('supplémentaire') if magnitude == 1 else tr('supplémentaires')
        return (
            tr('un trèfle à 4 feuilles +{0}', magnitude),
            tr("Chaque canard abattu te rapportera {0} {1} d'xp {2} pendant 24h.", magnitude, point, extra),
        )
    return _LOOT_EQUIPMENT_PRESENTATION.get(key)


def _carry_tag(multiplier: int) -> str:
    label = {1: "", 2: tr('encombré'), 3: tr('surchargé')}[multiplier]
    return "" if not label else f" {_COLOR_RED}[{label}]{_RESET}"


def _fatigue_tag(penalty_bps: int, excitement_bps: int = 0) -> str:
    label = tr('surexcité') if excitement_bps else tr('fatigué') if penalty_bps else ""
    return f" {_COLOR_RED}[{label}]{_RESET}" if label else ""


def _accuracy_text(state: GameState, player: PlayerState) -> str:
    accuracy = shot_accuracy(
        state, player, level_policy(player.level).accuracy_bps,
        settled_fatigue_penalty_bps=fatigue_penalty_bps(state, player),
        settled_overexcitation_penalty_bps=overexcitation_penalty_bps(state, player),
        settled_scope_bonus_points=live_scope_bonus_points(state, player),
    )
    text = f"{_basis_points(accuracy.base_bps)}%"
    labels = {'tonic': tr('tonique'), 'tremor': tr('tremblements'), 'glare': tr('ébloui'),
              'scope': tr('lunette'), tr('fatigue'): tr('fatigue'), 'overexcitation': tr('surexcitation')}
    for label, delta in accuracy.modifiers:
        sign = '+' if delta >= 0 else '-'
        text += tr(' {0}{1} pts {2}', sign, _basis_points(abs(delta)), labels[label])
    if accuracy.modifiers:
        text += f" = {_basis_points(accuracy.effective_bps)}%"
    return text


def _shot_sound(outcome: Outcome) -> str:
    sound = tr('BOUM') if outcome.ammunition_item_id == 4 else "BANG"
    return f"{_BOLD}*{sound}*{_RESET}"


def _golden_ammunition_tag(outcome: Outcome) -> str:
    label = {3: tr('mun. AP'), 4: tr('mun. expl.')}.get(outcome.ammunition_item_id)
    return "" if label is None else f" {_COLOR_GREEN}[{label}]{_RESET}"


def _duration(elapsed_ns: int) -> str:
    return format_duration_ns(elapsed_ns)


def _fatigue(value_centi: int) -> str:
    """Format fixed-point fatigue without binary floating-point arithmetic."""

    sign = "-" if value_centi < 0 else ""
    whole, fraction = divmod(abs(value_centi), FATIGUE_SCALE)
    if fraction == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:02d}".rstrip("0")


def _basis_points(value: int) -> str:
    """Render a signed fixed-point percentage without binary floats."""

    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 100)
    if fraction == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:02d}".rstrip("0")


def _ratio_centi(numerator: int, denominator: int) -> str:
    """Render one non-negative ratio with the screenshot's two decimals."""

    if denominator == 0:
        return "0.00"
    value = (numerator * 100 + denominator // 2) // denominator
    return f"{value // 100}.{value % 100:02d}"


def _level_title(level: int) -> str:
    return _LEVEL_TITLES.get(level, tr('chasseur de niveau {0}', level))


def _letter_status(player: PlayerState) -> str:
    letters = tuple(
        letter if owned else "_"
        for letter, owned in zip("DUCKHUNT", player.letter_slots, strict=True)
    )
    return " ".join(letters[:4]) + "   " + " ".join(letters[4:])


def _effect_status(effect: ActiveEffect, now_ns: int, *, scope_points: int | None = None) -> str:
    bounds: list[str] = []
    if effect.expires_at_ns is not None:
        bounds.append(_duration(effect.expires_at_ns - now_ns))
    if effect.remaining_uses is not None:
        bounds.append(tr('{0} util.', effect.remaining_uses))
    if effect.magnitude is not None and not 104 <= effect.item_id <= 111:
        bounds.append(
            tr('+{0} fatigue', _fatigue(effect.magnitude))
            if effect.item_id == 28
            else tr('+{0} pts précision', scope_points)
            if effect.item_id == 7 and scope_points is not None
            else f"+{effect.magnitude}"
        )
    label = _item_label(effect.item_id)
    return label if not bounds else f"{label} ({', '.join(bounds)})"


def _validated_response_lines(lines: Iterable[str]) -> tuple[str, ...]:
    rendered = tuple(lines)
    if len(rendered) > MAX_RESPONSE_LINES:
        raise IRCProtocolError("player response exceeds the bounded line count")
    if any(not isinstance(line, str) or not line for line in rendered):
        raise IRCProtocolError("player response lines must be non-empty strings")
    return rendered


def _pack_response_lines(lines: tuple[str, ...], budget: int) -> tuple[str, ...]:
    """Greedily join adjacent semantic lines while they fit one IRC payload."""

    packed: list[str] = []
    for line in lines:
        if not packed:
            packed.append(line)
            continue
        candidate = f"{packed[-1]}  {line}"
        if len(candidate.encode("utf-8")) <= budget:
            packed[-1] = candidate
        else:
            packed.append(line)
    return tuple(packed)


@localized
def render_wire_response(target: str, lines: Iterable[str]) -> tuple[bytes, ...]:
    """Frame the fewest bounded public lines allowed by the IRC byte budget."""

    packed = _pack_response_lines(
        _validated_response_lines(lines),
        privmsg_text_budget(target),
    )
    return tuple(render_privmsg_bounded(target, line) for line in packed)


@localized
def render_wire_notice(target: str, lines: Iterable[str]) -> tuple[bytes, ...]:
    """Frame the fewest bounded private NOTICE lines allowed by the byte budget."""

    packed = _pack_response_lines(
        _validated_response_lines(lines),
        notice_text_budget(target),
    )
    return tuple(render_notice_bounded(target, line) for line in packed)


@localized
def render_detector_notice(outcome: Outcome) -> tuple[str, ...]:
    """Render one player-scoped detector alert for the NOTICE transport."""

    if not isinstance(outcome, Outcome) or outcome.kind is not OutcomeKind.DUCK_ALERT:
        raise ValueError("detector notice requires a duck-alert outcome")
    if outcome.actor is None:
        return ()
    return (tr("Ton détecteur de canards t'avertit : un canard vient de s'envoler."),)


@localized
def render_profile(state: GameState, nickname: str) -> tuple[str, ...]:
    """Render the complete two-line hunting sheet shown by ``!duckstats``."""

    player = _player(state, nickname)
    if player is None:
        return (tr('{0} > Je ne connais aucun chasseur portant ce nom.', nickname),)
    total_experience = available_experience(player)
    best = "--" if player.best_time_ms is None else format_duration_ms(player.best_time_ms)
    level_target = experience_required(player.level)
    karma = player_karma_basis_points(player)
    policy = level_policy(player.level)
    accurate_shots = max(0, player.shots_fired - player.misses)
    effective_accuracy_bps = (
        0
        if player.shots_fired == 0
        else (
            accurate_shots * 10_000 + player.shots_fired // 2
        )
        // player.shots_fired
    )
    base_reliability_bps = 10_000 - policy.jam_bps
    effective_reliability_bps = 10_000 - karma_adjusted_jam_basis_points(
        policy.jam_bps,
        karma,
    )
    reliability_delta_bps = effective_reliability_bps - base_reliability_bps
    reliability_delta_percent = (
        (abs(reliability_delta_bps) + 50) // 100
    )
    reliability_modifier = (
        ""
        if reliability_delta_percent == 0
        else (
            "+" if reliability_delta_bps > 0 else "-"
        )
        + str(reliability_delta_percent)
    )
    jammed = tr('oui') if player.jammed else tr('non')
    confiscated = tr('oui') if player.confiscated else tr('non')
    return (
        tr((
            '{0}[Profil]{1} {2} xp | niv. {3} ({4}) +{5} xp = niv. sup. | fatigue: {6}{7} | karma: '
            '{8} | rentab.: {9} xp/canard | dépensé: {10} xp  {11}[Stats]{12} préc. théor.: {13} | '
            'effic. tirs: {14}% | fiab. arme: {15}{16}% | armure: {17}% | déflex.: {18}%  '
            '{19}[Arme]{20} enray.: {21} ({22} fois) | confisq.: {23} ({24} fois)'
        ), _COLOR_ORANGE, _RESET, total_experience, player.level, _level_title(player.level), level_target - player.experience, _fatigue(player.fatigue_centi), _fatigue_tag(fatigue_penalty_bps(state, player), overexcitation_penalty_bps(state, player)), _basis_points(karma), _ratio_centi(total_experience, player.hits), player.experience_spent, _COLOR_ORANGE, _RESET, _accuracy_text(state, player), _basis_points(effective_accuracy_bps), _basis_points(base_reliability_bps), reliability_modifier, _basis_points(policy.armor_bps), _basis_points(policy.deflection_bps), _COLOR_ORANGE, _RESET, jammed, player.jams, confiscated, player.confiscations),
        tr((
            '{0}[Tableau de chasse]{1} meill. tps.: {2} | {3} canards (dont {4} super-canards) | {5} '
            'tirs ratés | {6} tirs à vide | {7} tirs enray. | {8} recharg. compulsifs | {9} tirs '
            'sauvages | {10} accidents | {11} coups tirés  {12}[Accidents]{13} reçu {14} balles '
            'perdues dont {15} mortelles, {16} ont ricoché et {17} ont été encaissées.'
        ), _COLOR_ORANGE, _RESET, best, player.hits, player.golden_hits, player.misses, player.empty_shots, player.jammed_shots, player.compulsive_reloads, player.wild_shots, player.incidents_caused, player.shots_fired, _COLOR_ORANGE, _RESET, player.shots_received, player.deaths, player.incidents_deflected, player.incidents_absorbed),
    )


@localized
def render_inventory(
    state: GameState,
    nickname: str,
    *,
    channel: str | None = None,
) -> tuple[str, ...]:
    """Render canonical stacks and active effects without exposing state internals."""

    if channel is not None and (
        type(channel) is not str
        or not channel.startswith(("#", "&"))
        or any(character in channel for character in (" ", "\x00", "\r", "\n"))
    ):
        raise ValueError("inventory rendering channel is invalid")
    player = _player(state, nickname)
    if player is None:
        return (tr('{0} > Je ne connais aucun chasseur portant ce nom.', nickname),)
    durable_parts = [
        (
            f"{_INVENTORY_LABELS.get(stack.key, stack.key)}"
            if stack.quantity == 1
            else f"{_INVENTORY_LABELS.get(stack.key, stack.key)} x{stack.quantity}"
        )
        for stack in player.inventory
    ]
    effects = tuple(
        effect
        for effect in state.effects
        if effect.owner_key == player.key
    )
    suppressor = next(
        (effect for effect in effects if effect.item_id == 9),
        None,
    )
    inventory_parts = (
        [] if suppressor is None else [_effect_status(suppressor, state.now_ns)]
    )
    inventory_parts.extend(durable_parts)
    fatigue_penalty = fatigue_penalty_bps(state, player)
    excitement = overexcitation_penalty_bps(state, player)
    if fatigue_penalty or excitement:
        inventory_parts.append(
            tr('fatigue: {0}{1} (-{2} pts précision)', _fatigue(player.fatigue_centi), _fatigue_tag(fatigue_penalty, excitement), _basis_points(fatigue_penalty + excitement))
        )
    inventory_parts.extend(
        _effect_status(effect, state.now_ns, scope_points=live_scope_bonus_points(state, player))
        for effect in effects
        if effect.item_id != 9
    )
    if player.shop_credit:
        inventory_parts.append(tr("bon d'achat {0} xp", player.shop_credit))
    curses = tuple(curse.key for curse in state.curses if curse.owner_key == player.key)
    breads = active_channel_breads(state, state.now_ns)
    bread_count = len(breads)
    if bread_count:
        bread_label = tr('morceau') if bread_count == 1 else tr('morceaux')
        channel_label = tr('le canal') if channel is None else channel
        expirations = [effect.expires_at_ns for effect in breads
                       if effect.expires_at_ns is not None]
        expiry = ("" if not expirations else
                  tr(' (première expiration dans {0})', format_duration_ns(min(expirations) - state.now_ns)))
        effect_hint = (tr(' ; +{0}s aux nouveaux vols', 20 * bread_count) if state.bread_plan_effect_ids is not None else "")
        inventory_parts.append(
            tr('{0} {1} de pain sur {2}{3}{4}', bread_count, bread_label, channel_label, expiry, effect_hint)
        )
    if curses:
        inventory_parts.append(tr('malédiction: {0}', ', '.join(curses)))
    weapon_state = (
        tr(' (confisquée définitivement)')
        if player.permanently_confiscated
        else tr(' (confisquée)')
        if player.confiscated
        else tr(' (enrayée)') if player.jammed else ""
    )
    weapon = tr(level_policy(player.level).weapon_label)
    magazine_status = (
        "∞"
        if has_unlimited_magazines(state, player.key)
        else f"{player.magazines}/{player.magazine_capacity}"
    )
    unlimited_carry = has_unlimited_duck_carry(state, player.key)
    carry_label = tr('gibecière TARDIS:') if unlimited_carry else tr('gibecière:')
    carry_status = (
        _carry_tag(3)
        if not unlimited_carry and player.carried_ducks > 10
        else _carry_tag(2)
        if not unlimited_carry and player.carried_ducks > 5
        else ""
    )
    duck_label = tr('canard') if player.carried_ducks < 2 else tr('canards')
    base = (
        tr('{0}[Inventaire]{1} arme: {2}{3} | mun.: {4}/{5} | charg.: {6} | {7} {8} {9}{10} | lettres: {11}', _COLOR_ORANGE, _RESET, weapon, weapon_state, player.ammo, player.capacity, magazine_status, carry_label, player.carried_ducks, duck_label, carry_status, _letter_status(player))
    )
    if not inventory_parts:
        return (base,)
    return (base, "| " + " | ".join(inventory_parts))


@localized
def render_shop(shop_url: str | None = None) -> tuple[str, ...]:
    """Render an optional operator-controlled catalog link in one safe line."""

    normalized = normalize_shop_url(shop_url)
    if normalized is None:
        return (tr('Boutique: !shop [id [cible]]'),)
    return (tr('Boutique: {0} | !shop [id [cible]]', normalized),)


@localized
def render_ranking(
    state: GameState,
    *,
    limit: int = 5,
    ranking_url: str | None = None,
    excluded_nicknames: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Render one compact podium and its optional complete public page."""

    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("ranking limit must be between one and twenty")
    normalized_url = normalize_ranking_url(ranking_url)
    ordered = ranked_players(
        state,
        limit=limit,
        excluded_nicknames=excluded_nicknames,
    )
    if not ordered:
        lines = (tr('{0}[TOP {1}]{2} Aucun chasseur classé.', _COLOR_ORANGE, limit, _RESET),)
    else:
        medals = ("🥇", "🥈", "🥉")
        entries = "  •  ".join(
            f"{medals[index - 1] if index <= len(medals) else f'{index}.'} "
            f"{_BOLD}{player.nickname}{_RESET} "
            f"{_COLOR_GREEN}· {player.hits}{_RESET}"
            for index, player in enumerate(ordered, start=1)
        )
        lines = (f"{_COLOR_ORANGE}[TOP {limit}]{_RESET}  {entries}",)
    if normalized_url is not None:
        lines += (
            tr('{0}[Classement complet]{1} {2}', _COLOR_BLUE, _RESET, normalized_url),
        )
    return lines


@localized
def render_last_flight(
    last_flight: LastFlight | int | None,
    *,
    now_ns: int | None = None,
    active_flight: FlightState | None = None,
) -> tuple[str, ...]:
    """Render active or durable last-flight facts without reading a wall clock."""

    if active_flight is not None:
        if type(now_ns) is not int or not active_flight.spawned_at_ns <= now_ns < active_flight.expires_at_ns:
            raise ValueError("active-flight rendering requires its current game time")
        elapsed = _duration(now_ns - active_flight.spawned_at_ns)
        remaining = _duration(active_flight.expires_at_ns - now_ns)
        return (
            tr("Un canard est en vol depuis {0}; envol dans {1} s'il n'est pas touché.", elapsed, remaining),
        )
    if last_flight is None:
        return (tr("Aucun envol de canard n'a encore été enregistré."),)
    if type(last_flight) is int:
        return (tr('Le dernier canard a été aperçu il y a {0}.', _duration(last_flight)),)
    if not isinstance(last_flight, LastFlight) or type(now_ns) is not int or now_ns < last_flight.ended_at_ns:
        raise ValueError("last-flight rendering requires durable facts and current game time")
    ago = _duration(now_ns - last_flight.ended_at_ns)
    duration = _duration(last_flight.ended_at_ns - last_flight.spawned_at_ns)
    if last_flight.conclusion is LastFlightConclusion.HIT:
        result = tr('abattu par {0} en {1}', last_flight.actor, duration)
    elif last_flight.conclusion is LastFlightConclusion.ESCAPED:
        result = tr('envolé sans être touché après {0}', duration)
    else:
        result = tr('effrayé par un tir après {0}', duration)
    return (tr('Dernier canard : {0}, il y a {1}.', result, ago),)


@localized
def render_query(
    state: GameState,
    actor: str,
    command: Command,
    *,
    last_flight_elapsed_ns: int | None = None,
    shop_url: str | None = None,
    ranking_url: str | None = None,
    statistics_excluded_nicknames: tuple[str, ...] = (),
    channel: str | None = None,
) -> tuple[str, ...]:
    """Project a validated read-only command from immutable game state."""

    validate_command(command)
    if command.kind is CommandKind.STATS:
        nickname = command.arguments[0] if command.arguments else actor
        if is_statistically_excluded(
            nickname,
            excluded_nicknames=statistics_excluded_nicknames,
        ):
            return (tr('{0} > Je ne connais aucun chasseur portant ce nom.', nickname),)
        return render_profile(state, nickname)
    if command.kind is CommandKind.INVENTORY:
        return render_inventory(
            state,
            command.arguments[0] if command.arguments else actor,
            channel=channel,
        )
    if command.kind is CommandKind.SHOP and not command.arguments:
        return render_shop(shop_url)
    if command.kind is CommandKind.LAST_FLIGHT:
        if last_flight_elapsed_ns is not None:
            return render_last_flight(last_flight_elapsed_ns)
        return render_last_flight(
            state.last_flight,
            now_ns=state.now_ns,
            active_flight=state.flight,
        )
    if command.kind is CommandKind.RANK:
        return render_ranking(
            state,
            limit=rank_limit(command),
            ranking_url=ranking_url,
            excluded_nicknames=statistics_excluded_nicknames,
        )
    raise ValueError(f"{command_usage(command)} is not a read-only query")


@localized
def render_outcome(
    outcome: Outcome,
    *,
    flight_appearance: FlightAppearance | None = None,
    channel: str | None = None,
) -> tuple[str, ...]:
    """Render one engine outcome; bookkeeping-only outcomes stay silent."""

    actor = _player_name(outcome)
    player = outcome.player
    fatigued = _fatigue_tag(outcome.fatigue_penalty_bps, outcome.overexcitation_penalty_bps)
    if outcome.kind is OutcomeKind.FLIGHT_STARTED:
        if flight_appearance is not None:
            prefix = ""
            if outcome.flight_kind is FlightKind.MECHANICAL:
                prefix = tr('{0}[CANARD MÉCANIQUE]{1} ', _COLOR_GREY, _RESET)
            return (
                f"{prefix}{_COLOR_GREY}{flight_appearance.trail}{_RESET} "
                f"{_BOLD}{flight_appearance.silhouette}{_RESET}   "
                f"{tr(flight_appearance.utterance)}",
            )
        if outcome.flight_kind is FlightKind.MECHANICAL:
            return (tr('{0}[CANARD MÉCANIQUE]{1} {2}\\_O<{3}   CLIC', _COLOR_GREY, _RESET, _BOLD, _RESET),)
        return (
            tr("{0}·-.,¸¸.-·°'`'°·-.,¸¸.-·°'`'°{1} {2}\\_O<{3}   COIN", _COLOR_GREY, _RESET, _BOLD, _RESET),
        )
    if outcome.kind is OutcomeKind.FLIGHT_ALREADY_ACTIVE:
        return ()
    if outcome.kind is OutcomeKind.FLIGHT_EXPIRED:
        return (tr("Le canard s'échappe. {0}·°'`'°-.,¸¸.·°'`{1}", _COLOR_GREY, _RESET),)
    if outcome.kind is OutcomeKind.HIT:
        if channel is not None and (
            type(channel) is not str
            or not channel.startswith(("#", "&"))
            or any(character in channel for character in (" ", "\x00", "\r", "\n"))
        ):
            raise ValueError("hit rendering channel is invalid")
        elapsed = "--" if outcome.elapsed_ms is None else format_duration_ms(outcome.elapsed_ms)
        total = "?" if player is None else str(player.hits)
        level = "" if player is None else (
            tr(' niv. {0} (progression : {1}/{2})', player.level, player.experience, experience_required(player.level))
        )
        total_label = tr('canard') if total == "1" else tr('canards')
        location = "" if channel is None else tr(' sur {0}', channel)
        recycled = tr(' [munition recyclée]') if outcome.ammunition_recycled else ""
        carry = _carry_tag(outcome.carry_fatigue_multiplier)
        ammunition = (
            _golden_ammunition_tag(outcome)
            if outcome.flight_kind is FlightKind.GOLDEN
            else ""
        )
        target = (
            tr('le {0}[CANARD DORÉ]{1}', _COLOR_GREEN, _RESET)
            if outcome.flight_kind is FlightKind.GOLDEN
            else tr('le canard')
        )
        return (
            tr('{0} > {1}     Tu as eu {2} en {3}, ce qui te fait un total de {4} {5}{6}.     {7}\\_X<{8}   *COUAC*   {9}[{10} xp]{11}{12}{13}{14}{15}{16}', actor, _shot_sound(outcome), target, elapsed, total, total_label, location, _BOLD, _RESET, _COLOR_GREEN, outcome.experience_awarded, _RESET, level, recycled, ammunition, carry, fatigued),
        )
    if outcome.kind is OutcomeKind.LOOT_ACQUIRED:
        rarity = _loot_rarity_tag(outcome.loot_key)
        if outcome.letter_collection_completed:
            return (
                tr('{0} > {1}[DUCK HUNT]{2} Collection complète : lot aléatoire, bon de 50 xp et munitions réapprovisionnées.{3}', actor, _COLOR_GREEN, _RESET, rarity),
            )
        if (outcome.loot_key or "").startswith("letter_") and player is not None:
            label = _LOOT_LABELS[outcome.loot_key or ""]
            return (
                tr('{0} > {1}[Butin]{2} {3} | lettres : {4}{5}', actor, _COLOR_GREEN, _RESET, label, _letter_status(player), rarity),
            )
        equipment = _loot_equipment_presentation(outcome)
        if equipment is not None:
            label, description = equipment
            return (
                tr('{0} > En fouillant les buissons autour du canard, tu trouves {1}{2}{3}. {4}{5}', actor, _COLOR_GREEN, label, _RESET, description, rarity),
            )
        label = _LOOT_LABELS.get(outcome.loot_key or "", tr('un objet'))
        detail = f" ({outcome.curse_key})" if outcome.curse_key else ""
        return (
            tr('{0} > En fouillant les buissons autour du canard, tu trouves... {1}{2}{3}{4}.{5}', actor, _COLOR_GREEN, label, detail, _RESET, rarity),
        )
    if outcome.kind is OutcomeKind.CURSE_NEUTRALIZED:
        return (
            tr('{0} > Ton amulette de bénédiction neutralise la malédiction.', actor),
        )
    if outcome.kind is OutcomeKind.MILESTONE_CREDIT:
        return (
            tr("{0} > {1}[Palier]{2} Bon d'achat : {3} xp.", actor, _COLOR_GREEN, _RESET, outcome.shop_credit_awarded),
        )
    if outcome.kind is OutcomeKind.REWARD_TRIGGERED:
        if outcome.triggered_item_id == 21:
            return (tr('{0} > Ton amulette fait apparaître du pain sur le canal.', actor),)
        return (
            tr('{0} > Ton amulette programme un canard mécanique dans 10mn00s.', actor),
        )
    if outcome.kind is OutcomeKind.FLIGHT_SURVIVED:
        if outcome.flight_kind is FlightKind.GOLDEN:
            return (
                tr("{0} > {1} C'est un {2}[CANARD DORÉ]{3} ! Il a survécu. [vie -{4}]{5}", actor, _shot_sound(outcome), _COLOR_GREEN, _RESET, outcome.damage_dealt, fatigued),
            )
        return (tr('{0} > Le canard a survécu. [vie -{1}]{2}', actor, outcome.damage_dealt, fatigued),)
    if outcome.kind is OutcomeKind.MISS:
        recycled = tr(' [munition recyclée]') if outcome.ammunition_recycled else ""
        miss = tr('{0}[raté : -{1} xp]{2}', _COLOR_RED, outcome.miss_penalty, _RESET)
        if outcome.flight_id is None:
            wild = tr('{0}[tir sauvage : -{1} xp]{2}', _COLOR_RED, outcome.wild_penalty, _RESET)
            return (
                tr("{0} > Par chance tu as raté, mais tu visais qui au juste ? Il n'y a aucun canard dans le coin...   {1} {2}{3}", actor, miss, wild, recycled),
            )
        return (
            tr('{0} > Raté. {1}{2}{3}', actor, miss, recycled, fatigued),
        )
    if outcome.kind is OutcomeKind.LATE_SHOT:
        delay = "--" if outcome.late_by_ms is None else format_duration_ms(outcome.late_by_ms)
        recycled = tr(' [munition recyclée]') if outcome.ammunition_recycled else ""
        return (
            tr("{0} > C'est raté, tu as tiré {1} trop tard.   {2}[raté : -{3} xp]{4}{5}", actor, delay, _COLOR_RED, outcome.miss_penalty, _RESET, recycled),
        )
    if outcome.kind is OutcomeKind.EMPTY:
        return (tr('{0} > {1}*CLIC*{2} CHARGEUR VIDE', actor, _COLOR_GREY, _RESET),)
    if outcome.kind is OutcomeKind.JAMMED:
        return (tr('{0} > {1}*CLAC*{2} ARME ENRAYÉE', actor, _COLOR_GREY, _RESET),)
    if outcome.kind is OutcomeKind.RELOADED:
        ammo = "?" if player is None else f"{player.ammo}/{player.capacity}"
        magazines = (
            "?"
            if player is None
            else "∞"
            if outcome.unlimited_magazines
            else f"{player.magazines}/{player.magazine_capacity}"
        )
        automatic = tr(' [rechargement auto.]') if outcome.automatic else ""
        return (
            tr('{0} > {1}*CLAC CLAC*{2} Tu recharges. | Mun. : {3} | Charg. : {4}{5}', actor, _COLOR_GREY, _RESET, ammo, magazines, automatic),
        )
    if outcome.kind is OutcomeKind.UNJAMMED:
        return (tr('{0} > {1}*Crr..CLIC*{2} Tu décoinces ton arme.', actor, _COLOR_GREY, _RESET),)
    if outcome.kind is OutcomeKind.ALREADY_LOADED:
        if player is None:
            return (tr("{0} > Ton arme n'a pas besoin d'être rechargée.", actor),)
        magazines = (
            "∞"
            if outcome.unlimited_magazines
            else f"{player.magazines}/{player.magazine_capacity}"
        )
        return (
            tr("{0} > Ton arme n'a pas besoin d'être rechargée. | Mun. : {1}/{2} | Charg. : {3}", actor, player.ammo, player.capacity, magazines),
        )
    if outcome.kind is OutcomeKind.NO_RESERVE:
        return (tr('{0} > Tu es à court de chargeurs.', actor),)
    if outcome.kind is OutcomeKind.COMMAND_DELAYED:
        return (tr('{0} > Ton action est retardée de 5s par une malédiction.', actor),)
    if outcome.kind is OutcomeKind.COMMAND_THROTTLED:
        if not outcome.notice_emitted:
            return ()
        wait_ns = max(
            0,
            (outcome.defer_until_ns or 0) - (outcome.due_at_ns or 0),
        )
        return (
            tr('{0} > Trop de commandes ; réessaie dans {1}.', actor, _duration(wait_ns)),
        )
    if outcome.kind is OutcomeKind.CURSE_BLOCKED:
        return (tr("{0} > Cette malédiction t'empêche de recharger.", actor),)
    if outcome.kind is OutcomeKind.TRIGGER_LOCKED:
        return (tr('{0} > {1}*CLIC*{2} Gâchette verrouillée.', actor, _COLOR_GREY, _RESET),)
    if outcome.kind is OutcomeKind.FLIGHT_FRIGHTENED:
        return (tr("Effrayé par tout ce bruit, le canard s'échappe."),)
    if outcome.kind is OutcomeKind.HUNT_BLOCKED:
        return (tr('{0} > Tu ne peux pas chasser pour le moment.', actor),)
    if outcome.kind is OutcomeKind.WEAPON_CONFISCATED:
        return (tr('{0} > {1}[ARME CONFISQUÉE]{2}', actor, _COLOR_RED, _RESET),)
    if outcome.kind is OutcomeKind.SABOTAGE_TRIGGERED:
        return (tr("{0} > {1}*BOUM*{2} Ton arme vient d'exploser.", actor, _BOLD, _RESET),)
    if outcome.kind in (
        OutcomeKind.INCIDENT_DEFLECTED,
        OutcomeKind.INCIDENT_ABSORBED,
        OutcomeKind.INCIDENT_FATAL,
    ):
        return (_render_incident(outcome, None),)
    if outcome.kind is OutcomeKind.SHOP_PURCHASED:
        tags = ""
        if outcome.shop_credit_spent:
            tags += tr(" [bon d'achat]")
        if outcome.discount_percent:
            tags += tr(' [coupon promo.]')
        if outcome.item_id == 25 and player is not None:
            before = player.fatigue_centi - outcome.fatigue_changed_centi
            feeling = (tr('Tu te sens en pleine forme mais un peu surexcité. [surexcité]')
                       if player.fatigue_centi < 0 else tr('Tu te sens en pleine forme.')
                       if player.fatigue_centi == 0 else "")
            return (
                tr("{0} > Tu achètes un thermos de café en échange de {1} points d'xp. Fatigue : {2} → {3}. {4}{5}", actor, outcome.charged_experience, _fatigue(before), _fatigue(player.fatigue_centi), feeling, tags),
            )
        if outcome.item_id == 7:
            magnitude = outcome.effect_magnitude
            if type(magnitude) is not int or not 0 <= magnitude <= 15:
                raise ValueError("targeting-scope purchase magnitude is invalid")
            return (
                tr("{0} > Tu ajoutes une lunette de visée à ton arme en échange de {1} points d'xp. Lunette pour 6 tirs : +{2} points de précision actuellement.{3}", actor, outcome.charged_experience, magnitude, tags),
            )
        if outcome.item_id == 10:
            magnitude = outcome.effect_magnitude
            if type(magnitude) is not int or not 1 <= magnitude <= 10:
                raise ValueError("lucky-charm purchase magnitude is invalid")
            point = tr('point') if magnitude == 1 else tr('points')
            extra = tr('supplémentaire') if magnitude == 1 else tr('supplémentaires')
            return (
                tr((
                    "{0} > Tu achètes un trèfle à quatre feuilles en échange de {1} points d'xp. Ce "
                    "porte-bonheur te fera gagner {2} {3} d'xp {4} pour chaque canard abattu pendant 24h.{5}"
                ), actor, outcome.charged_experience, magnitude, point, extra, tags),
            )
        if outcome.item_id == 21:
            count = outcome.channel_effect_count
            if type(count) is not int or count < 1:
                raise ValueError("bread purchase count is invalid")
            bread = tr('morceau') if count == 1 else tr('morceaux')
            channel_label = tr('le canal') if channel is None else channel
            if outcome.effect_magnitude == 20:
                return (
                    tr((
                        "{0} > Tu achètes un morceau de pain en échange de {1} points d'xp. Pendant 1h, il "
                        "renforce l'attraction et retarde le départ des nouveaux canards de 20s par morceau. Il "
                        'reste en place à chaque envol. Karma temporaire : +2,00. Il y a actuellement {2} {3} de '
                        'pain sur {4}.{5}'
                    ), actor, outcome.charged_experience, count, bread, channel_label, tags),
                )
            return (
                tr((
                    "{0} > Tu achètes un morceau de pain en échange de {1} points d'xp. Il reste disponible "
                    "pendant 1h ou jusqu'au prochain envol, qui en consommera un. Ton karma temporaire "
                    'augmente aussi de 2,00. Il y a actuellement {2} {3} de pain sur {4}.{5}'
                ), actor, outcome.charged_experience, count, bread, channel_label, tags),
            )
        if outcome.item_id == 20:
            return (
                tr("{0} > Tu achètes et utilises un appeau en échange de {1} points d'xp, ce qui devrait attirer un canard dans les 10 prochaines minutes.{2}", actor, outcome.charged_experience, tags),
            )
        return (
            tr('{0} > Achat : {1} [{2} xp].{3}', actor, _item_label(outcome.item_id), outcome.charged_experience, tags),
        )
    if outcome.kind is OutcomeKind.SHOP_UNKNOWN_ITEM:
        return (tr("{0} > Cet objet n'existe pas.", actor),)
    if outcome.kind is OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE:
        return (tr("{0} > Tu n'es pas assez riche pour cet achat.", actor),)
    if outcome.kind is OutcomeKind.SHOP_NOT_APPLICABLE:
        if outcome.item_id == 21:
            return (tr('{0} > Il y a déjà 20 morceaux de pain sur le canal ; achat refusé sans dépense.', actor),)
        return (tr("{0} > Cet achat n'est pas utile actuellement.", actor),)
    if outcome.kind is OutcomeKind.SHOP_EFFECT_ACTIVE:
        return (tr('{0} > {1} est déjà actif.', actor, _item_label(outcome.item_id)),)
    if outcome.kind is OutcomeKind.SHOP_TARGET_REQUIRED:
        return (tr('{0} > Cet achat nécessite une cible.', actor),)
    if outcome.kind is OutcomeKind.SHOP_TARGET_UNKNOWN:
        return (tr('{0} > Je ne connais aucun chasseur portant ce nom.', actor),)
    if outcome.kind is OutcomeKind.SHOP_TARGET_ABSENT:
        return (tr("{0} > {1} n'est pas là.", actor, outcome.target or tr('Cette cible')),)
    if outcome.kind is OutcomeKind.SHOP_TARGET_UNARMED:
        return (tr("{0} > {1} n'a pas d'arme.", actor, outcome.target or tr('Cette cible')),)
    if outcome.kind is OutcomeKind.SHOP_TARGET_IMMUNE:
        return (
            tr("{0} > L'arme de {1} est immunisée contre cette nuisance.", actor, outcome.target or tr('cette cible')),
        )
    if outcome.kind is OutcomeKind.EFFECT_CONSUMED:
        if outcome.item_id == 21:
            return (tr('Le canard mange un morceau de pain posé sur le canal.'),)
        return ()
    if outcome.kind in (
        OutcomeKind.EFFECT_EXPIRED,
        OutcomeKind.CHANNEL_ACTION_DUE,
        OutcomeKind.DUCK_ALERT,
        OutcomeKind.CURSE_EXPIRED,
        OutcomeKind.SCHEDULED_FLIGHT_SKIPPED,
        OutcomeKind.QUERY,
    ):
        return ()
    raise ValueError(f"unsupported outcome kind: {outcome.kind}")


@localized
def render_outcomes(
    outcomes: Iterable[Outcome],
    *,
    flight_appearance: FlightAppearance | None = None,
    channel: str | None = None,
) -> tuple[str, ...]:
    """Flatten outcomes while preserving engine order and the flood boundary."""

    materialized = tuple(outcomes)
    lines_list: list[str] = []
    pending_miss: Outcome | None = None
    for index, outcome in enumerate(materialized):
        next_kind = (
            None if index + 1 == len(materialized) else materialized[index + 1].kind
        )
        if outcome.kind is OutcomeKind.MISS and next_kind in (
            OutcomeKind.INCIDENT_DEFLECTED,
            OutcomeKind.INCIDENT_ABSORBED,
            OutcomeKind.INCIDENT_FATAL,
        ):
            pending_miss = outcome
            continue
        if outcome.kind in (
            OutcomeKind.INCIDENT_DEFLECTED,
            OutcomeKind.INCIDENT_ABSORBED,
            OutcomeKind.INCIDENT_FATAL,
        ):
            lines_list.append(_render_incident(outcome, pending_miss))
            pending_miss = None
            continue
        lines_list.extend(
            render_outcome(
                outcome,
                flight_appearance=flight_appearance,
                channel=channel,
            )
        )
    lines = tuple(lines_list)
    if len(lines) <= MAX_RESPONSE_LINES:
        return lines
    retained = lines[: MAX_RESPONSE_LINES - 1]
    omitted = len(lines) - len(retained)
    return retained + (tr('{0}[+{1} événements]{2}', _COLOR_GREY, omitted, _RESET),)


def _render_incident(outcome: Outcome, miss: Outcome | None) -> str:
    actor = _player_name(outcome)
    target = outcome.target or tr('une cible')
    if outcome.kind is OutcomeKind.INCIDENT_DEFLECTED:
        defense = "?" if outcome.deflection_bps is None else str(outcome.deflection_bps // 100)
        text = (
            tr('{0}*PIEWWW*{1}     une balle de {2} ricoche sur {3} grâce à son modificateur de déflexion de {4}%.', _BOLD, _RESET, actor, target, defense)
        )
    elif outcome.kind is OutcomeKind.INCIDENT_ABSORBED:
        defense = "?" if outcome.armor_bps is None else str(outcome.armor_bps // 100)
        text = (
            tr("{0}*PLOC*{1}     l'armure de {2} arrête une balle perdue de {3} grâce à sa protection de {4}%.", _BOLD, _RESET, target, actor, defense)
        )
    else:
        text = (
            tr("{0}*BANG* xO'{1}     {2} vient de se faire descendre accidentellement par {3}.", _BOLD, _RESET, target, actor)
        )
    tags: list[str] = []
    if miss is not None:
        tags.append(tr('[raté : -{0} xp]', miss.miss_penalty))
        if miss.wild_penalty:
            tags.append(tr('[tir sauvage : -{0} xp]', miss.wild_penalty))
    tags.append(tr('[accident : -{0} xp]', outcome.incident_penalty))
    if outcome.weapon_confiscated:
        tags.append(tr('[ARME CONFISQUÉE : accident de chasse]'))
    fatigue = "" if miss is None else _fatigue_tag(miss.fatigue_penalty_bps, miss.overexcitation_penalty_bps)
    return f"{text}   {_COLOR_RED}{' '.join(tags)}{_RESET}{fatigue}"


if set(_ITEM_LABELS) != {item.item_id for item in SHOP_CATALOG}:
    raise RuntimeError("every supported shop item requires one public label")
if any(shop_item(item_id) is None for item_id in _ITEM_LABELS):
    raise RuntimeError("response labels reference an unsupported shop item")
_EQUIPMENT_LOOT_KEYS = {
    spec.key
    for spec in (*STANDARD_LOOT_CATALOG, *UNUSUAL_LOOT_CATALOG)
    if spec.grant_kind
    in (
        LootGrantKind.EFFECT,
        LootGrantKind.REWARD_EFFECT,
        LootGrantKind.PERMANENT_UPGRADE,
    )
}
if set(_LOOT_EQUIPMENT_PRESENTATION) | set(
    _VARIABLE_LOOT_EQUIPMENT_KEYS
) != _EQUIPMENT_LOOT_KEYS:
    raise RuntimeError("every equipment loot requires one complete presentation")
