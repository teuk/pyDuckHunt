"""Strict, private and atomic partyline credential storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pyduckhunt.identity import rfc1459_casefold


_HANDLE = re.compile(r"[A-Za-z0-9_\[\]\\{}^`|\-]{1,32}\Z")
_MAX_DATABASE_BYTES = 65_536
_MAX_USERS = 32
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_BYTES = 32
_SALT_BYTES = 16
_DUMMY_SALT = hashlib.sha256(b"Coin partyline unknown handle").digest()[:_SALT_BYTES]
_LEGACY_PASSWORD_MINIMUM = 8
_NEW_PASSWORD_MINIMUM = 12


class PartylineCredentialError(ValueError):
    """The private partyline credential store violates its contract."""


@dataclass(frozen=True, slots=True)
class PartylineUser:
    handle: str
    salt: bytes
    password_digest: bytes
    created_at_ns: int
    irc_account: str | None = None
    irc_mask: str | None = None
    role: str = "owner"

    def __post_init__(self) -> None:
        if not _HANDLE.fullmatch(self.handle):
            raise PartylineCredentialError("partyline handle is invalid")
        if type(self.salt) is not bytes or len(self.salt) != _SALT_BYTES:
            raise PartylineCredentialError("partyline password salt is invalid")
        if (
            type(self.password_digest) is not bytes
            or len(self.password_digest) != _KEY_BYTES
        ):
            raise PartylineCredentialError("partyline password digest is invalid")
        if type(self.created_at_ns) is not int or self.created_at_ns < 0:
            raise PartylineCredentialError("partyline creation time is invalid")
        for label, value in (
            ("IRC account", self.irc_account),
            ("IRC mask", self.irc_mask),
        ):
            if value is not None and (
                type(value) is not str
                or not value
                or len(value) > 255
                or any(character in value for character in ("\x00", "\r", "\n", " "))
            ):
                raise PartylineCredentialError(f"partyline {label} is invalid")
        if self.role != "owner":
            raise PartylineCredentialError("partyline role is unsupported")


class PartylineUserStore:
    """Own the small credential database without exposing password material."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute() or self.path.name in ("", ".", ".."):
            raise PartylineCredentialError("partyline user path must be absolute")

    def users(self) -> tuple[PartylineUser, ...]:
        if self.path.is_symlink():
            raise PartylineCredentialError("partyline user database cannot be a symlink")
        if not self.path.exists():
            return ()
        try:
            metadata = self.path.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PartylineCredentialError("partyline user database is not regular")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise PartylineCredentialError("partyline user database is not private")
            if metadata.st_size > _MAX_DATABASE_BYTES:
                raise PartylineCredentialError("partyline user database is too large")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except PartylineCredentialError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PartylineCredentialError("partyline user database cannot be loaded") from error
        if not isinstance(raw, dict) or set(raw) != {"users", "version"} or raw["version"] != 1:
            raise PartylineCredentialError("partyline user database schema is invalid")
        rows = raw["users"]
        if not isinstance(rows, list) or len(rows) > _MAX_USERS:
            raise PartylineCredentialError("partyline user list is invalid")
        users = tuple(self._decode_user(row) for row in rows)
        keys = tuple(rfc1459_casefold(user.handle) for user in users)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise PartylineCredentialError("partyline users are not unique and sorted")
        return users

    def has_users(self) -> bool:
        return bool(self.users())

    def find(self, handle: str) -> PartylineUser | None:
        if type(handle) is not str:
            return None
        key = rfc1459_casefold(handle)
        return next(
            (user for user in self.users() if rfc1459_casefold(user.handle) == key),
            None,
        )

    def verify(self, handle: str, password: str) -> PartylineUser | None:
        user = self.find(handle)
        # Existing deployments may contain credentials created before the
        # twelve-character policy.  Verification keeps that bounded legacy
        # compatibility; creation and rotation remain subject to the stronger
        # current policy.
        if not _valid_password(password, minimum=_LEGACY_PASSWORD_MINIMUM):
            return None
        candidate = _password_digest(
            password,
            _DUMMY_SALT if user is None else user.salt,
        )
        if user is None:
            return None
        return user if hmac.compare_digest(candidate, user.password_digest) else None

    def change_password(self, handle: str, password: str) -> PartylineUser:
        """Rotate one existing owner's password without changing IRC identity."""

        user = self.find(handle)
        if user is None:
            raise PartylineCredentialError("partyline owner does not exist")
        if not _valid_password(password, minimum=_NEW_PASSWORD_MINIMUM):
            raise PartylineCredentialError(
                "partyline password must contain 12 to 128 safe characters"
            )
        salt = os.urandom(_SALT_BYTES)
        updated = PartylineUser(
            handle=user.handle,
            salt=salt,
            password_digest=_password_digest(password, salt),
            created_at_ns=user.created_at_ns,
            irc_account=user.irc_account,
            irc_mask=user.irc_mask,
            role=user.role,
        )
        self._write(
            tuple(updated if candidate == user else candidate for candidate in self.users())
        )
        return updated

    def owner_for_irc(
        self,
        nickname: str,
        *,
        prefix: str | None,
        account: str | None,
    ) -> PartylineUser | None:
        """Resolve an IRC identity to its stored owner without trusting nick alone."""

        user = self.find(nickname)
        if user is None or user.role != "owner":
            return None
        normalized_account = None if account in (None, "*") else account
        if normalized_account is not None:
            if user.irc_account is None or not hmac.compare_digest(
                normalized_account.casefold(),
                user.irc_account.casefold(),
            ):
                return None
            return user
        if prefix is None or user.irc_mask is None:
            return None
        return (
            user
            if hmac.compare_digest(
                rfc1459_casefold(prefix),
                rfc1459_casefold(user.irc_mask),
            )
            else None
        )

    def create_first_owner(
        self,
        handle: str,
        password: str,
        now_ns: int,
        *,
        irc_account: str | None,
        irc_mask: str | None,
    ) -> PartylineUser:
        if self.users():
            raise PartylineCredentialError("partyline already has an owner")
        if not _HANDLE.fullmatch(handle):
            raise PartylineCredentialError("partyline handle is invalid")
        if not _valid_password(password, minimum=_NEW_PASSWORD_MINIMUM):
            raise PartylineCredentialError(
                "partyline password must contain 12 to 128 safe characters"
            )
        salt = os.urandom(_SALT_BYTES)
        user = PartylineUser(
            handle=handle,
            salt=salt,
            password_digest=_password_digest(password, salt),
            created_at_ns=now_ns,
            irc_account=irc_account,
            irc_mask=irc_mask,
        )
        self._write((user,))
        return user

    @staticmethod
    def _decode_user(raw: object) -> PartylineUser:
        if not isinstance(raw, dict) or set(raw) != {
            "created_at_ns",
            "handle",
            "irc_account",
            "irc_mask",
            "password_digest",
            "role",
            "salt",
        }:
            raise PartylineCredentialError("partyline user record schema is invalid")
        try:
            salt = base64.b64decode(raw["salt"], validate=True)
            digest = base64.b64decode(raw["password_digest"], validate=True)
            return PartylineUser(
                handle=raw["handle"],
                salt=salt,
                password_digest=digest,
                created_at_ns=raw["created_at_ns"],
                irc_account=raw["irc_account"],
                irc_mask=raw["irc_mask"],
                role=raw["role"],
            )
        except (TypeError, ValueError) as error:
            raise PartylineCredentialError("partyline user record values are invalid") from error

    def _write(self, users: tuple[PartylineUser, ...]) -> None:
        ordered = tuple(sorted(users, key=lambda user: rfc1459_casefold(user.handle)))
        payload = {
            "users": [
                {
                    "created_at_ns": user.created_at_ns,
                    "handle": user.handle,
                    "irc_account": user.irc_account,
                    "irc_mask": user.irc_mask,
                    "password_digest": base64.b64encode(user.password_digest).decode("ascii"),
                    "role": user.role,
                    "salt": base64.b64encode(user.salt).decode("ascii"),
                }
                for user in ordered
            ],
            "version": 1,
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_DATABASE_BYTES:
            raise PartylineCredentialError("partyline user database exceeds its bound")
        self.path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _valid_password(password: object, *, minimum: int) -> bool:
    return (
        type(password) is str
        and minimum <= len(password) <= 128
        and not any(character in password for character in ("\x00", "\r", "\n"))
    )


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )
