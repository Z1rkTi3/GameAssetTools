"""Regression checks for scene targeting, session drafts and panel availability."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "blender_addon")]
import game_asset_tools_addon as addon
from game_asset_tools_addon import operators, panels, properties, session
from game_asset_tools.asset.scene import find_root, asset_objects
from game_asset_tools.operations import execute


class Layout:
    """Record what real panel draw methods expose for a real Blender scene."""
    def __init__(self, records=None, parent=None):
        self.records = records if records is not None else []
        self.parent, self.enabled = parent, True

    def available(self):
        return self.enabled and (self.parent is None or self.parent.available())

    def row(self, **_):
        return Layout(self.records, self)

    column = row
    box = row

    def prop(self, data, name, **kwargs):
        self.records.append(("prop", name, self.available(), kwargs.get("text", "")))

    def label(self, **kwargs):
        self.records.append(("label", kwargs.get("text", ""), self.available()))

    def operator(self, name, **kwargs):
        result = SimpleNamespace()
        self.records.append(("operator", name, self.available(), kwargs.get("text", ""), result))
        return result


class UIPolishTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="gat_ui_polish_")
        self.project = Path(self.temporary.name) / "first"
        shutil.copytree(PROJECT / "game_assets", self.project / "game_assets")
        shutil.copyfile(PROJECT / "game_style.json", self.project / "game_style.json")
        addon.register()
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(self.project)
        properties.select_asset(self.settings, "rubin_tower")

    def tearDown(self):
        addon.unregister()
        self.temporary.cleanup()

    def geometry(self, key):
        return next(item for item in self.settings.parameters if item.path == key)

    def sprite(self, key):
        return next(item for item in self.settings.sprite_parameters if item.path == key)

    def build(self, asset="rubin_tower"):
        properties.select_asset(self.settings, asset)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})

    def test_geometry_sprite_and_stage_drafts_survive_switch_and_refresh(self):
        self.geometry("base.width").float_value = 6.5
        self.sprite("resolution").int_value = 128
        revision = self.settings.sprite_revision
        properties.select_asset(self.settings, "watchtower")
        self.settings.stage = "REFINE"
        properties.select_asset(self.settings, "rubin_tower")
        self.assertAlmostEqual(self.geometry("base.width").float_value, 6.5)
        self.assertEqual(self.sprite("resolution").int_value, 128)
        self.assertEqual(self.settings.sprite_revision, revision)
        bpy.ops.game_asset_tools.refresh()
        self.assertAlmostEqual(self.geometry("base.width").float_value, 6.5)
        self.assertEqual(self.sprite("resolution").int_value, 128)
        properties.select_asset(self.settings, "watchtower")
        self.assertEqual(self.settings.stage, "REFINE")

    def test_drafts_are_project_specific(self):
        second = Path(self.temporary.name) / "second"
        shutil.copytree(self.project, second)
        self.geometry("base.width").float_value = 6.5
        self.settings.project = str(second)
        properties.select_asset(self.settings, "rubin_tower")
        self.assertNotAlmostEqual(self.geometry("base.width").float_value, 6.5)
        self.geometry("base.width").float_value = 7.5
        self.settings.project = str(self.project)
        self.assertAlmostEqual(self.geometry("base.width").float_value, 6.5)
        self.settings.project = str(second)
        self.assertAlmostEqual(self.geometry("base.width").float_value, 7.5)

    def test_apply_geometry_keeps_sprite_draft_and_explicit_reload_discards_it(self):
        self.geometry("base.width").float_value = 6.5
        self.sprite("resolution").int_value = 128
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
        self.assertFalse(properties.geometry_dirty(self.settings))
        self.assertTrue(properties.sprite_dirty(self.settings))
        properties.select_asset(self.settings, "watchtower")
        properties.select_asset(self.settings, "rubin_tower")
        self.assertEqual(self.sprite("resolution").int_value, 128)
        bpy.ops.game_asset_tools.sprites(action="load")
        self.assertFalse(properties.sprite_dirty(self.settings))
        self.geometry("base.width").float_value = 7.5
        bpy.ops.game_asset_tools.reload_geometry()
        self.assertAlmostEqual(self.geometry("base.width").float_value, 6.5)

    def test_restored_stale_sprite_draft_keeps_revision_and_refuses_overwrite(self):
        self.sprite("resolution").int_value = 128
        revision = self.settings.sprite_revision
        properties.select_asset(self.settings, "watchtower")
        result = execute({"action":"sprite-settings", "project":str(self.project), "asset":"rubin_tower",
                          "sprite_updates":{"padding":3}})
        properties.select_asset(self.settings, "rubin_tower")
        self.assertEqual(self.settings.sprite_revision, revision)
        with self.assertRaises(RuntimeError):
            bpy.ops.game_asset_tools.sprites(action="save")
        self.assertEqual(self.sprite("resolution").int_value, 128)
        self.assertEqual(json.loads(Path(result["path"]).read_text())["sprites"]["padding"], 3)

    def test_geometry_source_change_requires_reload(self):
        self.geometry("base.width").float_value = 6.5
        path = self.project / "game_assets/towers/rubin_tower/config.json"
        config = json.loads(path.read_text())
        config["parameters"]["base"]["height"] += 0.2
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "source changed"):
            operators.operation_request(self.settings, "build")
        self.assertAlmostEqual(self.geometry("base.width").float_value, 6.5)

    def test_numeric_choice_uses_integer_core_value(self):
        control = self.sprite("directions")
        control.choice_value = "4"
        self.assertEqual(control.int_value, 4)
        self.assertEqual(properties.sprite_updates(self.settings)["directions"], 4)
        bpy.ops.game_asset_tools.sprites(action="save")
        value = json.loads(Path(self.settings.sprite_path).read_text())["sprites"]["directions"]
        self.assertIs(type(value), int)

    def test_open_one_asset_selects_it_and_does_not_persist_drafts(self):
        self.build()
        root_config = find_root("rubin_tower")["gat_config"]
        original = self.geometry("base.width").float_value
        self.geometry("base.width").float_value = original + 1
        self.sprite("resolution").int_value = 128
        self.assertNotIn("float_value", self.geometry("base.width").keys())
        self.assertNotIn("int_value", self.sprite("resolution").keys())
        properties.select_asset(self.settings, "watchtower")
        path = Path(self.temporary.name) / "single.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path))
        self.settings = bpy.context.scene.game_asset_tools
        self.assertEqual(self.settings.asset, "rubin_tower")
        self.assertAlmostEqual(self.geometry("base.width").float_value, original)
        self.assertFalse(properties.sprite_dirty(self.settings))
        self.assertEqual(find_root("rubin_tower")["gat_config"], root_config)

    def test_open_multiple_assets_requires_explicit_selection(self):
        self.build()
        self.build("industrial_crate")
        path = Path(self.temporary.name) / "multiple.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path))
        self.settings = bpy.context.scene.game_asset_tools
        self.assertEqual(self.settings.asset, properties.EMPTY)
        self.assertFalse(properties.scene_state(self.settings)["asset_available"])
        target = asset_objects(find_root("rubin_tower"))[0]
        bpy.context.view_layer.objects.active = target
        self.assertEqual(bpy.ops.game_asset_tools.use_selected_asset(), {"FINISHED"})
        self.assertEqual(self.settings.asset, "rubin_tower")
        fake = bpy.data.objects.new("rubin_tower_fake_name", None)
        bpy.context.scene.collection.objects.link(fake)
        bpy.context.view_layer.objects.active = fake
        self.assertFalse(properties.scene_state(self.settings)["selected_asset_id"])

    def test_existing_root_wrong_project_blocks_scene_actions(self):
        self.build()
        original = find_root("rubin_tower")["gat_config"]
        second = Path(self.temporary.name) / "second"
        shutil.copytree(self.project, second)
        self.settings.project = str(second)
        self.assertTrue(properties.scene_state(self.settings)["source_mismatch"])
        with self.assertRaises(ValueError):
            operators.operation_request(self.settings, "rebuild")
        self.assertEqual(find_root("rubin_tower")["gat_config"], original)
        self.settings.project = str(self.project)
        self.assertTrue(properties.scene_state(self.settings)["asset_available"])

    def test_report_collision_preserves_user_text_and_tracks_actual_name(self):
        user_text = bpy.data.texts.new("GameAssetTools_Report")
        user_text.write("User notes")
        operators.store_report(self.settings, {"status":"ok"})
        report = bpy.data.texts[self.settings.report_text]
        self.assertNotEqual(report, user_text)
        self.assertEqual(user_text.as_string(), "User notes")
        report.name = "My renamed GAT report"
        operators.store_report(self.settings, {"status":"saved"})
        self.assertEqual(self.settings.report_text, report.name)
        self.assertEqual(bpy.ops.game_asset_tools.show_report(), {"FINISHED"})

    def test_old_recipe_config_does_not_leave_a_partial_invalid_form(self):
        self.build()
        root = find_root("rubin_tower")
        config = json.loads(root["gat_config"])
        del config["parameters"]["body"]["height"]
        root["gat_config"] = json.dumps(config)
        properties.load_parameters(self.settings)
        self.assertEqual(len(self.settings.parameters), 0)
        self.assertFalse(properties.geometry_dirty(self.settings))
        properties.scene_state(self.settings)
        self.assertEqual(json.loads(root["gat_config"]), config)

    def test_panels_disable_scene_actions_and_use_numeric_choice_control(self):
        layout = Layout()
        panels.GAT_PT_preview.draw(SimpleNamespace(layout=layout), bpy.context)
        self.assertFalse(any(item[2] for item in layout.records if item[0] == "operator"))
        self.build()
        layout = Layout()
        panels.GAT_PT_preview.draw(SimpleNamespace(layout=layout), bpy.context)
        self.assertTrue(any(item[2] for item in layout.records if item[0] == "operator"))
        layout = Layout()
        panels.GAT_PT_sprites.draw(SimpleNamespace(layout=layout), bpy.context)
        self.assertTrue(any(item[:2] == ("prop", "choice_value") for item in layout.records))
        for panel in panels.CLASSES:
            layout = Layout()
            panel.draw(SimpleNamespace(layout=layout), bpy.context)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UIPolishTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
