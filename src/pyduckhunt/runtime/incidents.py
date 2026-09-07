"""Calibrated live incident selection from synchronized IRC membership."""

from __future__ import annotations

import threading
from collections.abc import Callable

from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import (
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    ShotAttempt,
)
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.message import IRCMessage
from pyduckhunt.runtime.application import IRCCommandContext


IntegerSource = Callable[[int, int], int]
IncidentObserver = Callable[[str], None]
HISTORICAL_INCIDENT_BPS = 500
MAX_INCIDENT_TARGETS = 16
_MEMBERSHIP_PREFIXES = "~&@%+"


class IRCChannelRoster:
    """Maintain bounded channel membership on the IRC event-loop thread."""

    def __init__(
        self,
        channels: tuple[str, ...],
        bot_nicknames: tuple[str, ...],
    ) -> None:
        if type(channels) is not tuple or not channels:
            raise ValueError("channel roster requires immutable channels")
        if type(bot_nicknames) is not tuple or not bot_nicknames:
            raise ValueError("channel roster requires immutable bot nicknames")
        canonical_channels = tuple(rfc1459_casefold(channel) for channel in channels)
        if len(set(canonical_channels)) != len(canonical_channels):
            raise ValueError("channel roster channels must be unique")
        if any(not channel.startswith(("#", "&")) for channel in channels):
            raise ValueError("channel roster channel is invalid")
        if any(type(nickname) is not str or not nickname for nickname in bot_nicknames):
            raise ValueError("channel roster bot nickname is invalid")
        self._channels = frozenset(canonical_channels)
        self._bots = frozenset(rfc1459_casefold(name) for name in bot_nicknames)
        self._members: dict[str, dict[str, str]] = {
            channel: {} for channel in canonical_channels
        }
        self._synchronized: set[str] = set()
        self._owner_thread = threading.get_ident()

    def observe(self, message: IRCMessage) -> None:
        """Apply one forwarded membership fact without retaining hostmasks."""

        self._ensure_owner()
        if not isinstance(message, IRCMessage):
            raise ValueError("channel roster requires an IRC message")
        command = message.command
        nickname = message.nickname
        if command == "353" and len(message.params) >= 3:
            channel = rfc1459_casefold(message.params[-2])
            if channel in self._channels:
                for raw_name in message.params[-1].split():
                    name = raw_name.lstrip(_MEMBERSHIP_PREFIXES)
                    if name:
                        self._members[channel][rfc1459_casefold(name)] = name
            return
        if command == "366" and len(message.params) >= 2:
            channel = rfc1459_casefold(message.params[-2])
            if channel in self._channels:
                self._synchronized.add(channel)
            return
        if command == "JOIN" and nickname is not None and message.params:
            channel = rfc1459_casefold(message.params[0])
            if channel not in self._channels:
                return
            key = rfc1459_casefold(nickname)
            if key in self._bots:
                self._members[channel].clear()
                self._synchronized.discard(channel)
            self._members[channel][key] = nickname
            return
        if command == "PART" and nickname is not None and message.params:
            self._remove(message.params[0], nickname)
            return
        if command == "KICK" and len(message.params) >= 2:
            self._remove(message.params[0], message.params[1])
            return
        if command == "QUIT" and nickname is not None:
            self._remove_everywhere(nickname)
            return
        if command == "NICK" and nickname is not None and message.params:
            old_key = rfc1459_casefold(nickname)
            new_name = message.params[0]
            new_key = rfc1459_casefold(new_name)
            for members in self._members.values():
                if old_key in members:
                    del members[old_key]
                    members[new_key] = new_name

    def present(self, channel: str, nickname: str) -> bool:
        self._ensure_owner()
        canonical = rfc1459_casefold(channel)
        return (
            canonical in self._synchronized
            and rfc1459_casefold(nickname) in self._members.get(canonical, {})
        )

    def candidates(self, channel: str, shooter: str) -> tuple[str, ...]:
        """Return stable eligible victims only after a complete NAMES reply."""

        self._ensure_owner()
        canonical = rfc1459_casefold(channel)
        if canonical not in self._synchronized:
            return ()
        excluded = set(self._bots)
        excluded.add(rfc1459_casefold(shooter))
        members = self._members.get(canonical, {})
        return tuple(
            members[key]
            for key in sorted(members)
            if key not in excluded
        )

    def _remove(self, channel: str, nickname: str) -> None:
        canonical = rfc1459_casefold(channel)
        if canonical in self._channels:
            key = rfc1459_casefold(nickname)
            self._members[canonical].pop(key, None)
            if key in self._bots:
                self._synchronized.discard(canonical)

    def _remove_everywhere(self, nickname: str) -> None:
        key = rfc1459_casefold(nickname)
        for channel, members in self._members.items():
            members.pop(key, None)
            if key in self._bots:
                self._synchronized.discard(channel)

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("channel roster is owned by one event-loop thread")


class CalibratedIncidentSource:
    """Select and explain a replay-complete historical incident chain."""

    def __init__(
        self,
        integer_source: IntegerSource,
        roster: IRCChannelRoster,
        observer: IncidentObserver | None = None,
    ) -> None:
        if not callable(integer_source):
            raise ValueError("incident source requires an integer source")
        if not isinstance(roster, IRCChannelRoster):
            raise ValueError("incident source requires a channel roster")
        if observer is not None and not callable(observer):
            raise ValueError("incident observer must be callable or none")
        self._integer_source = integer_source
        self._roster = roster
        self._observer = observer
        self._owner_thread = threading.get_ident()

    def __call__(
        self,
        state: GameState,
        context: IRCCommandContext,
        attempt: ShotAttempt,
    ) -> IncidentAttempt | None:
        self._ensure_owner()
        if not isinstance(state, GameState) or not isinstance(context, IRCCommandContext):
            raise ValueError("incident source requires validated game context")
        if not isinstance(attempt, ShotAttempt):
            raise ValueError("incident source requires a shot attempt")
        candidates = list(self._roster.candidates(context.channel, context.nickname))
        if not candidates:
            return None
        trigger_roll = self._draw(1, 10_000)
        if trigger_roll > HISTORICAL_INCIDENT_BPS:
            return None

        targets: list[IncidentTargetAttempt] = []
        while candidates and len(targets) < MAX_INCIDENT_TARGETS:
            selected = self._draw(0, len(candidates) - 1)
            nickname = candidates.pop(selected)
            player = state.player(rfc1459_casefold(nickname))
            policy = level_policy(1 if player is None else player.level)
            target = IncidentTargetAttempt(
                nickname,
                deflection_bps=policy.deflection_bps,
                armor_bps=policy.armor_bps,
                deflection_roll=self._draw(1, 10_000),
                armor_roll=self._draw(1, 10_000),
            )
            targets.append(target)
            if target.deflection_roll > target.deflection_bps:
                break

        shooter = state.player(rfc1459_casefold(context.nickname))
        shooter_policy = level_policy(1 if shooter is None else shooter.level)
        if self._observer is not None:
            target_facts = ",".join(
                f"{_safe_atom(target.nickname)}:"
                f"deflection={target.deflection_roll}/{target.deflection_bps}:"
                f"armor={target.armor_roll}/{target.armor_bps}"
                for target in targets
            )
            self._observer(
                "INCIDENT event=selected "
                f"channel={_safe_atom(context.channel)} "
                f"shooter={_safe_atom(context.nickname)} "
                f"trigger={trigger_roll}/{HISTORICAL_INCIDENT_BPS} "
                f"targets={target_facts}"
            )
        return IncidentAttempt(tuple(targets), shooter_policy.incident_penalty)

    def _draw(self, minimum: int, maximum: int) -> int:
        value = self._integer_source(minimum, maximum)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("incident integer source returned an invalid value")
        return value

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("incident source is owned by one event-loop thread")


def _safe_atom(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._:#-[]{}" else "_"
        for character in value
    )[:128]
