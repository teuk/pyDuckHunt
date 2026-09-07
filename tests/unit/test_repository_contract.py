from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/teuk/pyDuckHunt"
CREDIT = "https://scripts.eggdrop.fr/details-Duck+Hunt-s228.html"


class RepositoryContractTests(unittest.TestCase):
    def test_license_and_credit_are_explicit(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC BY-NC-SA 3.0", license_text)
        self.assertIn("Attribution-NonCommercial-ShareAlike 3.0 Unported", license_text)
        self.assertIn("Credits: MenzAgitat", license_text)
        self.assertIn(CREDIT, license_text)
        self.assertIn("Credits: [MenzAgitat]", readme)
        self.assertIn(CREDIT, readme)

    def test_package_metadata_points_to_the_public_repository(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["license"], "CC-BY-NC-SA-3.0")
        self.assertEqual(project["urls"]["Homepage"], REPOSITORY)
        self.assertEqual(project["urls"]["Source"], REPOSITORY)
        self.assertEqual(project["urls"]["Issues"], f"{REPOSITORY}/issues")

    def test_readme_badges_are_backed_by_repository_facts(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized = " ".join(readme.split())
        self.assertIn(f"{REPOSITORY}/actions/workflows/ci.yml", readme)
        self.assertIn("Status-Beta", readme)
        self.assertIn("no tag or GitHub Release has been published", normalized)
        self.assertIn("Python-3.11%2B", readme)
        self.assertIn("License-CC_BY--NC--SA_3.0", readme)
        self.assertNotIn("coverage", readme.lower())

    def test_ci_has_read_only_permissions_fast_matrix_and_one_full_job(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        for version in ("3.11", "3.12", "3.13"):
            self.assertIn(f'"{version}"', workflow)
        self.assertEqual(workflow.count("--lane full --progress"), 1)
        self.assertIn("--lane fast --progress", workflow)
        self.assertIn("python tools/project_guard.py", workflow)
        self.assertIn("run: ./install.sh", workflow)
        self.assertIn("run: .venv/bin/pyduckhunt --help", workflow)

    def test_github_community_files_are_present(self) -> None:
        required = (
            ".github/CODEOWNERS",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/pull_request_template.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "docs/RELEASING.md",
        )
        self.assertEqual([path for path in required if not (ROOT / path).is_file()], [])

    def test_local_runtime_and_operator_material_is_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for rule in (
            ".venv/",
            "config/pyduckhunt.toml",
            "state/",
            "logs/",
            "private/",
            "/commit.sh",
            "/*.tar.gz",
            "/*.tar.xz",
            "*.mp3",
        ):
            self.assertIn(rule, ignore)


if __name__ == "__main__":
    unittest.main()
