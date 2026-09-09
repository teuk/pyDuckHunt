"""Shared, fixed-point shot accuracy and its player-visible modifiers."""

from __future__ import annotations

from dataclasses import dataclass

from pyduckhunt.game.model import ActiveEffect, GameState, PlayerState
from pyduckhunt.game.level_policy import level_policy


FATIGUE_FREE_CENTI = 1_200
FATIGUE_PENALTY_PER_CENTI = 3


def _effect(state: GameState, player: PlayerState, item_id: int) -> ActiveEffect | None:
    return next((effect for effect in state.effects
                 if effect.owner_key == player.key and effect.item_id == item_id
                 and effect.activated_at_ns <= state.now_ns
                 and (effect.expires_at_ns is None or state.now_ns < effect.expires_at_ns)), None)


def fatigue_penalty_bps(state: GameState, player: PlayerState) -> int:
    """No penalty through 12 fatigue; then three percentage points per point."""
    if _effect(state, player, 102) is not None:
        return 0
    return min(10_000, max(0, player.fatigue_centi - FATIGUE_FREE_CENTI)
               * FATIGUE_PENALTY_PER_CENTI)


def overexcitation_penalty_bps(state: GameState, player: PlayerState) -> int:
    """Negative fatigue costs three accuracy points per point; endurance suppresses it."""
    if _effect(state, player, 102) is not None:
        return 0
    return min(10_000, max(0, -player.fatigue_centi) * FATIGUE_PENALTY_PER_CENTI)


def scope_bonus_points(base_bps: int) -> int:
    """One third of the gap to perfect base accuracy, rounded down to whole points."""
    if type(base_bps) is not int or not 0 <= base_bps <= 10_000:
        raise ValueError('base accuracy must be an integer from zero to 10000')
    return (10_000 - base_bps) // 300


def live_scope_bonus_points(state: GameState, player: PlayerState) -> int | None:
    """Display the same current-level bonus as a newly settled live shot."""
    if _effect(state, player, 7) is None:
        return None
    return scope_bonus_points(level_policy(player.level).accuracy_bps)


@dataclass(frozen=True, slots=True)
class AccuracyBreakdown:
    base_bps: int
    modifiers: tuple[tuple[str, int], ...]
    effective_bps: int


def shot_accuracy(
    state: GameState,
    player: PlayerState,
    base_bps: int,
    *,
    settled_fatigue_penalty_bps: int = 0,
    settled_overexcitation_penalty_bps: int = 0,
    settled_scope_bonus_points: int | None = None,
) -> AccuracyBreakdown:
    """Compose modifiers; legacy replay explicitly retains its zero penalty."""
    for value in (base_bps, settled_fatigue_penalty_bps, settled_overexcitation_penalty_bps):
        if type(value) is not int or not 0 <= value <= 10_000:
            raise ValueError('accuracy values must be integers from zero to 10000')
    if settled_scope_bonus_points is not None and (
        type(settled_scope_bonus_points) is not int or not 0 <= settled_scope_bonus_points <= 33
    ):
        raise ValueError("settled scope bonus must be an integer from zero to 33")
    current = base_bps
    modifiers: list[tuple[str, int]] = []
    tonic = _effect(state, player, 27)
    tremor = next((curse for curse in state.curses
                   if curse.owner_key == player.key and curse.key == 'tremor'
                   and state.now_ns < curse.expires_at_ns), None)
    glare = _effect(state, player, 14)
    for label, percent in (
        ('tonic', 10 if tonic is not None else 0),
        ('tremor', (tremor.magnitude or 0) if tremor is not None else 0),
        ('glare', 50 if glare is not None else 0),
    ):
        adjusted = current * (100 - percent) // 100
        if adjusted != current:
            modifiers.append((label, adjusted - current))
        current = adjusted
    scope = _effect(state, player, 7)
    if scope is not None:
        points = (scope.magnitude or 0) if settled_scope_bonus_points is None else settled_scope_bonus_points
        bonus = points * 100
        modifiers.append(('scope', bonus))
        current += bonus
    if settled_fatigue_penalty_bps:
        modifiers.append(('fatigue', -settled_fatigue_penalty_bps))
        current -= settled_fatigue_penalty_bps
    if settled_overexcitation_penalty_bps:
        modifiers.append(('overexcitation', -settled_overexcitation_penalty_bps))
        current -= settled_overexcitation_penalty_bps
    return AccuracyBreakdown(base_bps, tuple(modifiers), min(10_000, max(0, current)))
