"""Actual Blender checkbox/operator dispatch; GLB payload tests live with the exporter."""

import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "blender_addon"))

import game_asset_tools_addon as addon
from game_asset_tools_addon import operators
from game_asset_tools.cli import create_asset


class AnimatedExportUITests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_animated_export_ui_")
        self.project = Path(self.directory.name)
        create_asset(self.project, "sample")
        addon.register()
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(self.project)
        self.settings.output = str(self.project / "output")
        bpy.ops.game_asset_tools.refresh()

    def tearDown(self):
        addon.unregister()
        self.directory.cleanup()

    def test_registered_checkbox_defaults_to_static_and_operator_forwards_both_values(self):
        self.assertIsNotNone(bpy.types.Panel.bl_rna_get_subclass_py("GAT_PT_output"))
        self.assertFalse(self.settings.export_animations)
        self.assertFalse(self.settings.bl_rna.properties["export_animations"].default)
        config = self.project / "game_assets/other/sample/config.json"
        original = config.read_bytes()
        for enabled in (False, True, False):
            with self.subTest(enabled=enabled):
                self.settings.export_animations = enabled
                with patch("game_asset_tools.operations.execute", return_value={"status": "exported"}) as execute:
                    self.assertEqual(bpy.ops.game_asset_tools.action(action="export"), {"FINISHED"})
                request = execute.call_args.args[0]
                self.assertIs(request["animations"], enabled)
                self.assertEqual(request["asset"], "sample")
                self.assertEqual(Path(request["project"]), self.project)
                self.assertIs(request["overwrite"], False)
                self.assertEqual(json.loads(bpy.data.texts[self.settings.report_text].as_string())["status"], "exported")
        self.assertEqual(config.read_bytes(), original)

    def test_checkbox_does_not_add_animation_option_to_other_operations(self):
        self.settings.export_animations = True
        for action in ("save", "inspect", "validate", "preview"):
            with self.subTest(action=action):
                self.assertNotIn("animations", operators.operation_request(self.settings, action))

    def test_real_checkbox_exports_the_rigid_recipe(self):
        # Проходим настоящий оператор панели без mock dispatcher: готовый GLB
        # должен содержать тот же риг/клипы, что экспорт через Python API.
        target = self.project / "game_assets/tests/rig_fixture"
        shutil.copytree(PROJECT / "tests/fixtures/animated_rig", target)
        bpy.ops.game_asset_tools.refresh()
        operators.properties.select_asset(self.settings, "rig_fixture", bpy.context)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
        self.settings.export_animations = True
        self.assertEqual(bpy.ops.game_asset_tools.action(action="export"), {"FINISHED"})
        result = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        self.assertTrue(Path(result["glb"]).is_file())
        self.assertTrue(result["animations_requested"])
        self.assertEqual(set(result["structure"]["animation_names"]), {"swing", "fold"})
        self.assertEqual(len(result["structure"]["skin_bindings"]), 2)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AnimatedExportUITests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_ANIMATED_EXPORT_UI_TESTS_OK", result.testsRun)
