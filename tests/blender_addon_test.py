"""Register and exercise the generic add-on in real Blender, then test its ZIP."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import bpy

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
sys.path.insert(0,str(PROJECT/"blender_addon"))
import game_asset_tools_addon as addon
from game_asset_tools_addon import properties
from game_asset_tools.asset.scene import find_root, asset_objects
from game_asset_tools.cli import create_asset


class AddonTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon.register()
        self.settings=bpy.context.scene.game_asset_tools
        self.settings.project=str(PROJECT)
        self.settings.output=str(PROJECT/"output"/"addon_test")
        self.settings.overwrite=True
        bpy.ops.game_asset_tools.refresh()

    def tearDown(self):
        addon.unregister()
        self.assertFalse(hasattr(bpy.types.Scene,"game_asset_tools"))

    def select(self,category,asset):
        self.settings.category=category
        self.settings.asset=asset

    def test_registered_ui_types_and_roundtrip_registration(self):
        self.assertIsNotNone(bpy.types.Panel.bl_rna_get_subclass_py("GAT_PT_asset"))
        self.assertTrue(hasattr(bpy.ops.game_asset_tools,"action"))
        self.assertGreater(len(self.settings.parameters),0)

    def test_build_change_parameter_inspect_status_validate_export(self):
        self.select("mechs","scout_mech")
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"),{"FINISHED"})
        right=next(p for p in self.settings.parameters if p.path=="weapons.right_scale")
        right.float_value=1.4
        self.settings.component="Weapon_Right"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"),{"FINISHED"})
        stored=json.loads(find_root("scout_mech")["gat_config"])
        self.assertAlmostEqual(stored["parameters"]["weapons"]["right_scale"],1.4,places=5)
        target=asset_objects(find_root("scout_mech"),"Weapon_Right")[0]
        bpy.context.view_layer.objects.active=target
        self.assertEqual(bpy.ops.game_asset_tools.action(action="inspect",selected=True),{"FINISHED"})
        report=json.loads(bpy.data.texts[self.settings.report_text].as_string())
        self.assertEqual(report["component"],"Weapon_Right")
        self.settings.state="locked"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="status"),{"FINISHED"})
        self.settings.state="editable"
        bpy.ops.game_asset_tools.action(action="status")
        self.settings.component=properties.ALL
        for action in ("validate","save","export"):
            self.assertEqual(bpy.ops.game_asset_tools.action(action=action),{"FINISHED"})

    def test_bool_enum_parameters_and_new_recipe_discovery(self):
        self.select("props","industrial_crate")
        handle=next(p for p in self.settings.parameters if p.path=="details.handles")
        handle.bool_value=False
        material=next(p for p in self.settings.parameters if p.path=="finish.material")
        material.enum_value="Metal_Bronze"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"),{"FINISHED"})
        self.assertFalse(asset_objects(find_root("industrial_crate"),"Handles"))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            create_asset(root,"new_prop","new_category","New Prop")
            self.settings.project=str(root)
            bpy.ops.game_asset_tools.refresh()
            self.assertEqual(self.settings.asset,"new_prop")
            self.assertEqual(len(self.settings.parameters),1)
            self.assertEqual(bpy.ops.game_asset_tools.action(action="build"),{"FINISHED"})

    def test_cli_built_float_values_do_not_cause_unrelated_rebuilds(self):
        from game_asset_tools.operations import execute
        execute({"action":"build","project":str(PROJECT),"asset":"scout_mech"})
        self.select("mechs","scout_mech")
        self.settings.component="Weapon_Right"
        right=next(p for p in self.settings.parameters if p.path=="weapons.right_scale")
        right.float_value=1.5
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"),{"FINISHED"})
        stored=json.loads(find_root("scout_mech")["gat_config"])
        self.assertEqual(stored["parameters"]["body"]["width"],1.6)


if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AddonTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
    # ZIP content is imported in a fresh process by tests/check_packaged_addon.py.
    from scripts.package_addon import package_addon
    path=package_addon(PROJECT,overwrite=True)
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert "game_asset_tools_addon/bundled/game_style.json" in archive.namelist()
    print("GAT_ADDON_TESTS_OK",path)
