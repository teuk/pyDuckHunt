"""Strict TOML configuration loading without implicit environment access."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
from pathlib import Path

from pyduckhunt.irc.socket_adapter import IRCEndpoint
from pyduckhunt.irc.transport import IRCTransportPolicy
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.public_url import normalize_ranking_url, normalize_shop_url


_ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_LOG_LEVELS = frozenset(("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))


@dataclass(frozen=True, slots=True)
class IRCConfiguration:
    host: str
    port: int
    tls: bool
    nickname: str
    fallback_nickname: str
    channels: tuple[str, ...]
    password_environment: str
    bot_mode: bool = False

    def endpoint(self) -> IRCEndpoint:
        return IRCEndpoint(self.host, self.port, self.tls)

    def transport_policy(
        self,
        *,
        server_password: str | None = None,
    ) -> IRCTransportPolicy:
        return IRCTransportPolicy(
            nickname=self.nickname,
            fallback_nickname=self.fallback_nickname,
            username="pyduckhunt",
            realname="pyDuckHunt",
            channels=self.channels,
            server_password=server_password,
            bot_mode=self.bot_mode,
        )


@dataclass(frozen=True, slots=True)
class ProcessConfiguration:
    log_level: str
    state_directory: Path
    log_directory: Path
    ranking_page_path: Path | None = None
    metrics_page_path: Path | None = None


@dataclass(frozen=True, slots=True)
class GameConfiguration:
    enabled: bool
    flights_per_day: int
    golden_weight_per_eighteen: int
    flight_lifetime_seconds: int
    unusual_loot_chance_per_thousand: int
    shop_url: str | None = None
    ranking_url: str | None = None
    anti_cheat: bool = False


@dataclass(frozen=True, slots=True)
class PartylineConfiguration:
    enabled: bool = False
    bind_host: str = "127.0.0.1"
    port: int = 0
    bootstrap_accounts: tuple[str, ...] = ()
    bootstrap_masks: tuple[str, ...] = ()
    dcc_public_ip: str | None = None
    dcc_port_min: int = 0
    dcc_port_max: int = 0
    spontaneous_launch_enabled: bool = False
    spontaneous_launch_channel: str | None = None
    spontaneous_launch_min_seconds: int = 0
    spontaneous_launch_max_seconds: int = 0
    spontaneous_launch_announcement: str = "allez, je lance un canard"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("partyline enabled flag must be a truth value")
        try:
            bind_address = ip_address(self.bind_host)
        except (TypeError, ValueError) as error:
            raise ValueError("partyline bind host must be an IPv4 or IPv6 address") from error
        if bind_address.is_multicast:
            raise ValueError("partyline bind host cannot be multicast")
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("partyline port must be between 0 and 65535")
        for label, values in (
            ("bootstrap account", self.bootstrap_accounts),
            ("bootstrap mask", self.bootstrap_masks),
        ):
            if type(values) is not tuple or any(
                type(value) is not str
                or not value
                or value.strip() != value
                or len(value) > 255
                or any(character in value for character in ("\x00", "\r", "\n", " "))
                for value in values
            ):
                raise ValueError(f"partyline {label} allowlist is invalid")
        if self.enabled and not (self.bootstrap_accounts or self.bootstrap_masks):
            raise ValueError("enabled partyline requires a bootstrap identity")
        if self.dcc_public_ip is not None:
            try:
                public_address = ip_address(self.dcc_public_ip)
            except (TypeError, ValueError) as error:
                raise ValueError("DCC public IP must be an IPv4 address") from error
            if (
                not isinstance(public_address, IPv4Address)
                or public_address.is_unspecified
                or public_address.is_loopback
                or public_address.is_multicast
            ):
                raise ValueError("DCC public IP must be a usable IPv4 address")
        if any(
            type(value) is not int
            for value in (self.dcc_port_min, self.dcc_port_max)
        ):
            raise ValueError("DCC port range must use integers")
        if (self.dcc_port_min, self.dcc_port_max) != (0, 0) and not (
            1_024 <= self.dcc_port_min <= self.dcc_port_max <= 65_535
            and self.dcc_port_max - self.dcc_port_min <= 100
        ):
            raise ValueError("DCC port range must be zero or at most 101 ordered ports")
        if type(self.spontaneous_launch_enabled) is not bool:
            raise ValueError("spontaneous launch flag must be a truth value")
        if self.spontaneous_launch_enabled and not self.enabled:
            raise ValueError("spontaneous launches require the partyline control plane")
        channel = self.spontaneous_launch_channel
        if channel is not None and (
            type(channel) is not str
            or not channel.startswith(("#", "&"))
            or any(character in channel for character in (" ", "\x00", "\r", "\n"))
        ):
            raise ValueError("spontaneous launch channel is invalid")
        minimum = self.spontaneous_launch_min_seconds
        maximum = self.spontaneous_launch_max_seconds
        if any(type(value) is not int for value in (minimum, maximum)):
            raise ValueError("spontaneous launch interval must use integers")
        if self.spontaneous_launch_enabled:
            if channel is None:
                raise ValueError("spontaneous launches require one channel")
            if not 900 <= minimum <= maximum <= 86_400:
                raise ValueError(
                    "spontaneous launch interval must be between 15 minutes and one day"
                )
        elif (minimum, maximum) != (0, 0):
            raise ValueError("disabled spontaneous launches require a zero interval")
        announcement = self.spontaneous_launch_announcement
        if (
            type(announcement) is not str
            or not announcement
            or announcement.strip() != announcement
            or len(announcement.encode("utf-8")) > 240
            or any(character in announcement for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("spontaneous launch announcement is invalid")


@dataclass(frozen=True, slots=True)
class ApplicationConfiguration:
    irc: IRCConfiguration
    runtime: ProcessConfiguration
    game: GameConfiguration
    partyline: PartylineConfiguration = PartylineConfiguration()


def load_application_configuration(path: str | Path) -> ApplicationConfiguration:
    """Read and validate one exact TOML configuration document."""

    if not isinstance(path, (str, Path)):
        raise ValueError("configuration path must be text or a Path")
    config_path = Path(path)
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("configuration file cannot be loaded") from error
    return parse_application_configuration(payload)


def parse_application_configuration(
    payload: Mapping[str, object],
) -> ApplicationConfiguration:
    """Validate an already-decoded configuration mapping."""

    root = _mapping_with_optional(
        payload,
        "configuration",
        ("irc", "runtime", "game"),
        ("partyline",),
    )
    irc = _mapping_with_optional(
        root["irc"],
        "irc configuration",
        (
            "host",
            "port",
            "tls",
            "nickname",
            "fallback_nickname",
            "channels",
            "password_environment",
        ),
        ("bot_mode",),
    )
    runtime = _mapping_with_optional(
        root["runtime"],
        "runtime configuration",
        ("log_level", "state_directory", "log_directory"),
        ("ranking_page_path", "metrics_page_path"),
    )
    game = _mapping_with_optional(
        root["game"],
        "game configuration",
        (
            "enabled",
            "flights_per_day",
            "golden_weight_per_eighteen",
            "flight_lifetime_seconds",
            "unusual_loot_chance_per_thousand",
        ),
        ("shop_url", "ranking_url", "anti_cheat"),
    )
    partyline_raw = root.get("partyline")
    partyline = None
    if partyline_raw is not None:
        partyline = _mapping_with_optional(
            partyline_raw,
            "partyline configuration",
            (
                "enabled",
                "bind_host",
                "port",
                "bootstrap_accounts",
                "bootstrap_masks",
                "dcc_public_ip",
                "dcc_port_min",
                "dcc_port_max",
            ),
            (
                "spontaneous_launch_enabled",
                "spontaneous_launch_channel",
                "spontaneous_launch_min_seconds",
                "spontaneous_launch_max_seconds",
                "spontaneous_launch_announcement",
            ),
        )

    channels_value = irc["channels"]
    if type(channels_value) is not list or not channels_value or any(
        type(channel) is not str for channel in channels_value
    ):
        raise ValueError("IRC channels must be a non-empty string array")
    password_environment = _text(
        irc["password_environment"],
        "IRC password environment",
    )
    if not _ENVIRONMENT_NAME.fullmatch(password_environment):
        raise ValueError("IRC password environment name is invalid")

    irc_configuration = IRCConfiguration(
        host=_text(irc["host"], "IRC host"),
        port=_integer(irc["port"], "IRC port"),
        tls=_truth(irc["tls"], "IRC TLS flag"),
        nickname=_text(irc["nickname"], "IRC nickname"),
        fallback_nickname=_text(
            irc["fallback_nickname"],
            "IRC fallback nickname",
        ),
        channels=tuple(channels_value),
        password_environment=password_environment,
        bot_mode=_truth(irc.get("bot_mode", False), "IRC bot mode flag"),
    )
    irc_configuration.endpoint()
    irc_configuration.transport_policy()

    log_level = _text(runtime["log_level"], "runtime log level").upper()
    if log_level not in _LOG_LEVELS:
        raise ValueError("runtime log level is unsupported")
    process_configuration = ProcessConfiguration(
        log_level=log_level,
        state_directory=_path(runtime["state_directory"], "state directory"),
        log_directory=_path(runtime["log_directory"], "log directory"),
        ranking_page_path=_optional_html_path(
            runtime.get("ranking_page_path"),
            "ranking page",
        ),
        metrics_page_path=_optional_metrics_path(
            runtime.get("metrics_page_path"),
            "metrics page",
        ),
    )

    game_configuration = GameConfiguration(
        enabled=_truth(game["enabled"], "game enabled flag"),
        flights_per_day=_integer(game["flights_per_day"], "flights per day"),
        golden_weight_per_eighteen=_integer(
            game["golden_weight_per_eighteen"],
            "golden weight",
        ),
        flight_lifetime_seconds=_integer(
            game["flight_lifetime_seconds"],
            "flight lifetime",
        ),
        unusual_loot_chance_per_thousand=_integer(
            game["unusual_loot_chance_per_thousand"],
            "unusual loot chance",
        ),
        shop_url=normalize_shop_url(game.get("shop_url")),
        ranking_url=normalize_ranking_url(game.get("ranking_url")),
        anti_cheat=_truth(game.get("anti_cheat", False), "anti-cheat flag"),
    )
    _validate_game_boundary(game_configuration)
    partyline_configuration = PartylineConfiguration()
    if partyline is not None:
        accounts = _string_array(
            partyline["bootstrap_accounts"],
            "partyline bootstrap accounts",
        )
        masks = _string_array(
            partyline["bootstrap_masks"],
            "partyline bootstrap masks",
        )
        public_ip = partyline["dcc_public_ip"]
        if public_ip == "":
            public_ip = None
        elif type(public_ip) is not str:
            raise ValueError("DCC public IP must be text")
        partyline_configuration = PartylineConfiguration(
            enabled=_truth(partyline["enabled"], "partyline enabled flag"),
            bind_host=_text(partyline["bind_host"], "partyline bind host"),
            port=_integer(partyline["port"], "partyline port"),
            bootstrap_accounts=accounts,
            bootstrap_masks=masks,
            dcc_public_ip=public_ip,
            dcc_port_min=_integer(partyline["dcc_port_min"], "DCC minimum port"),
            dcc_port_max=_integer(partyline["dcc_port_max"], "DCC maximum port"),
            spontaneous_launch_enabled=_truth(
                partyline.get("spontaneous_launch_enabled", False),
                "spontaneous launch flag",
            ),
            spontaneous_launch_channel=_optional_channel(
                partyline.get("spontaneous_launch_channel"),
                "spontaneous launch channel",
            ),
            spontaneous_launch_min_seconds=_integer(
                partyline.get("spontaneous_launch_min_seconds", 0),
                "spontaneous launch minimum",
            ),
            spontaneous_launch_max_seconds=_integer(
                partyline.get("spontaneous_launch_max_seconds", 0),
                "spontaneous launch maximum",
            ),
            spontaneous_launch_announcement=_text(
                partyline.get(
                    "spontaneous_launch_announcement",
                    "allez, je lance un canard",
                ),
                "spontaneous launch announcement",
            ),
        )
        spontaneous_channel = partyline_configuration.spontaneous_launch_channel
        if spontaneous_channel is not None and not any(
            rfc1459_casefold(spontaneous_channel) == rfc1459_casefold(channel)
            for channel in irc_configuration.channels
        ):
            raise ValueError("spontaneous launch channel is not configured for IRC")
    return ApplicationConfiguration(
        irc_configuration,
        process_configuration,
        game_configuration,
        partyline_configuration,
    )


def resolve_irc_server_password(
    configuration: IRCConfiguration,
    environment: Mapping[str, str],
) -> str | None:
    """Resolve the configured secret explicitly, without retaining its mapping."""

    if not isinstance(configuration, IRCConfiguration):
        raise ValueError("IRC password resolution requires IRC configuration")
    if not isinstance(environment, Mapping):
        raise ValueError("IRC password resolution requires an environment mapping")
    value = environment.get(configuration.password_environment)
    if value is None:
        return None
    if type(value) is not str or not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ValueError("IRC server password is invalid")
    return value


def _exact_mapping(
    value: object,
    label: str,
    keys: tuple[str, ...],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        type(key) is not str for key in value
    ):
        raise ValueError(f"{label} must be a mapping")
    if set(value) != set(keys):
        raise ValueError(f"{label} fields do not match the supported schema")
    return value


def _mapping_with_optional(
    value: object,
    label: str,
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{label} must be a mapping")
    keys = set(value)
    if not set(required) <= keys or keys - set(required) - set(optional):
        raise ValueError(f"{label} fields do not match the supported schema")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ValueError(f"{label} must be safe non-empty text")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def _truth(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a truth value")
    return value


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError(f"{label} must be a string array")
    return tuple(value)


def _path(value: object, label: str) -> Path:
    text = _text(value, label)
    path = Path(text)
    if (
        text.strip() != text
        or path in (Path("."), Path("/"))
        or ".." in path.parts
    ):
        raise ValueError(f"{label} is not a safe path")
    return path


def _optional_html_path(value: object, label: str) -> Path | None:
    if value is None or value == "":
        return None
    path = _path(value, label)
    if not path.is_absolute() or path.suffix.casefold() != ".html":
        raise ValueError(f"{label} must be an absolute HTML path")
    return path


def _optional_metrics_path(value: object, label: str) -> Path | None:
    if value is None or value == "":
        return None
    path = _path(value, label)
    if (
        not path.is_absolute()
        or path == Path("/")
        or path.name in ("", ".", "..")
        or path.suffix.casefold() != ".prom"
        or ".." in path.parts
    ):
        raise ValueError(f"{label} must be a safe absolute .prom path")
    return path


def _optional_channel(value: object, label: str) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, label)


def _validate_game_boundary(configuration: GameConfiguration) -> None:
    if configuration.flights_per_day != 18:
        raise ValueError("configured daily flight count is not calibrated")
    if configuration.golden_weight_per_eighteen != 1:
        raise ValueError("configured golden weight is not calibrated")
    if configuration.flight_lifetime_seconds != 300:
        raise ValueError("configured flight lifetime is not calibrated")
    if configuration.unusual_loot_chance_per_thousand != 0:
        raise ValueError("uncalibrated unusual loot must remain disabled")
