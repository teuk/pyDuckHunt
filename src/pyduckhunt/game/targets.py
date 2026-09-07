"""Catalog rules for deterministic flight kinds and rewards."""

from __future__ import annotations

from pyduckhunt.game.model import FlightKind
from pyduckhunt.game.progression import BASE_HIT_EXPERIENCE


GOLDEN_MIN_HEALTH = 3
GOLDEN_MAX_HEALTH = 5
GOLDEN_REWARD_PER_HEALTH = 12
STANDARD_REWARD_EXPERIENCE = BASE_HIT_EXPERIENCE


def flight_reward(kind: FlightKind, health: int) -> int:
    if not isinstance(kind, FlightKind):
        raise ValueError("flight kind is invalid")
    if type(health) is not int or health < 1:
        raise ValueError("flight health must be a positive integer")
    if kind is FlightKind.GOLDEN:
        if not GOLDEN_MIN_HEALTH <= health <= GOLDEN_MAX_HEALTH:
            raise ValueError("golden flight health is outside its calibrated range")
        return GOLDEN_REWARD_PER_HEALTH * health
    if kind is FlightKind.MECHANICAL:
        if health != 1:
            raise ValueError("mechanical flight health must be one")
        return 0
    return STANDARD_REWARD_EXPERIENCE


def validate_flight_reward(kind: FlightKind, health: int, reward: int) -> None:
    if type(reward) is not int or reward < 0:
        raise ValueError("flight reward must be a non-negative integer")
    if reward != flight_reward(kind, health):
        raise ValueError("flight reward differs from the calibrated target catalog")
