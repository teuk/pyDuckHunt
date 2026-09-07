"""Append-only JSONL journal with sequence and digest-chain validation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from pyduckhunt.persistence.codec import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    CodecError,
    canonical_json_bytes,
)
from pyduckhunt.persistence.event import ReplayEvent


GENESIS_DIGEST = "0" * 64
MAX_RECORD_BYTES = 16_384


class JournalIntegrityError(CodecError):
    """Raised when journal framing, sequence or digest integrity fails."""


@dataclass(frozen=True, slots=True)
class JournalRecord:
    sequence: int
    previous_digest: str
    digest: str
    event: ReplayEvent
    source_schema: int = SCHEMA_VERSION


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _body(
    sequence: int,
    previous_digest: str,
    event: ReplayEvent,
    *,
    schema: int = SCHEMA_VERSION,
) -> dict[str, object]:
    return {
        "event": event.to_payload(),
        "previous_digest": previous_digest,
        "schema": schema,
        "sequence": sequence,
    }


def _digest(body: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _encode_record(record: JournalRecord) -> bytes:
    body = _body(
        record.sequence,
        record.previous_digest,
        record.event,
        schema=record.source_schema,
    )
    envelope = {**body, "digest": record.digest}
    line = canonical_json_bytes(envelope) + b"\n"
    if len(line) > MAX_RECORD_BYTES:
        raise JournalIntegrityError("journal record exceeds the bounded line size")
    return line


def _decode_record(
    line: bytes,
    *,
    expected_sequence: int,
    expected_previous: str,
) -> JournalRecord:
    if not line.endswith(b"\n"):
        raise JournalIntegrityError("journal ends with a partial record")
    if len(line) > MAX_RECORD_BYTES:
        raise JournalIntegrityError("journal record exceeds the bounded line size")
    try:
        raw = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JournalIntegrityError("journal record is not valid UTF-8 JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "digest",
        "event",
        "previous_digest",
        "schema",
        "sequence",
    }:
        raise JournalIntegrityError("journal record fields differ from schema")
    if raw["schema"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise JournalIntegrityError("journal schema version is unsupported")
    if type(raw["sequence"]) is not int or raw["sequence"] != expected_sequence:
        raise JournalIntegrityError("journal sequence is not contiguous")
    if raw["previous_digest"] != expected_previous:
        raise JournalIntegrityError("journal digest chain is broken")
    if not _is_digest(raw["digest"]):
        raise JournalIntegrityError("journal digest is invalid")
    try:
        event = ReplayEvent.from_payload(raw["event"])
    except (CodecError, ValueError) as error:
        raise JournalIntegrityError("journal event violates its schema") from error
    body = _body(
        raw["sequence"],
        raw["previous_digest"],
        event,
        schema=raw["schema"],
    )
    if _digest(body) != raw["digest"]:
        raise JournalIntegrityError("journal record digest does not match its payload")
    return JournalRecord(
        sequence=raw["sequence"],
        previous_digest=raw["previous_digest"],
        digest=raw["digest"],
        event=event,
        source_schema=raw["schema"],
    )


class JournalFile:
    """Single-process append-only writer and strict reader."""

    def __init__(self, path: Path, *, sync: bool = True) -> None:
        self.path = Path(path)
        self.sync = sync
        self._lock = threading.Lock()
        self._tail: tuple[int, str] | None = None

    def read_records(self) -> tuple[JournalRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[JournalRecord] = []
        expected_previous = GENESIS_DIGEST
        try:
            with self.path.open("rb") as handle:
                for expected_sequence, line in enumerate(handle, start=1):
                    record = _decode_record(
                        line,
                        expected_sequence=expected_sequence,
                        expected_previous=expected_previous,
                    )
                    records.append(record)
                    expected_previous = record.digest
        except OSError as error:
            raise JournalIntegrityError(f"unable to read journal: {error}") from error
        return tuple(records)

    def _load_tail(self) -> tuple[int, str]:
        records = self.read_records()
        if not records:
            return (0, GENESIS_DIGEST)
        return (records[-1].sequence, records[-1].digest)

    def append(self, event: ReplayEvent) -> JournalRecord:
        """Append one bounded record with one O_APPEND write."""

        with self._lock:
            if self._tail is None:
                self._tail = self._load_tail()
            last_sequence, previous_digest = self._tail
            sequence = last_sequence + 1
            body = _body(sequence, previous_digest, event)
            record = JournalRecord(
                sequence=sequence,
                previous_digest=previous_digest,
                digest=_digest(body),
                event=event,
            )
            encoded = _encode_record(record)
            self.path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o640,
            )
            try:
                os.fchmod(descriptor, 0o640)
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise JournalIntegrityError("journal append was incomplete")
                if self.sync:
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._tail = (record.sequence, record.digest)
            return record
