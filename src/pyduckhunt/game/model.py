"""Immutable state and outcomes for deterministic game replays."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.progression import experience_required
from pyduckhunt.identity import rfc1459_casefold


ITEM_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FATIGUE_SCALE = 100
MAX_FATIGUE_CENTI = 100 * FATIGUE_SCALE
LETTER_SLOT_COUNT = 8


@dataclass(frozen=True, slots=True)
class InventoryStack:
    key: str
    quantity: int

    def __post_init__(self) -> None:
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("inventory key must be a stable lowercase identifier")
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("inventory quantity must be a positive integer")


class EffectScope(str, Enum):
    PLAYER = "player"
    CHANNEL = "channel"


class FlightKind(str, Enum):
    STANDARD = "standard"
    GOLDEN = "golden"
    MECHANICAL = "mechanical"


class LastFlightConclusion(str, Enum):
    HIT = "hit"
    ESCAPED = "escaped"
    FRIGHTENED = "frightened"


@dataclass(frozen=True, slots=True)
class ActiveEffect:
    effect_id: int
    item_id: int
    key: str
    scope: EffectScope
    owner_key: str | None
    source_key: str | None
    activated_at_ns: int
    expires_at_ns: int | None = None
    remaining_uses: int | None = None
    magnitude: int | None = None

    def __post_init__(self) -> None:
        if type(self.effect_id) is not int or self.effect_id < 1:
            raise ValueError("effect identifier must be positive")
        if type(self.item_id) is not int or self.item_id < 1:
            raise ValueError("shop item identifier must be positive")
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("effect key must be a stable lowercase identifier")
        if self.scope is EffectScope.PLAYER and not self.owner_key:
            raise ValueError("player effect requires an owner key")
        if self.scope is EffectScope.CHANNEL and self.owner_key is not None:
            raise ValueError("channel effect cannot have an owner key")
        if self.source_key is not None and not isinstance(self.source_key, str):
            raise ValueError("effect source key must be a string or null")
        if self.source_key == "":
            raise ValueError("effect source key must not be empty")
        if type(self.activated_at_ns) is not int or self.activated_at_ns < 0:
            raise ValueError("effect activation time is invalid")
        if self.expires_at_ns is not None and (
            type(self.expires_at_ns) is not int
            or self.expires_at_ns <= self.activated_at_ns
        ):
            raise ValueError("effect expiration time is invalid")
        if self.remaining_uses is not None and (
            type(self.remaining_uses) is not int or self.remaining_uses < 1
        ):
            raise ValueError("effect use count must be positive")
        if self.expires_at_ns is None and self.remaining_uses is None:
            raise ValueError("effect must be time-bounded or use-bounded")
        if self.magnitude is not None and type(self.magnitude) is not int:
            raise ValueError("effect magnitude must be an integer")


@dataclass(frozen=True, slots=True)
class ScheduledAction:
    """One durable, externally dispatched channel action."""

    action_id: int
    item_id: int
    key: str
    source_key: str
    created_at_ns: int
    due_at_ns: int

    def __post_init__(self) -> None:
        if type(self.action_id) is not int or self.action_id < 1:
            raise ValueError("action identifier must be positive")
        if type(self.item_id) is not int or self.item_id < 1:
            raise ValueError("action shop item identifier must be positive")
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("action key must be a stable lowercase identifier")
        if not isinstance(self.source_key, str) or not self.source_key:
            raise ValueError("action source key must not be empty")
        if type(self.created_at_ns) is not int or self.created_at_ns < 0:
            raise ValueError("action creation time is invalid")
        if type(self.due_at_ns) is not int or self.due_at_ns <= self.created_at_ns:
            raise ValueError("action deadline must follow its creation time")


@dataclass(frozen=True, slots=True)
class DailySchedule:
    """One durable UTC-day flight plan and its next unconsumed deadline."""

    day_start_ns: int
    deadlines_ns: tuple[int, ...]
    next_index: int = 0

    def __post_init__(self) -> None:
        if type(self.day_start_ns) is not int or self.day_start_ns < 0:
            raise ValueError("schedule day start must be a non-negative integer")
        if type(self.deadlines_ns) is not tuple or not self.deadlines_ns:
            raise ValueError("schedule deadlines must be a non-empty tuple")
        if any(type(value) is not int for value in self.deadlines_ns):
            raise ValueError("schedule deadlines must be integers")
        if self.deadlines_ns != tuple(sorted(set(self.deadlines_ns))):
            raise ValueError("schedule deadlines must be unique and sorted")
        if type(self.next_index) is not int or not 0 <= self.next_index <= len(
            self.deadlines_ns
        ):
            raise ValueError("schedule cursor is outside the deadline sequence")


@dataclass(frozen=True, slots=True)
class ThrottleWindow:
    """Bounded expirations for one channel-wide or per-player command gate."""

    player_key: str | None
    command: CommandKind | None
    expires_at_ns: tuple[int, ...]
    notice_after_ns: int = 0

    def __post_init__(self) -> None:
        if (self.player_key is None) != (self.command is None):
            raise ValueError("throttle player and command must be paired")
        if self.player_key is not None and not self.player_key:
            raise ValueError("throttle player key must not be empty")
        if self.player_key is not None and self.player_key != rfc1459_casefold(
            self.player_key
        ):
            raise ValueError("throttle player key must be canonical")
        if self.command is not None and not isinstance(self.command, CommandKind):
            raise ValueError("throttle command must be a public command kind")
        if type(self.expires_at_ns) is not tuple or not self.expires_at_ns:
            raise ValueError("throttle window requires at least one expiration")
        if any(type(value) is not int or value < 1 for value in self.expires_at_ns):
            raise ValueError("throttle expirations must be positive integers")
        if self.expires_at_ns != tuple(sorted(self.expires_at_ns)):
            raise ValueError("throttle expirations must be sorted")
        if len(self.expires_at_ns) > 30:
            raise ValueError("throttle window exceeds the global bounded count")
        if type(self.notice_after_ns) is not int or self.notice_after_ns < 0:
            raise ValueError("throttle notice deadline must be non-negative")


@dataclass(frozen=True, slots=True)
class ActiveCurse:
    """A bounded negative modifier acquired outside the shop."""

    curse_id: int
    key: str
    owner_key: str
    activated_at_ns: int
    expires_at_ns: int
    magnitude: int | None = None

    def __post_init__(self) -> None:
        if type(self.curse_id) is not int or self.curse_id < 1:
            raise ValueError("curse identifier must be positive")
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("curse key must be a stable lowercase identifier")
        if not isinstance(self.owner_key, str) or not self.owner_key:
            raise ValueError("curse owner key must not be empty")
        if type(self.activated_at_ns) is not int or self.activated_at_ns < 0:
            raise ValueError("curse activation time is invalid")
        if type(self.expires_at_ns) is not int or self.expires_at_ns <= self.activated_at_ns:
            raise ValueError("curse expiration time is invalid")
        if self.magnitude is not None and type(self.magnitude) is not int:
            raise ValueError("curse magnitude must be an integer")


@dataclass(frozen=True, slots=True)
class IncidentTargetAttempt:
    """One injected victim and its immutable defensive rolls."""

    nickname: str
    deflection_bps: int = 0
    armor_bps: int = 0
    deflection_roll: int = 10_000
    armor_roll: int = 10_000

    def __post_init__(self) -> None:
        if not isinstance(self.nickname, str) or not self.nickname:
            raise ValueError("incident target nickname must not be empty")
        for field_name in ("deflection_bps", "armor_bps"):
            value = getattr(self, field_name)
            if type(value) is not int or not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be between zero and 10000")
        for field_name in ("deflection_roll", "armor_roll"):
            value = getattr(self, field_name)
            if type(value) is not int or not 1 <= value <= 10_000:
                raise ValueError(f"{field_name} must be between one and 10000")


@dataclass(frozen=True, slots=True)
class IncidentAttempt:
    """Injected cross-player chain and calibrated experience penalties."""

    targets: tuple[IncidentTargetAttempt, ...]
    incident_penalty: int = 0

    def __post_init__(self) -> None:
        if type(self.targets) is not tuple or not self.targets:
            raise ValueError("incident attempt requires at least one target")
        if len(self.targets) > 16:
            raise ValueError("incident chain exceeds the bounded target count")
        if not all(isinstance(target, IncidentTargetAttempt) for target in self.targets):
            raise ValueError("incident targets must satisfy the domain contract")
        if type(self.incident_penalty) is not int or self.incident_penalty < 0:
            raise ValueError("incident_penalty must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class LootAward:
    """One already-selected post-kill acquisition fact."""

    key: str
    magnitude: int | None = None
    curse_key: str | None = None
    completion_loot: tuple["LootAward", ...] = ()

    def __post_init__(self) -> None:
        if not ITEM_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("loot key must be a stable lowercase identifier")
        if self.magnitude is not None and type(self.magnitude) is not int:
            raise ValueError("loot magnitude must be an integer")
        if self.curse_key is not None and not ITEM_KEY_PATTERN.fullmatch(
            self.curse_key
        ):
            raise ValueError("loot curse key must be a stable lowercase identifier")
        if type(self.completion_loot) is not tuple or len(self.completion_loot) > 16:
            raise ValueError("completion loot must be an immutable bounded tuple")
        if any(not isinstance(award, LootAward) for award in self.completion_loot):
            raise ValueError("completion loot entries must satisfy the loot contract")


@dataclass(frozen=True, slots=True)
class ShotAttempt:
    """Injected rolls and baseline probabilities for one trigger pull."""

    base_accuracy_bps: int = 10_000
    base_jam_bps: int = 0
    accuracy_roll: int = 1
    jam_roll: int = 10_000
    recycler_roll: int | None = None
    frighten_on_miss: bool = False
    miss_penalty: int = 0
    wild_penalty: int = 0
    fatigue_gain_centi: int = FATIGUE_SCALE
    incident: IncidentAttempt | None = None
    loot: LootAward | None = None

    def __post_init__(self) -> None:
        for field_name in ("base_accuracy_bps", "base_jam_bps"):
            value = getattr(self, field_name)
            if type(value) is not int or not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be between zero and 10000")
        for field_name in ("accuracy_roll", "jam_roll"):
            value = getattr(self, field_name)
            if type(value) is not int or not 1 <= value <= 10_000:
                raise ValueError(f"{field_name} must be between one and 10000")
        if self.recycler_roll is not None and (
            type(self.recycler_roll) is not int
            or not 1 <= self.recycler_roll <= 30
        ):
            raise ValueError("recycler_roll must be between one and 30 or null")
        if type(self.frighten_on_miss) is not bool:
            raise ValueError("frighten_on_miss must be a truth value")
        for field_name in ("miss_penalty", "wild_penalty", "fatigue_gain_centi"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.fatigue_gain_centi > MAX_FATIGUE_CENTI:
            raise ValueError("fatigue_gain_centi exceeds the bounded player range")
        if self.incident is not None and not isinstance(self.incident, IncidentAttempt):
            raise ValueError("incident must satisfy the domain contract")
        if self.loot is not None and not isinstance(self.loot, LootAward):
            raise ValueError("loot must satisfy the domain contract")


@dataclass(frozen=True, slots=True)
class PlayerState:
    key: str
    nickname: str
    ammo: int = 6
    capacity: int = 6
    magazines: int = 2
    magazine_capacity: int = 2
    hits: int = 0
    misses: int = 0
    wild_shots: int = 0
    empty_shots: int = 0
    jammed_shots: int = 0
    compulsive_reloads: int = 0
    shots_fired: int = 0
    jams: int = 0
    best_time_ms: int | None = None
    level: int = 1
    experience: int = 0
    experience_spent: int = 0
    inventory: tuple[InventoryStack, ...] = ()
    jammed: bool = False
    confiscated: bool = False
    permanently_confiscated: bool = False
    confiscations: int = 0
    incidents_caused: int = 0
    shots_received: int = 0
    incidents_deflected: int = 0
    incidents_absorbed: int = 0
    deaths: int = 0
    golden_hits: int = 0
    fatigue_centi: int = 0
    shop_credit: int = 0
    karma_modifier_basis_points: int = 0
    karma_decay_at_ns: int | None = None
    carried_ducks: int = 0
    carried_day_start_ns: int = 0
    letter_slots: tuple[bool, ...] = (False,) * LETTER_SLOT_COUNT

    def __post_init__(self) -> None:
        if not self.key or not self.nickname:
            raise ValueError("player identity must not be empty")
        if self.capacity < 1 or not 0 <= self.ammo <= self.capacity:
            raise ValueError("invalid player ammunition state")
        if (
            type(self.magazine_capacity) is not int
            or self.magazine_capacity < 0
            or type(self.magazines) is not int
            or not 0 <= self.magazines <= self.magazine_capacity
        ):
            raise ValueError("invalid player magazine reserve")
        if (
            type(self.hits) is not int
            or self.hits < 0
            or type(self.misses) is not int
            or self.misses < 0
            or type(self.wild_shots) is not int
            or self.wild_shots < 0
            or type(self.empty_shots) is not int
            or self.empty_shots < 0
            or type(self.jammed_shots) is not int
            or self.jammed_shots < 0
            or type(self.compulsive_reloads) is not int
            or self.compulsive_reloads < 0
            or type(self.shots_fired) is not int
            or self.shots_fired < 0
            or type(self.jams) is not int
            or self.jams < 0
        ):
            raise ValueError("player counters must not be negative")
        if self.best_time_ms is not None and self.best_time_ms < 0:
            raise ValueError("best time must not be negative")
        if self.key != rfc1459_casefold(self.nickname):
            raise ValueError("player key does not match the IRC identity")
        if type(self.jammed) is not bool:
            raise ValueError("player jammed state must be a truth value")
        if type(self.confiscated) is not bool:
            raise ValueError("player confiscated state must be a truth value")
        if type(self.permanently_confiscated) is not bool:
            raise ValueError("player permanent confiscation must be a truth value")
        if self.permanently_confiscated and not self.confiscated:
            raise ValueError("permanent confiscation requires a confiscated weapon")
        for field_name in (
            "confiscations",
            "incidents_caused",
            "shots_received",
            "incidents_deflected",
            "incidents_absorbed",
            "deaths",
            "golden_hits",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"player {field_name} must be a non-negative integer")
        if (
            type(self.fatigue_centi) is not int
            or not 0 <= self.fatigue_centi <= MAX_FATIGUE_CENTI
        ):
            raise ValueError("player fatigue is outside the calibrated range")
        if type(self.shop_credit) is not int or self.shop_credit < 0:
            raise ValueError("player shop credit must be a non-negative integer")
        if type(self.carried_ducks) is not int or self.carried_ducks < 0:
            raise ValueError("player carried ducks must be a non-negative integer")
        if (
            type(self.carried_day_start_ns) is not int
            or self.carried_day_start_ns < 0
            or self.carried_day_start_ns % 86_400_000_000_000
        ):
            raise ValueError("player carry day must use a canonical calendar-day marker")
        if (
            type(self.letter_slots) is not tuple
            or len(self.letter_slots) != LETTER_SLOT_COUNT
            or any(type(value) is not bool for value in self.letter_slots)
        ):
            raise ValueError("player letter slots must be eight truth values")
        if (
            type(self.karma_modifier_basis_points) is not int
            or not -10_000 <= self.karma_modifier_basis_points <= 10_000
        ):
            raise ValueError("player karma modifier is outside the bounded range")
        if self.karma_modifier_basis_points == 0:
            if self.karma_decay_at_ns is not None:
                raise ValueError("neutral karma modifier cannot have a decay deadline")
        elif type(self.karma_decay_at_ns) is not int or self.karma_decay_at_ns < 1:
            raise ValueError("non-neutral karma modifier requires a decay deadline")
        if type(self.level) is not int or self.level < 1:
            raise ValueError("player level must be a positive integer")
        if (
            type(self.experience) is not int
            or not 0 <= self.experience < experience_required(self.level)
        ):
            raise ValueError("player experience is outside the current level")
        if type(self.experience_spent) is not int or self.experience_spent < 0:
            raise ValueError("player spent experience must be a non-negative integer")
        item_keys = tuple(stack.key for stack in self.inventory)
        if item_keys != tuple(sorted(item_keys)) or len(item_keys) != len(set(item_keys)):
            raise ValueError("inventory stacks must be unique and sorted by key")


@dataclass(frozen=True, slots=True)
class FlightState:
    flight_id: int
    spawned_at_ns: int
    expires_at_ns: int
    health: int = 1
    max_health: int = 1
    kind: FlightKind = FlightKind.STANDARD
    reward_experience: int = 10

    def __post_init__(self) -> None:
        if self.flight_id < 1:
            raise ValueError("flight identifier must be positive")
        if self.spawned_at_ns < 0 or self.expires_at_ns <= self.spawned_at_ns:
            raise ValueError("invalid flight timing")
        if type(self.health) is not int or self.health < 1:
            raise ValueError("flight health must be a positive integer")
        if type(self.max_health) is not int or self.max_health < self.health:
            raise ValueError("flight maximum health is invalid")
        if not isinstance(self.kind, FlightKind):
            raise ValueError("flight kind is invalid")
        if type(self.reward_experience) is not int or self.reward_experience < 0:
            raise ValueError("flight reward must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class LastFlight:
    flight_id: int
    kind: FlightKind
    spawned_at_ns: int
    ended_at_ns: int
    conclusion: LastFlightConclusion
    actor: str | None = None

    def __post_init__(self) -> None:
        if type(self.flight_id) is not int or self.flight_id < 1:
            raise ValueError("last-flight identifier must be positive")
        if not isinstance(self.kind, FlightKind):
            raise ValueError("last-flight kind is invalid")
        if (
            type(self.spawned_at_ns) is not int
            or type(self.ended_at_ns) is not int
            or self.spawned_at_ns < 0
            or self.ended_at_ns <= self.spawned_at_ns
        ):
            raise ValueError("last-flight timing is invalid")
        if not isinstance(self.conclusion, LastFlightConclusion):
            raise ValueError("last-flight conclusion is invalid")
        if self.actor is not None and (
            type(self.actor) is not str
            or not self.actor
            or any(character in self.actor for character in (" ", "\x00", "\r", "\n"))
        ):
            raise ValueError("last-flight actor is invalid")
        if self.conclusion is LastFlightConclusion.HIT and self.actor is None:
            raise ValueError("a hit last-flight record requires an actor")


@dataclass(frozen=True, slots=True)
class GameState:
    now_ns: int = 0
    next_flight_id: int = 1
    flight: FlightState | None = None
    last_flight: LastFlight | None = None
    last_shooter_key: str | None = None
    players: tuple[PlayerState, ...] = ()
    next_effect_id: int = 1
    effects: tuple[ActiveEffect, ...] = ()
    next_action_id: int = 1
    scheduled_actions: tuple[ScheduledAction, ...] = ()
    next_curse_id: int = 1
    curses: tuple[ActiveCurse, ...] = ()
    daily_schedule: DailySchedule | None = None
    throttle_windows: tuple[ThrottleWindow, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.now_ns < 0
            or self.next_flight_id < 1
            or self.next_effect_id < 1
            or self.next_action_id < 1
            or self.next_curse_id < 1
        ):
            raise ValueError("invalid game clock or flight sequence")
        keys = tuple(player.key for player in self.players)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("players must be unique and sorted by canonical key")
        if self.last_shooter_key is not None and self.last_shooter_key not in set(keys):
            raise ValueError("last shooter is absent from game state")
        if self.flight is not None:
            if self.now_ns >= self.flight.expires_at_ns:
                raise ValueError("active flight has already reached its deadline")
            if self.next_flight_id <= self.flight.flight_id:
                raise ValueError("flight sequence does not advance beyond active flight")
        if self.last_flight is not None:
            if not isinstance(self.last_flight, LastFlight):
                raise ValueError("last flight must satisfy the domain contract")
            if self.last_flight.ended_at_ns > self.now_ns:
                raise ValueError("last flight cannot end after the game clock")
            if self.last_flight.flight_id >= self.next_flight_id:
                raise ValueError("last flight must precede the next flight identifier")
            if (
                self.flight is not None
                and self.last_flight.flight_id >= self.flight.flight_id
            ):
                raise ValueError("last flight must precede the active flight")
        effect_ids = tuple(effect.effect_id for effect in self.effects)
        if effect_ids != tuple(sorted(effect_ids)) or len(effect_ids) != len(set(effect_ids)):
            raise ValueError("effects must be unique and sorted by identifier")
        if self.effects and self.next_effect_id <= self.effects[-1].effect_id:
            raise ValueError("effect sequence does not advance beyond active effects")
        if any(
            effect.expires_at_ns is not None and self.now_ns >= effect.expires_at_ns
            for effect in self.effects
        ):
            raise ValueError("active effect has already reached its deadline")
        if any(
            effect.scope is EffectScope.PLAYER and effect.owner_key not in set(keys)
            for effect in self.effects
        ):
            raise ValueError("player effect owner is absent from game state")
        if any(
            effect.source_key is not None and effect.source_key not in set(keys)
            for effect in self.effects
        ):
            raise ValueError("effect source is absent from game state")
        action_ids = tuple(action.action_id for action in self.scheduled_actions)
        if action_ids != tuple(sorted(action_ids)) or len(action_ids) != len(set(action_ids)):
            raise ValueError("scheduled actions must be unique and sorted by identifier")
        if self.scheduled_actions and self.next_action_id <= self.scheduled_actions[-1].action_id:
            raise ValueError("action sequence does not advance beyond scheduled actions")
        if any(action.due_at_ns <= self.now_ns for action in self.scheduled_actions):
            raise ValueError("scheduled action has already reached its deadline")
        if any(action.source_key not in set(keys) for action in self.scheduled_actions):
            raise ValueError("scheduled action source is absent from game state")
        curse_ids = tuple(curse.curse_id for curse in self.curses)
        if curse_ids != tuple(sorted(curse_ids)) or len(curse_ids) != len(set(curse_ids)):
            raise ValueError("curses must be unique and sorted by identifier")
        if self.curses and self.next_curse_id <= self.curses[-1].curse_id:
            raise ValueError("curse sequence does not advance beyond active curses")
        if any(curse.expires_at_ns <= self.now_ns for curse in self.curses):
            raise ValueError("active curse has already reached its deadline")
        if any(curse.owner_key not in set(keys) for curse in self.curses):
            raise ValueError("curse owner is absent from game state")
        if self.daily_schedule is not None and not isinstance(
            self.daily_schedule,
            DailySchedule,
        ):
            raise ValueError("daily schedule must satisfy the domain contract")
        if not all(
            isinstance(window, ThrottleWindow) for window in self.throttle_windows
        ):
            raise ValueError("throttle windows must satisfy the domain contract")
        window_keys = tuple(
            (
                "" if window.player_key is None else window.player_key,
                "" if window.command is None else window.command.value,
            )
            for window in self.throttle_windows
        )
        if window_keys != tuple(sorted(window_keys)) or len(window_keys) != len(
            set(window_keys)
        ):
            raise ValueError("throttle windows must be unique and sorted")

    def player(self, key: str) -> PlayerState | None:
        return next((player for player in self.players if player.key == key), None)

    def with_player(self, replacement: PlayerState) -> GameState:
        retained = tuple(player for player in self.players if player.key != replacement.key)
        players = tuple(sorted((*retained, replacement), key=lambda player: player.key))
        return GameState(
            now_ns=self.now_ns,
            next_flight_id=self.next_flight_id,
            flight=self.flight,
            last_flight=self.last_flight,
            last_shooter_key=self.last_shooter_key,
            players=players,
            next_effect_id=self.next_effect_id,
            effects=self.effects,
            next_action_id=self.next_action_id,
            scheduled_actions=self.scheduled_actions,
            next_curse_id=self.next_curse_id,
            curses=self.curses,
            daily_schedule=self.daily_schedule,
            throttle_windows=self.throttle_windows,
        )


class OutcomeKind(str, Enum):
    FLIGHT_STARTED = "flight_started"
    FLIGHT_ALREADY_ACTIVE = "flight_already_active"
    FLIGHT_EXPIRED = "flight_expired"
    HIT = "hit"
    MISS = "miss"
    LATE_SHOT = "late_shot"
    EMPTY = "empty"
    JAMMED = "jammed"
    RELOADED = "reloaded"
    UNJAMMED = "unjammed"
    ALREADY_LOADED = "already_loaded"
    NO_RESERVE = "no_reserve"
    COMMAND_DELAYED = "command_delayed"
    CURSE_BLOCKED = "curse_blocked"
    TRIGGER_LOCKED = "trigger_locked"
    FLIGHT_SURVIVED = "flight_survived"
    FLIGHT_FRIGHTENED = "flight_frightened"
    HUNT_BLOCKED = "hunt_blocked"
    WEAPON_CONFISCATED = "weapon_confiscated"
    SABOTAGE_TRIGGERED = "sabotage_triggered"
    INCIDENT_DEFLECTED = "incident_deflected"
    INCIDENT_ABSORBED = "incident_absorbed"
    INCIDENT_FATAL = "incident_fatal"
    EFFECT_EXPIRED = "effect_expired"
    EFFECT_CONSUMED = "effect_consumed"
    CHANNEL_ACTION_DUE = "channel_action_due"
    DUCK_ALERT = "duck_alert"
    CURSE_EXPIRED = "curse_expired"
    CURSE_NEUTRALIZED = "curse_neutralized"
    LOOT_ACQUIRED = "loot_acquired"
    MILESTONE_CREDIT = "milestone_credit"
    REWARD_TRIGGERED = "reward_triggered"
    SCHEDULED_FLIGHT_SKIPPED = "scheduled_flight_skipped"
    COMMAND_THROTTLED = "command_throttled"
    SHOP_PURCHASED = "shop_purchased"
    SHOP_UNKNOWN_ITEM = "shop_unknown_item"
    SHOP_INSUFFICIENT_EXPERIENCE = "shop_insufficient_experience"
    SHOP_NOT_APPLICABLE = "shop_not_applicable"
    SHOP_EFFECT_ACTIVE = "shop_effect_active"
    SHOP_TARGET_REQUIRED = "shop_target_required"
    SHOP_TARGET_UNKNOWN = "shop_target_unknown"
    SHOP_TARGET_ABSENT = "shop_target_absent"
    SHOP_TARGET_UNARMED = "shop_target_unarmed"
    SHOP_TARGET_IMMUNE = "shop_target_immune"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    actor: str | None = None
    command: CommandKind | None = None
    flight_id: int | None = None
    flight_kind: FlightKind | None = None
    elapsed_ms: int | None = None
    late_by_ms: int | None = None
    player: PlayerState | None = None
    experience_awarded: int = 0
    levels_gained: int = 0
    levels_lost: int = 0
    item_id: int | None = None
    charged_experience: int = 0
    effect_id: int | None = None
    effect_magnitude: int | None = None
    damage_dealt: int = 0
    rounds_consumed: int = 0
    ammunition_recycled: bool = False
    remaining_health: int | None = None
    accuracy_bonus_percent: int = 0
    effective_accuracy_bps: int | None = None
    effective_jam_bps: int | None = None
    noise_suppressed: bool = False
    target: str | None = None
    ricochet_index: int | None = None
    deflection_bps: int | None = None
    armor_bps: int | None = None
    miss_penalty: int = 0
    wild_penalty: int = 0
    incident_penalty: int = 0
    insurance_award: int = 0
    weapon_confiscated: bool = False
    safe_conduct_applied: bool = False
    liability_applied: bool = False
    nuisance_source_key: str | None = None
    effect_blocked: bool = False
    counter_item_id: int | None = None
    removed_item_ids: tuple[int, ...] = ()
    action_id: int | None = None
    due_at_ns: int | None = None
    fatigue_changed_centi: int = 0
    defer_until_ns: int | None = None
    automatic: bool = False
    unlimited_magazines: bool = False
    curse_key: str | None = None
    removed_curse_keys: tuple[str, ...] = ()
    loot_key: str | None = None
    loot_magnitude: int | None = None
    shop_credit_awarded: int = 0
    shop_credit_spent: int = 0
    experience_spent: int = 0
    discount_percent: int = 0
    triggered_item_id: int | None = None
    channel_effect_count: int | None = None
    skipped_deadlines_ns: tuple[int, ...] = ()
    notice_emitted: bool = False
    letter_collection_completed: bool = False
    carry_fatigue_multiplier: int = 1

    def __post_init__(self) -> None:
        if self.late_by_ms is not None and (
            type(self.late_by_ms) is not int or self.late_by_ms < 0
        ):
            raise ValueError("late shot delay must be a non-negative integer")
        if self.channel_effect_count is not None and (
            type(self.channel_effect_count) is not int
            or self.channel_effect_count < 1
        ):
            raise ValueError("channel effect count must be a positive integer")
        if type(self.letter_collection_completed) is not bool:
            raise ValueError("letter completion state must be a truth value")
        if type(self.carry_fatigue_multiplier) is not int or (
            self.carry_fatigue_multiplier not in (1, 2, 3)
        ):
            raise ValueError("carry fatigue multiplier must be one, two or three")


@dataclass(frozen=True, slots=True)
class Transition:
    state: GameState
    outcomes: tuple[Outcome, ...]
