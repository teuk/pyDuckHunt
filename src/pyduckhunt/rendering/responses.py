"""Render deterministic game facts as concise French IRC responses."""

from __future__ import annotations

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

_RARITY_PRESENTATION = {
    LootRarity.UNUSUAL: (_COLOR_GREEN, "item inhabituel"),
    LootRarity.RARE: (_COLOR_BLUE, "item rare"),
    LootRarity.VERY_RARE: (_COLOR_PURPLE, "item très rare"),
    LootRarity.LEGENDARY: (_COLOR_ORANGE, "item légendaire"),
}

_ITEM_LABELS = {
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
}

_LOOT_LABELS = {
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
}

_LOOT_EQUIPMENT_PRESENTATION = {
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
}

_VARIABLE_LOOT_EQUIPMENT_KEYS = frozenset(("targeting_scope", "lucky_charm"))

_INVENTORY_LABELS = {
    "large_ammo_bag": "grande gibecière",
    "extended_magazine": "chargeur étendu",
    "military_ammo_recycler": "recycl. mun. (10%)",
    "indestructible_sunglasses": "lunettes soleil",
    "tearproof_raincoat": "imperméable",
    "military_self_lubricating_system": "syst. autolubrifiant",
    "permanent_killing_license": "permis de tuer",
}

_LEVEL_TITLES = {
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
}

_REWARD_EFFECT_LABELS = {
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
}


def _player(state: GameState, nickname: str) -> PlayerState | None:
    return state.player(rfc1459_casefold(nickname))


def _player_name(outcome: Outcome) -> str:
    if outcome.actor:
        return outcome.actor
    if outcome.player:
        return outcome.player.nickname
    return "Chasseur"


def _item_label(item_id: int | None) -> str:
    if item_id is None:
        return "objet"
    return _ITEM_LABELS.get(
        item_id,
        _REWARD_EFFECT_LABELS.get(item_id, f"objet {item_id}"),
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
            "une lunette de visée pour ton arme",
            f"Lunette pour 6 tirs : +{magnitude} points de précision actuellement.",
        )
    if key == "lucky_charm":
        magnitude = outcome.loot_magnitude
        if type(magnitude) is not int or not 1 <= magnitude <= 10:
            raise ValueError("lucky-charm loot magnitude is invalid")
        point = "point" if magnitude == 1 else "points"
        extra = "supplémentaire" if magnitude == 1 else "supplémentaires"
        return (
            f"un trèfle à 4 feuilles +{magnitude}",
            f"Chaque canard abattu te rapportera {magnitude} {point} d'xp {extra} "
            "pendant 24h.",
        )
    return _LOOT_EQUIPMENT_PRESENTATION.get(key)


def _carry_tag(multiplier: int) -> str:
    label = {1: "", 2: "encombré", 3: "surchargé"}[multiplier]
    return "" if not label else f" {_COLOR_RED}[{label}]{_RESET}"


def _fatigue_tag(penalty_bps: int, excitement_bps: int = 0) -> str:
    label = "surexcité" if excitement_bps else "fatigué" if penalty_bps else ""
    return f" {_COLOR_RED}[{label}]{_RESET}" if label else ""


def _accuracy_text(state: GameState, player: PlayerState) -> str:
    accuracy = shot_accuracy(
        state, player, level_policy(player.level).accuracy_bps,
        settled_fatigue_penalty_bps=fatigue_penalty_bps(state, player),
        settled_overexcitation_penalty_bps=overexcitation_penalty_bps(state, player),
        settled_scope_bonus_points=live_scope_bonus_points(state, player),
    )
    text = f"{_basis_points(accuracy.base_bps)}%"
    labels = {'tonic': 'tonique', 'tremor': 'tremblements', 'glare': 'ébloui',
              'scope': 'lunette', 'fatigue': 'fatigue', 'overexcitation': 'surexcitation'}
    for label, delta in accuracy.modifiers:
        sign = '+' if delta >= 0 else '-'
        text += f" {sign}{_basis_points(abs(delta))} pts {labels[label]}"
    if accuracy.modifiers:
        text += f" = {_basis_points(accuracy.effective_bps)}%"
    return text


def _shot_sound(outcome: Outcome) -> str:
    sound = "BOUM" if outcome.ammunition_item_id == 4 else "BANG"
    return f"{_BOLD}*{sound}*{_RESET}"


def _golden_ammunition_tag(outcome: Outcome) -> str:
    label = {3: "mun. AP", 4: "mun. expl."}.get(outcome.ammunition_item_id)
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
    return _LEVEL_TITLES.get(level, f"chasseur de niveau {level}")


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
        bounds.append(f"{effect.remaining_uses} util.")
    if effect.magnitude is not None and not 104 <= effect.item_id <= 111:
        bounds.append(
            f"+{_fatigue(effect.magnitude)} fatigue"
            if effect.item_id == 28
            else f"+{scope_points} pts précision"
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


def render_wire_response(target: str, lines: Iterable[str]) -> tuple[bytes, ...]:
    """Frame the fewest bounded public lines allowed by the IRC byte budget."""

    packed = _pack_response_lines(
        _validated_response_lines(lines),
        privmsg_text_budget(target),
    )
    return tuple(render_privmsg_bounded(target, line) for line in packed)


def render_wire_notice(target: str, lines: Iterable[str]) -> tuple[bytes, ...]:
    """Frame the fewest bounded private NOTICE lines allowed by the byte budget."""

    packed = _pack_response_lines(
        _validated_response_lines(lines),
        notice_text_budget(target),
    )
    return tuple(render_notice_bounded(target, line) for line in packed)


def render_detector_notice(outcome: Outcome) -> tuple[str, ...]:
    """Render one player-scoped detector alert for the NOTICE transport."""

    if not isinstance(outcome, Outcome) or outcome.kind is not OutcomeKind.DUCK_ALERT:
        raise ValueError("detector notice requires a duck-alert outcome")
    if outcome.actor is None:
        return ()
    return ("Ton détecteur de canards t'avertit : un canard vient de s'envoler.",)


def render_profile(state: GameState, nickname: str) -> tuple[str, ...]:
    """Render the complete two-line hunting sheet shown by ``!duckstats``."""

    player = _player(state, nickname)
    if player is None:
        return (f"{nickname} > Je ne connais aucun chasseur portant ce nom.",)
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
    jammed = "oui" if player.jammed else "non"
    confiscated = "oui" if player.confiscated else "non"
    return (
        f"{_COLOR_ORANGE}[Profil]{_RESET} {total_experience} xp | "
        f"niv. {player.level} ({_level_title(player.level)}) "
        f"+{level_target - player.experience} xp = niv. sup. | "
        f"fatigue: {_fatigue(player.fatigue_centi)}{_fatigue_tag(fatigue_penalty_bps(state, player), overexcitation_penalty_bps(state, player))} | "
        f"karma: {_basis_points(karma)} | "
        f"rentab.: {_ratio_centi(total_experience, player.hits)} xp/canard | "
        f"dépensé: {player.experience_spent} xp  "
        f"{_COLOR_ORANGE}[Stats]{_RESET} "
        f"préc. théor.: {_accuracy_text(state, player)} | "
        f"effic. tirs: {_basis_points(effective_accuracy_bps)}% | "
        f"fiab. arme: {_basis_points(base_reliability_bps)}"
        f"{reliability_modifier}% | "
        f"armure: {_basis_points(policy.armor_bps)}% | "
        f"déflex.: {_basis_points(policy.deflection_bps)}%  "
        f"{_COLOR_ORANGE}[Arme]{_RESET} "
        f"enray.: {jammed} ({player.jams} fois) | "
        f"confisq.: {confiscated} ({player.confiscations} fois)",
        f"{_COLOR_ORANGE}[Tableau de chasse]{_RESET} "
        f"meill. tps.: {best} | "
        f"{player.hits} canards (dont {player.golden_hits} super-canards) | "
        f"{player.misses} tirs ratés | "
        f"{player.empty_shots} tirs à vide | "
        f"{player.jammed_shots} tirs enray. | "
        f"{player.compulsive_reloads} recharg. compulsifs | "
        f"{player.wild_shots} tirs sauvages | "
        f"{player.incidents_caused} accidents | "
        f"{player.shots_fired} coups tirés  "
        f"{_COLOR_ORANGE}[Accidents]{_RESET} "
        f"reçu {player.shots_received} balles perdues dont {player.deaths} mortelles, "
        f"{player.incidents_deflected} ont ricoché et "
        f"{player.incidents_absorbed} ont été encaissées.",
    )


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
        return (f"{nickname} > Je ne connais aucun chasseur portant ce nom.",)
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
            f"fatigue: {_fatigue(player.fatigue_centi)}{_fatigue_tag(fatigue_penalty, excitement)} "
            f"(-{_basis_points(fatigue_penalty + excitement)} pts précision)"
        )
    inventory_parts.extend(
        _effect_status(effect, state.now_ns, scope_points=live_scope_bonus_points(state, player))
        for effect in effects
        if effect.item_id != 9
    )
    if player.shop_credit:
        inventory_parts.append(f"bon d'achat {player.shop_credit} xp")
    curses = tuple(curse.key for curse in state.curses if curse.owner_key == player.key)
    breads = active_channel_breads(state, state.now_ns)
    bread_count = len(breads)
    if bread_count:
        bread_label = "morceau" if bread_count == 1 else "morceaux"
        channel_label = "le canal" if channel is None else channel
        expirations = [effect.expires_at_ns for effect in breads
                       if effect.expires_at_ns is not None]
        expiry = ("" if not expirations else
                  f" (première expiration dans {format_duration_ns(min(expirations) - state.now_ns)})")
        effect_hint = (f" ; +{20 * bread_count}s aux nouveaux vols" if state.bread_plan_effect_ids is not None else "")
        inventory_parts.append(
            f"{bread_count} {bread_label} de pain sur {channel_label}{expiry}{effect_hint}"
        )
    if curses:
        inventory_parts.append(f"malédiction: {', '.join(curses)}")
    weapon_state = (
        " (confisquée définitivement)"
        if player.permanently_confiscated
        else " (confisquée)"
        if player.confiscated
        else " (enrayée)" if player.jammed else ""
    )
    weapon = level_policy(player.level).weapon_label
    magazine_status = (
        "∞"
        if has_unlimited_magazines(state, player.key)
        else f"{player.magazines}/{player.magazine_capacity}"
    )
    unlimited_carry = has_unlimited_duck_carry(state, player.key)
    carry_label = "gibecière TARDIS:" if unlimited_carry else "gibecière:"
    carry_status = (
        _carry_tag(3)
        if not unlimited_carry and player.carried_ducks > 10
        else _carry_tag(2)
        if not unlimited_carry and player.carried_ducks > 5
        else ""
    )
    duck_label = "canard" if player.carried_ducks < 2 else "canards"
    base = (
        f"{_COLOR_ORANGE}[Inventaire]{_RESET} "
        f"arme: {weapon}{weapon_state} | "
        f"mun.: {player.ammo}/{player.capacity} | "
        f"charg.: {magazine_status} | "
        f"{carry_label} {player.carried_ducks} {duck_label}{carry_status} | "
        f"lettres: {_letter_status(player)}"
    )
    if not inventory_parts:
        return (base,)
    return (base, "| " + " | ".join(inventory_parts))


def render_shop(shop_url: str | None = None) -> tuple[str, ...]:
    """Render an optional operator-controlled catalog link in one safe line."""

    normalized = normalize_shop_url(shop_url)
    if normalized is None:
        return ("Boutique: !shop [id [cible]]",)
    return (f"Boutique: {normalized} | !shop [id [cible]]",)


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
        lines = (f"{_COLOR_ORANGE}[TOP {limit}]{_RESET} Aucun chasseur classé.",)
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
            f"{_COLOR_BLUE}[Classement complet]{_RESET} {normalized_url}",
        )
    return lines


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
            f"Un canard est en vol depuis {elapsed}; envol dans {remaining} s'il n'est pas touché.",
        )
    if last_flight is None:
        return ("Aucun envol de canard n'a encore été enregistré.",)
    if type(last_flight) is int:
        return (f"Le dernier canard a été aperçu il y a {_duration(last_flight)}.",)
    if not isinstance(last_flight, LastFlight) or type(now_ns) is not int or now_ns < last_flight.ended_at_ns:
        raise ValueError("last-flight rendering requires durable facts and current game time")
    ago = _duration(now_ns - last_flight.ended_at_ns)
    duration = _duration(last_flight.ended_at_ns - last_flight.spawned_at_ns)
    if last_flight.conclusion is LastFlightConclusion.HIT:
        result = f"abattu par {last_flight.actor} en {duration}"
    elif last_flight.conclusion is LastFlightConclusion.ESCAPED:
        result = f"envolé sans être touché après {duration}"
    else:
        result = f"effrayé par un tir après {duration}"
    return (f"Dernier canard : {result}, il y a {ago}.",)


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
            return (f"{nickname} > Je ne connais aucun chasseur portant ce nom.",)
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
                prefix = f"{_COLOR_GREY}[CANARD MÉCANIQUE]{_RESET} "
            return (
                f"{prefix}{_COLOR_GREY}{flight_appearance.trail}{_RESET} "
                f"{_BOLD}{flight_appearance.silhouette}{_RESET}   "
                f"{flight_appearance.utterance}",
            )
        if outcome.flight_kind is FlightKind.MECHANICAL:
            return (f"{_COLOR_GREY}[CANARD MÉCANIQUE]{_RESET} {_BOLD}\\_O<{_RESET}   CLIC",)
        return (
            f"{_COLOR_GREY}·-.,¸¸.-·°'`'°·-.,¸¸.-·°'`'°{_RESET} "
            f"{_BOLD}\\_O<{_RESET}   COIN",
        )
    if outcome.kind is OutcomeKind.FLIGHT_ALREADY_ACTIVE:
        return ()
    if outcome.kind is OutcomeKind.FLIGHT_EXPIRED:
        return (f"Le canard s'échappe. {_COLOR_GREY}·°'`'°-.,¸¸.·°'`{_RESET}",)
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
            f" niv. {player.level} (progression : "
            f"{player.experience}/{experience_required(player.level)})"
        )
        total_label = "canard" if total == "1" else "canards"
        location = "" if channel is None else f" sur {channel}"
        recycled = " [munition recyclée]" if outcome.ammunition_recycled else ""
        carry = _carry_tag(outcome.carry_fatigue_multiplier)
        ammunition = (
            _golden_ammunition_tag(outcome)
            if outcome.flight_kind is FlightKind.GOLDEN
            else ""
        )
        target = (
            f"le {_COLOR_GREEN}[CANARD DORÉ]{_RESET}"
            if outcome.flight_kind is FlightKind.GOLDEN
            else "le canard"
        )
        return (
            f"{actor} > {_shot_sound(outcome)}     Tu as eu {target} en {elapsed}, "
            f"ce qui te fait un total de {total} {total_label}{location}.     "
            f"{_BOLD}\\_X<{_RESET}   *COUAC*   "
            f"{_COLOR_GREEN}[{outcome.experience_awarded} xp]{_RESET}"
            f"{level}{recycled}{ammunition}{carry}{fatigued}",
        )
    if outcome.kind is OutcomeKind.LOOT_ACQUIRED:
        rarity = _loot_rarity_tag(outcome.loot_key)
        if outcome.letter_collection_completed:
            return (
                f"{actor} > {_COLOR_GREEN}[DUCK HUNT]{_RESET} Collection complète : "
                "lot aléatoire, bon de 50 xp et munitions réapprovisionnées."
                f"{rarity}",
            )
        if (outcome.loot_key or "").startswith("letter_") and player is not None:
            label = _LOOT_LABELS[outcome.loot_key or ""]
            return (
                f"{actor} > {_COLOR_GREEN}[Butin]{_RESET} {label} | "
                f"lettres : {_letter_status(player)}{rarity}",
            )
        equipment = _loot_equipment_presentation(outcome)
        if equipment is not None:
            label, description = equipment
            return (
                f"{actor} > En fouillant les buissons autour du canard, tu trouves "
                f"{_COLOR_GREEN}{label}{_RESET}. {description}{rarity}",
            )
        label = _LOOT_LABELS.get(outcome.loot_key or "", "un objet")
        detail = f" ({outcome.curse_key})" if outcome.curse_key else ""
        return (
            f"{actor} > En fouillant les buissons autour du canard, tu trouves... "
            f"{_COLOR_GREEN}{label}{detail}{_RESET}.{rarity}",
        )
    if outcome.kind is OutcomeKind.CURSE_NEUTRALIZED:
        return (
            f"{actor} > Ton amulette de bénédiction neutralise la malédiction.",
        )
    if outcome.kind is OutcomeKind.MILESTONE_CREDIT:
        return (
            f"{actor} > {_COLOR_GREEN}[Palier]{_RESET} Bon d'achat : "
            f"{outcome.shop_credit_awarded} xp.",
        )
    if outcome.kind is OutcomeKind.REWARD_TRIGGERED:
        if outcome.triggered_item_id == 21:
            return (f"{actor} > Ton amulette fait apparaître du pain sur le canal.",)
        return (
            f"{actor} > Ton amulette programme un canard mécanique dans 10mn00s.",
        )
    if outcome.kind is OutcomeKind.FLIGHT_SURVIVED:
        if outcome.flight_kind is FlightKind.GOLDEN:
            return (
                f"{actor} > {_shot_sound(outcome)} C'est un "
                f"{_COLOR_GREEN}[CANARD DORÉ]{_RESET} ! "
                f"Il a survécu. [vie -{outcome.damage_dealt}]{fatigued}",
            )
        return (f"{actor} > Le canard a survécu. [vie -{outcome.damage_dealt}]{fatigued}",)
    if outcome.kind is OutcomeKind.MISS:
        recycled = " [munition recyclée]" if outcome.ammunition_recycled else ""
        miss = f"{_COLOR_RED}[raté : -{outcome.miss_penalty} xp]{_RESET}"
        if outcome.flight_id is None:
            wild = f"{_COLOR_RED}[tir sauvage : -{outcome.wild_penalty} xp]{_RESET}"
            return (
                f"{actor} > Par chance tu as raté, mais tu visais qui au juste ? "
                f"Il n'y a aucun canard dans le coin...   {miss} {wild}{recycled}",
            )
        return (
            f"{actor} > Raté. {miss}{recycled}{fatigued}",
        )
    if outcome.kind is OutcomeKind.LATE_SHOT:
        delay = "--" if outcome.late_by_ms is None else format_duration_ms(outcome.late_by_ms)
        recycled = " [munition recyclée]" if outcome.ammunition_recycled else ""
        return (
            f"{actor} > C'est raté, tu as tiré {delay} trop tard.   "
            f"{_COLOR_RED}[raté : -{outcome.miss_penalty} xp]{_RESET}{recycled}",
        )
    if outcome.kind is OutcomeKind.EMPTY:
        return (f"{actor} > {_COLOR_GREY}*CLIC*{_RESET} CHARGEUR VIDE",)
    if outcome.kind is OutcomeKind.JAMMED:
        return (f"{actor} > {_COLOR_GREY}*CLAC*{_RESET} ARME ENRAYÉE",)
    if outcome.kind is OutcomeKind.RELOADED:
        ammo = "?" if player is None else f"{player.ammo}/{player.capacity}"
        magazines = (
            "?"
            if player is None
            else "∞"
            if outcome.unlimited_magazines
            else f"{player.magazines}/{player.magazine_capacity}"
        )
        automatic = " [rechargement auto.]" if outcome.automatic else ""
        return (
            f"{actor} > {_COLOR_GREY}*CLAC CLAC*{_RESET} Tu recharges. "
            f"| Mun. : {ammo} | Charg. : {magazines}{automatic}",
        )
    if outcome.kind is OutcomeKind.UNJAMMED:
        return (f"{actor} > {_COLOR_GREY}*Crr..CLIC*{_RESET} Tu décoinces ton arme.",)
    if outcome.kind is OutcomeKind.ALREADY_LOADED:
        if player is None:
            return (f"{actor} > Ton arme n'a pas besoin d'être rechargée.",)
        magazines = (
            "∞"
            if outcome.unlimited_magazines
            else f"{player.magazines}/{player.magazine_capacity}"
        )
        return (
            f"{actor} > Ton arme n'a pas besoin d'être rechargée. "
            f"| Mun. : {player.ammo}/{player.capacity} | Charg. : {magazines}",
        )
    if outcome.kind is OutcomeKind.NO_RESERVE:
        return (f"{actor} > Tu es à court de chargeurs.",)
    if outcome.kind is OutcomeKind.COMMAND_DELAYED:
        return (f"{actor} > Ton action est retardée de 5s par une malédiction.",)
    if outcome.kind is OutcomeKind.COMMAND_THROTTLED:
        if not outcome.notice_emitted:
            return ()
        wait_ns = max(
            0,
            (outcome.defer_until_ns or 0) - (outcome.due_at_ns or 0),
        )
        return (
            f"{actor} > Trop de commandes ; réessaie dans {_duration(wait_ns)}.",
        )
    if outcome.kind is OutcomeKind.CURSE_BLOCKED:
        return (f"{actor} > Cette malédiction t'empêche de recharger.",)
    if outcome.kind is OutcomeKind.TRIGGER_LOCKED:
        return (f"{actor} > {_COLOR_GREY}*CLIC*{_RESET} Gâchette verrouillée.",)
    if outcome.kind is OutcomeKind.FLIGHT_FRIGHTENED:
        return ("Effrayé par tout ce bruit, le canard s'échappe.",)
    if outcome.kind is OutcomeKind.HUNT_BLOCKED:
        return (f"{actor} > Tu ne peux pas chasser pour le moment.",)
    if outcome.kind is OutcomeKind.WEAPON_CONFISCATED:
        return (f"{actor} > {_COLOR_RED}[ARME CONFISQUÉE]{_RESET}",)
    if outcome.kind is OutcomeKind.SABOTAGE_TRIGGERED:
        return (f"{actor} > {_BOLD}*BOUM*{_RESET} Ton arme vient d'exploser.",)
    if outcome.kind in (
        OutcomeKind.INCIDENT_DEFLECTED,
        OutcomeKind.INCIDENT_ABSORBED,
        OutcomeKind.INCIDENT_FATAL,
    ):
        return (_render_incident(outcome, None),)
    if outcome.kind is OutcomeKind.SHOP_PURCHASED:
        tags = ""
        if outcome.shop_credit_spent:
            tags += " [bon d'achat]"
        if outcome.discount_percent:
            tags += " [coupon promo.]"
        if outcome.item_id == 25 and player is not None:
            before = player.fatigue_centi - outcome.fatigue_changed_centi
            feeling = ("Tu te sens en pleine forme mais un peu surexcité. [surexcité]"
                       if player.fatigue_centi < 0 else "Tu te sens en pleine forme."
                       if player.fatigue_centi == 0 else "")
            return (
                f"{actor} > Tu achètes un thermos de café en échange de "
                f"{outcome.charged_experience} points d'xp. "
                f"Fatigue : {_fatigue(before)} → {_fatigue(player.fatigue_centi)}. "
                f"{feeling}{tags}",
            )
        if outcome.item_id == 7:
            magnitude = outcome.effect_magnitude
            if type(magnitude) is not int or not 0 <= magnitude <= 15:
                raise ValueError("targeting-scope purchase magnitude is invalid")
            return (
                f"{actor} > Tu ajoutes une lunette de visée à ton arme en échange de "
                f"{outcome.charged_experience} points d'xp. Lunette pour 6 tirs : "
                f"+{magnitude} points de précision actuellement.{tags}",
            )
        if outcome.item_id == 10:
            magnitude = outcome.effect_magnitude
            if type(magnitude) is not int or not 1 <= magnitude <= 10:
                raise ValueError("lucky-charm purchase magnitude is invalid")
            point = "point" if magnitude == 1 else "points"
            extra = "supplémentaire" if magnitude == 1 else "supplémentaires"
            return (
                f"{actor} > Tu achètes un trèfle à quatre feuilles en échange de "
                f"{outcome.charged_experience} points d'xp. Ce porte-bonheur te fera "
                f"gagner {magnitude} {point} d'xp {extra} pour chaque canard abattu "
                f"pendant 24h.{tags}",
            )
        if outcome.item_id == 21:
            count = outcome.channel_effect_count
            if type(count) is not int or count < 1:
                raise ValueError("bread purchase count is invalid")
            bread = "morceau" if count == 1 else "morceaux"
            channel_label = "le canal" if channel is None else channel
            if outcome.effect_magnitude == 20:
                return (
                    f"{actor} > Tu achètes un morceau de pain en échange de "
                    f"{outcome.charged_experience} points d'xp. Pendant 1h, il renforce "
                    "l'attraction et retarde le départ des nouveaux canards de 20s par morceau. "
                    "Il reste en place à chaque envol. Karma temporaire : +2,00. "
                    f"Il y a actuellement {count} {bread} de pain sur {channel_label}.{tags}",
                )
            return (
                f"{actor} > Tu achètes un morceau de pain en échange de "
                f"{outcome.charged_experience} points d'xp. Il reste disponible "
                "pendant 1h ou jusqu'au prochain envol, qui en consommera un. "
                "Ton karma temporaire augmente aussi de 2,00. "
                f"Il y a actuellement {count} {bread} de pain sur {channel_label}."
                f"{tags}",
            )
        if outcome.item_id == 20:
            return (
                f"{actor} > Tu achètes et utilises un appeau en échange de "
                f"{outcome.charged_experience} points d'xp, ce qui devrait attirer "
                f"un canard dans les 10 prochaines minutes.{tags}",
            )
        return (
            f"{actor} > Achat : {_item_label(outcome.item_id)} "
            f"[{outcome.charged_experience} xp].{tags}",
        )
    if outcome.kind is OutcomeKind.SHOP_UNKNOWN_ITEM:
        return (f"{actor} > Cet objet n'existe pas.",)
    if outcome.kind is OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE:
        return (f"{actor} > Tu n'es pas assez riche pour cet achat.",)
    if outcome.kind is OutcomeKind.SHOP_NOT_APPLICABLE:
        if outcome.item_id == 21:
            return (f"{actor} > Il y a déjà 20 morceaux de pain sur le canal ; achat refusé sans dépense.",)
        return (f"{actor} > Cet achat n'est pas utile actuellement.",)
    if outcome.kind is OutcomeKind.SHOP_EFFECT_ACTIVE:
        return (f"{actor} > {_item_label(outcome.item_id)} est déjà actif.",)
    if outcome.kind is OutcomeKind.SHOP_TARGET_REQUIRED:
        return (f"{actor} > Cet achat nécessite une cible.",)
    if outcome.kind is OutcomeKind.SHOP_TARGET_UNKNOWN:
        return (f"{actor} > Je ne connais aucun chasseur portant ce nom.",)
    if outcome.kind is OutcomeKind.SHOP_TARGET_ABSENT:
        return (f"{actor} > {outcome.target or 'Cette cible'} n'est pas là.",)
    if outcome.kind is OutcomeKind.SHOP_TARGET_UNARMED:
        return (f"{actor} > {outcome.target or 'Cette cible'} n'a pas d'arme.",)
    if outcome.kind is OutcomeKind.SHOP_TARGET_IMMUNE:
        return (
            f"{actor} > L'arme de {outcome.target or 'cette cible'} "
            "est immunisée contre cette nuisance.",
        )
    if outcome.kind is OutcomeKind.EFFECT_CONSUMED:
        if outcome.item_id == 21:
            return ("Le canard mange un morceau de pain posé sur le canal.",)
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
    return retained + (f"{_COLOR_GREY}[+{omitted} événements]{_RESET}",)


def _render_incident(outcome: Outcome, miss: Outcome | None) -> str:
    actor = _player_name(outcome)
    target = outcome.target or "une cible"
    if outcome.kind is OutcomeKind.INCIDENT_DEFLECTED:
        defense = "?" if outcome.deflection_bps is None else str(outcome.deflection_bps // 100)
        text = (
            f"{_BOLD}*PIEWWW*{_RESET}     une balle de {actor} ricoche sur {target} "
            f"grâce à son modificateur de déflexion de {defense}%."
        )
    elif outcome.kind is OutcomeKind.INCIDENT_ABSORBED:
        defense = "?" if outcome.armor_bps is None else str(outcome.armor_bps // 100)
        text = (
            f"{_BOLD}*PLOC*{_RESET}     l'armure de {target} arrête une balle perdue "
            f"de {actor} grâce à sa protection de {defense}%."
        )
    else:
        text = (
            f"{_BOLD}*BANG* xO'{_RESET}     {target} vient de se faire descendre "
            f"accidentellement par {actor}."
        )
    tags: list[str] = []
    if miss is not None:
        tags.append(f"[raté : -{miss.miss_penalty} xp]")
        if miss.wild_penalty:
            tags.append(f"[tir sauvage : -{miss.wild_penalty} xp]")
    tags.append(f"[accident : -{outcome.incident_penalty} xp]")
    if outcome.weapon_confiscated:
        tags.append("[ARME CONFISQUÉE : accident de chasse]")
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
