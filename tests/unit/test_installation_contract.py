from __future__ import annotations

import subprocess
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InstallationContractTests(unittest.TestCase):
    def test_installer_check_is_read_only_and_succeeds(self) -> None:
        installer = ROOT / "install.sh"
        guarded = (ROOT / "pyproject.toml", ROOT / "config" / "pyduckhunt.example.toml")
        before = {path: path.stat().st_mtime_ns for path in guarded}
        result = subprocess.run(
            ["bash", str(installer), "--check"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing was changed", result.stdout)
        after = {path: path.stat().st_mtime_ns for path in guarded}
        self.assertEqual(after, before)

    def test_installer_is_local_non_root_and_does_not_start_services(self) -> None:
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("$(id -u)", installer)
        self.assertIn("-m venv", installer)
        self.assertIn("--editable", installer)
        self.assertIn("install -m 0600", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("systemctl", installer)

    def test_copied_configuration_source_is_disabled(self) -> None:
        sample = tomllib.loads(
            (ROOT / "config" / "pyduckhunt.example.toml").read_text(encoding="utf-8")
        )
        self.assertFalse(sample["game"]["enabled"])
        self.assertTrue(sample["irc"]["host"].endswith(".invalid"))

    def test_beta_status_and_no_release_boundary_are_public(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized = " ".join(readme.split())
        releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("**beta software**", readme)
        self.assertIn("no tag or GitHub Release", normalized)
        self.assertIn("must not create a tag or GitHub", releasing)
        self.assertIn("Development Status :: 4 - Beta", metadata["project"]["classifiers"])


if __name__ == "__main__":
    unittest.main()
