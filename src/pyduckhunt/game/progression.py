"""Pure profile progression calibrated from observed game outcomes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pyduckhunt.game.level_policy import level_policy

if TYPE_CHECKING:
    from pyduckhunt.game.model import PlayerState


BASE_HIT_EXPERIENCE = 10


def experience_required(level: int) -> int:
    """Return the observed progression target for a displayed level."""

    if type(level) is not int or level < 1:
        raise ValueError("level must be a positive integer")
    if level <= 60:
        multiplier = 10
    elif level <= 69:
        multiplier = 20
    elif level <= 79:
        multiplier = 30
    else:
        multiplier = 40 + 10 * ((level - 80) // 10)
    return (level + 1) * multiplier


@dataclass(frozen=True, slots=True)
class ProgressionChange:
    player: PlayerState
    amount: int
    levels_gained: int = 0
    levels_lost: int = 0


def _replace_progress(
    player: PlayerState,
    *,
    level: int,
    experience: int,
) -> PlayerState:
    """Apply progress and level-derived weapon capacities atomically."""

    if level == player.level:
        return replace(player, level=level, experience=experience)
    previous = level_policy(player.level)
    current = level_policy(level)
    capacity_bonus = max(0, player.capacity - previous.ammo_capacity)
    magazine_bonus = max(
        0,
        player.magazine_capacity - previous.magazine_capacity,
    )
    capacity = current.ammo_capacity + capacity_bonus
    magazine_capacity = current.magazine_capacity + magazine_bonus
    return replace(
        player,
        level=level,
        experience=experience,
        ammo=min(player.ammo, capacity),
        capacity=capacity,
        magazines=min(player.magazines, magazine_capacity),
        magazine_capacity=magazine_capacity,
    )


def grant_experience(player: PlayerState, amount: int) -> ProgressionChange:
    """Grant points and carry overflow across any number of levels."""

    if type(amount) is not int or amount < 0:
        raise ValueError("experience grant must be a non-negative integer")
    level = player.level
    experience = player.experience + amount
    gained = 0
    while experience >= experience_required(level):
        experience -= experience_required(level)
        level += 1
        gained += 1
    return ProgressionChange(
        _replace_progress(player, level=level, experience=experience),
        amount,
        gained,
    )


def spend_experience(player: PlayerState, amount: int) -> ProgressionChange:
    """Debit points, crossing level boundaries without creating experience debt."""

    if type(amount) is not int or amount < 0:
        raise ValueError("experience cost must be a non-negative integer")
    available = available_experience(player)
    if amount > available:
        raise ValueError("insufficient experience")
    level = player.level
    experience = player.experience
    remaining = amount
    lost = 0
    while remaining > experience:
        remaining -= experience
        level -= 1
        if level < 1:
            raise ValueError("insufficient experience")
        experience = experience_required(level)
        lost += 1
    experience -= remaining
    return ProgressionChange(
        _replace_progress(player, level=level, experience=experience),
        -amount,
        levels_lost=lost,
    )


def available_experience(player: PlayerState) -> int:
    """Return the total spendable balance represented by level and progress."""

    return player.experience + sum(
        experience_required(level) for level in range(1, player.level)
    )


def debit_experience(player: PlayerState, amount: int) -> ProgressionChange:
    """Apply a bounded penalty, never allowing a negative balance."""

    if type(amount) is not int or amount < 0:
        raise ValueError("experience penalty must be a non-negative integer")
    return spend_experience(player, min(amount, available_experience(player)))
