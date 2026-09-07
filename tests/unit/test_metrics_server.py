from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.metrics_server import read_metrics_file


class MetricsServerTests(unittest.TestCase):
    def test_reader_accepts_one_owner_controlled_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metrics.prom"
            payload = b"# pyDuckHunt aggregate metrics; identities absent.\nmetric 1\n"
            path.write_bytes(payload)
            path.chmod(0o644)
            self.assertEqual(
                read_metrics_file(path, expected_uid=os.geteuid()),
                payload,
            )

    def test_reader_rejects_symlink_wrong_owner_mode_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real.prom"
            real.write_bytes(b"not metrics\n")
            real.chmod(0o644)
            with self.assertRaises(ValueError):
                read_metrics_file(real, expected_uid=os.geteuid())
            real.write_bytes(b"# pyDuckHunt aggregate metrics; safe.\nmetric 1\n")
            real.chmod(0o666)
            with self.assertRaises(ValueError):
                read_metrics_file(real, expected_uid=os.geteuid())
            real.chmod(0o644)
            with self.assertRaises(ValueError):
                read_metrics_file(real, expected_uid=os.geteuid() + 1)
            linked = root / "linked.prom"
            linked.symlink_to(real)
            with self.assertRaises(OSError):
                read_metrics_file(linked, expected_uid=os.geteuid())


if __name__ == "__main__":
    unittest.main()
