"""Parse the stable public command vocabulary into domain intents."""

from __future__ import annotations

from pyduckhunt.i18n import tr, localized, localized_method

from dataclasses import dataclass
from enum import Enum


class CommandKind(str, Enum):
    SHOT = "shot"
    RELOAD = "reload"
    SHOP = "shop"
    INVENTORY = "inventory"
    STATS = "stats"
    LAST_FLIGHT = "last_flight"
    RANK = "rank"


_ALIASES = {
    "bang": CommandKind.SHOT,
    "pan": CommandKind.SHOT,
    "reload": CommandKind.RELOAD,
    "shop": CommandKind.SHOP,
    "inventory": CommandKind.INVENTORY,
    "duckstats": CommandKind.STATS,
    "lastduck": CommandKind.LAST_FLIGHT,
    "duckrank": CommandKind.RANK,
}


@dataclass(frozen=True, slots=True)
class Command:
    kind: CommandKind
    invoked_as: str
    arguments: tuple[str, ...] = ()


class CommandSyntaxError(ValueError):
    """Raised when a known command has an invalid public argument shape."""


_USAGE = {
    CommandKind.SHOT: "!bang",
    CommandKind.RELOAD: "!reload",
    CommandKind.SHOP: "!shop [id [cible]]",
    CommandKind.INVENTORY: "!inventory [nick]",
    CommandKind.STATS: "!duckstats [nick]",
    CommandKind.LAST_FLIGHT: "!lastduck",
    CommandKind.RANK: "!duckrank [limite]",
}


@localized
def command_usage(command: Command | CommandKind) -> str:
    """Return the stable public syntax for a parsed command."""

    kind = command.kind if isinstance(command, Command) else command
    return tr(_USAGE[kind])


def validate_command(command: Command, *, maximum_rank_limit: int = 20) -> Command:
    """Validate calibrated argument arity without mutating the parsed command."""

    if type(maximum_rank_limit) is not int or maximum_rank_limit < 1:
        raise ValueError("maximum rank limit must be a positive integer")

    arguments = command.arguments
    if command.kind in (CommandKind.SHOT, CommandKind.RELOAD, CommandKind.LAST_FLIGHT):
        valid = not arguments
    elif command.kind in (CommandKind.INVENTORY, CommandKind.STATS):
        valid = len(arguments) <= 1
    elif command.kind is CommandKind.SHOP:
        valid = len(arguments) <= 2
        if arguments:
            valid = valid and arguments[0].isascii() and arguments[0].isdigit()
            valid = valid and int(arguments[0]) > 0
    elif command.kind is CommandKind.RANK:
        valid = len(arguments) <= 1
        if arguments:
            valid = valid and arguments[0].isascii() and arguments[0].isdigit()
            valid = valid and 1 <= int(arguments[0]) <= maximum_rank_limit
    else:  # pragma: no cover - the enum makes this defensive branch unreachable.
        valid = False

    if not valid:
        raise CommandSyntaxError(tr('syntaxe : {0}', command_usage(command)))
    return command


def rank_limit(command: Command, *, default: int = 5, maximum: int = 20) -> int:
    """Resolve the optional bounded ranking size after syntax validation."""

    if command.kind is not CommandKind.RANK:
        raise ValueError("rank limit requires the rank command")
    if type(default) is not int or not 1 <= default <= maximum:
        raise ValueError("default rank limit must be inside the public boundary")
    validate_command(command, maximum_rank_limit=maximum)
    return default if not command.arguments else int(command.arguments[0])


def parse_command(text: str, *, prefix: str = "!") -> Command | None:
    """Parse an exact command at the start of an IRC PRIVMSG."""

    if not prefix or not text.startswith(prefix) or text.startswith("\x01"):
        return None
    remainder = text[len(prefix) :]
    if not remainder or remainder[0].isspace():
        return None
    words = remainder.split()
    invoked_as = words[0].casefold()
    kind = _ALIASES.get(invoked_as)
    if kind is None:
        return None
    return Command(kind=kind, invoked_as=invoked_as, arguments=tuple(words[1:]))
