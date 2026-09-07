"""Derived hunting karma and bounded loot-quality policy."""

from __future__ import annotations

from dataclasses import replace

from pyduckhunt.game.model import PlayerState


KARMA_MIN_BASIS_POINTS = -10_000
KARMA_MAX_BASIS_POINTS = 10_000
KARMA_MODIFIER_CHANGE_BASIS_POINTS = 200
KARMA_DECAY_STEP_BASIS_POINTS = 12
KARMA_DECAY_PERIOD_NS = 2 * 60 * 60 * 1_000_000_000


def calculate_karma_basis_points(
    hits: int,
    wild_shots: int,
    incidents_caused: int,
    empty_shots: int = 0,
    jammed_shots: int = 0,
    compulsive_reloads: int = 0,
) -> int:
    """Return the historical TCL karma formula as an exact fixed-point percent."""

    for name, value in (
        ("hits", hits),
        ("wild_shots", wild_shots),
        ("incidents_caused", incidents_caused),
        ("empty_shots", empty_shots),
        ("jammed_shots", jammed_shots),
        ("compulsive_reloads", compulsive_reloads),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    # Multiply the historical weights by four to preserve the three 0.25
    # penalties exactly without floating-point arithmetic.
    good = hits * 8
    bad = (
        wild_shots * 4
        + incidents_caused * 12
        + empty_shots
        + jammed_shots
        + compulsive_reloads
    )
    total = good + bad
    if total == 0:
        return 0
    numerator = KARMA_MAX_BASIS_POINTS * (good - bad)
    sign = -1 if numerator < 0 else 1
    rounded = (abs(numerator) + total // 2) // total
    return sign * rounded


def player_base_karma_basis_points(player: PlayerState) -> int:
    """Derive permanent karma from the durable counters of one player."""

    if not isinstance(player, PlayerState):
        raise ValueError("player must satisfy the domain contract")
    return calculate_karma_basis_points(
        player.hits,
        player.wild_shots,
        player.incidents_caused,
        player.empty_shots,
        player.jammed_shots,
        player.compulsive_reloads,
    )


def player_karma_basis_points(player: PlayerState) -> int:
    """Return bounded effective karma, including the temporary shop modifier."""

    base = player_base_karma_basis_points(player)
    return min(
        KARMA_MAX_BASIS_POINTS,
        max(KARMA_MIN_BASIS_POINTS, base + player.karma_modifier_basis_points),
    )


def adjust_karma_modifier(
    player: PlayerState,
    delta_basis_points: int,
    now_ns: int,
) -> PlayerState:
    """Apply one settled shop action and start decay only from neutral."""

    if not isinstance(player, PlayerState):
        raise ValueError("player must satisfy the domain contract")
    if type(delta_basis_points) is not int or delta_basis_points == 0:
        raise ValueError("karma modifier delta must be a non-zero integer")
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("karma modifier time must be a non-negative integer")
    modifier = min(
        KARMA_MAX_BASIS_POINTS,
        max(
            KARMA_MIN_BASIS_POINTS,
            player.karma_modifier_basis_points + delta_basis_points,
        ),
    )
    if modifier == 0:
        deadline = None
    elif player.karma_decay_at_ns is None:
        deadline = now_ns + KARMA_DECAY_PERIOD_NS
    else:
        deadline = player.karma_decay_at_ns
    return replace(
        player,
        karma_modifier_basis_points=modifier,
        karma_decay_at_ns=deadline,
    )


def decay_karma_modifier(player: PlayerState, now_ns: int) -> PlayerState:
    """Move the temporary modifier 0.12 points toward zero every two hours."""

    if not isinstance(player, PlayerState):
        raise ValueError("player must satisfy the domain contract")
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("karma decay time must be a non-negative integer")
    deadline = player.karma_decay_at_ns
    if deadline is None or now_ns < deadline:
        return player
    steps = (now_ns - deadline) // KARMA_DECAY_PERIOD_NS + 1
    amount = steps * KARMA_DECAY_STEP_BASIS_POINTS
    current = player.karma_modifier_basis_points
    modifier = max(0, current - amount) if current > 0 else min(0, current + amount)
    next_deadline = None if modifier == 0 else deadline + steps * KARMA_DECAY_PERIOD_NS
    return replace(
        player,
        karma_modifier_basis_points=modifier,
        karma_decay_at_ns=next_deadline,
    )


def karma_adjusted_jam_basis_points(base_jam_basis_points: int, karma: int) -> int:
    """Reduce positive-karma jam risk by half, or double it at -100%."""

    if type(base_jam_basis_points) is not int or not 0 <= base_jam_basis_points <= 10_000:
        raise ValueError("base jam risk must be between zero and 10000")
    if type(karma) is not int or not -10_000 <= karma <= 10_000:
        raise ValueError("karma must be between -10000 and 10000")
    scale = 10_000 - karma // 2 if karma >= 0 else 10_000 - karma
    return min(10_000, (base_jam_basis_points * scale + 5_000) // 10_000)
