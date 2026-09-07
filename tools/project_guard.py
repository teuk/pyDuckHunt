#!/usr/bin/env python3
"""Validate that the publishable tree contains only safe project material."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Iterable
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "backups",
    "corpus",
    "exports",
    "logs",
    "private",
    "reference",
    "state",
    "venv",
}
DENIED_SUFFIXES = {
    ".db",
    ".flac",
    ".gz",
    ".log",
    ".mp3",
    ".ogg",
    ".sqlite",
    ".sqlite3",
    ".wav",
    ".weechatlog",
    ".xz",
    ".zip",
}
DENIED_FILENAMES = {".env", "commit.sh"}
MAX_PUBLIC_FILE_BYTES = 1_048_576

# Private identifiers are represented only by one-way digests. The scanner
# compares case-insensitive sliding windows and never needs their clear text.
BLOCKED_WINDOW_DIGESTS = {
    5: {
        "5aaaa62ecf0aff849f36f52d6640ca4995acfadc64ed340584eb6f7b8f2b00ea",
    },
    7: {
        "6a082c833e642de9ae1b223852e70fb6937a3ca293ccf5faf701f0093f824e69",
        "c1cb6b91008e205f7b37e66d719f7ace437fc7cad44195abfb00b6c5c634a944",
    },
}

# The original-author name and scripts.eggdrop.fr are intentionally public in
# the required CC BY-NC-SA 3.0 attribution. They are therefore not part of the
# private-identifier digest set.

SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "generic secret assignment": re.compile(
        rb"(?i)\b(?:api[_-]?key|password|secret|token)\s*=\s*[\"'][^\"']{12,}[\"']"
    ),
}


def iter_public_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_file() or path.is_symlink():
            yield path


def blocked_digest(data: bytes) -> str | None:
    folded = data.lower()
    for window_size, forbidden in BLOCKED_WINDOW_DIGESTS.items():
        if len(folded) < window_size:
            continue
        for offset in range(0, len(folded) - window_size + 1):
            digest = hashlib.sha256(folded[offset : offset + window_size]).hexdigest()
            if digest in forbidden:
                return digest
    return None


def inspect_file(root: Path, path: Path) -> list[str]:
    relative = path.relative_to(root)
    issues: list[str] = []

    if path.is_symlink():
        return [f"{relative}: symbolic links are not allowed"]
    if path.name in DENIED_FILENAMES:
        issues.append(f"{relative}: denied private/operator filename")
    if path.suffix.lower() in DENIED_SUFFIXES:
        issues.append(f"{relative}: denied private/runtime file suffix")

    size = path.stat().st_size
    if size > MAX_PUBLIC_FILE_BYTES:
        issues.append(f"{relative}: public file exceeds 1 MiB")
        return issues

    payload = path.read_bytes()
    path_digest = blocked_digest(relative.as_posix().encode("utf-8"))
    content_digest = blocked_digest(payload)
    if path_digest or content_digest:
        issues.append(f"{relative}: blocked private identifier digest detected")

    if b"\x00" in payload:
        issues.append(f"{relative}: NUL byte detected")
        return issues
    if b"\r" in payload:
        issues.append(f"{relative}: CR byte detected; LF-only text is required")
    if payload and not payload.endswith(b"\n"):
        issues.append(f"{relative}: missing final newline")

    for line_number, line in enumerate(payload.splitlines(), start=1):
        if line.rstrip(b" \t") != line:
            issues.append(f"{relative}:{line_number}: trailing whitespace")

    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(payload):
            issues.append(f"{relative}: possible {label}")

    return issues


def inspect_tree(root: Path) -> tuple[list[str], int]:
    issues: list[str] = []
    count = 0
    for path in iter_public_files(root):
        count += 1
        issues.extend(inspect_file(root, path))
    return issues, count


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"[KO] Project root is not a directory: {root}", file=sys.stderr)
        return 2

    issues, count = inspect_tree(root)
    if issues:
        for issue in issues:
            print(f"[KO] {issue}", file=sys.stderr)
        print(f"[KO] Public-tree policy failed with {len(issues)} issue(s).", file=sys.stderr)
        return 1

    print(f"[OK] Public-tree policy passed ({count} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
