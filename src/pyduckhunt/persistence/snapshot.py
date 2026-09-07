"""Checksummed snapshots committed with fsync and atomic replacement."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pyduckhunt.game.model import GameState
from pyduckhunt.persistence.codec import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    CodecError,
    canonical_json_bytes,
    decode_game_state,
    encode_game_state,
)
from pyduckhunt.persistence.journal import GENESIS_DIGEST


MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Snapshot:
    journal_sequence: int
    journal_digest: str
    state: GameState
    source_schema: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.journal_sequence) is not int or self.journal_sequence < 0:
            raise ValueError("snapshot journal sequence is invalid")
        if not _valid_digest(self.journal_digest):
            raise ValueError("snapshot journal digest is invalid")
        if self.journal_sequence == 0 and self.journal_digest != GENESIS_DIGEST:
            raise ValueError("empty snapshot must use the genesis digest")
        if self.source_schema not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("snapshot source schema is unsupported")


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _body(snapshot: Snapshot) -> dict[str, object]:
    return {
        "journal_digest": snapshot.journal_digest,
        "journal_sequence": snapshot.journal_sequence,
        "schema": SCHEMA_VERSION,
        "state": encode_game_state(snapshot.state),
    }


def _encode_snapshot(snapshot: Snapshot) -> bytes:
    body = _body(snapshot)
    checksum = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    encoded = canonical_json_bytes({**body, "checksum": checksum}) + b"\n"
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise CodecError("snapshot exceeds the bounded size")
    return encoded


def _decode_snapshot(encoded: bytes) -> Snapshot:
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise CodecError("snapshot exceeds the bounded size")
    if not encoded.endswith(b"\n"):
        raise CodecError("snapshot is not newline terminated")
    try:
        raw = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CodecError("snapshot is not valid UTF-8 JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "checksum",
        "journal_digest",
        "journal_sequence",
        "schema",
        "state",
    }:
        raise CodecError("snapshot fields differ from schema")
    if raw["schema"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise CodecError("snapshot schema version is unsupported")
    if type(raw["journal_sequence"]) is not int or raw["journal_sequence"] < 0:
        raise CodecError("snapshot journal sequence is invalid")
    if not _valid_digest(raw["journal_digest"]) or not _valid_digest(raw["checksum"]):
        raise CodecError("snapshot digest is invalid")
    if raw["journal_sequence"] == 0 and raw["journal_digest"] != GENESIS_DIGEST:
        raise CodecError("empty snapshot does not use the genesis digest")
    body = {key: raw[key] for key in ("journal_digest", "journal_sequence", "schema", "state")}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != raw["checksum"]:
        raise CodecError("snapshot checksum does not match its payload")
    return Snapshot(
        journal_sequence=raw["journal_sequence"],
        journal_digest=raw["journal_digest"],
        state=decode_game_state(raw["state"], schema_version=raw["schema"]),
        source_schema=raw["schema"],
    )


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> Snapshot | None:
        if not self.path.exists():
            return None
        try:
            return _decode_snapshot(self.path.read_bytes())
        except OSError as error:
            raise CodecError(f"unable to read snapshot: {error}") from error

    def write(self, snapshot: Snapshot) -> None:
        encoded = _encode_snapshot(snapshot)
        parent = self.path.parent
        parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.fchmod(handle.fileno(), 0o640)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
