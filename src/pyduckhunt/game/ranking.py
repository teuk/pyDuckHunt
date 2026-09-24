"""Stable player-ranking order shared by IRC and public exports."""

from __future__ import annotations

from enum import Enum

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.game.progression import available_experience
from pyduckhunt.identity import rfc1459_casefold


class RankingCriterion(str, Enum):
    """Supported deterministic ranking views."""

    EXPERIENCE = "experience"
    HITS = "hits"


def is_statistically_excluded(
    nickname: str,
    *,
    excluded_nicknames: tuple[str, ...] = (),
) -> bool:
    """Return whether one validated IRC identity is outside public statistics."""

    if type(nickname) is not str or not nickname or any(
        character in nickname for character in (" ", "\x00", "\r", "\n")
    ):
        raise ValueError("statistics require one IRC nickname")
    return rfc1459_casefold(nickname) in _excluded_keys(excluded_nicknames)


def statistical_players(
    state: GameState,
    *,
    excluded_nicknames: tuple[str, ...] = (),
) -> tuple[PlayerState, ...]:
    """Return players visible to public statistics without mutating history."""

    if not isinstance(state, GameState):
        raise ValueError("statistics require a game state")
    excluded_keys = _excluded_keys(excluded_nicknames)
    return tuple(player for player in state.players if player.key not in excluded_keys)


def _excluded_keys(excluded_nicknames: tuple[str, ...]) -> frozenset[str]:
    if type(excluded_nicknames) is not tuple or any(
        type(nickname) is not str
        or not nickname
        or any(character in nickname for character in (" ", "\x00", "\r", "\n"))
        for nickname in excluded_nicknames
    ):
        raise ValueError("statistics exclusions must be immutable IRC nicknames")
    excluded_keys = frozenset(
        rfc1459_casefold(nickname) for nickname in excluded_nicknames
    )
    if len(excluded_keys) != len(excluded_nicknames):
        raise ValueError("statistics exclusions must be unique IRC identities")
    return excluded_keys


def ranked_players(
    state: GameState,
    *,
    limit: int | None = None,
    excluded_nicknames: tuple[str, ...] = (),
    criterion: RankingCriterion = RankingCriterion.EXPERIENCE,
) -> tuple[PlayerState, ...]:
    """Return hunters by one explicit stable public-ranking criterion."""

    if not isinstance(state, GameState):
        raise ValueError("ranking requires a game state")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("ranking limit must be a positive integer or none")
    if not isinstance(criterion, RankingCriterion):
        raise ValueError("ranking criterion is unsupported")
    ranking_key = (
        _experience_ranking_key
        if criterion is RankingCriterion.EXPERIENCE
        else _hit_ranking_key
    )
    ordered = tuple(
        sorted(
            statistical_players(state, excluded_nicknames=excluded_nicknames),
            key=ranking_key,
        )
    )
    return ordered if limit is None else ordered[:limit]


def _best_time_key(player: PlayerState) -> int:
    return player.best_time_ms if player.best_time_ms is not None else 2**63 - 1


def _experience_ranking_key(player: PlayerState) -> tuple[int, int, int, str]:
    return (
        -available_experience(player),
        -player.hits,
        _best_time_key(player),
        player.key,
    )


def _hit_ranking_key(player: PlayerState) -> tuple[int, int, str]:
    return (-player.hits, _best_time_key(player), player.key)
