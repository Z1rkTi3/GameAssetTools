"""Release version, distributable contents, and overwrite protection without Blender."""

import contextlib
import io
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
import zipfile

from game_asset_tools import __version__
from game_asset_tools.cli import main
from scripts.package_addon import default_output, package_addon, release_version

PROJECT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_version_metadata_and_cli_without_blender(self):
        metadata = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["dependencies"], [])
        self.assertEqual(metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"],
                         "game_asset_tools.__version__")
        self.assertIn("version", metadata["project"]["dynamic"])
        self.assertEqual(release_version(PROJECT), __version__)
        self.assertEqual(default_output(PROJECT).name, f"game_asset_tools_blender_{__version__}.zip")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main(["--version"])
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"GameAssetTools {__version__}")

    def test_standalone_zip_contents_reproducibility_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / default_output(PROJECT).name
            package_addon(PROJECT, path)
            original = path.read_bytes()
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertTrue(all(name.startswith("game_asset_tools_addon/") for name in names))
                self.assertIn("game_asset_tools_addon/__init__.py", names)
                self.assertIn("game_asset_tools_addon/bundled/game_style.json", names)
                self.assertEqual(archive.read("game_asset_tools_addon/LICENSE"),
                                 (PROJECT / "LICENSE").read_bytes())
                self.assertEqual(archive.read("game_asset_tools_addon/bundled/game_asset_tools/__init__.py"),
                                 (PROJECT / "game_asset_tools" / "__init__.py").read_bytes())
                for category, asset in (("buildings", "watchtower"), ("mechs", "scout_mech"),
                                        ("props", "industrial_crate")):
                    self.assertIn(f"game_asset_tools_addon/bundled/game_assets/{category}/{asset}/asset.py", names)
                self.assertFalse(any("__pycache__" in name or name.endswith((".pyc", ".blend"))
                                     for name in names))
            with self.assertRaises(FileExistsError):
                package_addon(PROJECT, path)
            self.assertEqual(path.read_bytes(), original)
            package_addon(PROJECT, path, overwrite=True)
            self.assertEqual(path.read_bytes(), original)

    def test_version_drift_rejected_before_output_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for source in ("game_asset_tools/__init__.py", "blender_addon/game_asset_tools_addon/__init__.py"):
                destination = project / source
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT / source, destination)
            (project / "game_asset_tools" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
            output = project / "existing.zip"
            output.write_bytes(b"existing archive")
            with self.assertRaisesRegex(ValueError, "bl_info version"):
                package_addon(project, output, overwrite=True)
            self.assertEqual(output.read_bytes(), b"existing archive")


if __name__ == "__main__":
    unittest.main()
