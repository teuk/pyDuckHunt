"""Bounded anti-automation variety for scheduled flight presentation."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


IntegerSource = Callable[[int, int], int]


FLIGHT_TRAILS = (
    "·-.,_¸,.-·°'`°·-.,¸_¸,.·'`'°",
    "-.,¸_¸,.·°'`'°·-.¸_¸,.-·°'`°",
    "·.¸_¸,.-·°`'°·-.,¸_,.-·°'`'°",
    "·.,¸_¸,.-·'`'°·-.,¸_,-·°'`'°",
    "·-.,¸¸.-·°'`'°-.,¸_¸,.-°'`'°",
    "·.,¸_¸,.-·°`°·-.,¸_¸.-·°'`'°",
    "·-.,¸_¸,.·'`'°·-.,_¸,.-·°'`°",
    "·-.¸_¸,.-·°''°·-.,¸_¸,-°'`'°",
    "·-,¸_¸,.-·°`'°·-.,¸_¸.·°'`'°",
    "·-,_¸,.-·°''°·-.,¸_¸.-·°'`'°",
    "-,¸_¸,.-·'`'°·-.,¸¸,.-·°'`'°",
    "·-.,¸_¸,-°'`'°·-.¸_¸,.-·°''°",
    "·-.,¸_,.-·°'`'°·.¸_¸,.-·°`'°",
    "·-.,¸_,.-·°'`'°-.,¸_¸,.-·''°",
    "·-.,¸¸,.-·°'`'·-.,¸_¸,.-°`'°",
    "·-.,¸_¸.-·°'`'°·-,_¸,.-·°''°",
    "·-.,¸_¸,-·°'`'°·-,¸_¸,.-·°''",
    "·-.,¸_¸.-·°'`'°·.,¸_¸,.-·°`°",
    "·-.,¸_¸,-·°'`'°·-.¸¸,.-·°'`°",
    "·-.¸¸,.-·°'`°·-.,¸_¸,-·°'`'°",
    "·-.,¸_¸,.-°`'°·-.,¸¸,.-·°'`'",
    "·-,¸_¸,.-·°''·-.,¸_¸,-·°'`'°",
    "·-.,_¸,.-·°'`'·.,¸_¸,.-°'`'°",
    "-.,¸_¸,.-·''°·-.,¸_,.-·°'`'°",
    "·-.,¸_¸,.·°'`'°·-.,_,.-·°'`'",
    "·-.,_,.-·°'`'·-.,¸_¸,.·°'`'°",
    "-.,¸_¸,.-°'`'°·-.,¸¸.-·°'`'°",
    "·-.,¸_¸.·°'`'°·-,¸_¸,.-·°`'°",
    "·.,¸_¸,.-°'`'°·-.,_¸,.-·°'`'",
    "·-.,¸¸,.-·°'`'°-,¸_¸,.-·'`'°",
    "·-.¸_¸,.-·°'`°-.,¸_¸,.·°'`'°",
    "·-.,¸_,-·°'`'°·.,¸_¸,.-·'`'°",
)

FLIGHT_WINGS = ("\\", "/")
FLIGHT_EYES = (
    "O",
    "o",
    "0",
    "@",
    "^",
    "©",
    "°",
    "º",
    "Ò",
    "Ó",
    "Ô",
    "Õ",
    "Ö",
    "Ø",
    "ò",
    "ó",
    "ô",
    "õ",
    "ö",
    "ø",
)
FLIGHT_BEAKS = ("<", "{", "-")

FLIGHT_CALLS = (
    "COIN",
    "KAAK",
    "COUAK",
    "COUAAAACK",
    "COUAAAAC",
    "QUAK",
    "QUAACK",
    "QUAAAK",
    "AAAARK",
    "QWAAACK",
    "COUAAAAK",
    "COUAC",
    "AARK",
    "QUAAAACK",
    "COUAAACK",
    "COUAAK",
    "QUACK",
    "QUAAK",
    "KWAAAK",
    "KAAAAK",
    "COUAAC",
    "COUACK",
    "ARK",
    "COUAAAK",
    "QWAAAACK",
    "KWAAAAK",
    "KAAAK",
    "COUAAAC",
    "QWAK",
    "QWACK",
    "QWAAAAK",
    "QUAAACK",
    "KWAK",
    "COUAACK",
    "QUAAAAK",
    "QWAAK",
    "KWAAK",
    "QWAAAK",
    "AAARK",
    "QWAACK",
)

FLIGHT_LINES = (
    "c'est ici que ça canarde ?",
    "PIOU ?",
    "on m'a parlé d'un troupeau de touristes avec des pétoires, c'est ici ?",
    "regardez, là bas ! une diversion !",
    "vous visez vraiment mal...",
    "c'est ici pour le casting ?",
    "tirez pas, je suis un pigeon !",
    "tirez pas, je suis un fake !",
    "c'est moi que tu regardes, là ? C'EST MOI QUE TU REGARDES ?!",
    "POUÊT",
    "n'ayez pas peur, je ne vous veux aucun mal",
    "ah que coin coin !",
    "CôÔT ?",
    "je suis invulnérable HAHAHAHA",
    "Hello world",
    "*sifflote*",
    "ne tirez pas, je me rends !",
    "bon, c'est qui le trou du cul qui a tué mon pote ?!",
    "pourvu que personne ne me remarque...",
    "CUI ?",
    "vous connaissez l'histoire du con qui dit !bang ?",
    "laissez-moi tranquille, je drope des malédictions",
    "je viens en paix",
    "je suis venu négocier une trêve",
    "je ne vous en veux pas",
    "arrêtez, c'est pas ce que vous croyez !",
    "euh... pourquoi vous avez tous une arme dans la main ?",
    "je cherche mon pote, il devait m'attendre ici",
    "ne tirez pas, je ne suis pas armé !",
    "بطبطة",
    "QUECK",
)


@dataclass(frozen=True, slots=True)
class FlightAppearance:
    """One already-settled, bounded visual presentation for a flight."""

    trail: str
    silhouette: str
    utterance: str

    def __post_init__(self) -> None:
        _validate_fragment(self.trail, "flight trail", 64)
        _validate_fragment(self.silhouette, "flight silhouette", 8)
        _validate_fragment(self.utterance, "flight utterance", 120)


class RandomizedFlightAppearanceSource:
    """Draw independent presentation components from an injected source."""

    def __init__(self, integer_source: IntegerSource) -> None:
        if not callable(integer_source):
            raise ValueError("flight appearance requires an integer source")
        self._integer_source = integer_source
        self._owner_thread = threading.get_ident()

    def __call__(self) -> FlightAppearance:
        self._ensure_owner()
        trail = self._pick(FLIGHT_TRAILS)
        wing = self._pick(FLIGHT_WINGS)
        eye = self._pick(FLIGHT_EYES)
        beak = self._pick(FLIGHT_BEAKS)
        utterances = FLIGHT_LINES if self._draw(1, 4) == 1 else FLIGHT_CALLS
        utterance = self._pick(utterances)
        return FlightAppearance(trail, f"{wing}_{eye}{beak}", utterance)

    def _pick(self, values: tuple[str, ...]) -> str:
        return values[self._draw(0, len(values) - 1)]

    def _draw(self, minimum: int, maximum: int) -> int:
        value = self._integer_source(minimum, maximum)
        if type(value) is not int or not minimum <= value <= maximum:
            raise RuntimeError("flight appearance integer source violated its bounds")
        return value

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("flight appearance source is owned by one event-loop thread")


def _validate_fragment(value: object, label: str, maximum: int) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(character in value for character in ("\x00", "\r", "\n", "\x02", "\x03", "\x0f"))
    ):
        raise ValueError(f"{label} is invalid")


if len(FLIGHT_TRAILS) != 32 or len(set(FLIGHT_TRAILS)) != len(FLIGHT_TRAILS):
    raise RuntimeError("flight trail catalog must contain 32 unique entries")
if len(FLIGHT_CALLS) != 40 or len(set(FLIGHT_CALLS)) != len(FLIGHT_CALLS):
    raise RuntimeError("flight call catalog must contain 40 unique entries")
if len(FLIGHT_LINES) != 31 or len(set(FLIGHT_LINES)) != len(FLIGHT_LINES):
    raise RuntimeError("flight line catalog must contain 31 unique entries")
