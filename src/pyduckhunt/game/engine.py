"""Pure state transitions for flight arbitration and player commands."""

from __future__ import annotations

from dataclasses import replace

from pyduckhunt.game.bread import active_channel_breads, BREAD_DELAY_NS
from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import (
    ActiveCurse,
    ActiveEffect,
    EffectScope,
    MAX_FATIGUE_CENTI,
    FlightState,
    FlightKind,
    GameState,
    LastFlight,
    LastFlightConclusion,
    IncidentAttempt,
    Outcome,
    OutcomeKind,
    PlayerState,
    ShotAttempt,
    ScheduledAction,
    Transition,
)
from pyduckhunt.game.catalog import HOUR_NS, MINUTE_NS, validate_active_effect
from pyduckhunt.game.loot import acquire_loot, validate_loot_award
from pyduckhunt.game.accuracy import shot_accuracy
from pyduckhunt.game.karma import decay_karma_modifier
from pyduckhunt.game.inventory import item_quantity
from pyduckhunt.game.targets import flight_reward, validate_flight_reward
from pyduckhunt.game.day_boundary import paris_calendar_day_marker_ns
from pyduckhunt.game.rewards import (
    ammunition_recycler_successes_per_thirty,
    has_unlimited_duck_carry,
    has_unlimited_magazines,
    milestone_credit,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.game.progression import (
    debit_experience,
    grant_experience,
)


LATE_SHOT_WINDOW_NS = 3_000_000_000


def _check_time(state: GameState, now_ns: int) -> None:
    if now_ns < state.now_ns:
        raise ValueError("game time must be monotonic")


def _advance(state: GameState, now_ns: int) -> Transition:
    _check_time(state, now_ns)
    outcomes: list[Outcome] = []
    flight = state.flight
    last_flight = state.last_flight
    if state.flight is not None and now_ns >= state.flight.expires_at_ns:
        expired = state.flight
        flight = None
        last_flight = LastFlight(
            flight_id=expired.flight_id,
            kind=expired.kind,
            spawned_at_ns=expired.spawned_at_ns,
            ended_at_ns=expired.expires_at_ns,
            conclusion=LastFlightConclusion.ESCAPED,
        )
        outcomes.append(
            Outcome(OutcomeKind.FLIGHT_EXPIRED, flight_id=expired.flight_id)
        )
    day_start_ns = paris_calendar_day_marker_ns(now_ns)
    players = {}
    for existing in state.players:
        player = decay_karma_modifier(existing, now_ns)
        if player.carried_day_start_ns != day_start_ns:
            player = replace(
                player,
                ammo=player.capacity,
                magazines=player.magazine_capacity,
                confiscated=player.permanently_confiscated,
                carried_ducks=0,
                carried_day_start_ns=day_start_ns,
                fatigue_centi=0,
            )
        players[player.key] = player
    active_effects = []
    for effect in state.effects:
        if effect.expires_at_ns is not None and now_ns >= effect.expires_at_ns:
            fatigue_changed_centi = 0
            expired_player = None
            if effect.item_id == 28 and effect.owner_key in players:
                owner = players[effect.owner_key]
                fatigue_changed_centi = -min(
                    effect.magnitude or 0,
                    max(0, owner.fatigue_centi),
                )
                expired_player = replace(
                    owner,
                    fatigue_centi=owner.fatigue_centi + fatigue_changed_centi,
                )
                players[owner.key] = expired_player
            outcomes.append(
                Outcome(
                    OutcomeKind.EFFECT_EXPIRED,
                    item_id=effect.item_id,
                    effect_id=effect.effect_id,
                    player=expired_player,
                    fatigue_changed_centi=fatigue_changed_centi,
                )
            )
        else:
            active_effects.append(effect)
    active_curses = []
    for curse in state.curses:
        if now_ns >= curse.expires_at_ns:
            outcomes.append(
                Outcome(
                    OutcomeKind.CURSE_EXPIRED,
                    curse_key=curse.key,
                )
            )
        else:
            active_curses.append(curse)
    pending_actions = []
    due_actions = []
    for action in state.scheduled_actions:
        if state.bread_plan_effect_ids is not None and action.item_id in (20, 23):
            # Channel calls wait durably until a matching flight really starts.
            # A bread expiry/replan must never discard a pending paid call.
            pending_actions.append(action)
        elif now_ns >= action.due_at_ns:
            due_actions.append(action)
        else:
            pending_actions.append(action)
    for action in sorted(due_actions, key=lambda value: (value.due_at_ns, value.action_id)):
        source = state.player(action.source_key)
        outcomes.append(
            Outcome(
                OutcomeKind.CHANNEL_ACTION_DUE,
                actor=None if source is None else source.nickname,
                item_id=action.item_id,
                action_id=action.action_id,
                due_at_ns=action.due_at_ns,
            )
        )
    return Transition(
        state=replace(
            state,
            now_ns=now_ns,
            flight=flight,
            last_flight=last_flight,
            players=tuple(sorted(players.values(), key=lambda player: player.key)),
            effects=tuple(active_effects),
            curses=tuple(active_curses),
            scheduled_actions=tuple(pending_actions),
        ),
        outcomes=tuple(outcomes),
    )


def advance_time(state: GameState, now_ns: int) -> Transition:
    """Advance the injected monotonic clock and expire a due flight."""

    return _advance(state, now_ns)


def start_flight(
    state: GameState,
    now_ns: int,
    *,
    lifetime_ns: int,
    health: int = 1,
    kind: FlightKind = FlightKind.STANDARD,
    reward_experience: int | None = None,
) -> Transition:
    """Start one flight unless another remains active."""

    if lifetime_ns <= 0:
        raise ValueError("flight lifetime must be positive")
    if reward_experience is None:
        reward_experience = flight_reward(kind, health)
    validate_flight_reward(kind, health, reward_experience)
    advanced = _advance(state, now_ns)
    current = advanced.state
    if current.flight is not None:
        return Transition(
            state=current,
            outcomes=advanced.outcomes
            + (Outcome(OutcomeKind.FLIGHT_ALREADY_ACTIVE, flight_id=current.flight.flight_id),),
        )

    hourly_bread = current.bread_plan_effect_ids is not None
    bread_delay_ns = (len(active_channel_breads(current, now_ns)) * BREAD_DELAY_NS
                      if hourly_bread else 0)
    flight = FlightState(
        flight_id=current.next_flight_id,
        spawned_at_ns=now_ns,
        expires_at_ns=now_ns + lifetime_ns + bread_delay_ns,
        health=health,
        max_health=health,
        kind=kind,
        reward_experience=reward_experience,
    )
    next_state = replace(
        current,
        flight=flight,
        next_flight_id=current.next_flight_id + 1,
    )
    bread = min(
        (
            effect
            for effect in next_state.effects
            if not hourly_bread and effect.item_id == 21
            and effect.key == "channel_bread"
            and effect.scope is EffectScope.CHANNEL
            and effect.owner_key is None
        ),
        key=lambda effect: (effect.activated_at_ns, effect.effect_id),
        default=None,
    )
    consumed = (
        ()
        if bread is None
        else (
            Outcome(
                OutcomeKind.EFFECT_CONSUMED,
                item_id=bread.item_id,
                effect_id=bread.effect_id,
            ),
        )
    )
    alerts: list[Outcome] = []
    retained_effects = []
    for effect in next_state.effects:
        if bread is not None and effect.effect_id == bread.effect_id:
            continue
        if effect.item_id == 22:
            owner = next_state.player(effect.owner_key or "")
            alerts.append(
                Outcome(
                    OutcomeKind.DUCK_ALERT,
                    actor=None if owner is None else owner.nickname,
                    flight_id=flight.flight_id,
                    item_id=effect.item_id,
                    effect_id=effect.effect_id,
                )
            )
        else:
            retained_effects.append(effect)
    next_state = replace(next_state, effects=tuple(retained_effects))
    action_outcomes = ()
    if hourly_bread:
        matching_item = 23 if kind is FlightKind.MECHANICAL else 20 if kind is FlightKind.STANDARD else None
        action = min((a for a in next_state.scheduled_actions
                      if a.item_id == matching_item and a.due_at_ns <= now_ns),
                     key=lambda a: (a.due_at_ns, a.action_id), default=None)
        if action is not None:
            source = next_state.player(action.source_key)
            next_state = replace(next_state, scheduled_actions=tuple(
                a for a in next_state.scheduled_actions if a.action_id != action.action_id))
            action_outcomes = (Outcome(OutcomeKind.CHANNEL_ACTION_DUE,
                actor=None if source is None else source.nickname, item_id=action.item_id,
                action_id=action.action_id, due_at_ns=action.due_at_ns),)
    return Transition(
        state=next_state,
        outcomes=advanced.outcomes
        + (
            Outcome(
                OutcomeKind.FLIGHT_STARTED,
                flight_id=flight.flight_id,
                flight_kind=flight.kind,
                channel_effect_count=(len(active_channel_breads(current, now_ns)) or None) if hourly_bread else None,
                effect_magnitude=bread_delay_ns // 1_000_000_000 if hourly_bread else None,
            ),
        )
        + consumed
        + tuple(alerts)
        + action_outcomes,
    )


def _resolved_player(state: GameState, nickname: str) -> PlayerState:
    if not nickname:
        raise ValueError("nickname must not be empty")
    key = rfc1459_casefold(nickname)
    player = state.player(key)
    if player is None:
        return PlayerState(
            key=key,
            nickname=nickname,
            carried_day_start_ns=paris_calendar_day_marker_ns(state.now_ns),
        )
    if player.nickname != nickname:
        return replace(player, nickname=nickname)
    return player


def _replace_player(state: GameState, player: PlayerState) -> GameState:
    return state.with_player(player)


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


def _owned_curse(
    state: GameState,
    owner_key: str,
    key: str,
) -> ActiveCurse | None:
    return next(
        (
            curse
            for curse in state.curses
            if curse.owner_key == owner_key and curse.key == key
        ),
        None,
    )


def _consume_effect_use(state: GameState, effect: ActiveEffect) -> GameState:
    if effect.remaining_uses is None:
        raise ValueError("effect is not use-bounded")
    if effect.remaining_uses == 1:
        effects = tuple(
            candidate
            for candidate in state.effects
            if candidate.effect_id != effect.effect_id
        )
    else:
        replacement = replace(effect, remaining_uses=effect.remaining_uses - 1)
        effects = tuple(
            replacement if candidate.effect_id == effect.effect_id else candidate
            for candidate in state.effects
        )
    return replace(state, effects=effects)


def _apply_miss_penalty(
    state: GameState,
    player: PlayerState,
    attempt: ShotAttempt,
    *,
    wild: bool,
) -> tuple[GameState, PlayerState, int]:
    penalty = attempt.miss_penalty + (attempt.wild_penalty if wild else 0)
    change = debit_experience(player, penalty)
    player = change.player
    return _replace_player(state, player), player, change.levels_lost


def _accrue_shot_fatigue(
    state: GameState,
    player: PlayerState,
    attempt: ShotAttempt,
) -> tuple[GameState, PlayerState, int]:
    """Apply the replayed base gain and every active fatigue multiplier."""

    if _owned_effect(state, player.key, 102) is not None:
        return state, player, 0
    multiplier = _carry_fatigue_multiplier(state, player)
    burden = _owned_curse(state, player.key, "burden")
    frenzy = _owned_curse(state, player.key, "frenzy")
    if burden is not None:
        multiplier *= burden.magnitude or 1
    if frenzy is not None:
        multiplier *= frenzy.magnitude or 1
    requested = attempt.fatigue_gain_centi * multiplier
    settled = min(requested, MAX_FATIGUE_CENTI - player.fatigue_centi)
    if settled:
        player = replace(player, fatigue_centi=player.fatigue_centi + settled)
        state = _replace_player(state, player)
    return state, player, settled


def _carry_fatigue_multiplier(state: GameState, player: PlayerState) -> int:
    if has_unlimited_duck_carry(state, player.key):
        return 1
    if player.carried_ducks > 10:
        return 3
    if player.carried_ducks > 5:
        return 2
    return 1


def _apply_kill_reward_triggers(
    state: GameState,
    player: PlayerState,
    now_ns: int,
    *,
    baker: ActiveEffect | None,
    prankster: ActiveEffect | None,
) -> tuple[GameState, tuple[Outcome, ...]]:
    """Apply deterministic channel consequences of pre-existing reward effects."""

    outcomes: list[Outcome] = []
    if baker is not None:
        bread = ActiveEffect(
            effect_id=state.next_effect_id,
            item_id=21,
            key="channel_bread",
            scope=EffectScope.CHANNEL,
            owner_key=None,
            source_key=None,
            activated_at_ns=now_ns,
            expires_at_ns=now_ns + HOUR_NS,
        )
        validate_active_effect(bread)
        state = replace(
            state,
            effects=tuple((*state.effects, bread)),
            next_effect_id=state.next_effect_id + 1,
        )
        outcomes.append(
            Outcome(
                OutcomeKind.REWARD_TRIGGERED,
                actor=player.nickname,
                player=player,
                item_id=baker.item_id,
                effect_id=bread.effect_id,
                triggered_item_id=bread.item_id,
            )
        )
    if prankster is not None:
        action = ScheduledAction(
            action_id=state.next_action_id,
            item_id=23,
            key="mechanical_duck",
            source_key=player.key,
            created_at_ns=now_ns,
            due_at_ns=now_ns + 10 * MINUTE_NS,
        )
        state = replace(
            state,
            scheduled_actions=tuple((*state.scheduled_actions, action)),
            next_action_id=state.next_action_id + 1,
        )
        outcomes.append(
            Outcome(
                OutcomeKind.REWARD_TRIGGERED,
                actor=player.nickname,
                player=player,
                item_id=prankster.item_id,
                action_id=action.action_id,
                due_at_ns=action.due_at_ns,
                triggered_item_id=action.item_id,
            )
        )
    return state, tuple(outcomes)


def _finish_fired_transition(
    state: GameState,
    nickname: str,
    command: CommandKind,
    outcomes: list[Outcome],
) -> Transition:
    """Apply the post-shot automatic reload after all shot settlement."""

    player = state.player(rfc1459_casefold(nickname))
    assert player is not None
    player = replace(player, shots_fired=player.shots_fired + 1)
    state = _replace_player(state, player)
    automatic = _owned_effect(state, player.key, 30)
    unlimited_magazines = has_unlimited_magazines(state, player.key)
    if (
        automatic is not None
        and player.ammo == 0
        and (player.magazines > 0 or unlimited_magazines)
    ):
        player = replace(
            player,
            ammo=player.capacity,
            magazines=(player.magazines if unlimited_magazines else player.magazines - 1),
        )
        state = _replace_player(state, player)
        outcomes.append(
            Outcome(
                OutcomeKind.RELOADED,
                actor=nickname,
                command=command,
                player=player,
                item_id=automatic.item_id,
                effect_id=automatic.effect_id,
                automatic=True,
                unlimited_magazines=unlimited_magazines,
            )
        )
    return Transition(
        state=replace(state, last_shooter_key=player.key),
        outcomes=tuple(outcomes),
    )


def late_shot_delay_ms(state: GameState, now_ns: int) -> int | None:
    """Return the bounded post-kill delay that is not a wild shot."""

    if not isinstance(state, GameState):
        raise ValueError("late-shot classification requires a game state")
    if type(now_ns) is not int or now_ns < state.now_ns:
        raise ValueError("late-shot timestamp cannot precede game state")
    if state.flight is not None or state.last_flight is None:
        return None
    if state.last_flight.conclusion is not LastFlightConclusion.HIT:
        return None
    delay_ns = now_ns - state.last_flight.ended_at_ns
    if not 0 <= delay_ns <= LATE_SHOT_WINDOW_NS:
        return None
    return delay_ns // 1_000_000


def _settle_incident(
    state: GameState,
    nickname: str,
    command: CommandKind,
    incident: IncidentAttempt,
) -> tuple[GameState, tuple[Outcome, ...]]:
    """Settle one injected ricochet chain without consulting external state."""

    shooter_key = rfc1459_casefold(nickname)
    shooter = state.player(shooter_key)
    if shooter is None:
        raise ValueError("incident shooter is absent from game state")
    shooter_level = shooter.level
    safe_conduct = _owned_effect(state, shooter_key, 29)
    permanent_killing_license = (
        item_quantity(shooter, "permanent_killing_license") > 0
    )
    incident_protected = safe_conduct is not None or permanent_killing_license
    liability = _owned_effect(state, shooter_key, 19)
    confiscated_now = False
    if not incident_protected and not shooter.confiscated:
        shooter = replace(
            shooter,
            confiscated=True,
            confiscations=shooter.confiscations + 1,
        )
        state = _replace_player(state, shooter)
        confiscated_now = True

    outcomes: list[Outcome] = []
    for index, target_attempt in enumerate(incident.targets, start=1):
        shooter = state.player(shooter_key)
        assert shooter is not None
        settled_penalty = 0
        lost_levels = 0
        if not incident_protected:
            settled_penalty = incident.incident_penalty
            if liability is not None:
                settled_penalty //= 3
            penalty = debit_experience(shooter, settled_penalty)
            shooter = penalty.player
            lost_levels = penalty.levels_lost
        shooter = replace(
            shooter,
            incidents_caused=shooter.incidents_caused + 1,
        )
        state = _replace_player(state, shooter)

        victim = _resolved_player(state, target_attempt.nickname)
        state = _replace_player(state, victim)
        life_insurance = _owned_effect(state, victim.key, 18)
        insurance_award = 0
        gained_levels = 0
        if life_insurance is not None:
            insurance_award = shooter_level * 3
            progression = grant_experience(victim, insurance_award)
            victim = progression.player
            gained_levels = progression.levels_gained
            state = _replace_player(state, victim)
            state = _consume_effect_use(state, life_insurance)

        victim = state.player(victim.key)
        assert victim is not None
        victim = replace(victim, shots_received=victim.shots_received + 1)
        if target_attempt.deflection_roll <= target_attempt.deflection_bps:
            outcome_kind = OutcomeKind.INCIDENT_DEFLECTED
            victim = replace(
                victim,
                incidents_deflected=victim.incidents_deflected + 1,
            )
        elif target_attempt.armor_roll <= target_attempt.armor_bps:
            outcome_kind = OutcomeKind.INCIDENT_ABSORBED
            victim = replace(
                victim,
                incidents_absorbed=victim.incidents_absorbed + 1,
            )
        else:
            outcome_kind = OutcomeKind.INCIDENT_FATAL
            victim = replace(victim, deaths=victim.deaths + 1)
        state = _replace_player(state, victim)
        shooter = state.player(shooter_key)
        assert shooter is not None
        outcomes.append(
            Outcome(
                outcome_kind,
                actor=nickname,
                command=command,
                player=shooter,
                target=target_attempt.nickname,
                ricochet_index=index,
                deflection_bps=target_attempt.deflection_bps,
                armor_bps=target_attempt.armor_bps,
                incident_penalty=settled_penalty,
                insurance_award=insurance_award,
                weapon_confiscated=confiscated_now and index == 1,
                safe_conduct_applied=incident_protected,
                liability_applied=not incident_protected and liability is not None,
                levels_gained=gained_levels,
                levels_lost=lost_levels,
            )
        )
        if outcome_kind is not OutcomeKind.INCIDENT_DEFLECTED:
            break
    return state, tuple(outcomes)


def apply_command(
    state: GameState,
    nickname: str,
    command: Command,
    now_ns: int,
    *,
    shot_attempt: ShotAttempt | None = None,
    delay_settled: bool = False,
) -> Transition:
    """Apply one parsed player command at an injected monotonic timestamp."""

    advanced = _advance(state, now_ns)
    current = advanced.state
    player = _resolved_player(current, nickname)
    outcomes = list(advanced.outcomes)
    if shot_attempt is not None and not isinstance(shot_attempt, ShotAttempt):
        raise ValueError("shot attempt must satisfy the domain contract")
    if command.kind is not CommandKind.SHOT and shot_attempt is not None:
        raise ValueError("shot attempt can only accompany a shot command")
    if type(delay_settled) is not bool:
        raise ValueError("delay settlement must be a truth value")
    if delay_settled and command.kind not in (CommandKind.SHOT, CommandKind.RELOAD):
        raise ValueError("only shot and reload commands can settle a delay")

    slowness = _owned_curse(current, player.key, "slowness")
    if (
        not delay_settled
        and slowness is not None
        and command.kind in (CommandKind.SHOT, CommandKind.RELOAD)
    ):
        current = _replace_player(current, player)
        defer_until_ns = now_ns + (slowness.magnitude or 0) * 1_000_000_000
        outcomes.append(
            Outcome(
                OutcomeKind.COMMAND_DELAYED,
                actor=nickname,
                command=command.kind,
                player=player,
                curse_key=slowness.key,
                defer_until_ns=defer_until_ns,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    if command.kind in (CommandKind.SHOT, CommandKind.RELOAD) and player.confiscated:
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                OutcomeKind.WEAPON_CONFISCATED,
                actor=nickname,
                command=command.kind,
                player=player,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    if command.kind is CommandKind.RELOAD:
        unlimited_magazines = has_unlimited_magazines(current, player.key)
        one_armed = _owned_curse(current, player.key, "one_armed")
        if one_armed is not None:
            current = _replace_player(current, player)
            outcomes.append(
                Outcome(
                    OutcomeKind.CURSE_BLOCKED,
                    actor=nickname,
                    command=command.kind,
                    player=player,
                    curse_key=one_armed.key,
                )
            )
            return Transition(state=current, outcomes=tuple(outcomes))
        if player.jammed:
            player = replace(player, jammed=False)
            outcome_kind = OutcomeKind.UNJAMMED
        elif player.ammo > 0:
            player = replace(
                player,
                compulsive_reloads=player.compulsive_reloads + 1,
            )
            outcome_kind = OutcomeKind.ALREADY_LOADED
        elif player.magazines == 0 and not unlimited_magazines:
            outcome_kind = OutcomeKind.NO_RESERVE
        else:
            player = replace(
                player,
                ammo=player.capacity,
                magazines=(
                    player.magazines
                    if unlimited_magazines
                    else player.magazines - 1
                ),
            )
            outcome_kind = OutcomeKind.RELOADED
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                outcome_kind,
                actor=nickname,
                command=command.kind,
                player=player,
                unlimited_magazines=unlimited_magazines,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    if command.kind is not CommandKind.SHOT:
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                OutcomeKind.QUERY,
                actor=nickname,
                command=command.kind,
                player=player,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    soaked = _owned_effect(current, player.key, 16)
    if soaked is not None:
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                OutcomeKind.HUNT_BLOCKED,
                actor=nickname,
                command=command.kind,
                player=player,
                item_id=soaked.item_id,
                effect_id=soaked.effect_id,
                nuisance_source_key=soaked.source_key,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    if player.jammed:
        player = replace(player, jammed_shots=player.jammed_shots + 1)
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(OutcomeKind.JAMMED, actor=nickname, command=command.kind, player=player)
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    if player.ammo == 0:
        player = replace(player, empty_shots=player.empty_shots + 1)
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(OutcomeKind.EMPTY, actor=nickname, command=command.kind, player=player)
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    infrared = _owned_effect(current, player.key, 8)
    if current.flight is None and infrared is not None:
        current = _replace_player(current, player)
        current = _consume_effect_use(current, infrared)
        outcomes.append(
            Outcome(
                OutcomeKind.TRIGGER_LOCKED,
                actor=nickname,
                command=command.kind,
                player=player,
                item_id=infrared.item_id,
                effect_id=infrared.effect_id,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    attempt = shot_attempt if shot_attempt is not None else ShotAttempt()
    grease = _owned_effect(current, player.key, 6)
    permanent_grease = (
        item_quantity(player, "military_self_lubricating_system") > 0
    )
    scope = _owned_effect(current, player.key, 7)
    glare = _owned_effect(current, player.key, 14)
    sand = _owned_effect(current, player.key, 15)
    sabotage = _owned_effect(current, player.key, 17)
    suppressor = _owned_effect(current, player.key, 9)
    charm = _owned_effect(current, player.key, 10)
    penetrating = _owned_effect(current, player.key, 3)
    explosive = _owned_effect(current, player.key, 4)
    baker = _owned_effect(current, player.key, 112)
    prankster = _owned_effect(current, player.key, 113)
    confusion = _owned_curse(current, player.key, "confusion")
    decay = _owned_curse(current, player.key, "decay")
    frenzy = _owned_curse(current, player.key, "frenzy")
    unerring_miss = _owned_curse(current, player.key, "unerring_miss")
    recycler_successes = ammunition_recycler_successes_per_thirty(
        current,
        player.key,
    )
    if recycler_successes and attempt.recycler_roll is None:
        raise ValueError("active ammunition recycler requires one injected roll")
    if not recycler_successes and attempt.recycler_roll is not None:
        raise ValueError("recycler roll requires an active ammunition recycler")

    effective_jam_bps = attempt.base_jam_bps
    if decay is not None:
        reliability_bps = 10_000 - effective_jam_bps
        reliability_bps = reliability_bps * (100 - (decay.magnitude or 0)) // 100
        effective_jam_bps = 10_000 - reliability_bps
    if sand is not None:
        effective_jam_bps = min(10_000, effective_jam_bps * 2)
    if grease is not None or permanent_grease:
        effective_jam_bps //= 2
    accuracy_bonus_percent = (0 if scope is None else
        (scope.magnitude or 0) if attempt.scope_bonus_points is None else attempt.scope_bonus_points)
    accuracy = shot_accuracy(
        current, player, attempt.base_accuracy_bps,
        settled_fatigue_penalty_bps=attempt.fatigue_penalty_bps,
        settled_overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
        settled_scope_bonus_points=attempt.scope_bonus_points,
    )
    effective_accuracy_bps = accuracy.effective_bps
    ammunition_item_id = (
        4 if explosive is not None else 3 if penetrating is not None else None
    )
    damage = 3 if explosive is not None else 2 if penetrating is not None else 1
    if frenzy is not None:
        damage *= frenzy.magnitude or 1
    if attempt.loot is not None:
        validate_loot_award(attempt.loot)
        killing_standard_shot = (
            sabotage is None
            and attempt.jam_roll > effective_jam_bps
            and current.flight is not None
            and current.flight.kind is FlightKind.STANDARD
            and attempt.accuracy_roll <= effective_accuracy_bps
            and (attempt.incident is None or unerring_miss is not None)
            and damage >= current.flight.health
        )
        if not killing_standard_shot:
            raise ValueError("loot requires a killing shot on a standard flight")
    if sabotage is not None:
        if sand is not None:
            current = _consume_effect_use(current, sand)
        current = _consume_effect_use(current, sabotage)
        player = replace(player, jammed=True, jams=player.jams + 1)
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                OutcomeKind.SABOTAGE_TRIGGERED,
                actor=nickname,
                command=command.kind,
                player=player,
                item_id=sabotage.item_id,
                effect_id=sabotage.effect_id,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                nuisance_source_key=sabotage.source_key,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))
    if attempt.jam_roll <= effective_jam_bps:
        if sand is not None:
            current = _consume_effect_use(current, sand)
        player = replace(player, jammed=True, jams=player.jams + 1)
        current = _replace_player(current, player)
        outcomes.append(
            Outcome(
                OutcomeKind.JAMMED,
                actor=nickname,
                command=command.kind,
                player=player,
                item_id=None if sand is None else sand.item_id,
                effect_id=None if sand is None else sand.effect_id,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                nuisance_source_key=None if sand is None else sand.source_key,
            )
        )
        return Transition(state=current, outcomes=tuple(outcomes))

    late_by_ms = late_shot_delay_ms(current, now_ns)
    incident_forced_miss = attempt.incident is not None and unerring_miss is None
    would_miss = (
        current.flight is None
        or incident_forced_miss
        or attempt.accuracy_roll > effective_accuracy_bps
    )
    if (
        unerring_miss is not None
        and would_miss
        and late_by_ms is None
        and attempt.incident is None
    ):
        raise ValueError("unerring_miss requires an incident settlement for this shot")
    if sand is not None:
        current = _consume_effect_use(current, sand)

    ammunition_recycled = (
        recycler_successes > 0
        and attempt.recycler_roll is not None
        and attempt.recycler_roll <= recycler_successes
    )
    rounds_consumed = (
        0
        if ammunition_recycled
        else min(
            player.ammo,
            1 if frenzy is None else frenzy.magnitude or 1,
        )
    )
    player = replace(player, ammo=player.ammo - rounds_consumed)
    current = _replace_player(current, player)
    current, player, fatigue_changed_centi = _accrue_shot_fatigue(
        current,
        player,
        attempt,
    )
    if scope is not None:
        current = _consume_effect_use(current, scope)
    if glare is not None:
        current = _consume_effect_use(current, glare)

    if late_by_ms is not None:
        if attempt.incident is not None:
            raise ValueError("a late shot cannot carry an incident settlement")
        player = replace(player, misses=player.misses + 1)
        current, player, lost_levels = _apply_miss_penalty(
            current,
            player,
            attempt,
            wild=False,
        )
        outcomes.append(
            Outcome(
                OutcomeKind.LATE_SHOT,
                actor=nickname,
                command=command.kind,
                player=player,
                late_by_ms=late_by_ms,
                rounds_consumed=rounds_consumed,
                ammunition_recycled=ammunition_recycled,
                fatigue_changed_centi=fatigue_changed_centi,
                fatigue_penalty_bps=attempt.fatigue_penalty_bps,
                overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
                accuracy_bonus_percent=accuracy_bonus_percent,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                miss_penalty=attempt.miss_penalty,
                levels_lost=lost_levels,
                item_id=None if glare is None else glare.item_id,
                effect_id=None if glare is None else glare.effect_id,
                nuisance_source_key=None if glare is None else glare.source_key,
            )
        )
        return _finish_fired_transition(current, nickname, command.kind, outcomes)

    if current.flight is None:
        player = replace(
            player,
            misses=player.misses + 1,
            wild_shots=player.wild_shots + 1,
        )
        current, player, lost_levels = _apply_miss_penalty(
            current,
            player,
            attempt,
            wild=True,
        )
        outcomes.append(
            Outcome(
                OutcomeKind.MISS,
                actor=nickname,
                command=command.kind,
                player=player,
                rounds_consumed=rounds_consumed,
                ammunition_recycled=ammunition_recycled,
                fatigue_changed_centi=fatigue_changed_centi,
                fatigue_penalty_bps=attempt.fatigue_penalty_bps,
                overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
                accuracy_bonus_percent=accuracy_bonus_percent,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                miss_penalty=attempt.miss_penalty,
                wild_penalty=attempt.wild_penalty,
                levels_lost=lost_levels,
                item_id=None if glare is None else glare.item_id,
                effect_id=None if glare is None else glare.effect_id,
                nuisance_source_key=None if glare is None else glare.source_key,
            )
        )
        if attempt.incident is not None:
            current, incident_outcomes = _settle_incident(
                current,
                nickname,
                command.kind,
                attempt.incident,
            )
            outcomes.extend(incident_outcomes)
        return _finish_fired_transition(current, nickname, command.kind, outcomes)

    if incident_forced_miss or attempt.accuracy_roll > effective_accuracy_bps:
        player = replace(player, misses=player.misses + 1)
        current, player, lost_levels = _apply_miss_penalty(
            current,
            player,
            attempt,
            wild=False,
        )
        counted_noise = attempt.noisy_miss_limit is not None
        noise_suppressed = (counted_noise or attempt.frighten_on_miss) and suppressor is not None
        frightened_by_miss = attempt.frighten_on_miss and suppressor is None
        if counted_noise and suppressor is None:
            flight = replace(current.flight, noisy_misses=(current.flight.noisy_misses or 0) + 1)
            current = replace(current, flight=flight)
            frightened_by_miss = (flight.kind is FlightKind.STANDARD
                                  and flight.noisy_misses >= attempt.noisy_miss_limit)
        outcomes.append(
            Outcome(
                OutcomeKind.MISS,
                actor=nickname,
                command=command.kind,
                flight_id=current.flight.flight_id,
                player=player,
                rounds_consumed=rounds_consumed,
                ammunition_recycled=ammunition_recycled,
                fatigue_changed_centi=fatigue_changed_centi,
                fatigue_penalty_bps=attempt.fatigue_penalty_bps,
                overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
                accuracy_bonus_percent=accuracy_bonus_percent,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                noise_suppressed=noise_suppressed,
                miss_penalty=attempt.miss_penalty,
                levels_lost=lost_levels,
                item_id=None if glare is None else glare.item_id,
                effect_id=None if glare is None else glare.effect_id,
                nuisance_source_key=None if glare is None else glare.source_key,
            )
        )
        if attempt.incident is not None:
            current, incident_outcomes = _settle_incident(
                current,
                nickname,
                command.kind,
                attempt.incident,
            )
            outcomes.extend(incident_outcomes)
        if frightened_by_miss:
            frightened = current.flight
            flight_id = frightened.flight_id
            current = replace(
                current,
                flight=None,
                last_flight=LastFlight(
                    flight_id=frightened.flight_id,
                    kind=frightened.kind,
                    spawned_at_ns=frightened.spawned_at_ns,
                    ended_at_ns=now_ns,
                    conclusion=LastFlightConclusion.FRIGHTENED,
                    actor=nickname,
                ),
            )
            outcomes.append(
                Outcome(
                    OutcomeKind.FLIGHT_FRIGHTENED,
                    actor=nickname,
                    command=command.kind,
                    flight_id=flight_id,
                )
            )
        return _finish_fired_transition(current, nickname, command.kind, outcomes)

    flight = current.flight
    remaining_health = max(0, flight.health - damage)
    if remaining_health > 0:
        current = replace(current, flight=replace(flight, health=remaining_health))
        outcomes.append(
            Outcome(
                OutcomeKind.FLIGHT_SURVIVED,
                actor=nickname,
                command=command.kind,
                flight_id=flight.flight_id,
                flight_kind=flight.kind,
                player=player,
                rounds_consumed=rounds_consumed,
                ammunition_recycled=ammunition_recycled,
                ammunition_item_id=ammunition_item_id,
                fatigue_changed_centi=fatigue_changed_centi,
                fatigue_penalty_bps=attempt.fatigue_penalty_bps,
                overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
                damage_dealt=damage,
                remaining_health=remaining_health,
                accuracy_bonus_percent=accuracy_bonus_percent,
                effective_accuracy_bps=effective_accuracy_bps,
                effective_jam_bps=effective_jam_bps,
                item_id=None if glare is None else glare.item_id,
                effect_id=None if glare is None else glare.effect_id,
                nuisance_source_key=None if glare is None else glare.source_key,
            )
        )
        return _finish_fired_transition(current, nickname, command.kind, outcomes)

    elapsed_ms = (now_ns - flight.spawned_at_ns) // 1_000_000
    best_time_ms = (
        elapsed_ms
        if player.best_time_ms is None
        else min(player.best_time_ms, elapsed_ms)
    )
    player = replace(
        player,
        hits=player.hits + 1,
        golden_hits=(
            player.golden_hits + 1
            if flight.kind is FlightKind.GOLDEN
            else player.golden_hits
        ),
        best_time_ms=best_time_ms,
        carried_ducks=(
            player.carried_ducks + 1
            if flight.kind is not FlightKind.MECHANICAL
            else player.carried_ducks
        ),
    )
    carry_fatigue_multiplier = (
        _carry_fatigue_multiplier(current, player)
        if flight.kind is not FlightKind.MECHANICAL
        else 1
    )
    milestone_award = milestone_credit(player.hits)
    if milestone_award:
        player = replace(
            player,
            shop_credit=player.shop_credit + milestone_award,
        )
    experience_awarded = flight.reward_experience + (
        0 if charm is None else charm.magnitude or 0
    )
    if confusion is not None:
        experience_awarded //= confusion.magnitude or 1
    progression = grant_experience(player, experience_awarded)
    player = progression.player
    current = replace(
        _replace_player(current, player),
        flight=None,
        last_flight=LastFlight(
            flight_id=flight.flight_id,
            kind=flight.kind,
            spawned_at_ns=flight.spawned_at_ns,
            ended_at_ns=now_ns,
            conclusion=LastFlightConclusion.HIT,
            actor=nickname,
        ),
    )
    outcomes.append(
        Outcome(
            OutcomeKind.HIT,
            actor=nickname,
            command=command.kind,
            flight_id=flight.flight_id,
            flight_kind=flight.kind,
            elapsed_ms=elapsed_ms,
            player=player,
            rounds_consumed=rounds_consumed,
            ammunition_recycled=ammunition_recycled,
            ammunition_item_id=ammunition_item_id,
            fatigue_changed_centi=fatigue_changed_centi,
            fatigue_penalty_bps=attempt.fatigue_penalty_bps,
            overexcitation_penalty_bps=attempt.overexcitation_penalty_bps,
            experience_awarded=experience_awarded,
            levels_gained=progression.levels_gained,
            damage_dealt=damage,
            remaining_health=0,
            accuracy_bonus_percent=accuracy_bonus_percent,
            effective_accuracy_bps=effective_accuracy_bps,
            effective_jam_bps=effective_jam_bps,
            item_id=None if glare is None else glare.item_id,
            effect_id=None if glare is None else glare.effect_id,
            nuisance_source_key=None if glare is None else glare.source_key,
            carry_fatigue_multiplier=carry_fatigue_multiplier,
        )
    )
    if milestone_award:
        outcomes.append(
            Outcome(
                OutcomeKind.MILESTONE_CREDIT,
                actor=nickname,
                player=player,
                shop_credit_awarded=milestone_award,
            )
        )
    current, reward_outcomes = _apply_kill_reward_triggers(
        current,
        player,
        now_ns,
        baker=baker,
        prankster=prankster,
    )
    outcomes.extend(reward_outcomes)
    if attempt.loot is not None:
        acquisition = acquire_loot(current, nickname, attempt.loot, now_ns)
        current = acquisition.state
        outcomes.extend(acquisition.outcomes)
    return _finish_fired_transition(current, nickname, command.kind, outcomes)
