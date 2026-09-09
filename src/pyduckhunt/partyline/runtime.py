"""Non-blocking Eggdrop-style partyline integrated with Coin's owner loop."""

from __future__ import annotations

from pyduckhunt.i18n import validate_language, tr, localized, localized_method

import errno
import ipaddress
import re
import secrets
import select
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

from pyduckhunt.game.bread import active_channel_breads
from pyduckhunt.configuration import PartylineConfiguration
from pyduckhunt.game.admin import (
    PlayerAdministrationError,
    apply_admin_channel_item,
    apply_player_update,
    apply_weapon_control,
)
from pyduckhunt.game.catalog import MINUTE_NS
from pyduckhunt.game.model import (
    FlightKind,
    GameState,
    OutcomeKind,
    PlayerState,
    Transition,
)
from pyduckhunt.game.progression import experience_required
from pyduckhunt.game.ranking import is_statistically_excluded, ranked_players
from pyduckhunt.game.runtime import DAY_NS
from pyduckhunt.game.targets import flight_reward
from pyduckhunt.identity import rfc1459_casefold, same_irc_name
from pyduckhunt.irc.message import IRCMessage, render_notice_bounded, render_privmsg
from pyduckhunt.partyline.users import PartylineCredentialError, PartylineUserStore
from pyduckhunt.persistence.event import ReplayEvent
from pyduckhunt.persistence.codec import SCHEMA_VERSION
from pyduckhunt.rendering.flight_appearance import (
    FlightAppearance,
    RandomizedFlightAppearanceSource,
)
from pyduckhunt.rendering.responses import (
    render_detector_notice,
    render_inventory,
    render_outcomes,
    render_profile,
    render_ranking,
    render_wire_notice,
    render_wire_response,
)

if TYPE_CHECKING:
    from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator


MAX_LINE_BYTES = 4_096
MAX_OUTPUT_BYTES = 65_536
MAX_SESSIONS = 8
MAX_PENDING_DCC = 4
AUTH_TIMEOUT_NS = 60 * 1_000_000_000
DCC_TIMEOUT_NS = 60 * 1_000_000_000
BOOTSTRAP_TIMEOUT_NS = 10 * 60 * 1_000_000_000
IP_FAILURE_WINDOW_NS = 10 * 60 * 1_000_000_000
MAX_SESSION_FAILURES = 5
MAX_IP_FAILURES = 15
PARIS_ZONE = ZoneInfo("Europe/Paris")
TELNET_IAC = 255
TELNET_WILL = 251
TELNET_WONT = 252
TELNET_DO = 253
TELNET_DONT = 254
TELNET_SUBNEGOTIATION = 250
TELNET_END_SUBNEGOTIATION = 240
TELNET_ECHO = 1


PartylineObserver = Callable[[str], None]
NetworkStatusProvider = Callable[[], tuple[str, str, bool, tuple[str, ...]]]
IntegerSource = Callable[[int, int], int]


def _system_integer(minimum: int, maximum: int) -> int:
    if type(minimum) is not int or type(maximum) is not int or minimum > maximum:
        raise ValueError("integer draw bounds are invalid")
    return minimum + secrets.randbelow(maximum - minimum + 1)


@dataclass(frozen=True, slots=True)
class BootstrapInvite:
    nickname: str
    prefix: str
    account: str | None
    expires_at_ns: int
    reset_handle: str | None = None


@dataclass(slots=True)
class PartylineSession:
    stream: socket.socket
    peer_ip: str
    transport: str
    connected_at_ns: int
    auth_deadline_ns: int
    irc_nickname: str | None = None
    input_buffer: bytearray = field(default_factory=bytearray)
    output_buffer: bytearray = field(default_factory=bytearray)
    telnet_pending: bytearray = field(default_factory=bytearray)
    stage: str = "handle"
    pending_handle: str | None = None
    pending_password: str | None = None
    bootstrap_invite: BootstrapInvite | None = None
    handle: str | None = None
    authenticated_at_ns: int | None = None
    failures: int = 0


@dataclass(slots=True)
class PendingDCCOffer:
    listener: socket.socket
    nickname: str
    deadline_ns: int
    token: str | None = None


@dataclass(slots=True)
class PendingDCCConnect:
    stream: socket.socket
    nickname: str
    peer_ip: str
    deadline_ns: int


@dataclass(frozen=True, slots=True)
class FlightLaunchResult:
    status: str
    channel: str | None = None
    flight_id: int | None = None
    health: int | None = None

    @property
    def started(self) -> bool:
        return self.status == "started"


class PartylineController:
    """Own the local listener, DCC handshakes, sessions and admin commands."""

    def __init__(
        self,
        configuration: PartylineConfiguration,
        runtime: RuntimeOrchestrator,
        state_directory: Path,
        network_status: NetworkStatusProvider,
        *,
        observer: PartylineObserver | None = None,
        language: str = "fr",
        flight_lifetime_ns: int = 300 * 1_000_000_000,
        anti_cheat: bool = False,
        integer_source: IntegerSource | None = None,
        ranking_url: str | None = None,
        statistics_excluded_nicknames: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(configuration, PartylineConfiguration):
            raise ValueError("partyline requires validated configuration")
        if not all(
            hasattr(runtime, attribute)
            for attribute in ("dispatch", "emit_priority", "persistence", "state")
        ):
            raise ValueError("partyline requires the game runtime")
        if not callable(network_status):
            raise ValueError("partyline requires a network status provider")
        if observer is not None and not callable(observer):
            raise ValueError("partyline observer must be callable or none")
        if type(flight_lifetime_ns) is not int or flight_lifetime_ns <= 0:
            raise ValueError("partyline flight lifetime must be positive")
        if type(anti_cheat) is not bool:
            raise ValueError("partyline anti-cheat flag must be a truth value")
        selected_integers = (
            _system_integer if integer_source is None else integer_source
        )
        if not callable(selected_integers):
            raise ValueError("partyline integer source must be callable")
        self.language = validate_language(language)
        self.configuration = configuration
        self.runtime = runtime
        self.user_store = PartylineUserStore(
            Path(state_directory) / "partyline-users.json"
        )
        self._network_status = network_status
        self._observer = observer
        self._flight_lifetime_ns = flight_lifetime_ns
        self._integer_source = selected_integers
        self._ranking_url = ranking_url
        self._statistics_excluded_nicknames = statistics_excluded_nicknames
        self._flight_appearance_source = (
            RandomizedFlightAppearanceSource(selected_integers)
            if anti_cheat
            else None
        )
        self._listener: socket.socket | None = None
        self._sessions: dict[int, PartylineSession] = {}
        self._offers: dict[str, PendingDCCOffer] = {}
        self._connects: dict[int, PendingDCCConnect] = {}
        self._bootstrap: dict[str, BootstrapInvite] = {}
        self._ip_failures: dict[str, list[int]] = {}
        self._started_at_ns: int | None = None
        self._last_now_ns: int | None = None
        self._next_spontaneous_launch_ns: int | None = None

    @property
    def enabled(self) -> bool:
        return self.configuration.enabled

    @property
    def bound_port(self) -> int | None:
        if self._listener is None:
            return None
        return int(self._listener.getsockname()[1])

    @property
    def authenticated_count(self) -> int:
        return sum(session.handle is not None for session in self._sessions.values())

    @localized_method
    def start(self, now_ns: int) -> None:
        self._accept_now(now_ns)
        if not self.enabled:
            return
        if self._listener is not None:
            raise RuntimeError("partyline listener can only start once")
        self.user_store.users()
        listener = _listening_socket(
            self.configuration.bind_host,
            self.configuration.port,
        )
        self._listener = listener
        self._started_at_ns = now_ns
        if self.configuration.spontaneous_launch_enabled:
            self._schedule_next_spontaneous_launch(now_ns)
        self._emit(
            "event=listener-started "
            f"bind={self.configuration.bind_host} port={self.bound_port}"
        )

    @localized_method
    def close(self, reason: str = "shutdown") -> None:
        had_resources = bool(
            self._listener is not None
            or self._sessions
            or self._offers
            or self._connects
        )
        for session in tuple(self._sessions.values()):
            self._close_session(session, reason, broadcast=False)
        for offer in tuple(self._offers.values()):
            _close_socket(offer.listener)
        self._offers.clear()
        for pending in tuple(self._connects.values()):
            _close_socket(pending.stream)
        self._connects.clear()
        if self._listener is not None:
            _close_socket(self._listener)
            self._listener = None
        self._next_spontaneous_launch_ns = None
        if self.enabled and had_resources:
            self._emit(f"event=listener-stopped reason={_safe_atom(reason)}")

    @localized_method
    def poll(self, now_ns: int) -> bool:
        """Advance every non-blocking socket once; return whether work occurred."""

        self._accept_now(now_ns)
        if not self.enabled or self._listener is None:
            return False
        changed = self._expire(now_ns)
        changed = self._accept_primary(now_ns) or changed
        changed = self._accept_offers(now_ns) or changed
        changed = self._finish_connects(now_ns) or changed
        changed = self._poll_sessions(now_ns) or changed
        changed = self._poll_spontaneous_launch(now_ns) or changed
        return changed

    @localized_method
    def handle_irc(
        self,
        now_ns: int,
        message: IRCMessage,
        bot_nickname: str,
    ) -> bool:
        """Consume owner IRC administration, bootstrap and DCC requests."""

        self._accept_now(now_ns)
        if not self.enabled or not isinstance(message, IRCMessage):
            return False
        if message.command != "PRIVMSG" or message.nickname is None or len(message.params) != 2:
            return False
        target, text = message.params
        if self._is_joined_channel(target) and self._is_weapon_command(
            text,
            private=False,
        ):
            self._handle_irc_weapon_command(now_ns, message, private=False)
            return True
        if self._is_joined_channel(target) and self._is_admin_channel_item_command(text):
            self._handle_irc_admin_channel_item(now_ns, message)
            return True
        if self._is_joined_channel(target) and self._is_duckplanning_command(
            text,
            private=False,
        ):
            self._handle_irc_duckplanning(now_ns, message, private=False)
            return True
        if same_irc_name(target, bot_nickname) and self._is_weapon_command(
            text,
            private=True,
        ):
            self._handle_irc_weapon_command(now_ns, message, private=True)
            return True
        if same_irc_name(target, bot_nickname) and self._is_duckplanning_command(
            text,
            private=True,
        ):
            self._handle_irc_duckplanning(now_ns, message, private=True)
            return True
        if not same_irc_name(target, bot_nickname):
            return False
        nickname = message.nickname
        arguments = text.split()
        if arguments and arguments[0].casefold() == "ducklaunch":
            self._handle_irc_ducklaunch(now_ns, message, arguments)
            return True
        if text.casefold() == "hello":
            self._handle_hello(now_ns, message)
            return True
        if text.casefold() == "reset":
            self._handle_reset(now_ns, message)
            return True
        if text.casefold().startswith("pass "):
            self._notice(
                nickname,
                tr('Mot de passe refusé sur IRC : choisissez-le dans la partyline.'),
            )
            return True
        payload = _ctcp_payload(text)
        if payload is None:
            return False
        if payload.casefold() == "chat":
            self._offer_dcc(now_ns, nickname, None)
            return True
        request = parse_dcc_chat(payload)
        if request is None:
            return False
        address, port, token = request
        if address is None and port == 0 and token is not None:
            self._offer_dcc(now_ns, nickname, token)
            return True
        assert address is not None
        self._connect_dcc(now_ns, nickname, address, port)
        return True

    def _is_joined_channel(self, target: str) -> bool:
        _, _, _, joined_channels = self._network_status()
        return any(same_irc_name(target, channel) for channel in joined_channels)

    @staticmethod
    def _is_weapon_command(text: str, *, private: bool) -> bool:
        arguments = text.split()
        if not arguments:
            return False
        accepted = ("rearm", "unarm", "!rearm", "!unarm") if private else (
            "!rearm",
            "!unarm",
        )
        return arguments[0].casefold() in accepted

    def _handle_irc_weapon_command(
        self,
        now_ns: int,
        message: IRCMessage,
        *,
        private: bool,
    ) -> None:
        assert message.nickname is not None
        target, text = message.params
        owner = self.user_store.owner_for_irc(
            message.nickname,
            prefix=message.prefix,
            account=message.tag("account"),
        )
        arguments = text.split()
        command = arguments[0].casefold()
        normalized_command = command.removeprefix("!")
        if owner is None:
            self._emit(
                "event=irc-admin-refused "
                f"nick={_safe_atom(message.nickname)} command={_safe_atom(command)}"
            )
            return
        operation: str | None = None
        nickname: str | None = None
        if normalized_command == "rearm" and len(arguments) == 2:
            operation, nickname = "rearm", arguments[1]
        elif normalized_command == "unarm" and len(arguments) == 2:
            operation, nickname = "unarm", arguments[1]
        elif (
            normalized_command == "unarm"
            and len(arguments) == 3
            and arguments[1].casefold() == "-permanent"
        ):
            operation, nickname = "unarm_permanent", arguments[2]
        response_target = message.nickname if private else target
        usage = (
            "rearm nick | unarm [-permanent] nick"
            if private
            else "!rearm nick | !unarm [-permanent] nick"
        )

        def render_reply(lines: tuple[str, ...]) -> tuple[bytes, ...]:
            return (
                render_wire_notice(response_target, lines)
                if private
                else render_wire_response(response_target, lines)
            )

        if operation is None or nickname is None:
            self.runtime.emit_priority(render_reply((tr('{0} > Usage : {1}', owner.handle, usage),)))
            return
        before_player = self.runtime.state.player(rfc1459_casefold(nickname))
        if before_player is None:
            self.runtime.emit_priority(
                render_reply((tr('{0} > Joueur inconnu : {1}.', owner.handle, nickname),))
            )
            return
        try:
            event = ReplayEvent.admin_weapon_control(
                now_ns,
                owner.handle,
                before_player.nickname,
                operation=operation,
            )
            apply_weapon_control(
                self.runtime.state,
                before_player.nickname,
                now_ns,
                operation=operation,
            )
        except (PlayerAdministrationError, ValueError):
            self.runtime.emit_priority(
                render_reply((tr("{0} > Modification de l'arme refusée.", owner.handle),))
            )
            return
        messages = {
            "rearm": tr('{0} > Arme de {1} restituée.', owner.handle, before_player.nickname),
            "unarm": (
                tr("{0} > Arme de {1} confisquée jusqu'à minuit, heure de Paris.", owner.handle, before_player.nickname)
            ),
            "unarm_permanent": (
                tr('{0} > Arme de {1} confisquée de façon permanente.', owner.handle, before_player.nickname)
            ),
        }
        result = self.runtime.dispatch(
            event,
            lambda transition: render_reply((messages[operation],)),
        )
        if result.status.value == "backpressured" or result.transition is None:
            self.runtime.emit_priority(
                render_reply((tr('{0} > Modification refusée : persistance occupée.', owner.handle),))
            )
            return
        self._broadcast(
            f"*** {owner.handle} used {command} on {before_player.nickname} "
            f"from IRC ({'private' if private else target}, {operation}). ***"
        )
        self._emit(
            "event=irc-weapon-control "
            f"actor={_safe_atom(owner.handle)} target={_safe_atom(before_player.nickname)} "
            f"scope={'private' if private else _safe_atom(target)} operation={operation}"
        )

    @staticmethod
    def _is_admin_channel_item_command(text: str) -> bool:
        arguments = text.split()
        return bool(arguments) and arguments[0].casefold() in ("!appeau", tr('!pain'))

    @staticmethod
    def _is_duckplanning_command(text: str, *, private: bool) -> bool:
        arguments = text.split()
        if not arguments:
            return False
        accepted = ("duckplanning", "!duckplanning") if private else ("!duckplanning",)
        return arguments[0].casefold() in accepted

    def _handle_irc_duckplanning(
        self,
        now_ns: int,
        message: IRCMessage,
        *,
        private: bool,
    ) -> None:
        assert message.nickname is not None
        _, text = message.params
        arguments = text.split()
        command = arguments[0].casefold()
        owner = self.user_store.owner_for_irc(
            message.nickname,
            prefix=message.prefix,
            account=message.tag("account"),
        )
        if owner is None:
            self._emit(
                "event=irc-admin-refused "
                f"nick={_safe_atom(message.nickname)} command={_safe_atom(command)}"
            )
            return
        if len(arguments) != 1:
            usage = "duckplanning" if private else "!duckplanning"
            lines = (tr('{0} > Usage : {1}', owner.handle, usage),)
        else:
            lines = self._duckplanning_lines(now_ns)
        self.runtime.emit_priority(
            tuple(render_notice_bounded(message.nickname, line) for line in lines)
        )
        self._emit(
            "event=irc-duckplanning "
            f"actor={_safe_atom(owner.handle)} scope={'private' if private else 'channel'}"
        )

    def _handle_irc_admin_channel_item(
        self,
        now_ns: int,
        message: IRCMessage,
    ) -> None:
        assert message.nickname is not None
        channel, text = message.params
        owner = self.user_store.owner_for_irc(
            message.nickname,
            prefix=message.prefix,
            account=message.tag("account"),
        )
        arguments = text.split()
        command = arguments[0].casefold()
        if owner is None:
            self._emit(
                "event=irc-admin-refused "
                f"nick={_safe_atom(message.nickname)} command={_safe_atom(command)}"
            )
            return
        if len(arguments) != 1:
            self.runtime.emit_priority(
                render_wire_notice(
                    message.nickname,
                    (tr('{0} > Usage : {1}', owner.handle, command),),
                )
            )
            return
        item_id = 20 if command == "!appeau" else 21
        scheduled_for_ns = (
            self._integer_source(now_ns + 1, now_ns + 10 * MINUTE_NS)
            if item_id == 20
            else None
        )
        try:
            event = ReplayEvent.admin_channel_item(
                now_ns,
                owner.handle,
                item_id,
                scheduled_for_ns=scheduled_for_ns,
            )
            apply_admin_channel_item(
                self.runtime.state,
                owner.handle,
                item_id,
                now_ns,
                scheduled_for_ns=scheduled_for_ns,
            )
        except (PlayerAdministrationError, ValueError):
            self.runtime.emit_priority(
                render_wire_notice(
                    message.nickname,
                    (tr('{0} > Action administrative refusée.', owner.handle),),
                )
            )
            return

        def render_reply(transition: Transition) -> tuple[bytes, ...]:
            if item_id == 20:
                message_text = (
                    tr('{0} > Tu utilises un appeau. Échéance prévue : {1} (après le vol actif si nécessaire). Le prochain envol quotidien ne change pas.', owner.handle, _paris(scheduled_for_ns))
                )
            else:
                count = sum(
                    1
                    for effect in transition.state.effects
                    if effect.item_id == 21
                    and effect.key == "channel_bread"
                    and effect.owner_key is None
                )
                bread = tr('morceau') if count == 1 else tr('morceaux')
                message_text = (
                    tr('{0} > Tu déposes un morceau de pain sur {1}. Il y a actuellement {2} {3} de pain. ', owner.handle, channel, count, bread)
                    + (tr('Actif 1h, conservé à chaque envol. Attraction renforcée ; départ des nouveaux canards retardé de {0}s.', 20 * count)
                       if transition.state.bread_plan_effect_ids is not None else
                       tr('Disponible 1h ; un morceau consommé par envol s’il est encore valide. Le prochain envol quotidien ne change pas.'))
                )
            return render_wire_notice(message.nickname, (message_text,))

        result = self.runtime.dispatch(event, render_reply)
        if result.status.value == "backpressured" or result.transition is None:
            self.runtime.emit_priority(
                render_wire_notice(
                    message.nickname,
                    (tr('{0} > Action refusée : persistance occupée.', owner.handle),),
                )
            )
            return
        self._broadcast(
            f"*** {owner.handle} used {command} on {channel} from IRC. ***"
        )
        self._emit(
            "event=irc-admin-channel-item "
            f"actor={_safe_atom(owner.handle)} channel={_safe_atom(channel)} "
            f"item={item_id}"
        )

    def _handle_irc_ducklaunch(
        self,
        now_ns: int,
        message: IRCMessage,
        arguments: list[str],
    ) -> None:
        assert message.nickname is not None
        owner = self.user_store.owner_for_irc(
            message.nickname,
            prefix=message.prefix,
            account=message.tag("account"),
        )
        if owner is None:
            self._emit(
                "event=irc-admin-refused "
                f"nick={_safe_atom(message.nickname)} command=ducklaunch"
            )
            return
        if len(arguments) not in (2, 3) or (
            len(arguments) == 3 and arguments[2] != "1"
        ):
            self._notice(
                message.nickname,
                tr('Usage : /msg Coin ducklaunch #canal [1] — 1 lance un canard doré.'),
            )
            return
        kind = FlightKind.GOLDEN if len(arguments) == 3 else FlightKind.STANDARD
        requested_channel = arguments[1]
        result = self._launch_channel_flight(
            now_ns,
            kind,
            requested_channel,
            actor=owner.handle,
            source="irc-owner",
        )
        if result.started:
            assert result.channel is not None and result.flight_id is not None
            label = tr('Canard doré') if kind is FlightKind.GOLDEN else tr("Canard")
            suffix = tr(' (vie : {0})', result.health) if kind is FlightKind.GOLDEN else ""
            self._notice(
                message.nickname,
                tr('{0} #{1} lancé sur {2}{3}.', label, result.flight_id, result.channel, suffix),
            )
            return
        self._notice(
            message.nickname,
            self._irc_launch_rejection(result, requested_channel),
        )

    @localized_method
    def observe_runtime(self, message: str) -> None:
        """Broadcast privacy-safe runner facts to authenticated operators."""

        if type(message) is not str or not message:
            return
        if message.startswith("DUCKPLANNING "):
            now_ns = max(self.runtime.state.now_ns, self._last_now_ns or 0)
            self._broadcast("*** Coin duckplanning changed. ***")
            for line in self._duckplanning_lines(now_ns):
                self._broadcast(f"*** Coin {line} ***")
            return
        if message.startswith(
            (
                "STATE ",
                "APPLICATION ",
                "SCHEDULE ",
                "FLIGHT ",
                "NETWORK ",
                "RANKING ",
                "PUBLICATION ",
            )
        ):
            self._broadcast(f"*** Coin {message} ***")

    def _handle_hello(self, now_ns: int, message: IRCMessage) -> None:
        assert message.nickname is not None
        nickname = message.nickname
        if self.user_store.has_users():
            self._notice(
                nickname,
                tr('Partyline déjà initialisée. Utilisez /msg Coin reset si le mot de passe doit être remplacé.'),
            )
            return
        prefix = message.prefix or nickname
        account = message.tag("account")
        if account in (None, "*"):
            account = None
        if not self._bootstrap_allowed(prefix, account):
            self._notice(nickname, tr('Initialisation partyline refusée pour cette identité IRC.'))
            self._emit(f"event=bootstrap-refused nick={_safe_atom(nickname)}")
            return
        invite = BootstrapInvite(
            nickname,
            prefix,
            account,
            now_ns + BOOTSTRAP_TIMEOUT_NS,
        )
        self._bootstrap[rfc1459_casefold(nickname)] = invite
        self._notice(
            nickname,
            tr('Hello ! Bootstrap owner armé pour 10 minutes ; aucun mot de passe ne doit être envoyé sur IRC.'),
        )
        port = self.bound_port
        self._notice(
            nickname,
            tr('Ouvrez /ctcp Coin CHAT ou /dcc chat Coin')
            + (tr(' ; en local : telnet localhost ') + str(port) if port else "")
            + ".",
        )
        self._emit(f"event=bootstrap-armed nick={_safe_atom(nickname)}")

    def _handle_reset(self, now_ns: int, message: IRCMessage) -> None:
        """Arm one short-lived recovery for the configured owner identity."""

        assert message.nickname is not None
        nickname = message.nickname
        users = self.user_store.users()
        if not users:
            self._handle_hello(now_ns, message)
            return
        prefix = message.prefix or nickname
        account = message.tag("account")
        if account in (None, "*"):
            account = None
        owner = self.user_store.owner_for_irc(
            nickname,
            prefix=message.prefix,
            account=account,
        )
        if (
            owner is None
            and len(users) == 1
            and self._bootstrap_allowed(prefix, account)
        ):
            owner = users[0]
        if owner is None:
            self._notice(
                nickname,
                tr('Réinitialisation partyline refusée pour cette identité IRC.'),
            )
            self._emit(f"event=password-reset-refused nick={_safe_atom(nickname)}")
            return
        invite = BootstrapInvite(
            nickname,
            prefix,
            account,
            now_ns + BOOTSTRAP_TIMEOUT_NS,
            reset_handle=owner.handle,
        )
        self._bootstrap[rfc1459_casefold(nickname)] = invite
        self._notice(
            nickname,
            tr('Réinitialisation armée pour 10 minutes ; aucun mot de passe ne doit être envoyé sur IRC.'),
        )
        port = self.bound_port
        self._notice(
            nickname,
            tr('Ouvrez /ctcp Coin CHAT ou /dcc chat Coin')
            + (tr(' ; en local : telnet localhost ') + str(port) if port else "")
            + ".",
        )
        self._emit(
            "event=password-reset-armed "
            f"nick={_safe_atom(nickname)} handle={_safe_atom(owner.handle)}"
        )

    def _bootstrap_allowed(self, prefix: str, account: str | None) -> bool:
        if account is not None and any(
            account.casefold() == allowed.casefold()
            for allowed in self.configuration.bootstrap_accounts
        ):
            return True
        folded_prefix = rfc1459_casefold(prefix)
        return any(
            _irc_mask_matches(folded_prefix, rfc1459_casefold(mask))
            for mask in self.configuration.bootstrap_masks
        )

    def _offer_dcc(self, now_ns: int, nickname: str, token: str | None) -> None:
        public_ip = self.configuration.dcc_public_ip
        key = rfc1459_casefold(nickname)
        if public_ip is None:
            self._notice(nickname, tr("Offre DCC indisponible : dcc_public_ip n'est pas configurée."))
            return
        if key in self._offers:
            self._notice(nickname, tr('Une offre DCC CHAT est déjà en attente.'))
            return
        if self._pending_dcc_count() >= MAX_PENDING_DCC:
            self._notice(nickname, tr("Trop d'offres DCC CHAT sont déjà en attente."))
            return
        if token is not None and not _valid_dcc_token(token):
            self._notice(nickname, tr('Jeton DCC passif invalide.'))
            return
        try:
            listener = self._dcc_listener()
        except OSError:
            self._notice(nickname, tr("Impossible d'ouvrir l'écoute DCC CHAT."))
            self._emit(f"event=dcc-listen-failed nick={_safe_atom(nickname)}")
            return
        port = int(listener.getsockname()[1])
        self._offers[key] = PendingDCCOffer(
            listener,
            nickname,
            now_ns + DCC_TIMEOUT_NS,
            token,
        )
        ip_integer = int(ipaddress.IPv4Address(public_ip))
        suffix = "" if token is None else f" {token}"
        self.runtime.emit_priority(
            (render_privmsg(nickname, f"\x01DCC CHAT chat {ip_integer} {port}{suffix}\x01"),)
        )
        self._emit(f"event=dcc-offered nick={_safe_atom(nickname)} port={port}")

    def _dcc_listener(self) -> socket.socket:
        first = self.configuration.dcc_port_min
        last = self.configuration.dcc_port_max
        ports = (0,) if (first, last) == (0, 0) else range(first, last + 1)
        last_error: OSError | None = None
        for port in ports:
            try:
                return _listening_socket("0.0.0.0", port, backlog=1)
            except OSError as error:
                last_error = error
        assert last_error is not None
        raise last_error

    def _connect_dcc(
        self,
        now_ns: int,
        nickname: str,
        address: ipaddress.IPv4Address,
        port: int,
    ) -> None:
        if self._pending_dcc_count() >= MAX_PENDING_DCC or any(
            same_irc_name(pending.nickname, nickname)
            for pending in self._connects.values()
        ):
            self._notice(nickname, tr('Trop de connexions DCC CHAT sont déjà en attente.'))
            return
        stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stream.setblocking(False)
        result = stream.connect_ex((str(address), port))
        if result == 0:
            self._new_session(stream, str(address), "dcc-active", now_ns, nickname)
            return
        if result not in (
            errno.EINPROGRESS,
            errno.EWOULDBLOCK,
            errno.EALREADY,
            errno.EINTR,
        ):
            _close_socket(stream)
            self._notice(nickname, tr('Connexion DCC CHAT impossible.'))
            return
        self._connects[stream.fileno()] = PendingDCCConnect(
            stream,
            nickname,
            str(address),
            now_ns + DCC_TIMEOUT_NS,
        )
        self._emit(f"event=dcc-connecting nick={_safe_atom(nickname)}")

    def _accept_primary(self, now_ns: int) -> bool:
        assert self._listener is not None
        changed = False
        while len(self._sessions) < MAX_SESSIONS:
            try:
                stream, address = self._listener.accept()
            except BlockingIOError:
                break
            stream.setblocking(False)
            peer_ip = str(address[0])
            self._new_session(stream, peer_ip, "telnet", now_ns, None)
            changed = True
        return changed

    def _accept_offers(self, now_ns: int) -> bool:
        changed = False
        for key, offer in tuple(self._offers.items()):
            try:
                stream, address = offer.listener.accept()
            except BlockingIOError:
                continue
            except OSError:
                _close_socket(offer.listener)
                self._offers.pop(key, None)
                continue
            _close_socket(offer.listener)
            self._offers.pop(key, None)
            stream.setblocking(False)
            self._new_session(
                stream,
                str(address[0]),
                "dcc-offer",
                now_ns,
                offer.nickname,
            )
            changed = True
        return changed

    def _finish_connects(self, now_ns: int) -> bool:
        if not self._connects:
            return False
        streams = [pending.stream for pending in self._connects.values()]
        try:
            _, writable, exceptional = select.select([], streams, streams, 0)
        except OSError:
            writable, exceptional = [], streams
        ready = set(writable) | set(exceptional)
        changed = False
        for descriptor, pending in tuple(self._connects.items()):
            if pending.stream not in ready:
                continue
            self._connects.pop(descriptor, None)
            try:
                error = pending.stream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            except OSError:
                error = errno.EIO
            if error:
                _close_socket(pending.stream)
                self._notice(pending.nickname, tr('Connexion DCC CHAT impossible.'))
            else:
                self._new_session(
                    pending.stream,
                    pending.peer_ip,
                    "dcc-active",
                    now_ns,
                    pending.nickname,
                )
            changed = True
        return changed

    def _new_session(
        self,
        stream: socket.socket,
        peer_ip: str,
        transport: str,
        now_ns: int,
        irc_nickname: str | None,
    ) -> None:
        if len(self._sessions) >= MAX_SESSIONS:
            try:
                stream.send(b"Partyline busy.\r\n")
            except OSError:
                pass
            _close_socket(stream)
            return
        session = PartylineSession(
            stream,
            peer_ip,
            transport,
            now_ns,
            now_ns + AUTH_TIMEOUT_NS,
            irc_nickname=irc_nickname,
        )
        self._sessions[stream.fileno()] = session
        self._queue(session, b"Coin Partyline\r\n\r\nHandle: ")
        self._emit(
            f"event=session-open transport={transport} peer={_safe_atom(peer_ip)}"
        )

    def _poll_sessions(self, now_ns: int) -> bool:
        if not self._sessions:
            return False
        streams = [session.stream for session in self._sessions.values()]
        write_streams = [
            session.stream
            for session in self._sessions.values()
            if session.output_buffer
        ]
        try:
            readable, writable, exceptional = select.select(
                streams,
                write_streams,
                streams,
                0,
            )
        except OSError:
            readable, writable, exceptional = [], [], streams
        changed = False
        for stream in exceptional:
            session = self._sessions.get(stream.fileno())
            if session is not None:
                self._close_session(session, "socket-error")
                changed = True
        for stream in readable:
            session = self._sessions.get(stream.fileno())
            if session is None:
                continue
            changed = self._read_session(session, now_ns) or changed
        for stream in writable:
            session = self._sessions.get(stream.fileno())
            if session is None:
                continue
            changed = self._flush_session(session) or changed
        return changed

    def _read_session(self, session: PartylineSession, now_ns: int) -> bool:
        try:
            chunk = session.stream.recv(4_096)
        except BlockingIOError:
            return False
        except OSError:
            self._close_session(session, "read-error")
            return True
        if not chunk:
            self._close_session(session, "disconnected")
            return True
        session.input_buffer.extend(_strip_telnet_iac(chunk, session.telnet_pending))
        if len(session.telnet_pending) > MAX_LINE_BYTES:
            self._close_session(session, "oversized-telnet-negotiation")
            return True
        if len(session.input_buffer) > MAX_LINE_BYTES and b"\n" not in session.input_buffer:
            self._close_session(session, "oversized-input")
            return True
        while b"\n" in session.input_buffer:
            raw, _, retained = session.input_buffer.partition(b"\n")
            session.input_buffer[:] = retained
            raw = raw.rstrip(b"\r")
            if len(raw) > MAX_LINE_BYTES:
                self._close_session(session, "oversized-input")
                return True
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._queue_line(session, "Invalid UTF-8 input.")
                continue
            try:
                self._handle_session_line(session, line, now_ns)
            except Exception as error:
                self._emit(
                    "event=command-failed "
                    f"category={_safe_atom(type(error).__name__)}"
                )
                self._queue_line(session, "Command failed safely; inspect status before retrying.")
            if session.stream.fileno() not in self._sessions:
                break
        return True

    def _handle_session_line(
        self,
        session: PartylineSession,
        line: str,
        now_ns: int,
    ) -> None:
        if session.stage == "handle":
            self._handle_login_name(session, line.strip(), now_ns)
        elif session.stage == "password":
            self._handle_login_password(session, line, now_ns)
        elif session.stage == "new-password":
            self._handle_new_password(session, line)
        elif session.stage == "confirm-password":
            self._handle_password_confirmation(session, line, now_ns)
        elif session.stage == "reset-password":
            self._handle_reset_password(session, line)
        elif session.stage == "confirm-reset-password":
            self._handle_reset_password_confirmation(session, line, now_ns)
        elif session.stage == "change-password":
            self._handle_changed_password(session, line)
        elif session.stage == "confirm-changed-password":
            self._handle_changed_password_confirmation(session, line)
        elif session.stage == "authenticated":
            self._handle_authenticated_line(session, line.strip(), now_ns)

    def _handle_login_name(
        self,
        session: PartylineSession,
        handle: str,
        now_ns: int,
    ) -> None:
        if not handle or len(handle) > 32 or any(
            character in handle for character in (" ", "\x00", "\r", "\n")
        ):
            self._auth_failure(session, now_ns, "Unknown handle.")
            return
        invite = self._invite_for_session(session, handle, now_ns)
        if not self.user_store.has_users():
            if invite is None:
                self._auth_failure(
                    session,
                    now_ns,
                    "Initialization requires /msg Coin hello from an allowed identity.",
                )
                return
            session.pending_handle = handle
            session.bootstrap_invite = invite
            session.stage = "new-password"
            self._echo_off(session)
            self._queue(session, b"Choose a new password (12-128 characters): ")
            return
        if invite is not None and invite.reset_handle is not None:
            session.pending_handle = invite.reset_handle
            session.bootstrap_invite = invite
            session.stage = "reset-password"
            self._echo_off(session)
            self._queue(
                session,
                b"Choose a replacement password (12-128 characters): ",
            )
            return
        user = self.user_store.find(handle)
        session.pending_handle = handle if user is None else user.handle
        session.stage = "password"
        self._echo_off(session)
        self._queue(session, b"Password: ")

    def _handle_login_password(
        self,
        session: PartylineSession,
        password: str,
        now_ns: int,
    ) -> None:
        handle = session.pending_handle or ""
        user = self.user_store.verify(handle, password)
        self._echo_on(session)
        if user is None:
            session.pending_handle = None
            session.stage = "handle"
            self._auth_failure(session, now_ns, "Authentication failed.\r\n\r\nHandle: ")
            return
        self._authenticate(session, user.handle, now_ns)

    def _handle_new_password(self, session: PartylineSession, password: str) -> None:
        if (
            not 12 <= len(password) <= 128
            or any(character in password for character in ("\x00", "\r", "\n"))
        ):
            self._queue(session, b"Password rejected; use 12-128 characters.\r\nNew password: ")
            return
        session.pending_password = password
        session.stage = "confirm-password"
        self._queue(session, b"Confirm password: ")

    def _handle_password_confirmation(
        self,
        session: PartylineSession,
        password: str,
        now_ns: int,
    ) -> None:
        if session.pending_password != password:
            session.pending_password = None
            session.stage = "new-password"
            self._queue(session, b"Passwords differ.\r\nNew password: ")
            return
        invite = session.bootstrap_invite
        handle = session.pending_handle
        if invite is None or handle is None:
            self._close_session(session, "bootstrap-state-error")
            return
        try:
            user = self.user_store.create_first_owner(
                handle,
                password,
                now_ns,
                irc_account=invite.account,
                irc_mask=invite.prefix,
            )
        except PartylineCredentialError:
            self._echo_on(session)
            self._close_session(session, "bootstrap-write-error")
            return
        session.pending_password = None
        self._bootstrap.pop(rfc1459_casefold(invite.nickname), None)
        self._echo_on(session)
        self._authenticate(session, user.handle, now_ns, created=True)

    def _handle_reset_password(
        self,
        session: PartylineSession,
        password: str,
    ) -> None:
        if (
            not 12 <= len(password) <= 128
            or any(character in password for character in ("\x00", "\r", "\n"))
        ):
            self._queue(
                session,
                b"Password rejected; use 12-128 characters.\r\nReplacement password: ",
            )
            return
        session.pending_password = password
        session.stage = "confirm-reset-password"
        self._queue(session, b"Confirm replacement password: ")

    def _handle_reset_password_confirmation(
        self,
        session: PartylineSession,
        password: str,
        now_ns: int,
    ) -> None:
        if session.pending_password != password:
            session.pending_password = None
            session.stage = "reset-password"
            self._queue(session, b"Passwords differ.\r\nReplacement password: ")
            return
        invite = session.bootstrap_invite
        handle = session.pending_handle
        if (
            invite is None
            or invite.reset_handle is None
            or handle is None
            or not same_irc_name(handle, invite.reset_handle)
        ):
            self._echo_on(session)
            self._close_session(session, "password-reset-state-error")
            return
        try:
            user = self.user_store.change_password(handle, password)
        except PartylineCredentialError:
            self._echo_on(session)
            self._close_session(session, "password-reset-write-error")
            return
        session.pending_password = None
        self._bootstrap.pop(rfc1459_casefold(invite.nickname), None)
        for active in tuple(self._sessions.values()):
            if (
                active is not session
                and active.handle is not None
                and same_irc_name(active.handle, user.handle)
            ):
                self._queue_line(
                    active,
                    "Credential reset; reconnect with the new password.",
                )
                self._flush_session(active)
                self._close_session(active, "credential-reset", broadcast=False)
        self._echo_on(session)
        self._queue_line(
            session,
            "Password reset complete; previous credential revoked.",
        )
        self._authenticate(session, user.handle, now_ns)
        self._emit(f"event=password-reset handle={_safe_atom(user.handle)}")

    def _handle_changed_password(
        self,
        session: PartylineSession,
        password: str,
    ) -> None:
        if (
            not 12 <= len(password) <= 128
            or any(character in password for character in ("\x00", "\r", "\n"))
        ):
            self._queue(
                session,
                b"Password rejected; use 12-128 characters.\r\nNew password: ",
            )
            return
        session.pending_password = password
        session.stage = "confirm-changed-password"
        self._queue(session, b"Confirm new password: ")

    def _handle_changed_password_confirmation(
        self,
        session: PartylineSession,
        password: str,
    ) -> None:
        if session.pending_password != password:
            session.pending_password = None
            session.stage = "change-password"
            self._queue(session, b"Passwords differ.\r\nNew password: ")
            return
        try:
            self.user_store.change_password(
                session.handle or "",
                password,
            )
        except PartylineCredentialError:
            session.pending_password = None
            session.stage = "authenticated"
            self._echo_on(session)
            self._queue_line(session, "Password change failed safely.")
            return
        session.pending_password = None
        session.stage = "authenticated"
        self._echo_on(session)
        self._queue_line(session, "Password changed; previous credential revoked.")
        self._emit(
            f"event=password-changed handle={_safe_atom(session.handle or 'unknown')}"
        )

    def _authenticate(
        self,
        session: PartylineSession,
        handle: str,
        now_ns: int,
        *,
        created: bool = False,
    ) -> None:
        session.handle = handle
        session.authenticated_at_ns = now_ns
        session.stage = "authenticated"
        session.pending_handle = None
        session.bootstrap_invite = None
        session.failures = 0
        self._ip_failures.pop(session.peer_ip, None)
        self._queue_line(
            session,
            "",
        )
        self._queue_line(
            session,
            ("Owner created. " if created else "")
            + f"Hey {handle}! Welcome to the Coin partyline.",
        )
        for line in self._status_lines(now_ns):
            self._queue_line(session, line)
        self._queue_line(session, "Type .help for commands; ordinary text is broadcast.")
        self._broadcast(f"*** {handle} joined the partyline. ***", exclude=session)
        self._emit(
            f"event=auth-success handle={_safe_atom(handle)} transport={session.transport}"
        )

    def _auth_failure(
        self,
        session: PartylineSession,
        now_ns: int,
        response: str,
    ) -> None:
        session.failures += 1
        failures = self._ip_failures.setdefault(session.peer_ip, [])
        failures[:] = [value for value in failures if now_ns - value <= IP_FAILURE_WINDOW_NS]
        failures.append(now_ns)
        self._emit(
            f"event=auth-failure peer={_safe_atom(session.peer_ip)} count={session.failures}"
        )
        if session.failures >= MAX_SESSION_FAILURES or len(failures) >= MAX_IP_FAILURES:
            self._queue_line(session, "Too many authentication failures.")
            self._flush_session(session)
            self._close_session(session, "auth-throttled")
            return
        self._queue(session, response.encode("utf-8"))

    def _invite_for_session(
        self,
        session: PartylineSession,
        handle: str,
        now_ns: int,
    ) -> BootstrapInvite | None:
        expected = rfc1459_casefold(session.irc_nickname or handle)
        invite = self._bootstrap.get(expected)
        if invite is None and session.irc_nickname is None:
            candidates = tuple(
                candidate
                for candidate in self._bootstrap.values()
                if candidate.reset_handle is not None
                and same_irc_name(candidate.reset_handle, handle)
            )
            invite = candidates[0] if len(candidates) == 1 else None
        if invite is None or invite.expires_at_ns <= now_ns:
            return None
        expected_handle = invite.reset_handle or invite.nickname
        if not same_irc_name(handle, expected_handle):
            return None
        if session.irc_nickname is not None and not same_irc_name(
            session.irc_nickname,
            invite.nickname,
        ):
            return None
        if session.irc_nickname is None:
            try:
                if not ipaddress.ip_address(session.peer_ip).is_loopback:
                    return None
            except ValueError:
                return None
        return invite

    def _handle_authenticated_line(
        self,
        session: PartylineSession,
        line: str,
        now_ns: int,
    ) -> None:
        if not line:
            return
        if not line.startswith("."):
            self._broadcast(f"<{session.handle}> {line}")
            self._emit(
                f"event=chat handle={_safe_atom(session.handle or 'unknown')} bytes={len(line.encode('utf-8'))}"
            )
            return
        arguments = line.split()
        command = arguments[0].casefold()
        if command in (".quit", ".exit"):
            self._queue_line(session, "Bye.")
            self._flush_session(session)
            self._close_session(session, "quit")
        elif command == ".help":
            for help_line in _HELP_LINES:
                self._queue_line(session, help_line)
        elif command == ".passwd" and len(arguments) == 1:
            session.stage = "change-password"
            session.pending_password = None
            self._echo_off(session)
            self._queue(session, b"New password (12-128 characters): ")
        elif command in (".who", ".whom"):
            handles = sorted(
                active.handle
                for active in self._sessions.values()
                if active.handle is not None
            )
            self._queue_line(session, "Partyline: " + ", ".join(handles))
        elif command in (".status", ".stat"):
            for status_line in self._status_lines(now_ns):
                self._queue_line(session, status_line)
        elif command in (".dcc", ".dccstat"):
            for status_line in self._dcc_lines():
                self._queue_line(session, status_line)
        elif command == ".game":
            for game_line in self._game_lines(now_ns):
                self._queue_line(session, game_line)
        elif command == ".duckplanning" and len(arguments) == 1:
            for planning_line in self._duckplanning_lines(now_ns):
                self._queue_line(session, planning_line)
        elif command == ".summary" and len(arguments) == 1:
            for summary_line in self._summary_lines():
                self._queue_line(session, summary_line)
        elif command == ".duck" and len(arguments) in (1, 2):
            self._launch_flight(session, now_ns, FlightKind.STANDARD, arguments)
        elif command in (".goldenduck", ".golden") and len(arguments) in (1, 2):
            self._launch_flight(session, now_ns, FlightKind.GOLDEN, arguments)
        elif command == ".player" and len(arguments) == 2:
            self._show_player(session, arguments[1])
        elif command == ".fields" and len(arguments) == 1:
            self._queue_line(
                session,
                tr((
                    'Fields: ammo capacity magazines magazine_capacity fatigue level xp credit jammed '
                    'confiscated carried_ducks hits misses wild_shots empty_shots jammed_shots '
                    'compulsive_reloads golden_hits deaths.'
                )),
            )
        elif command == ".giveammo" and len(arguments) in (2, 3):
            self._increment_player(session, now_ns, arguments, "ammo")
        elif command == ".givemag" and len(arguments) in (2, 3):
            self._increment_player(session, now_ns, arguments, "magazines")
        elif command == ".returnweapon" and len(arguments) == 2:
            self._weapon_control(session, now_ns, arguments[1], "rearm")
        elif command == ".unjam" and len(arguments) == 2:
            self._update_player(session, now_ns, arguments[1], "jammed", "set", 0)
        elif command == ".setplayer" and len(arguments) == 4:
            self._set_player(session, now_ns, arguments[1], arguments[2], arguments[3])
        else:
            self._queue_line(session, "Unknown command or syntax; type .help.")

    def _launch_flight(
        self,
        session: PartylineSession,
        now_ns: int,
        kind: FlightKind,
        arguments: list[str],
    ) -> None:
        _, _, connected, joined_channels = self._network_status()
        if not connected:
            self._queue_line(session, "Launch rejected: Coin is not connected to IRC.")
            return
        if len(arguments) == 2:
            requested = arguments[1]
            if not any(same_irc_name(joined, requested) for joined in joined_channels):
                self._queue_line(
                    session,
                    f"Launch rejected: Coin is not joined to {requested}.",
                )
                return
        elif len(joined_channels) == 1:
            requested = joined_channels[0]
        elif not joined_channels:
            self._queue_line(session, "Launch rejected: Coin has no joined channel.")
            return
        else:
            self._queue_line(
                session,
                "Launch rejected: specify one joined channel ("
                + ", ".join(joined_channels)
                + ").",
            )
            return
        result = self._launch_channel_flight(
            now_ns,
            kind,
            requested,
            actor=session.handle or "unknown",
            source="partyline",
        )
        if result.started:
            return
        messages = {
            "not-connected": "Launch rejected: Coin is not connected to IRC.",
            "not-joined": f"Launch rejected: Coin is not joined to {requested}.",
            "active-flight": (
                f"Launch rejected: duck #{result.flight_id} is still active."
            ),
            "backpressured": "Launch rejected: persistence queue is busy.",
            "collision": "Launch rejected: a duck is already active.",
        }
        self._queue_line(session, messages[result.status])

    def _launch_channel_flight(
        self,
        now_ns: int,
        kind: FlightKind,
        requested_channel: str,
        *,
        actor: str,
        source: str,
        announcement: str | None = None,
    ) -> FlightLaunchResult:
        _, _, connected, joined_channels = self._network_status()
        if not connected:
            return FlightLaunchResult("not-connected")
        channel = next(
            (
                joined
                for joined in joined_channels
                if same_irc_name(joined, requested_channel)
            ),
            None,
        )
        if channel is None:
            return FlightLaunchResult("not-joined")
        active = self.runtime.state.flight
        if active is not None and active.expires_at_ns > now_ns:
            return FlightLaunchResult(
                "active-flight",
                channel,
                active.flight_id,
                active.health,
            )
        health = 1 if kind is FlightKind.STANDARD else self._draw_integer(3, 5)
        event = ReplayEvent.start_flight(
            now_ns,
            self._flight_lifetime_ns,
            health=health,
            kind=kind,
            reward_experience=flight_reward(kind, health),
        )
        dispatched = self.runtime.dispatch(
            event,
            lambda transition: self._render_manual_flight(
                transition,
                channel,
                announcement=announcement,
            ),
        )
        if dispatched.status.value == "backpressured" or dispatched.transition is None:
            return FlightLaunchResult("backpressured", channel)
        started = next(
            (
                outcome
                for outcome in dispatched.transition.outcomes
                if outcome.kind is OutcomeKind.FLIGHT_STARTED
            ),
            None,
        )
        if started is None:
            return FlightLaunchResult("collision", channel)
        flight = dispatched.transition.state.flight
        assert flight is not None
        label = "golden duck" if kind is FlightKind.GOLDEN else "duck"
        suffix = f" (hp={flight.health})" if kind is FlightKind.GOLDEN else ""
        self._broadcast(
            f"*** {actor} launched {label} #{flight.flight_id} on {channel}{suffix}. ***"
        )
        self._emit(
            "event=flight-launch "
            f"source={source} actor={_safe_atom(actor)} channel={_safe_atom(channel)} "
            f"kind={kind.value} flight_id={flight.flight_id} health={flight.health}"
        )
        return FlightLaunchResult("started", channel, flight.flight_id, flight.health)

    @staticmethod
    def _irc_launch_rejection(
        result: FlightLaunchResult,
        requested_channel: str,
    ) -> str:
        messages = {
            "not-connected": tr("Lancement refusé : Coin n'est pas connecté à IRC."),
            "not-joined": tr("Lancement refusé : Coin n'est pas sur {0}.", requested_channel),
            "active-flight": tr('Lancement refusé : un canard est déjà présent.'),
            "backpressured": tr('Lancement refusé : la persistance est occupée.'),
            "collision": tr('Lancement refusé : un canard est déjà présent.'),
        }
        return messages[result.status]

    def _poll_spontaneous_launch(self, now_ns: int) -> bool:
        due_at_ns = self._next_spontaneous_launch_ns
        if due_at_ns is None or now_ns < due_at_ns:
            return False
        self._schedule_next_spontaneous_launch(now_ns)
        channel = self.configuration.spontaneous_launch_channel
        assert channel is not None
        result = self._launch_channel_flight(
            now_ns,
            FlightKind.STANDARD,
            channel,
            actor="Coin",
            source="spontaneous",
            announcement=tr(self.configuration.spontaneous_launch_announcement),
        )
        if not result.started:
            self._emit(
                "event=spontaneous-launch-skipped "
                f"channel={_safe_atom(channel)} reason={result.status}"
            )
        return True

    def _schedule_next_spontaneous_launch(self, now_ns: int) -> None:
        delay_seconds = self._draw_integer(
            self.configuration.spontaneous_launch_min_seconds,
            self.configuration.spontaneous_launch_max_seconds,
        )
        self._next_spontaneous_launch_ns = now_ns + delay_seconds * 1_000_000_000
        self._emit(
            "event=spontaneous-launch-scheduled "
            f"delay_seconds={delay_seconds}"
        )

    def _render_manual_flight(
        self,
        transition: Transition,
        channel: str,
        *,
        announcement: str | None = None,
    ) -> tuple[bytes, ...]:
        appearance: FlightAppearance | None = None
        if any(
            outcome.kind is OutcomeKind.FLIGHT_STARTED
            for outcome in transition.outcomes
        ) and self._flight_appearance_source is not None:
            appearance = self._flight_appearance_source()
        announcement_batch = (
            ()
            if announcement is None
            or not any(
                outcome.kind is OutcomeKind.FLIGHT_STARTED
                for outcome in transition.outcomes
            )
            else render_wire_response(channel, (announcement,))
        )
        channel_batch = render_wire_response(
            channel,
            render_outcomes(
                transition.outcomes,
                flight_appearance=appearance,
                channel=channel,
            ),
        )
        detector_batch = tuple(
            wire
            for outcome in transition.outcomes
            if outcome.kind is OutcomeKind.DUCK_ALERT and outcome.actor is not None
            for wire in render_wire_notice(
                outcome.actor,
                render_detector_notice(outcome),
            )
        )
        return announcement_batch + channel_batch + detector_batch

    def _draw_integer(self, minimum: int, maximum: int) -> int:
        value = self._integer_source(minimum, maximum)
        if type(value) is not int or not minimum <= value <= maximum:
            raise RuntimeError("partyline integer source violated its bounds")
        return value

    def _status_lines(self, now_ns: int) -> tuple[str, ...]:
        nickname, transport, connected, channels = self._network_status()
        uptime = 0 if self._started_at_ns is None else max(0, now_ns - self._started_at_ns)
        persistence = self.runtime.persistence
        return (
            f"Coin {nickname} | IRC {transport} | connected={'yes' if connected else 'no'} | channels={','.join(channels)}",
            f"Uptime {_duration(uptime)} | players={len(self.runtime.state.players)} | partyline={self.authenticated_count}/{MAX_SESSIONS}",
            f"Persistence {persistence.state.value} | pending={persistence.pending_count} | journal schema={SCHEMA_VERSION}",
            f"Listener {self.configuration.bind_host}:{self.bound_port or 0} | DCC public={self.configuration.dcc_public_ip or 'disabled'}",
        )

    def _dcc_lines(self) -> tuple[str, ...]:
        dcc_sessions = sum(
            session.handle is not None and session.transport.startswith("dcc")
            for session in self._sessions.values()
        )
        telnet_sessions = sum(
            session.handle is not None and session.transport == "telnet"
            for session in self._sessions.values()
        )
        port_mode = (
            "ephemeral"
            if (self.configuration.dcc_port_min, self.configuration.dcc_port_max)
            == (0, 0)
            else f"{self.configuration.dcc_port_min}-{self.configuration.dcc_port_max}"
        )
        return (
            "DCC Partyline status:",
            f"  Public IP: {self.configuration.dcc_public_ip or 'disabled'} | ports: {port_mode}",
            f"  Pending offers: {len(self._offers)} | outbound connects: {len(self._connects)}",
            f"  DCC sessions: {dcc_sessions} | Telnet sessions: {telnet_sessions}",
        )

    def _game_lines(self, now_ns: int) -> tuple[str, ...]:
        state = self.runtime.state
        if state.flight is None:
            flight = "none"
        else:
            remaining = max(0, state.flight.expires_at_ns - now_ns)
            flight = (
                f"#{state.flight.flight_id} {state.flight.kind.value} "
                f"hp={state.flight.health}/{state.flight.max_health} ttl={_duration(remaining)}"
            )
        schedule = state.daily_schedule
        if schedule is None:
            schedule_line = "Schedule: none"
        else:
            next_deadline = (
                None
                if schedule.next_index >= len(schedule.deadlines_ns)
                else schedule.deadlines_ns[schedule.next_index]
            )
            schedule_line = (
                f"Schedule: {schedule.next_index}/{len(schedule.deadlines_ns)} "
                f"next={_utc(next_deadline)}"
            )
        if not self.configuration.spontaneous_launch_enabled:
            spontaneous_line = "Spontaneous: disabled"
        else:
            channel = self.configuration.spontaneous_launch_channel
            spontaneous_line = (
                f"Spontaneous: channel={channel} "
                f"next={_utc(self._next_spontaneous_launch_ns)}"
            )
        return (
            f"Flight: {flight}",
            schedule_line,
            spontaneous_line,
            f"State: players={len(state.players)} effects={len(state.effects)} actions={len(state.scheduled_actions)} curses={len(state.curses)}",
        )

    def _duckplanning_lines(self, now_ns: int) -> tuple[str, ...]:
        state = self.runtime.state
        _, _, _, joined_channels = self._network_status()
        channel = ",".join(joined_channels) if joined_channels else tr('aucun canal')
        schedule = state.daily_schedule
        lines: list[str] = []
        daily_next_ns: int | None = None
        if schedule is None:
            lines.append(tr('Duckplanning {0} — aucun planning quotidien.', channel))
        else:
            daily_next_ns = (
                schedule.day_start_ns + DAY_NS
                if schedule.next_index >= len(schedule.deadlines_ns)
                else schedule.deadlines_ns[schedule.next_index]
            )
            lines.append(
                f"Duckplanning {channel} — Europe/Paris — "
                f"{schedule.next_index}/{len(schedule.deadlines_ns)} "
                + (tr('échéances passées du plan actuel.') if state.bread_plan_effect_ids is not None
                   else tr('créneaux traités.'))
            )
            entries = tuple(
                f"{index + 1:02d}{'✓' if index < schedule.next_index else '→' if index == schedule.next_index else '·'}"
                f"{_paris(deadline)}"
                for index, deadline in enumerate(schedule.deadlines_ns)
            )
            for offset in range(0, len(entries), 6):
                first = offset + 1
                last = min(offset + 6, len(entries))
                lines.append(
                    tr('Vols {0:02d}-{1:02d}: ', first, last) + " | ".join(entries[offset:last])
                )

        actions = tuple(
            sorted(
                state.scheduled_actions,
                key=lambda action: (action.due_at_ns, action.action_id),
            )
        )
        active_breads = active_channel_breads(state, now_ns)
        hourly_bread = state.bread_plan_effect_ids is not None
        if hourly_bread:
            lines.append(tr("Base=24 vols/jour | pains actifs={0} | attraction : plan à {1} créneaux (sans garantie d'envol pendant l'heure).", len(active_breads), 24 + min(20, len(active_breads))))
        if state.flight is not None and now_ns < state.flight.expires_at_ns:
            wake_candidates = tuple(
                value
                for value in (daily_next_ns, state.flight.expires_at_ns)
                if value is not None
            )
        else:
            action_next_ns = None if not actions else actions[0].due_at_ns
            wake_candidates = tuple(
                value
                for value in (daily_next_ns, action_next_ns)
                if value is not None
            )
        if hourly_bread:
            wake_candidates += tuple(e.expires_at_ns for e in active_breads
                                     if e.expires_at_ns is not None)
        wake_ns = min(wake_candidates) if wake_candidates else None
        flight = (
            tr('aucun')
            if state.flight is None
            else tr('#{0} fin={1}', state.flight.flight_id, _paris(state.flight.expires_at_ns))
        )
        lines.append(
            tr('Prochain quotidien={0} | réveil effectif={1} | vol={2}.', _paris(daily_next_ns), _paris(wake_ns), flight)
        )
        lines.append(
            tr('Pains={0} | appeaux/actions={1} | ', len(active_breads), len(actions))
            + (tr('aucun pain disponible.') if not active_breads else
               tr('pain conservé à chaque envol ; +{0}s aux nouveaux vols.', 20 * len(active_breads))
               if hourly_bread else tr('un morceau au plus par envol, uniquement avant son expiration.'))
        )
        for action in actions:
            source = state.player(action.source_key or "")
            actor = "Owner" if source is None else source.nickname
            label = tr("appeau") if action.item_id == 20 else tr('canard mécanique')
            lines.append(
                tr('Action #{0}: {1}, auteur={2}, échéance={3}.', action.action_id, label, actor, _paris(action.due_at_ns))
            )
        if active_breads:
            expirations = ", ".join(
                _paris(effect.expires_at_ns) for effect in active_breads
            )
            lines.append(tr('Expiration des pains: {0}.', expirations))
            # Only actual future flight slots/actions can consume bread. A day
            # rollover or the end of an existing flight is not a new takeoff.
            earliest_ns = max(now_ns, state.flight.expires_at_ns) if state.flight else now_ns
            known_flights = ([] if schedule is None else [
                deadline for deadline in schedule.deadlines_ns[schedule.next_index:]
                if deadline >= earliest_ns
            ])
            known_flights.extend(max(earliest_ns, action.due_at_ns) for action in actions
                                 if action.item_id in (20, 23))
            if known_flights:
                next_flight_ns = min(known_flights)
                at_risk = sum(effect.expires_at_ns is not None
                              and effect.expires_at_ns <= next_flight_ns
                              for effect in active_breads)
                if at_risk:
                    lines.append(
                        tr("Attention : {0}/{1} pain(s) expirent avant ou à la prochaine échéance d'envol connue ({2}). ", at_risk, len(active_breads), _paris(next_flight_ns))
                        + (tr("L'attraction ne garantit pas un envol avant expiration.")
                           if hourly_bread else tr('Seul un envol plus tôt pourrait les consommer.'))
                    )
            else:
                lines.append(tr('Aucun prochain envol connu avant recalcul.') if hourly_bread else
                             tr('Aucun prochain envol connu : consommation du pain non garantie.'))
        lines.append(tr('Légende: ✓ échéance passée du plan actuel (pas un bilan de chasse) | → prochain | · à venir.')
                     if hourly_bread else tr('Légende: ✓ traité | → prochain quotidien | · à venir.'))
        return tuple(lines)

    def _summary_lines(self) -> tuple[str, ...]:
        state = self.runtime.state
        _, _, _, joined_channels = self._network_status()
        channel = joined_channels[0] if len(joined_channels) == 1 else None
        ordered = ranked_players(
            state,
            limit=5,
            excluded_nicknames=self._statistics_excluded_nicknames,
        )
        lines = [tr('=== Coin · résumé DuckHunt ===')]
        lines.extend(_plain_irc(line) for line in render_ranking(
            state,
            limit=5,
            ranking_url=self._ranking_url,
            excluded_nicknames=self._statistics_excluded_nicknames,
        ))
        for index, player in enumerate(ordered, start=1):
            lines.append(f"--- #{index} · {player.nickname} ---")
            lines.extend(_plain_irc(line) for line in render_profile(state, player.nickname))
            lines.extend(
                _plain_irc(line)
                for line in render_inventory(state, player.nickname, channel=channel)
            )
        lines.append(tr('=== Dernier tireur ==='))
        last_shooter = (
            None
            if state.last_shooter_key is None
            else state.player(state.last_shooter_key)
        )
        if last_shooter is not None and is_statistically_excluded(
            last_shooter.nickname,
            excluded_nicknames=self._statistics_excluded_nicknames,
        ):
            last_shooter = None
        if last_shooter is None:
            lines.append(tr('Aucun tir enregistré.'))
        else:
            rank = next(
                (
                    index
                    for index, player in enumerate(ordered, start=1)
                    if player.key == last_shooter.key
                ),
                None,
            )
            suffix = "" if rank is None else tr(' (également #{0})', rank)
            lines.append(f"--- {last_shooter.nickname}{suffix} ---")
            lines.extend(_plain_irc(line) for line in render_profile(state, last_shooter.nickname))
            lines.extend(
                _plain_irc(line)
                for line in render_inventory(
                    state,
                    last_shooter.nickname,
                    channel=channel,
                )
            )
        return tuple(lines)

    def _weapon_control(
        self,
        session: PartylineSession,
        now_ns: int,
        nickname: str,
        operation: str,
    ) -> None:
        before_player = self.runtime.state.player(rfc1459_casefold(nickname))
        if before_player is None:
            self._queue_line(session, f"Player {nickname}: not found.")
            return
        actor = session.handle or "unknown"
        try:
            event = ReplayEvent.admin_weapon_control(
                now_ns,
                actor,
                before_player.nickname,
                operation=operation,
            )
            apply_weapon_control(
                self.runtime.state,
                before_player.nickname,
                now_ns,
                operation=operation,
            )
        except (PlayerAdministrationError, ValueError) as error:
            self._queue_line(session, f"Update rejected: {error}.")
            return
        result = self.runtime.dispatch(event, lambda transition: ())
        if result.status.value == "backpressured" or result.transition is None:
            self._queue_line(session, "Update rejected: persistence queue is busy.")
            return
        updated = result.transition.state.player(before_player.key)
        assert updated is not None
        self._broadcast(
            f"*** {actor} returned {updated.nickname}'s weapon "
            f"(permanent confiscation cleared). ***"
        )
        self._emit(
            "event=weapon-control "
            f"actor={_safe_atom(actor)} target={_safe_atom(updated.nickname)} "
            f"operation={operation}"
        )

    def _show_player(self, session: PartylineSession, nickname: str) -> None:
        player = self.runtime.state.player(rfc1459_casefold(nickname))
        if player is None:
            self._queue_line(session, f"Player {nickname}: not found.")
            return
        for line in _player_lines(player):
            self._queue_line(session, line)

    def _increment_player(
        self,
        session: PartylineSession,
        now_ns: int,
        arguments: list[str],
        field_name: str,
    ) -> None:
        try:
            count = 1 if len(arguments) == 2 else int(arguments[2], 10)
        except ValueError:
            self._queue_line(session, "Count must be an integer.")
            return
        self._update_player(session, now_ns, arguments[1], field_name, "add", count)

    def _set_player(
        self,
        session: PartylineSession,
        now_ns: int,
        nickname: str,
        raw_field: str,
        raw_value: str,
    ) -> None:
        aliases = {
            "credit": "shop_credit",
            tr('fatigue'): "fatigue_centi",
            "mags": "magazines",
            "mag_capacity": "magazine_capacity",
            "xp": "experience",
        }
        field_name = aliases.get(raw_field.casefold(), raw_field.casefold())
        if field_name in ("confiscated", "jammed"):
            values = {"0": 0, "1": 1, "false": 0, "off": 0, "true": 1, "on": 1}
            if raw_value.casefold() not in values:
                self._queue_line(session, "Value must be on/off, true/false or 1/0.")
                return
            value = values[raw_value.casefold()]
        else:
            try:
                value = int(raw_value, 10)
            except ValueError:
                self._queue_line(session, "Player value must be an integer.")
                return
            if field_name == "fatigue_centi":
                value *= 100
        self._update_player(session, now_ns, nickname, field_name, "set", value)

    def _update_player(
        self,
        session: PartylineSession,
        now_ns: int,
        nickname: str,
        field_name: str,
        operation: str,
        value: int,
    ) -> None:
        before_player = self.runtime.state.player(rfc1459_casefold(nickname))
        if before_player is None:
            self._queue_line(session, f"Player {nickname}: not found.")
            return
        actor = session.handle or "unknown"
        try:
            event = ReplayEvent.admin_player_update(
                now_ns,
                actor,
                before_player.nickname,
                field=field_name,
                operation=operation,
                value=value,
            )
            apply_player_update(
                self.runtime.state,
                before_player.nickname,
                now_ns,
                field=field_name,
                operation=operation,
                value=value,
            )
        except (PlayerAdministrationError, ValueError) as error:
            self._queue_line(session, f"Update rejected: {error}.")
            return
        result = self.runtime.dispatch(event, lambda transition: ())
        if result.status.value == "backpressured" or result.transition is None:
            self._queue_line(session, "Update rejected: persistence queue is busy.")
            return
        after_player = result.transition.state.player(before_player.key)
        assert after_player is not None
        before = _field_display(field_name, getattr(before_player, field_name))
        after = _field_display(field_name, getattr(after_player, field_name))
        notice = (
            f"*** {actor} updated {after_player.nickname}: "
            f"{field_name} {before} -> {after}. ***"
        )
        self._broadcast(notice)
        self._emit(
            "event=player-update "
            f"actor={_safe_atom(actor)} target={_safe_atom(after_player.nickname)} "
            f"field={field_name} operation={operation}"
        )

    def _broadcast(
        self,
        line: str,
        *,
        exclude: PartylineSession | None = None,
    ) -> None:
        encoded = (line + "\r\n").encode("utf-8")
        for session in tuple(self._sessions.values()):
            if session is exclude or session.handle is None:
                continue
            self._queue(session, encoded)

    def _queue_line(self, session: PartylineSession, line: str) -> None:
        self._queue(session, (line + "\r\n").encode("utf-8"))

    def _queue(self, session: PartylineSession, payload: bytes) -> None:
        if len(session.output_buffer) + len(payload) > MAX_OUTPUT_BYTES:
            self._close_session(session, "output-overflow")
            return
        session.output_buffer.extend(payload)

    def _flush_session(self, session: PartylineSession) -> bool:
        if not session.output_buffer:
            return False
        try:
            sent = session.stream.send(session.output_buffer)
        except BlockingIOError:
            return False
        except OSError:
            self._close_session(session, "write-error")
            return True
        del session.output_buffer[:sent]
        return sent > 0

    def _close_session(
        self,
        session: PartylineSession,
        reason: str,
        *,
        broadcast: bool = True,
    ) -> None:
        descriptor = session.stream.fileno()
        self._sessions.pop(descriptor, None)
        handle = session.handle
        _close_socket(session.stream)
        if handle is not None and broadcast:
            self._broadcast(f"*** {handle} left the partyline. ***")
        self._emit(
            f"event=session-close transport={session.transport} reason={_safe_atom(reason)}"
        )

    def _expire(self, now_ns: int) -> bool:
        changed = False
        for key, invite in tuple(self._bootstrap.items()):
            if invite.expires_at_ns <= now_ns:
                self._bootstrap.pop(key, None)
                changed = True
        for key, offer in tuple(self._offers.items()):
            if offer.deadline_ns <= now_ns:
                _close_socket(offer.listener)
                self._offers.pop(key, None)
                self._notice(offer.nickname, tr('Offre DCC CHAT expirée.'))
                changed = True
        for descriptor, pending in tuple(self._connects.items()):
            if pending.deadline_ns <= now_ns:
                _close_socket(pending.stream)
                self._connects.pop(descriptor, None)
                self._notice(pending.nickname, tr('Connexion DCC CHAT expirée.'))
                changed = True
        for session in tuple(self._sessions.values()):
            if session.handle is None and session.auth_deadline_ns <= now_ns:
                self._queue_line(session, "Authentication timeout.")
                self._flush_session(session)
                self._close_session(session, "auth-timeout")
                changed = True
        for peer_ip, failures in tuple(self._ip_failures.items()):
            failures[:] = [value for value in failures if now_ns - value <= IP_FAILURE_WINDOW_NS]
            if not failures:
                self._ip_failures.pop(peer_ip, None)
        return changed

    def _pending_dcc_count(self) -> int:
        return len(self._offers) + len(self._connects)

    def _notice(self, nickname: str, text: str) -> None:
        self.runtime.emit_priority((render_notice_bounded(nickname, text),))

    def _echo_off(self, session: PartylineSession) -> None:
        if session.transport == "telnet":
            self._queue(session, bytes((TELNET_IAC, TELNET_WILL, TELNET_ECHO)))

    def _echo_on(self, session: PartylineSession) -> None:
        if session.transport == "telnet":
            self._queue(session, bytes((TELNET_IAC, TELNET_WONT, TELNET_ECHO)))

    def _emit(self, message: str) -> None:
        if self._observer is not None:
            self._observer("PARTYLINE " + message)

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("partyline time must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("partyline clock cannot move backwards")
        self._last_now_ns = now_ns


def parse_dcc_chat(
    payload: str,
) -> tuple[ipaddress.IPv4Address | None, int, str | None] | None:
    """Parse one bounded active or passive CTCP DCC CHAT request."""

    if type(payload) is not str or len(payload) > 512:
        return None
    fields = payload.split()
    if len(fields) not in (5, 6) or tuple(value.casefold() for value in fields[:3]) != (
        "dcc",
        "chat",
        "chat",
    ):
        return None
    raw_address, raw_port = fields[3:5]
    token = fields[5] if len(fields) == 6 else None
    try:
        port = int(raw_port, 10)
    except ValueError:
        return None
    if raw_address == "0" and port == 0 and token is not None and _valid_dcc_token(token):
        return (None, 0, token)
    if token is not None or not 1_024 <= port <= 65_535:
        return None
    try:
        if raw_address.isdecimal():
            numeric = int(raw_address, 10)
            if not 1 <= numeric <= (1 << 32) - 1:
                return None
            address = ipaddress.IPv4Address(numeric)
        else:
            address = ipaddress.IPv4Address(raw_address)
    except ipaddress.AddressValueError:
        return None
    if not address.is_global:
        return None
    return (address, port, None)


def _ctcp_payload(text: str) -> str | None:
    if len(text) < 3 or not text.startswith("\x01") or not text.endswith("\x01"):
        return None
    payload = text[1:-1]
    return payload if payload and "\x01" not in payload else None


def _valid_dcc_token(value: str) -> bool:
    return (
        1 <= len(value) <= 64
        and all(character.isascii() and (character.isalnum() or character in "_-.") for character in value)
    )


def _irc_mask_matches(value: str, pattern: str) -> bool:
    expression = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(expression, value, flags=re.DOTALL) is not None


def _listening_socket(host: str, port: int, *, backlog: int = MAX_SESSIONS) -> socket.socket:
    address = ipaddress.ip_address(host)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setblocking(False)
        listener.bind((host, port))
        listener.listen(backlog)
        return listener
    except Exception:
        _close_socket(listener)
        raise


def _strip_telnet_iac(payload: bytes, pending: bytearray) -> bytes:
    """Strip Telnet negotiation, retaining fragmented commands between reads."""

    source = bytes(pending) + payload
    pending.clear()
    retained = bytearray()
    index = 0
    while index < len(source):
        if source[index] != TELNET_IAC:
            retained.append(source[index])
            index += 1
            continue
        if index + 1 >= len(source):
            pending.extend(source[index:])
            break
        command = source[index + 1]
        if command == TELNET_IAC:
            retained.append(TELNET_IAC)
            index += 2
        elif command == TELNET_SUBNEGOTIATION:
            end = source.find(
                bytes((TELNET_IAC, TELNET_END_SUBNEGOTIATION)),
                index + 2,
            )
            if end < 0:
                pending.extend(source[index:])
                break
            index = end + 2
        elif command in (TELNET_WILL, TELNET_WONT, TELNET_DO, TELNET_DONT):
            if index + 2 >= len(source):
                pending.extend(source[index:])
                break
            index += 3
        else:
            index += 2
    return bytes(retained)


def _close_socket(stream: socket.socket) -> None:
    try:
        stream.close()
    except OSError:
        pass


def _safe_atom(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._:-[]{}" else "_"
        for character in value
    )[:128]


def _duration(value_ns: int) -> str:
    seconds = max(0, value_ns // 1_000_000_000)
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _utc(value_ns: int | None) -> str:
    if value_ns is None:
        return "none"
    return datetime.fromtimestamp(value_ns / 1_000_000_000, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _paris(value_ns: int | None) -> str:
    if value_ns is None:
        return tr('aucun')
    return datetime.fromtimestamp(value_ns / 1_000_000_000, PARIS_ZONE).strftime(
        "%d/%m %H:%M:%S %Z"
    )


def _field_display(field_name: str, value: object) -> str:
    if field_name == "fatigue_centi":
        return f"{int(value) / 100:.2f}%"
    if field_name in ("confiscated", "jammed"):
        return "yes" if value else "no"
    return str(value)


def _plain_irc(value: str) -> str:
    """Remove mIRC presentation controls from canonical IRC renderings."""

    without_colours = re.sub(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?", "", value)
    return without_colours.translate({ord("\x02"): None, ord("\x0f"): None})


def _player_lines(player: PlayerState) -> tuple[str, ...]:
    best = "none" if player.best_time_ms is None else f"{player.best_time_ms / 1000:.3f}s"
    inventory = (
        "empty"
        if not player.inventory
        else ", ".join(f"{stack.key} x{stack.quantity}" for stack in player.inventory)
    )
    return (
        f"Player {player.nickname} | level={player.level} xp={player.experience}/{experience_required(player.level)} | hits={player.hits} golden={player.golden_hits} best={best}",
        f"Weapon ammo={player.ammo}/{player.capacity} magazines={player.magazines}/{player.magazine_capacity} confiscated={'permanent' if player.permanently_confiscated else 'yes' if player.confiscated else 'no'} jammed={'yes' if player.jammed else 'no'}",
        tr('Activity misses={0} wild={1} empty={2} fatigue={3:.2f}% carried={4} credit={5}', player.misses, player.wild_shots, player.empty_shots, player.fatigue_centi / 100, player.carried_ducks, player.shop_credit),
        f"Inventory: {inventory}",
    )


_HELP_LINES = (
    tr('.status                         Coin, IRC, persistance et sessions'),
    tr('.dccstat                        IP, ports, offres et sessions DCC'),
    tr('.game                           vol, planning et état DuckHunt'),
    tr('.duckplanning                   les 24 horaires, pains, appeaux et réveil effectif'),
    tr('.summary                        top 5, profils, inventaires et dernier tireur'),
    tr('.duck [#canal]                 lance un canard sans déplacer le planning'),
    tr('.goldenduck [#canal]           lance un canard doré (alias : .golden)'),
    tr('.who                            opérateurs connectés'),
    tr(".player <nick>                  profil complet d'un joueur"),
    tr('.fields                         champs acceptés par .setplayer'),
    tr('.giveammo <nick> [n]            donne 1 à 100 munitions, sans dépasser la capacité'),
    tr('.givemag <nick> [n]             donne 1 à 100 chargeurs, sans dépasser la réserve'),
    tr('.returnweapon <nick>             restitue une arme confisquée'),
    tr('.passwd                          remplace le mot de passe de la partyline'),
    tr(".unjam <nick>                    déraie l'arme"),
    tr('.setplayer <nick> <champ> <v>    modifie un champ borné (liste avec .fields)'),
    tr('.quit                            ferme la session'),
)
