"""Read-only views of channel bread and its one-shot attraction deadline."""
from pyduckhunt.game.model import ActiveEffect, EffectScope, GameState


def active_channel_breads(state: GameState, now_ns: int) -> tuple[ActiveEffect, ...]:
    return tuple(sorted((effect for effect in state.effects
        if effect.item_id == 21 and effect.key == "channel_bread"
        and effect.scope is EffectScope.CHANNEL and effect.owner_key is None
        and effect.activated_at_ns <= now_ns
        and (effect.expires_at_ns is None or now_ns < effect.expires_at_ns)),
        key=lambda effect: (effect.activated_at_ns, effect.effect_id)))


MAX_CHANNEL_BREAD = 20
BREAD_DELAY_NS = 20_000_000_000


def bread_identifiers(state: GameState, now_ns: int) -> tuple[int, ...]:
    return tuple(sorted(effect.effect_id for effect in active_channel_breads(state, now_ns)))


def bread_attraction_deadline(effect: ActiveEffect) -> int | None:
    """Return a v2 bread attraction deadline, excluding legacy hourly bread."""

    if effect.item_id != 21 or effect.key != "channel_bread":
        raise ValueError("bread attraction requires channel bread")
    return effect.magnitude


def due_channel_bread(state: GameState, now_ns: int) -> ActiveEffect | None:
    """Return the oldest active piece whose attraction attempt is due."""

    return min(
        (
            effect
            for effect in active_channel_breads(state, now_ns)
            if bread_attraction_deadline(effect) is not None
            and bread_attraction_deadline(effect) <= now_ns
        ),
        key=lambda effect: (
            bread_attraction_deadline(effect),
            effect.activated_at_ns,
            effect.effect_id,
        ),
        default=None,
    )


def next_bread_attraction_deadline(state: GameState, now_ns: int) -> int | None:
    """Return the next live bread-attraction wake-up, if one is scheduled."""

    return min(
        (
            deadline
            for effect in active_channel_breads(state, now_ns)
            if (deadline := bread_attraction_deadline(effect)) is not None
        ),
        default=None,
    )


def preserved_bread_deadline(state: GameState, now_ns: int) -> int | None:
    """Keep the next time on addition / expiry with bread still present."""
    schedule = state.daily_schedule
    if not active_channel_breads(state, now_ns) or schedule is None:
        return None
    day_ns = 86_400_000_000_000
    if schedule.day_start_ns != now_ns - now_ns % day_ns:
        return None
    return next((d for d in schedule.deadlines_ns[schedule.next_index:] if d > now_ns), None)
