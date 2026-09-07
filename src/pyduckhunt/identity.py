"""IRC identity normalization shared by protocol and game layers."""

from __future__ import annotations


_RFC1459_CASEMAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[]\\^",
    "abcdefghijklmnopqrstuvwxyz{}|~",
)


def rfc1459_casefold(value: str) -> str:
    """Return the canonical RFC1459 form of a nickname or channel."""

    return value.translate(_RFC1459_CASEMAP)


def same_irc_name(left: str, right: str) -> bool:
    """Compare two IRC identifiers using the RFC1459 casemapping."""

    return rfc1459_casefold(left) == rfc1459_casefold(right)
