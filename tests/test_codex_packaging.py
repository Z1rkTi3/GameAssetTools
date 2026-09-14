"""Portable Codex release contents and source validation without Blender or an account."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.package_codex_plugin import SOURCE_PATH, default_output, package_codex_plugin
from scripts.package_addon import package_addon, release_version


PROJECT = Path(__file__).resolve().parents[1]
PREFIX = "game-asset-tools/"


def copy_sources(destination: Path) -> Path:
    for relative in (SOURCE_PATH, Path("game_asset_tools"), Path("game_assets"),
                     Path("docs"), Path("codex/workflows")):
        shutil.copytree(PROJECT / relative, destination / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for relative in ("codex/install_codex_plugin.py", "scripts/blender_command.py",
                     "game_style.json", "AGENTS.md", "LICENSE"):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, path)
    return destination


class CodexPackagingTests(unittest.TestCase):
    def test_default_filename_uses_plugin_manifest_version(self):
        manifest = json.loads((PROJECT / SOURCE_PATH / ".codex-plugin/plugin.json").read_bytes())
        self.assertEqual(manifest["version"], release_version(PROJECT))
        self.assertEqual(default_output(PROJECT),
                         PROJECT / "output" / f"game_asset_tools_codex_{manifest['version']}.zip")

    def test_archive_contains_portable_plugin_and_unmodified_shared_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            output = package_codex_plugin(PROJECT, Path(directory) / "plugin.zip")
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                self.assertTrue(all(name.startswith(PREFIX) for name in names))
                for required in (".codex-plugin/plugin.json", "scripts/gat.py", "README.md",
                                 "install_codex_plugin.py", "bundled/scripts/blender_command.py",
                                 "bundled/game_style.json", "bundled/AGENTS.md", "bundled/LICENSE",
                                 "bundled/game_asset_tools/i18n.py",
                                 "bundled/docs/asset_recipes.md", "bundled/codex/workflows/create_asset.md"):
                    self.assertIn(PREFIX + required, names)
                self.assertTrue(any(name.startswith(PREFIX + "skills/") and name.endswith("/SKILL.md")
                                    for name in names))
                for path in (PROJECT / "game_asset_tools").rglob("*.py"):
                    name = PREFIX + "bundled/" + path.relative_to(PROJECT).as_posix()
                    self.assertEqual(archive.read(name), path.read_bytes(), name)
                for asset in ("buildings/watchtower", "mechs/scout_mech", "props/industrial_crate",
                              "towers/rubin_tower"):
                    for filename in ("asset.py", "metadata.json", "config.json"):
                        relative = f"game_assets/{asset}/{filename}"
                        self.assertEqual(archive.read(PREFIX + "bundled/" + relative),
                                         (PROJECT / relative).read_bytes())
                self.assertIn(PREFIX + "bundled/game_assets/towers/rubin_tower/README.md", names)
                for name in names:
                    content = archive.read(name)
                    for local_path in (str(PROJECT), PROJECT.as_posix(),
                                       str(Path.home()), Path.home().as_posix()):
                        self.assertNotIn(local_path.encode("utf-8"), content, name)
                    self.assertNotIn("..", Path(name).parts)
                    self.assertNotIn("__pycache__", name)
                    self.assertFalse(name.endswith((".pyc", ".blend", ".zip")), name)

    def test_reproducibility_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            output = package_codex_plugin(PROJECT, Path(directory) / "plugin.zip")
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                package_codex_plugin(PROJECT, output)
            self.assertEqual(output.read_bytes(), original)
            package_codex_plugin(PROJECT, output, overwrite=True)
            self.assertEqual(output.read_bytes(), original)
            second = package_codex_plugin(PROJECT, Path(directory) / "second.zip")
            self.assertEqual(second.read_bytes(), original)

    def test_caches_credentials_and_generated_assets_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            project = copy_sources(Path(directory) / "project")
            unwanted = (SOURCE_PATH / "auth.json", SOURCE_PATH / ".env",
                        SOURCE_PATH / ".git/config.json", SOURCE_PATH / "__pycache__/test.py",
                        SOURCE_PATH / "bundled/stale.py", SOURCE_PATH / "output/test.json",
                        Path("game_asset_tools/__pycache__/fake.py"),
                        Path("game_assets/towers/rubin_tower/output/report.json"),
                        Path("game_assets/towers/rubin_tower/render.png"),
                        Path("game_assets/towers/rubin_tower/model.blend"))
            marker = b"DO_NOT_PACKAGE_THIS_LOCAL_FILE"
            for relative in unwanted:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(marker)
            with zipfile.ZipFile(package_codex_plugin(project)) as archive:
                for name in archive.namelist():
                    self.assertNotIn(marker, archive.read(name), name)

    def test_invalid_required_sources_preserve_existing_output(self):
        cases = (
            ("missing runtime", "game_asset_tools/cli.py", None),
            ("missing locale catalog", "game_asset_tools/i18n.py", None),
            ("missing Blender adapter", "scripts/blender_command.py", None),
            ("missing installer", "codex/install_codex_plugin.py", None),
            ("missing recipe config", "game_assets/towers/rubin_tower/config.json", None),
            ("invalid style", "game_style.json", b"{invalid"),
            ("invalid manifest", str(SOURCE_PATH / ".codex-plugin/plugin.json"), b"{}"),
            ("invalid runtime", "game_asset_tools/operations.py", b"def broken("),
        )
        for label, relative, replacement in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                project = copy_sources(Path(directory) / "project")
                path = project / relative
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                output = project / "existing.zip"
                output.write_bytes(b"existing distributable")
                with self.assertRaises((ValueError, SyntaxError)):
                    package_codex_plugin(project, output, overwrite=True)
                self.assertEqual(output.read_bytes(), b"existing distributable")

    def test_version_drift_rejected_before_output_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            project = copy_sources(Path(directory) / "project")
            manifest_path = project / SOURCE_PATH / ".codex-plugin/plugin.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["version"] = "99.99.99"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = project / "existing.zip"
            output.write_bytes(b"existing distributable")
            with self.assertRaisesRegex(ValueError, "manifest version"):
                package_codex_plugin(project, output, overwrite=True)
            self.assertEqual(output.read_bytes(), b"existing distributable")

    def test_both_archives_have_identical_core_and_runnable_locale_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (package_codex_plugin(PROJECT, root / "codex.zip"),
                     package_addon(PROJECT, root / "addon.zip"))
            cores = []
            for archive_path, package_name in zip(paths, ("game-asset-tools", "game_asset_tools_addon")):
                with self.subTest(package=package_name), zipfile.ZipFile(archive_path) as archive:
                    prefix = package_name + "/bundled/game_asset_tools/"
                    cores.append({name.removeprefix(prefix): archive.read(name)
                                  for name in archive.namelist() if name.startswith(prefix)})
                    self.assertIn("i18n.py", cores[-1])
                    if package_name == "game_asset_tools_addon":
                        self.assertEqual(archive.read(package_name + "/i18n.py"),
                                         (PROJECT / "blender_addon" / package_name / "i18n.py").read_bytes())
                    archive.extractall(root / "extracted")
                bundled = root / "extracted" / package_name / "bundled"
                # Isolated Python omits cwd, PYTHONPATH, and user site packages.
                # The imported catalog must come only from this extracted ZIP.
                code = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import game_asset_tools.i18n as i18n
assert Path(i18n.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert i18n.translate('Build', 'en_US') == 'Build'
assert i18n.translate('Build', 'ru_RU') == '\\u0421\\u043e\\u0437\\u0434\\u0430\\u0442\\u044c'
assert i18n.translate('Untranslated fallback', 'ru_RU') == 'Untranslated fallback'
assert 'bpy' not in sys.modules
print('GAT_EXTRACTED_LOCALE_OK')
"""
                result = subprocess.run([sys.executable, "-I", "-c", code, str(bundled)],
                                        cwd=root, env={**os.environ, "PYTHONPATH": ""},
                                        text=True, capture_output=True, check=True)
                self.assertIn("GAT_EXTRACTED_LOCALE_OK", result.stdout)
            self.assertEqual(cores[0], cores[1], "Both distributions must ship byte-identical Core")


if __name__ == "__main__":
    unittest.main()
