"""The portable adapter must protect projects and the installed plugin cache."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.package_codex_plugin import package_codex_plugin

PROJECT = Path(__file__).resolve().parents[1]


class CodexRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        archive = package_codex_plugin(PROJECT, self.root / "plugin.zip")
        with zipfile.ZipFile(archive) as package:
            package.extractall(self.root)
        self.plugin = self.root / "game-asset-tools"
        spec = importlib.util.spec_from_file_location("gat_portable", self.plugin / "scripts/gat.py")
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)

    def test_initialization_and_cli_outside_repository(self):
        project = self.root / "my-game"
        project.mkdir()
        instructions = project / "AGENTS.md"
        instructions.write_text("Preserve user instructions.", encoding="utf-8")
        self.runner.init_project(project)
        self.assertEqual(instructions.read_text(), "Preserve user instructions.")
        self.assertTrue((project / "game_assets/towers/rubin_tower/config.json").is_file())
        result = subprocess.run([sys.executable, str(self.plugin / "scripts/gat.py"),
                                 "--project", str(project), "list"], cwd=self.root,
                                check=True, text=True, capture_output=True)
        self.assertIn("rubin_tower", {e["id"] for e in json.loads(result.stdout)["assets"]})

    def test_initialization_preserves_existing_project(self):
        project = self.root / "my-game"
        self.runner.init_project(project)
        config = project / "game_assets/towers/rubin_tower/config.json"
        config.write_text("user content", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already has"):
            self.runner.init_project(project)
        self.assertEqual(config.read_text(), "user content")

    def test_plugin_cache_cannot_be_used_as_project(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            self.runner.init_project(self.plugin / "new-project")
        result = subprocess.run([sys.executable, str(self.plugin / "scripts/gat.py"),
                                 "--project", str(self.plugin / "bundled"), "create", "bad_asset"],
                                cwd=self.root, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.plugin / "bundled/game_assets/other/bad_asset").exists())

    def test_missing_bundle_fails_without_creating_project(self):
        with patch.object(self.runner, "BUNDLED", self.root / "missing"):
            with self.assertRaisesRegex(ValueError, "Bundled recipes"):
                self.runner.init_project(self.root / "my-game")
        self.assertFalse((self.root / "my-game").exists())


if __name__ == "__main__":
    unittest.main()
