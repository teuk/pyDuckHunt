"""Deferred nickname transfers compatible with MenzAgitat Duck Hunt 2.11."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    GameState,
    InventoryStack,
    PendingIdentityTransfer,
    PlayerState,
    ThrottleWindow,
    Transition,
)
from pyduckhunt.game.progression import available_experience, grant_experience
from pyduckhunt.identity import rfc1459_casefold


PENDING_IDENTITY_TRANSFER_TTL_NS = 3_600_000_000_000


def pending_identity_transfer(
    state: GameState,
    nickname: str,
) -> PendingIdentityTransfer | None:
    """Return the transfer awaiting participation under *nickname*, if any."""

    _validate_state_and_nickname(state, nickname)
    key = rfc1459_casefold(nickname)
    return next(
        (
            transfer
            for transfer in state.pending_identity_transfers
            if transfer.destination_key == key
        ),
        None,
    )


def should_track_nick_change(
    state: GameState,
    old_nickname: str,
    new_nickname: str,
) -> bool:
    """Return whether one IRC NICK fact can affect a known or pending profile."""

    _validate_state_and_nickname(state, old_nickname)
    _validate_nickname(new_nickname)
    old_key = rfc1459_casefold(old_nickname)
    new_key = rfc1459_casefold(new_nickname)
    if old_key == new_key:
        return False
    return (
        state.player(old_key) is not None
        or state.player(new_key) is not None
        or pending_identity_transfer(state, old_nickname) is not None
    )


def track_nick_change(
    state: GameState,
    old_nickname: str,
    new_nickname: str,
    now_ns: int,
) -> Transition:
    """Remember a rename; do not move statistics until later participation."""

    _validate_state_and_nickname(state, old_nickname)
    _validate_nickname(new_nickname)
    if type(now_ns) is not int or now_ns != state.now_ns:
        raise ValueError("nickname tracking requires the already-advanced game clock")
    old_key = rfc1459_casefold(old_nickname)
    new_key = rfc1459_casefold(new_nickname)
    if old_key == new_key:
        return Transition(state, ())

    transfers = {
        transfer.destination_key: transfer
        for transfer in state.pending_identity_transfers
    }
    inherited = transfers.pop(old_key, None)
    source_key = old_key if inherited is None else inherited.source_key
    source_nickname = (
        old_nickname if inherited is None else inherited.source_nickname
    )

    # Returning to the original nickname cancels the unconsumed chain.
    if source_key == new_key:
        return Transition(
            replace(
                state,
                pending_identity_transfers=_sorted_transfers(transfers.values()),
            ),
            (),
        )

    # Duck Hunt records both ordinary renames and potential score takeovers.
    # A chain keeps its first source and follows the participant's latest nick.
    if (
        inherited is not None
        or state.player(old_key) is not None
        or state.player(new_key) is not None
    ):
        transfers[new_key] = PendingIdentityTransfer(
            source_key=source_key,
            source_nickname=source_nickname,
            destination_key=new_key,
            destination_nickname=new_nickname,
            expires_at_ns=now_ns + PENDING_IDENTITY_TRANSFER_TTL_NS,
        )
    return Transition(
        replace(
            state,
            pending_identity_transfers=_sorted_transfers(transfers.values()),
        ),
        (),
    )


def cancel_pending_identity_transfer(
    state: GameState,
    nickname: str,
) -> Transition:
    """Forget an unconsumed rename when its destination leaves IRC."""

    _validate_state_and_nickname(state, nickname)
    key = rfc1459_casefold(nickname)
    retained = tuple(
        transfer
        for transfer in state.pending_identity_transfers
        if transfer.destination_key != key
    )
    return Transition(replace(state, pending_identity_transfers=retained), ())


def resolve_pending_identity_transfer(
    state: GameState,
    nickname: str,
) -> Transition:
    """Consume and settle one rename immediately before player participation."""

    transfer = pending_identity_transfer(state, nickname)
    if transfer is None:
        return Transition(state, ())
    retained = tuple(
        candidate
        for candidate in state.pending_identity_transfers
        if candidate.destination_key != transfer.destination_key
    )
    current = replace(state, pending_identity_transfers=retained)
    source = current.player(transfer.source_key)
    if source is None:
        return Transition(current, ())
    destination = current.player(transfer.destination_key)
    if destination is None:
        return Transition(_rename_profile(current, source, transfer), ())
    return Transition(_merge_profiles(current, source, destination, transfer), ())


def _rename_profile(
    state: GameState,
    source: PlayerState,
    transfer: PendingIdentityTransfer,
) -> GameState:
    replacement = replace(
        source,
        key=transfer.destination_key,
        nickname=transfer.destination_nickname,
    )
    return _replace_profile_and_references(
        state,
        source.key,
        replacement,
        remove_keys=(source.key,),
    )


def _merge_profiles(
    state: GameState,
    source: PlayerState,
    destination: PlayerState,
    transfer: PendingIdentityTransfer,
) -> GameState:
    source_policy = level_policy(source.level)
    destination_policy = level_policy(destination.level)
    base_policy = level_policy(1)
    capacity_bonus = max(
        0,
        source.capacity - source_policy.ammo_capacity,
        destination.capacity - destination_policy.ammo_capacity,
    )
    magazine_bonus = max(
        0,
        source.magazine_capacity - source_policy.magazine_capacity,
        destination.magazine_capacity - destination_policy.magazine_capacity,
    )
    progression_base = replace(
        destination,
        key=transfer.destination_key,
        nickname=transfer.destination_nickname,
        level=1,
        experience=0,
        capacity=base_policy.ammo_capacity + capacity_bonus,
        magazine_capacity=base_policy.magazine_capacity + magazine_bonus,
        ammo=min(destination.ammo, base_policy.ammo_capacity + capacity_bonus),
        magazines=min(
            destination.magazines,
            base_policy.magazine_capacity + magazine_bonus,
        ),
    )
    progressed = grant_experience(
        progression_base,
        available_experience(source) + available_experience(destination),
    ).player
    ammo, magazines = _merged_ammunition(source, destination, progressed)
    inventory = _merged_inventory(source.inventory, destination.inventory)
    karma = max(
        -10_000,
        min(
            10_000,
            source.karma_modifier_basis_points
            + destination.karma_modifier_basis_points,
        ),
    )
    karma_deadline = (
        None
        if karma == 0
        else max(
            value
            for value in (source.karma_decay_at_ns, destination.karma_decay_at_ns)
            if value is not None
        )
    )
    merged = replace(
        progressed,
        ammo=ammo,
        magazines=magazines,
        hits=source.hits + destination.hits,
        misses=source.misses + destination.misses,
        wild_shots=source.wild_shots + destination.wild_shots,
        empty_shots=source.empty_shots + destination.empty_shots,
        jammed_shots=source.jammed_shots + destination.jammed_shots,
        compulsive_reloads=(
            source.compulsive_reloads + destination.compulsive_reloads
        ),
        shots_fired=source.shots_fired + destination.shots_fired,
        jams=source.jams + destination.jams,
        best_time_ms=_best_time(source.best_time_ms, destination.best_time_ms),
        experience_spent=source.experience_spent + destination.experience_spent,
        inventory=inventory,
        jammed=source.jammed or destination.jammed,
        confiscated=source.confiscated or destination.confiscated,
        permanently_confiscated=(
            source.permanently_confiscated
            or destination.permanently_confiscated
        ),
        confiscations=source.confiscations + destination.confiscations,
        incidents_caused=source.incidents_caused + destination.incidents_caused,
        shots_received=source.shots_received + destination.shots_received,
        incidents_deflected=(
            source.incidents_deflected + destination.incidents_deflected
        ),
        incidents_absorbed=(
            source.incidents_absorbed + destination.incidents_absorbed
        ),
        deaths=source.deaths + destination.deaths,
        golden_hits=source.golden_hits + destination.golden_hits,
        fatigue_centi=max(source.fatigue_centi, destination.fatigue_centi),
        shop_credit=source.shop_credit + destination.shop_credit,
        karma_modifier_basis_points=karma,
        karma_decay_at_ns=karma_deadline,
        carried_ducks=source.carried_ducks + destination.carried_ducks,
        carried_day_start_ns=max(
            source.carried_day_start_ns,
            destination.carried_day_start_ns,
        ),
        letter_slots=tuple(
            left or right
            for left, right in zip(
                source.letter_slots,
                destination.letter_slots,
                strict=True,
            )
        ),
    )
    if merged.permanently_confiscated and not merged.confiscated:
        merged = replace(merged, confiscated=True)
    return _replace_profile_and_references(
        state,
        source.key,
        merged,
        remove_keys=(source.key, destination.key),
    )


def _replace_profile_and_references(
    state: GameState,
    source_key: str,
    replacement: PlayerState,
    *,
    remove_keys: tuple[str, ...],
) -> GameState:
    destination_key = replacement.key
    players = tuple(
        sorted(
            (
                *(player for player in state.players if player.key not in remove_keys),
                replacement,
            ),
            key=lambda player: player.key,
        )
    )
    effects = _deduplicate_effects(
        tuple(
            replace(
                effect,
                owner_key=(
                    destination_key if effect.owner_key == source_key else effect.owner_key
                ),
                source_key=(
                    destination_key if effect.source_key == source_key else effect.source_key
                ),
            )
            for effect in state.effects
        )
    )
    actions = tuple(
        replace(
            action,
            source_key=(
                destination_key if action.source_key == source_key else action.source_key
            ),
        )
        for action in state.scheduled_actions
    )
    curses = _deduplicate_curses(
        tuple(
            replace(
                curse,
                owner_key=(
                    destination_key if curse.owner_key == source_key else curse.owner_key
                ),
            )
            for curse in state.curses
        )
    )
    windows = _merge_throttle_windows(
        tuple(
            replace(
                window,
                player_key=(
                    destination_key if window.player_key == source_key else window.player_key
                ),
            )
            for window in state.throttle_windows
        )
    )
    transfers = _rekey_remaining_transfers(
        state.pending_identity_transfers,
        source_key,
        destination_key,
        replacement.nickname,
    )
    return replace(
        state,
        players=players,
        last_shooter_key=(
            destination_key
            if state.last_shooter_key == source_key
            else state.last_shooter_key
        ),
        effects=effects,
        scheduled_actions=actions,
        curses=curses,
        throttle_windows=windows,
        pending_identity_transfers=transfers,
    )


def _merged_ammunition(
    source: PlayerState,
    destination: PlayerState,
    merged: PlayerState,
) -> tuple[int, int]:
    source_full = source.capacity * (source.magazine_capacity + 1)
    destination_full = destination.capacity * (destination.magazine_capacity + 1)
    used = (
        source_full
        - source.ammo
        - source.magazines * source.capacity
        + destination_full
        - destination.ammo
        - destination.magazines * destination.capacity
    )
    remaining = max(
        0,
        merged.capacity * (merged.magazine_capacity + 1) - used,
    )
    if remaining == 0:
        return 0, 0
    ammo = (remaining - 1) % merged.capacity + 1
    magazines = min(merged.magazine_capacity, (remaining - ammo) // merged.capacity)
    return ammo, magazines


def _merged_inventory(
    source: tuple[InventoryStack, ...],
    destination: tuple[InventoryStack, ...],
) -> tuple[InventoryStack, ...]:
    quantities: dict[str, int] = {}
    for stack in (*source, *destination):
        quantities[stack.key] = max(quantities.get(stack.key, 0), stack.quantity)
    return tuple(
        InventoryStack(key, quantities[key])
        for key in sorted(quantities)
    )


def _best_time(left: int | None, right: int | None) -> int | None:
    candidates = tuple(value for value in (left, right) if value is not None)
    return min(candidates) if candidates else None


def _effect_preference(effect: ActiveEffect) -> tuple[int, int, int, int]:
    return (
        1 if effect.expires_at_ns is None else 0,
        effect.expires_at_ns or 0,
        effect.remaining_uses or 0,
        -effect.effect_id,
    )


def _deduplicate_effects(effects: tuple[ActiveEffect, ...]) -> tuple[ActiveEffect, ...]:
    retained = [effect for effect in effects if effect.scope is EffectScope.CHANNEL]
    selected: dict[tuple[EffectScope, str | None, int, str], ActiveEffect] = {}
    for effect in effects:
        if effect.scope is EffectScope.CHANNEL:
            continue
        identity = (effect.scope, effect.owner_key, effect.item_id, effect.key)
        existing = selected.get(identity)
        if existing is None or _effect_preference(effect) > _effect_preference(existing):
            selected[identity] = effect
    retained.extend(selected.values())
    return tuple(sorted(retained, key=lambda effect: effect.effect_id))


def _deduplicate_curses(curses: tuple[ActiveCurse, ...]) -> tuple[ActiveCurse, ...]:
    selected: dict[tuple[str, str], ActiveCurse] = {}
    for curse in curses:
        identity = (curse.owner_key, curse.key)
        existing = selected.get(identity)
        if existing is None or (curse.expires_at_ns, -curse.curse_id) > (
            existing.expires_at_ns,
            -existing.curse_id,
        ):
            selected[identity] = curse
    return tuple(sorted(selected.values(), key=lambda curse: curse.curse_id))


def _merge_throttle_windows(
    windows: tuple[ThrottleWindow, ...],
) -> tuple[ThrottleWindow, ...]:
    selected: dict[tuple[str | None, object], ThrottleWindow] = {}
    for window in windows:
        identity = (window.player_key, window.command)
        existing = selected.get(identity)
        if existing is None:
            selected[identity] = window
            continue
        expirations = tuple(sorted((*existing.expires_at_ns, *window.expires_at_ns)))[-30:]
        selected[identity] = replace(
            existing,
            expires_at_ns=expirations,
            notice_after_ns=max(existing.notice_after_ns, window.notice_after_ns),
        )
    return tuple(
        sorted(
            selected.values(),
            key=lambda window: (
                "" if window.player_key is None else window.player_key,
                "" if window.command is None else window.command.value,
            ),
        )
    )


def _rekey_remaining_transfers(
    transfers: tuple[PendingIdentityTransfer, ...],
    source_key: str,
    destination_key: str,
    destination_nickname: str,
) -> tuple[PendingIdentityTransfer, ...]:
    selected: dict[str, PendingIdentityTransfer] = {}
    for transfer in transfers:
        updated = transfer
        if transfer.source_key == source_key:
            if transfer.destination_key == destination_key:
                continue
            updated = replace(
                transfer,
                source_key=destination_key,
                source_nickname=destination_nickname,
            )
        existing = selected.get(updated.destination_key)
        if existing is None or updated.expires_at_ns > existing.expires_at_ns:
            selected[updated.destination_key] = updated
    return _sorted_transfers(selected.values())


def _sorted_transfers(
    transfers: Iterable[PendingIdentityTransfer],
) -> tuple[PendingIdentityTransfer, ...]:
    return tuple(sorted(transfers, key=lambda transfer: transfer.destination_key))


def _validate_state_and_nickname(state: GameState, nickname: str) -> None:
    if not isinstance(state, GameState):
        raise ValueError("identity transfer requires game state")
    _validate_nickname(nickname)


def _validate_nickname(nickname: str) -> None:
    if (
        type(nickname) is not str
        or not nickname
        or any(character in nickname for character in (" ", "\x00", "\r", "\n"))
    ):
        raise ValueError("identity transfer nickname is invalid")
