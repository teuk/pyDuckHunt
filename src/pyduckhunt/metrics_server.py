"""Serve one validated Prometheus snapshot on an explicit loopback endpoint."""

from __future__ import annotations

import argparse
import os
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pyduckhunt.publishing.metrics_page import MAX_METRICS_PAGE_BYTES


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def read_metrics_file(path: Path, *, expected_uid: int) -> bytes:
    """Read one stable, regular, owner-controlled metrics snapshot."""

    if not isinstance(path, Path) or not path.is_absolute() or path.suffix != ".prom":
        raise ValueError("metrics source must be an absolute .prom path")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("metrics source is not a regular file")
        if before.st_uid != expected_uid or before.st_mode & 0o022:
            raise ValueError("metrics source ownership or mode is unsafe")
        if not 0 < before.st_size <= MAX_METRICS_PAGE_BYTES:
            raise ValueError("metrics source size is outside the boundary")
        payload = bytearray()
        while len(payload) <= MAX_METRICS_PAGE_BYTES:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or len(payload) > MAX_METRICS_PAGE_BYTES
        ):
            raise ValueError("metrics source changed while being read")
        if not payload.startswith(b"# pyDuckHunt aggregate metrics;"):
            raise ValueError("metrics source identity is absent")
        return bytes(payload)
    finally:
        os.close(descriptor)


class MetricsRequestHandler(BaseHTTPRequestHandler):
    """Expose only `/metrics` and a minimal health response."""

    server_version = "pyDuckHunt-metrics"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP method name
        self._respond(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - inherited HTTP method name
        self._respond(include_body=False)

    def _respond(self, *, include_body: bool) -> None:
        if self.path == "/-/healthy":
            self._write(HTTPStatus.OK, b"ok\n", include_body=include_body)
            return
        if self.path != "/metrics":
            self._write(HTTPStatus.NOT_FOUND, b"not found\n", include_body=include_body)
            return
        source = self.server.metrics_source  # type: ignore[attr-defined]
        expected_uid = self.server.expected_uid  # type: ignore[attr-defined]
        try:
            payload = read_metrics_file(source, expected_uid=expected_uid)
        except (OSError, ValueError):
            self._write(
                HTTPStatus.SERVICE_UNAVAILABLE,
                b"metrics unavailable\n",
                include_body=include_body,
            )
            return
        self._write(
            HTTPStatus.OK,
            payload,
            include_body=include_body,
            content_type=PROMETHEUS_CONTENT_TYPE,
        )

    def _write(
        self,
        status: HTTPStatus,
        payload: bytes,
        *,
        include_body: bool,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class MetricsHTTPServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], source: Path) -> None:
        self.metrics_source = source
        self.expected_uid = os.geteuid()
        super().__init__(address, MetricsRequestHandler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9817)
    parser.add_argument("--source", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.listen != "127.0.0.1":
        raise SystemExit("metrics listener must stay on 127.0.0.1")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("metrics port must be between 1024 and 65535")
    source = args.source
    if not source.is_absolute() or source.suffix != ".prom" or ".." in source.parts:
        raise SystemExit("metrics source must be a safe absolute .prom path")
    server = MetricsHTTPServer((args.listen, args.port), source)
    print(f"pyDuckHunt metrics listening on {args.listen}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
