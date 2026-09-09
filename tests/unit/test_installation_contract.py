from __future__ import annotations

import subprocess
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InstallationContractTests(unittest.TestCase):
    def isolated_installer(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'config').mkdir()
        shutil.copy2(ROOT / 'install.sh', root / 'install.sh')
        shutil.copy2(ROOT / 'pyproject.toml', root / 'pyproject.toml')
        shutil.copy2(ROOT / 'config/pyduckhunt.example.toml', root / 'config/pyduckhunt.example.toml')
        # Installation side effects run for real; package installation and the
        # identity query are isolated so this test needs neither network nor sudo.
        binaries = root / '.venv/bin'
        binaries.mkdir(parents=True)
        for name, body in {'python': 'exit 0', 'pyduckhunt': 'echo test-version',
                           'id': 'echo 1000'}.items():
            executable = binaries / name
            executable.write_text('#!/bin/sh\n' + body + '\n')
            executable.chmod(0o700)
        env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'])
        # The real system Python still handles parsing and exclusive creation.
        env['PYDUCKHUNT_PYTHON'] = shutil.which('python3')
        def run(*args):
            return subprocess.run(['bash', str(root/'install.sh'), *args],
                                  env=env, capture_output=True, text=True, timeout=20)
        return root, run

    def test_install_creates_private_disabled_english_configuration(self):
        root, run = self.isolated_installer()
        result = run('--language', 'en')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = root / 'config/pyduckhunt.toml'
        data = tomllib.loads(config.read_text())
        self.assertEqual(data['game']['language'], 'en')
        self.assertFalse(data['game']['enabled'])
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(data['partyline']['spontaneous_launch_announcement'],
                         'all right, here comes a duck')
        before = config.read_bytes()
        self.assertEqual(run().returncode, 0)
        self.assertEqual(config.read_bytes(), before)
        self.assertNotEqual(run('--language', 'fr').returncode, 0)
        self.assertEqual(config.read_bytes(), before)

    def test_language_check_and_invalid_choice_create_no_configuration(self):
        root, run = self.isolated_installer()
        self.assertEqual(run('--check', '--language', 'en').returncode, 0)
        for arguments in (('--language', 'de'), ('--language',),
                          ('--language', 'en', '--language', 'fr')):
            self.assertNotEqual(run(*arguments).returncode, 0)
        self.assertFalse((root/'config/pyduckhunt.toml').exists())

    def test_install_without_language_remains_french(self):
        root, run = self.isolated_installer()
        result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = tomllib.loads((root/'config/pyduckhunt.toml').read_text())
        self.assertEqual(data['game']['language'], 'fr')

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
        self.assertIn("os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600", installer)
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
