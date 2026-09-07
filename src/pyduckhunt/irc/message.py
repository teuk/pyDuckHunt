"""Parse and render bounded IRC messages without opening a socket."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


MAX_WIRE_BYTES = 512
MAX_PARAMS = 15
_COMMAND_PATTERN = re.compile(r"(?:[A-Za-z]+|[0-9]{3})\Z")
_FORBIDDEN_TEXT = frozenset(("\x00", "\r", "\n"))
_TAG_UNESCAPE = {":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}
_TAG_ESCAPE = str.maketrans({";": r"\:", " ": r"\s", "\\": r"\\", "\r": r"\r", "\n": r"\n"})


class IRCProtocolError(ValueError):
    """Raised when an IRC line violates a boundary required by pyDuckHunt."""


@dataclass(frozen=True, slots=True)
class IRCMessage:
    """One decoded IRC message."""

    command: str
    params: tuple[str, ...] = ()
    prefix: str | None = None
    tags: tuple[tuple[str, str | None], ...] = ()

    @property
    def nickname(self) -> str | None:
        """Return the nickname portion of the prefix, when present."""

        if self.prefix is None:
            return None
        return self.prefix.split("!", 1)[0].split("@", 1)[0]

    def tag(self, key: str) -> str | None:
        """Return the last value associated with *key*."""

        for candidate, value in reversed(self.tags):
            if candidate == key:
                return value
        return None


def _ensure_safe_text(value: str, field: str) -> None:
    if any(character in value for character in _FORBIDDEN_TEXT):
        raise IRCProtocolError(f"{field} contains a forbidden control character")


def _decode_tag_value(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\" or index + 1 >= len(value):
            result.append(character)
            index += 1
            continue
        index += 1
        escaped = value[index]
        result.append(_TAG_UNESCAPE.get(escaped, escaped))
        index += 1
    return "".join(result)


def _parse_tags(raw_tags: str) -> tuple[tuple[str, str | None], ...]:
    parsed: list[tuple[str, str | None]] = []
    for raw_tag in raw_tags.split(";"):
        if not raw_tag:
            raise IRCProtocolError("an IRCv3 tag key is empty")
        key, separator, value = raw_tag.partition("=")
        _ensure_safe_text(key, "tag key")
        parsed.append((key, _decode_tag_value(value) if separator else None))
    return tuple(parsed)


def _without_wire_ending(line: str | bytes) -> str:
    if isinstance(line, bytes):
        wire = line
        assumed_ending_bytes = 0 if wire.endswith(b"\r\n") else 2
        if len(wire) + assumed_ending_bytes > MAX_WIRE_BYTES:
            raise IRCProtocolError("IRC line exceeds 512 wire bytes")
        text = wire.decode("utf-8", errors="replace")
    else:
        text = line
        wire_length = len(text.encode("utf-8"))
        if text.endswith("\r\n"):
            if wire_length > MAX_WIRE_BYTES:
                raise IRCProtocolError("IRC line exceeds 512 wire bytes")
        elif wire_length + 2 > MAX_WIRE_BYTES:
            raise IRCProtocolError("IRC line exceeds 512 wire bytes")

    if text.endswith("\r\n"):
        text = text[:-2]
    if "\r" in text or "\n" in text or "\x00" in text:
        raise IRCProtocolError("IRC input contains an embedded line break or NUL")
    if not text:
        raise IRCProtocolError("IRC line is empty")
    return text


def parse_irc_line(line: str | bytes) -> IRCMessage:
    """Parse one complete IRC line into an immutable message."""

    remaining = _without_wire_ending(line)
    tags: tuple[tuple[str, str | None], ...] = ()
    prefix: str | None = None

    if remaining.startswith("@"):
        raw_tags, separator, remaining = remaining[1:].partition(" ")
        if not separator:
            raise IRCProtocolError("IRCv3 tags are not followed by a command")
        tags = _parse_tags(raw_tags)
        remaining = remaining.lstrip(" ")

    if remaining.startswith(":"):
        prefix, separator, remaining = remaining[1:].partition(" ")
        if not separator or not prefix:
            raise IRCProtocolError("IRC prefix is not followed by a command")
        remaining = remaining.lstrip(" ")

    command, separator, remaining = remaining.partition(" ")
    if not _COMMAND_PATTERN.fullmatch(command):
        raise IRCProtocolError(f"invalid IRC command: {command!r}")

    params: list[str] = []
    while separator:
        remaining = remaining.lstrip(" ")
        if not remaining:
            break
        if remaining.startswith(":"):
            params.append(remaining[1:])
            remaining = ""
            separator = ""
            break
        parameter, separator, remaining = remaining.partition(" ")
        params.append(parameter)

    if len(params) > MAX_PARAMS:
        raise IRCProtocolError("IRC message has more than 15 parameters")

    return IRCMessage(
        command=command.upper(),
        params=tuple(params),
        prefix=prefix,
        tags=tags,
    )


def _serialized_tags(tags: Mapping[str, str | None] | Iterable[tuple[str, str | None]]) -> str:
    items = tags.items() if isinstance(tags, Mapping) else tags
    rendered: list[str] = []
    for key, value in items:
        if not key or ";" in key or " " in key:
            raise IRCProtocolError(f"invalid IRCv3 tag key: {key!r}")
        _ensure_safe_text(key, "tag key")
        rendered.append(key if value is None else f"{key}={value.translate(_TAG_ESCAPE)}")
    return ";".join(rendered)


def render_irc_message(
    command: str,
    params: Sequence[str] = (),
    *,
    tags: Mapping[str, str | None] | Iterable[tuple[str, str | None]] = (),
) -> bytes:
    """Render one client command, enforcing injection and wire-size limits."""

    normalized_command = command.upper()
    if not _COMMAND_PATTERN.fullmatch(normalized_command):
        raise IRCProtocolError(f"invalid IRC command: {command!r}")
    if len(params) > MAX_PARAMS:
        raise IRCProtocolError("IRC message has more than 15 parameters")

    parts: list[str] = []
    rendered_tags = _serialized_tags(tags)
    if rendered_tags:
        parts.append(f"@{rendered_tags}")
    parts.append(normalized_command)

    for index, parameter in enumerate(params):
        _ensure_safe_text(parameter, "parameter")
        last = index == len(params) - 1
        needs_trailing = last and (
            parameter == "" or " " in parameter or parameter.startswith(":")
        )
        if not last and (not parameter or " " in parameter or parameter.startswith(":")):
            raise IRCProtocolError("only the final IRC parameter may contain spaces or be empty")
        parts.append(f":{parameter}" if needs_trailing else parameter)

    wire = (" ".join(parts) + "\r\n").encode("utf-8")
    if len(wire) > MAX_WIRE_BYTES:
        raise IRCProtocolError("IRC line exceeds 512 wire bytes")
    return wire


def render_privmsg(target: str, text: str) -> bytes:
    """Render a bounded PRIVMSG."""

    if not target or " " in target or target.startswith(":"):
        raise IRCProtocolError("invalid PRIVMSG target")
    return render_irc_message("PRIVMSG", (target, text))


def render_notice(target: str, text: str) -> bytes:
    """Render a bounded NOTICE."""

    if not target or " " in target or target.startswith(":"):
        raise IRCProtocolError("invalid NOTICE target")
    return render_irc_message("NOTICE", (target, text))


def privmsg_text_budget(target: str) -> int:
    """Return the conservative UTF-8 payload budget for one PRIVMSG."""

    if not target or " " in target or target.startswith(":"):
        raise IRCProtocolError("invalid PRIVMSG target")
    _ensure_safe_text(target, "PRIVMSG target")
    overhead = len(f"PRIVMSG {target} :\r\n".encode("utf-8"))
    budget = MAX_WIRE_BYTES - overhead
    if budget < 1:
        raise IRCProtocolError("PRIVMSG target leaves no text budget")
    return budget


def notice_text_budget(target: str) -> int:
    """Return the conservative UTF-8 payload budget for one NOTICE."""

    if not target or " " in target or target.startswith(":"):
        raise IRCProtocolError("invalid NOTICE target")
    _ensure_safe_text(target, "NOTICE target")
    overhead = len(f"NOTICE {target} :\r\n".encode("utf-8"))
    budget = MAX_WIRE_BYTES - overhead
    if budget < 1:
        raise IRCProtocolError("NOTICE target leaves no text budget")
    return budget


def _utf8_prefix(value: str, byte_limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value
    return encoded[:byte_limit].decode("utf-8", errors="ignore")


def render_privmsg_bounded(target: str, text: str, *, ellipsis: str = "…") -> bytes:
    """Render one PRIVMSG, shortening only at a valid UTF-8 boundary."""

    _ensure_safe_text(text, "PRIVMSG text")
    _ensure_safe_text(ellipsis, "PRIVMSG ellipsis")
    budget = privmsg_text_budget(target)
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return render_privmsg(target, text)

    suffix = ellipsis.encode("utf-8")
    if len(suffix) > budget:
        raise IRCProtocolError("PRIVMSG ellipsis exceeds the text budget")
    shortened = _utf8_prefix(text, budget - len(suffix)) + ellipsis
    return render_privmsg(target, shortened)


def render_notice_bounded(target: str, text: str, *, ellipsis: str = "…") -> bytes:
    """Render one NOTICE, shortening only at a valid UTF-8 boundary."""

    _ensure_safe_text(text, "NOTICE text")
    _ensure_safe_text(ellipsis, "NOTICE ellipsis")
    budget = notice_text_budget(target)
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return render_notice(target, text)

    suffix = ellipsis.encode("utf-8")
    if len(suffix) > budget:
        raise IRCProtocolError("NOTICE ellipsis exceeds the text budget")
    shortened = _utf8_prefix(text, budget - len(suffix)) + ellipsis
    return render_notice(target, shortened)


def render_pong(ping: IRCMessage) -> bytes:
    """Render the PONG corresponding to a parsed PING."""

    if ping.command != "PING" or not ping.params:
        raise IRCProtocolError("PONG requires a PING with at least one parameter")
    return render_irc_message("PONG", ping.params)
