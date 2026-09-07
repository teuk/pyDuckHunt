from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import pyduckhunt


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def test_package_version_is_pep440_compatible(self) -> None:
        self.assertRegex(pyduckhunt.__version__, r"^\d+\.\d+\.\d+\.dev\d+$")

    def test_version_file_matches_package_version(self) -> None:
        public_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        normalized = re.sub(r"-dev$", ".dev0", public_version)
        self.assertEqual(normalized, pyduckhunt.__version__)

    def test_project_metadata_matches_package(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["name"], "pyduckhunt")
        self.assertEqual(metadata["project"]["version"], pyduckhunt.__version__)
        self.assertEqual(metadata["project"]["dependencies"], [])

    def test_required_public_files_exist(self) -> None:
        required = {
            ".github/workflows/ci.yml",
            ".gitignore",
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "VERSION",
            "install.sh",
            "docs/ARCHITECTURE.md",
            "docs/INSTALL.md",
            "docs/PRIVACY.md",
            "docs/RELEASING.md",
            "docs/ROADMAP.md",
            "pyproject.toml",
        }
        missing = sorted(path for path in required if not (ROOT / path).is_file())
        self.assertEqual(missing, [])

    def test_sample_configuration_is_disarmed(self) -> None:
        sample = tomllib.loads(
            (ROOT / "config/pyduckhunt.example.toml").read_text(encoding="utf-8")
        )
        self.assertFalse(sample["game"]["enabled"])
        self.assertTrue(sample["irc"]["host"].endswith(".invalid"))


if __name__ == "__main__":
    unittest.main()
