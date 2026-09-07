"""Strict optional URLs for operator-controlled public resources."""

from __future__ import annotations

from urllib.parse import urlsplit


MAX_SHOP_URL_BYTES = 240


def normalize_shop_url(value: object) -> str | None:
    """Return one safe HTTPS catalog URL, or ``None`` when disabled."""

    if value is None or value == "":
        return None
    if type(value) is not str:
        raise ValueError("shop URL must be text")
    if (
        value.strip() != value
        or not value.isascii()
        or len(value.encode("ascii")) > MAX_SHOP_URL_BYTES
        or any(not 0x21 <= ord(character) <= 0x7E for character in value)
        or "\\" in value
    ):
        raise ValueError("shop URL must be bounded visible ASCII text")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("shop URL is malformed") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.path.startswith("//")
    ):
        raise ValueError("shop URL must be an absolute credential-free HTTPS URL")
    labels = hostname.split(".")
    if any(
        not 1 <= len(label) <= 63
        or not label[0].isalnum()
        or not label[-1].isalnum()
        or any(not (character.isalnum() or character == "-") for character in label)
        for label in labels
    ):
        raise ValueError("shop URL hostname is invalid")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("shop URL port is invalid")
    return value


def normalize_ranking_url(value: object) -> str | None:
    """Validate one optional ranking URL through the shared public boundary."""

    try:
        return normalize_shop_url(value)
    except ValueError as error:
        raise ValueError(str(error).replace("shop URL", "ranking URL")) from error
