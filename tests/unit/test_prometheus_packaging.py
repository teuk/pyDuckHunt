from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "packaging" / "prometheus" / "pyduckhunt-prometheus-config"


class PrometheusPackagingTests(unittest.TestCase):
    def test_helper_inserts_checks_and_preserves_following_top_level_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "prometheus.yml"
            path.write_text(
                "global:\n  scrape_interval: 1m\nscrape_configs:\n"
                "  - job_name: node\n    static_configs: []\n"
                "rule_files:\n  - rules.yml\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            planned = subprocess.run(
                ("python3", str(HELPER), "plan", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertNotIn("job_name: pyduckhunt", path.read_text(encoding="utf-8"))
            before_owner = path.stat().st_uid, path.stat().st_gid
            applied = subprocess.run(
                ("python3", str(HELPER), "apply", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), before_owner)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            rendered = path.read_text(encoding="utf-8")
            self.assertEqual(rendered.count("job_name: pyduckhunt"), 1)
            self.assertLess(
                rendered.index("job_name: pyduckhunt"),
                rendered.index("rule_files:"),
            )
            checked = subprocess.run(
                ("python3", str(HELPER), "check", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            before = path.read_bytes()
            repeated = subprocess.run(
                ("python3", str(HELPER), "apply", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(path.read_bytes(), before)

    def test_helper_rejects_an_unexpected_existing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "prometheus.yml"
            path.write_text(
                "scrape_configs:\n  - job_name: pyduckhunt\n"
                "    static_configs: []\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            result = subprocess.run(
                ("python3", str(HELPER), "apply", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_helper_rejects_symlink_and_group_writable_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "prometheus.yml"
            path.write_text(
                "scrape_configs:\n  - job_name: node\n    static_configs: []\n",
                encoding="utf-8",
            )
            path.chmod(0o664)
            writable = subprocess.run(
                ("python3", str(HELPER), "plan", str(path)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(writable.returncode, 0)
            path.chmod(0o644)
            link = root / "linked.yml"
            os.symlink(path, link)
            linked = subprocess.run(
                ("python3", str(HELPER), "plan", str(link)),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(linked.returncode, 0)


if __name__ == "__main__":
    unittest.main()
