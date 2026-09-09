"""Read-only view of bread that is still available at the requested time."""
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


def preserved_bread_deadline(state: GameState, now_ns: int) -> int | None:
    """Keep the next time on addition / expiry with bread still present."""
    schedule = state.daily_schedule
    if not active_channel_breads(state, now_ns) or schedule is None:
        return None
    day_ns = 86_400_000_000_000
    if schedule.day_start_ns != now_ns - now_ns % day_ns:
        return None
    return next((d for d in schedule.deadlines_ns[schedule.next_index:] if d > now_ns), None)
