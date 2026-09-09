"""Atomic deterministic shop settlements and effect consumption."""

from __future__ import annotations

from dataclasses import replace

from pyduckhunt.game.bread import active_channel_breads, MAX_CHANNEL_BREAD
from pyduckhunt.game.catalog import (
    DuplicatePolicy,
    GrantKind,
    ShopItem,
    shop_item,
    validate_active_effect,
)
from pyduckhunt.game.engine import advance_time
from pyduckhunt.game.karma import (
    KARMA_MODIFIER_CHANGE_BASIS_POINTS,
    adjust_karma_modifier,
)
from pyduckhunt.game.inventory import item_quantity
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import (
    ActiveEffect,
    EffectScope,
    FATIGUE_SCALE,
    GameState,
    MAX_FATIGUE_CENTI,
    MIN_FATIGUE_CENTI,
    Outcome,
    OutcomeKind,
    PlayerState,
    ScheduledAction,
    Transition,
)
from pyduckhunt.game.progression import available_experience, spend_experience
from pyduckhunt.game.rewards import promotion_discount_percent, settled_shop_cost
from pyduckhunt.identity import rfc1459_casefold


def _resolved_player(state: GameState, nickname: str) -> PlayerState:
    if not nickname:
        raise ValueError("nickname must not be empty")
    key = rfc1459_casefold(nickname)
    player = state.player(key)
    if player is None:
        return PlayerState(key=key, nickname=nickname)
    if player.nickname != nickname:
        return replace(player, nickname=nickname)
    return player


def _effect_owner(item: ShopItem, player: PlayerState) -> str | None:
    return player.key if item.scope is EffectScope.PLAYER else None


def _effect_group(item_id: int) -> str | None:
    item = shop_item(item_id)
    return None if item is None else item.exclusive_group


def _matching_effects(
    state: GameState,
    item: ShopItem,
    owner_key: str | None,
) -> tuple[ActiveEffect, ...]:
    return tuple(
        effect
        for effect in state.effects
        if effect.item_id == item.item_id and effect.owner_key == owner_key
    )


def _owned_effect(
    state: GameState,
    owner_key: str,
    item_id: int,
) -> ActiveEffect | None:
    return next(
        (
            effect
            for effect in state.effects
            if effect.owner_key == owner_key and effect.item_id == item_id
        ),
        None,
    )


def _remove_effect(state: GameState, effect: ActiveEffect) -> GameState:
    return replace(
        state,
        effects=tuple(
            candidate
            for candidate in state.effects
            if candidate.effect_id != effect.effect_id
        ),
    )


def _remove_owned_items(
    state: GameState,
    owner_key: str,
    item_ids: tuple[int, ...],
) -> tuple[GameState, tuple[int, ...]]:
    removed = tuple(
        effect.item_id
        for effect in state.effects
        if effect.owner_key == owner_key and effect.item_id in item_ids
    )
    if not removed:
        return state, ()
    retained = tuple(
        effect
        for effect in state.effects
        if not (effect.owner_key == owner_key and effect.item_id in item_ids)
    )
    return replace(state, effects=retained), tuple(sorted(set(removed)))


def _validate_magnitude(item: ShopItem, magnitude: int | None) -> None:
    if not item.requires_magnitude:
        if magnitude is not None:
            raise ValueError("this shop item does not accept a magnitude")
        return
    if (
        type(magnitude) is not int
        or magnitude < item.magnitude_min
        or magnitude > item.magnitude_max
    ):
        raise ValueError("shop item magnitude is outside its calibrated range")


def purchase(
    state: GameState,
    nickname: str,
    item_id: int,
    now_ns: int,
    *,
    charged_cost: int | None = None,
    magnitude: int | None = None,
    replace_active_effect: bool = False,
    target_nickname: str | None = None,
    target_present: bool | None = None,
    scheduled_for_ns: int | None = None,
    fatigue_relief_centi: int | None = None,
    fatigue_target_centi: int | None = None,
) -> Transition:
    """Settle one already-priced purchase as a single immutable transition."""

    advanced = advance_time(state, now_ns)
    current = advanced.state
    outcomes = list(advanced.outcomes)
    item = shop_item(item_id)
    if item is None:
        outcomes.append(
            Outcome(OutcomeKind.SHOP_UNKNOWN_ITEM, actor=nickname, item_id=item_id)
        )
        return Transition(current, tuple(outcomes))
    if type(replace_active_effect) is not bool:
        raise ValueError("effect replacement must be a truth value")
    if replace_active_effect and item_id != 10:
        raise ValueError("effect replacement is unsupported for this item")

    target: PlayerState | None = None
    if item.grant_kind is GrantKind.TARGET_EFFECT:
        if not target_nickname:
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_TARGET_REQUIRED,
                    actor=nickname,
                    item_id=item_id,
                )
            )
            return Transition(current, tuple(outcomes))
        if type(target_present) is not bool:
            raise ValueError("target presence must be an injected truth value")
        target_key = rfc1459_casefold(target_nickname)
        target = current.player(target_key)
        if target is None:
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_TARGET_UNKNOWN,
                    actor=nickname,
                    item_id=item_id,
                    target=target_nickname,
                )
            )
            return Transition(current, tuple(outcomes))
        if target.nickname != target_nickname:
            target = replace(target, nickname=target_nickname)
            current = current.with_player(target)
        if item.target_presence_required and not target_present:
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_TARGET_ABSENT,
                    actor=nickname,
                    item_id=item_id,
                    target=target_nickname,
                )
            )
            return Transition(current, tuple(outcomes))
        if item.target_weapon_required and target.confiscated:
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_TARGET_UNARMED,
                    actor=nickname,
                    item_id=item_id,
                    target=target_nickname,
                )
            )
            return Transition(current, tuple(outcomes))
        if item.item_id in (15, 17) and level_policy(target.level).nuisance_immune:
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_TARGET_IMMUNE,
                    actor=nickname,
                    item_id=item_id,
                    target=target_nickname,
                )
            )
            return Transition(current, tuple(outcomes))
        if _matching_effects(current, item, target.key):
            outcomes.append(
                Outcome(
                    OutcomeKind.SHOP_EFFECT_ACTIVE,
                    actor=nickname,
                    item_id=item_id,
                    target=target_nickname,
                )
            )
            return Transition(current, tuple(outcomes))
    elif target_nickname is not None or target_present is not None:
        raise ValueError("this shop item does not accept a target")

    if item.grant_kind is GrantKind.CHANNEL_ACTION:
        if scheduled_for_ns is None:
            if item.schedule_min_ns != item.schedule_max_ns:
                raise ValueError("variable channel action requires an injected deadline")
            scheduled_for_ns = now_ns + item.schedule_min_ns
        if type(scheduled_for_ns) is not int or not (
            now_ns + item.schedule_min_ns
            <= scheduled_for_ns
            <= now_ns + item.schedule_max_ns
        ):
            raise ValueError("scheduled action deadline is outside its calibrated window")
    elif scheduled_for_ns is not None:
        raise ValueError("this shop item does not accept a scheduled deadline")

    player = _resolved_player(current, nickname)
    discount_percent = promotion_discount_percent(current, player.key)
    cost = (
        settled_shop_cost(item.base_cost, discount_percent)
        if charged_cost is None
        else charged_cost
    )
    if type(cost) is not int or not 0 <= cost <= item.base_cost:
        raise ValueError("charged cost must be between zero and the catalog price")
    _validate_magnitude(item, magnitude)
    owner_key = (
        target.key
        if item.grant_kind is GrantKind.TARGET_EFFECT and target is not None
        else _effect_owner(item, player)
    )
    fatigue_player = target if item.item_id == 27 else player
    if item.item_id == 25:
        if fatigue_relief_centi is not None:
            raise ValueError("the thermos records a fatigue target, not relief")
        assert item.fatigue_relief_max is not None
        if (
            type(fatigue_target_centi) is not int
            or not MIN_FATIGUE_CENTI <= fatigue_target_centi <= item.fatigue_relief_max * FATIGUE_SCALE
        ):
            raise ValueError("thermos fatigue target is outside its calibrated range")
    elif item.fatigue_relief_max is None:
        if fatigue_relief_centi is not None or fatigue_target_centi is not None:
            raise ValueError("this shop item does not accept fatigue settlement")
    else:
        if fatigue_target_centi is not None:
            raise ValueError("this shop item does not accept a fatigue target")
        assert fatigue_player is not None
        maximum_relief_centi = min(
            item.fatigue_relief_max * FATIGUE_SCALE,
            max(0, fatigue_player.fatigue_centi),
        )
        if fatigue_relief_centi is None:
            fatigue_relief_centi = maximum_relief_centi
        if (
            type(fatigue_relief_centi) is not int
            or not 0 <= fatigue_relief_centi <= maximum_relief_centi
        ):
            raise ValueError("fatigue relief differs from the settled player state")

    if item.grant_kind is GrantKind.AMMUNITION and player.ammo == player.capacity:
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_NOT_APPLICABLE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if item.grant_kind is GrantKind.MAGAZINE and player.magazines == player.magazine_capacity:
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_NOT_APPLICABLE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if item.grant_kind is GrantKind.WEAPON_RETURN and (
        not player.confiscated or player.permanently_confiscated
    ):
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_NOT_APPLICABLE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if item.grant_kind is GrantKind.REMEDY and not any(
        effect.owner_key == player.key and effect.item_id in item.removes_item_ids
        for effect in current.effects
    ):
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_NOT_APPLICABLE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if item.grant_kind is GrantKind.PURIFICATION and not any(
        curse.owner_key == player.key for curse in current.curses
    ):
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_NOT_APPLICABLE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if (
        item.grant_kind is GrantKind.EFFECT
        and item.duplicate_policy is DuplicatePolicy.REJECT
        and not replace_active_effect
        and _matching_effects(current, item, owner_key)
    ):
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_EFFECT_ACTIVE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))
    if (item_id == 21 and current.bread_plan_effect_ids is not None
            and len(active_channel_breads(current, now_ns)) >= MAX_CHANNEL_BREAD):
        return Transition(current, tuple(outcomes) + (Outcome(
            OutcomeKind.SHOP_NOT_APPLICABLE, actor=nickname, item_id=21, player=player),))
    shop_credit_spent = min(player.shop_credit, cost)
    experience_spent = cost - shop_credit_spent
    if available_experience(player) < experience_spent:
        outcomes.append(
            Outcome(
                OutcomeKind.SHOP_INSUFFICIENT_EXPERIENCE,
                actor=nickname,
                item_id=item_id,
                player=player,
            )
        )
        return Transition(current, tuple(outcomes))

    debit = spend_experience(player, experience_spent)
    player = replace(
        debit.player,
        shop_credit=player.shop_credit - shop_credit_spent,
        experience_spent=player.experience_spent + experience_spent,
    )
    effect_id: int | None = None
    settled_effect_magnitude: int | None = None
    action_id: int | None = None
    effects = current.effects
    next_effect_id = current.next_effect_id
    scheduled_actions = current.scheduled_actions
    next_action_id = current.next_action_id
    curses = current.curses
    removed_item_ids: tuple[int, ...] = ()
    removed_curse_keys: tuple[str, ...] = ()
    effect_blocked = False
    counter_item_id: int | None = None
    fatigue_changed_centi = 0
    if item.grant_kind is GrantKind.AMMUNITION:
        player = replace(player, ammo=player.ammo + 1)
    elif item.grant_kind is GrantKind.MAGAZINE:
        player = replace(player, magazines=player.magazines + 1)
    elif item.grant_kind is GrantKind.WEAPON_RETURN:
        player = replace(
            player,
            confiscated=False,
            permanently_confiscated=False,
        )
    elif item.grant_kind is GrantKind.REMEDY:
        current, removed_item_ids = _remove_owned_items(
            current,
            player.key,
            item.removes_item_ids,
        )
        effects = current.effects
    elif item.grant_kind is GrantKind.CHANNEL_ACTION:
        assert scheduled_for_ns is not None
        action_id = next_action_id
        action = ScheduledAction(
            action_id=action_id,
            item_id=item.item_id,
            key=item.key,
            source_key=player.key,
            created_at_ns=now_ns,
            due_at_ns=scheduled_for_ns,
        )
        scheduled_actions = tuple((*scheduled_actions, action))
        next_action_id += 1
    elif item.grant_kind is GrantKind.FATIGUE_RELIEF:
        if item.item_id == 25:
            assert fatigue_target_centi is not None
            fatigue_changed_centi = fatigue_target_centi - player.fatigue_centi
            player = replace(player, fatigue_centi=fatigue_target_centi)
        else:
            assert fatigue_relief_centi is not None
            fatigue_changed_centi = -fatigue_relief_centi
            player = replace(
                player,
                fatigue_centi=player.fatigue_centi - fatigue_relief_centi,
            )
    elif item.grant_kind is GrantKind.PURIFICATION:
        removed_curse_keys = tuple(
            curse.key for curse in curses if curse.owner_key == player.key
        )
        curses = tuple(curse for curse in curses if curse.owner_key != player.key)
    else:
        if replace_active_effect:
            effects = tuple(
                effect
                for effect in effects
                if not (
                    effect.owner_key == owner_key
                    and effect.item_id == item.item_id
                )
            )
        if item.grant_kind is GrantKind.EFFECT and item.removes_item_ids:
            current, removed_item_ids = _remove_owned_items(
                current,
                player.key,
                item.removes_item_ids,
            )
            effects = current.effects
        if item.duplicate_policy is DuplicatePolicy.REPLACE_GROUP:
            effects = tuple(
                effect
                for effect in effects
                if not (
                    effect.owner_key == owner_key
                    and _effect_group(effect.item_id) == item.exclusive_group
                )
            )
        permanent_counter_key = {
            14: "indestructible_sunglasses",
            15: "military_self_lubricating_system",
            16: "tearproof_raincoat",
        }.get(item.item_id)
        permanent_counter = (
            target is not None
            and permanent_counter_key is not None
            and item_quantity(target, permanent_counter_key) > 0
        )
        counter = (
            None
            if permanent_counter or item.counter_item_id is None or target is None
            else _owned_effect(current, target.key, item.counter_item_id)
        )
        if permanent_counter or counter is not None:
            effect_blocked = True
            counter_item_id = item.counter_item_id
            if counter is not None and item.consume_counter:
                current = _remove_effect(current, counter)
                effects = current.effects
                removed_item_ids = tuple(
                    sorted(set((*removed_item_ids, counter.item_id)))
                )
        if effect_blocked:
            effect = None
        else:
            effect_magnitude = magnitude
            if item.item_id == 28:
                assert target is not None
                fatigue_changed_centi = min(
                    6 * FATIGUE_SCALE,
                    MAX_FATIGUE_CENTI - target.fatigue_centi,
                )
                effect_magnitude = fatigue_changed_centi
            effect_id = next_effect_id
            effect = ActiveEffect(
                effect_id=effect_id,
                item_id=item.item_id,
                key=item.key,
                scope=item.scope,
                owner_key=owner_key,
                source_key=(
                    player.key
                    if item.grant_kind is GrantKind.TARGET_EFFECT
                    else None
                ),
                activated_at_ns=now_ns,
                expires_at_ns=(
                    None if item.duration_ns is None else now_ns + item.duration_ns
                ),
                remaining_uses=item.uses,
                magnitude=effect_magnitude,
            )
            validate_active_effect(effect)
            settled_effect_magnitude = effect.magnitude
            effects = tuple(sorted((*effects, effect), key=lambda value: value.effect_id))
            next_effect_id += 1

        if item.item_id == 27:
            assert target is not None and fatigue_relief_centi is not None
            fatigue_changed_centi = -fatigue_relief_centi
            if target.key == player.key:
                player = replace(
                    player,
                    fatigue_centi=player.fatigue_centi - fatigue_relief_centi,
                )
            else:
                target = replace(
                    target,
                    fatigue_centi=target.fatigue_centi - fatigue_relief_centi,
                )
                current = current.with_player(target)
        elif item.item_id == 28 and not effect_blocked:
            assert target is not None
            if target.key == player.key:
                player = replace(
                    player,
                    fatigue_centi=player.fatigue_centi + fatigue_changed_centi,
                )
            else:
                target = replace(
                    target,
                    fatigue_centi=target.fatigue_centi + fatigue_changed_centi,
                )
                current = current.with_player(target)

    karma_delta = 0
    if item.item_id in (20, 21):
        karma_delta = KARMA_MODIFIER_CHANGE_BASIS_POINTS
    elif item.item_id in (14, 15, 16, 17):
        karma_delta = -KARMA_MODIFIER_CHANGE_BASIS_POINTS
    elif (
        item.item_id in (27, 28)
        and target is not None
        and target.key != player.key
    ):
        karma_delta = -KARMA_MODIFIER_CHANGE_BASIS_POINTS
    if karma_delta:
        player = adjust_karma_modifier(player, karma_delta, now_ns)

    current = replace(
        current.with_player(player),
        effects=effects,
        next_effect_id=next_effect_id,
        scheduled_actions=scheduled_actions,
        next_action_id=next_action_id,
        curses=curses,
    )
    channel_effect_count = (
        sum(
            1
            for effect in current.effects
            if effect.item_id == item.item_id
            and effect.key == item.key
            and effect.scope is EffectScope.CHANNEL
            and effect.owner_key is None
        )
        if item.item_id == 21
        else None
    )
    outcomes.append(
        Outcome(
            OutcomeKind.SHOP_PURCHASED,
            actor=nickname,
            item_id=item_id,
            charged_experience=cost,
            experience_spent=experience_spent,
            shop_credit_spent=shop_credit_spent,
            discount_percent=discount_percent,
            levels_lost=debit.levels_lost,
            effect_id=effect_id,
            effect_magnitude=(20 if item_id == 21 and current.bread_plan_effect_ids is not None
                              else settled_effect_magnitude),
            player=player,
            target=target_nickname,
            effect_blocked=effect_blocked,
            counter_item_id=counter_item_id,
            removed_item_ids=removed_item_ids,
            action_id=action_id,
            due_at_ns=scheduled_for_ns,
            fatigue_changed_centi=fatigue_changed_centi,
            removed_curse_keys=removed_curse_keys,
            channel_effect_count=channel_effect_count,
        )
    )
    return Transition(current, tuple(outcomes))


def consume_effect_use(state: GameState, effect_id: int, now_ns: int) -> Transition:
    """Consume one use, removing the effect when its final use is spent."""

    advanced = advance_time(state, now_ns)
    current = advanced.state
    effect = next(
        (candidate for candidate in current.effects if candidate.effect_id == effect_id),
        None,
    )
    if effect is None or effect.remaining_uses is None:
        raise ValueError("effect is missing or is not use-bounded")
    if effect.remaining_uses == 1:
        effects = tuple(
            candidate for candidate in current.effects if candidate.effect_id != effect_id
        )
    else:
        replacement = replace(effect, remaining_uses=effect.remaining_uses - 1)
        effects = tuple(
            replacement if candidate.effect_id == effect_id else candidate
            for candidate in current.effects
        )
    outcome = Outcome(
        OutcomeKind.EFFECT_CONSUMED,
        item_id=effect.item_id,
        effect_id=effect.effect_id,
    )
    return Transition(replace(current, effects=effects), (*advanced.outcomes, outcome))
