"""Stable player-ranking order shared by IRC and public exports."""

from __future__ import annotations

from pyduckhunt.game.model import GameState, PlayerState


def ranked_players(
    state: GameState,
    *,
    limit: int | None = None,
) -> tuple[PlayerState, ...]:
    """Return hunters by hits, best time and canonical IRC identity."""

    if not isinstance(state, GameState):
        raise ValueError("ranking requires a game state")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("ranking limit must be a positive integer or none")
    ordered = tuple(
        sorted(
            state.players,
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
