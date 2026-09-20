from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from tools.project_guard import blocked_digest


ROOT = Path(__file__).resolve().parents[2]


class PublicTreePolicyTests(unittest.TestCase):
    def test_public_tree_guard_accepts_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/project_guard.py"), str(ROOT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Public-tree policy passed", result.stdout)

    def test_public_attribution_identifiers_are_allowed(self) -> None:
        public_attribution = (
            "boulets",
            "#boulets",
            "https://boulets.eggdrop.fr/",
        )
        for value in public_attribution:
            with self.subTest(value=value):
                self.assertIsNone(blocked_digest(value.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
