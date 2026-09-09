"""Stable player-ranking order shared by IRC and public exports."""

from __future__ import annotations

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.identity import rfc1459_casefold


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
) -> tuple[PlayerState, ...]:
    """Return hunters by hits, best time and canonical IRC identity."""

    if not isinstance(state, GameState):
        raise ValueError("ranking requires a game state")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("ranking limit must be a positive integer or none")
    ordered = tuple(
        sorted(
            statistical_players(state, excluded_nicknames=excluded_nicknames),
            key=lambda player: (
                -player.hits,
                (
                    player.best_time_ms
                    if player.best_time_ms is not None
                    else 2**63 - 1
                ),
                player.key,
            ),
        )
    )
    return ordered if limit is None else ordered[:limit]
