"""Exercise local Blender controls against the same persisted profile as the CLI."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "blender_addon"))

import game_asset_tools_addon as addon
from game_asset_tools_addon import operators, properties
from game_asset_tools.operations import execute
from game_asset_tools.sprites.settings import FIELDS, read_settings, write_settings


class SpriteUITests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_sprite_ui_")
        self.project = Path(self.directory.name)
        recipe = Path("game_assets/towers/rubin_tower")
        shutil.copytree(PROJECT / recipe, self.project / recipe)
        shutil.copyfile(PROJECT / "game_style.json", self.project / "game_style.json")
        addon.register()
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(self.project)
        self.settings.output = str(self.project / "output")
        self.settings.overwrite = True
        bpy.ops.game_asset_tools.refresh()

    def tearDown(self):
        addon.unregister()
        self.directory.cleanup()

    def control(self, key):
        return next(item for item in self.settings.sprite_parameters if item.path == key)

    def test_every_shared_field_has_a_manual_control_and_ui_save_reaches_core(self):
        self.assertIsNotNone(bpy.types.Panel.bl_rna_get_subclass_py("GAT_PT_sprites"))
        self.assertEqual({item.path for item in self.settings.sprite_parameters}, {field["key"] for field in FIELDS})
        original = json.loads(Path(self.settings.sprite_path).read_text(encoding="utf-8"))
        self.control("resolution").int_value = 128
        self.control("look").enum_value = "standard"
        self.control("elevation").float_value = 42
        self.assertEqual(bpy.ops.game_asset_tools.sprites(action="save"), {"FINISHED"})
        profile = execute({"action": "sprite-settings", "project": str(self.project), "asset": "rubin_tower"})
        self.assertEqual(profile["settings"]["resolution"], 128)
        self.assertEqual(profile["settings"]["look"], "standard")
        self.assertEqual(profile["settings"]["elevation"], 42)
        self.assertEqual(profile["revision"], self.settings.sprite_revision)
        self.assertFalse(properties.sprite_updates(self.settings))
        saved = json.loads(Path(profile["path"]).read_text(encoding="utf-8"))
        self.assertEqual({key: value for key, value in original.items() if key != "sprites"},
                         {key: value for key, value in saved.items() if key != "sprites"})

    def test_programmatic_edit_reloads_into_same_controls_and_project_switch(self):
        write_settings(self.project, "rubin_tower", {"directions": 16, "padding": 6})
        self.assertEqual(bpy.ops.game_asset_tools.sprites(action="load"), {"FINISHED"})
        self.assertEqual(self.control("directions").int_value, 16)
        self.assertEqual(self.control("padding").int_value, 6)
        with tempfile.TemporaryDirectory(prefix="gat_sprite_other_") as folder:
            project = Path(folder)
            recipe = Path("game_assets/towers/rubin_tower")
            shutil.copytree(self.project / recipe, project / recipe)
            write_settings(project, "rubin_tower", {"directions": 4, "padding": 1})
            self.settings.project = str(project)
            self.assertEqual(self.control("directions").int_value, 4)
            self.assertEqual(self.control("padding").int_value, 1)
            self.assertEqual(Path(self.settings.sprite_path), project / recipe / "config.json")

    def test_conflicting_external_edit_never_gets_overwritten_or_rendered(self):
        self.control("resolution").int_value = 128
        profile = write_settings(self.project, "rubin_tower", {"resolution": 256})
        saved = Path(profile["path"]).read_bytes()
        for action in ("save", "preview", "export"):
            with self.assertRaises(RuntimeError):
                bpy.ops.game_asset_tools.sprites(action=action)
            self.assertEqual(Path(profile["path"]).read_bytes(), saved)
            self.assertEqual(properties.sprite_updates(self.settings)["resolution"], 128)
        self.assertFalse((self.project / "output").exists())

    def test_invalid_manual_value_uses_core_validation_without_writing(self):
        original = Path(self.settings.sprite_path).read_bytes()
        self.control("directions").int_value = 3
        with self.assertRaises(RuntimeError):
            bpy.ops.game_asset_tools.sprites(action="save")
        self.assertIn("directions", self.settings.sprite_status)
        self.assertEqual(Path(self.settings.sprite_path).read_bytes(), original)

    def test_explicit_unchanged_save_checks_revision_and_requires_reload(self):
        profile = write_settings(self.project, "rubin_tower", {"padding": 3})
        original = Path(profile["path"]).read_bytes()
        self.assertFalse(properties.sprite_updates(self.settings))
        with self.assertRaises(RuntimeError):
            bpy.ops.game_asset_tools.sprites(action="save")
        self.assertEqual(Path(profile["path"]).read_bytes(), original)
        self.assertEqual(bpy.ops.game_asset_tools.sprites(action="load"), {"FINISHED"})
        self.assertEqual(bpy.ops.game_asset_tools.sprites(action="save"), {"FINISHED"})
        self.assertEqual(read_settings(self.project, "rubin_tower")["settings"]["padding"], 3)

    def test_preview_export_save_then_dispatch_saved_settings_without_ui_only_overrides(self):
        calls = []

        def dispatch(request):
            calls.append(dict(request))
            if request["action"] == "sprites":
                saved = read_settings(self.project, "rubin_tower")
                self.assertEqual(saved["settings"]["resolution"], 128)
                self.assertEqual(saved["settings"]["directions"], 4)
                self.assertNotIn("sprite_updates", request)
                self.assertNotIn("components", request)
                self.assertNotIn("replace_edited", request)
                return {"status": "ok", "asset": "rubin_tower"}
            return execute(request)

        self.settings.component = "Body"
        self.settings.replace_edited = True
        self.control("resolution").int_value = 128
        self.control("directions").int_value = 4
        with patch("game_asset_tools.operations.execute", side_effect=dispatch):
            self.assertEqual(bpy.ops.game_asset_tools.sprites(action="preview"), {"FINISHED"})
            self.assertEqual(bpy.ops.game_asset_tools.sprites(action="export"), {"FINISHED"})
        self.assertEqual([call["action"] for call in calls], ["sprite-settings", "sprites", "sprite-settings", "sprites"])
        self.assertTrue(calls[1]["sprite_preview"])
        self.assertFalse(calls[3]["sprite_preview"])
        self.assertIn("expected_revision", calls[0])
        self.assertNotIn("sprite_updates", calls[2])

    def test_unchanged_ui_render_adopts_new_programmatic_settings(self):
        profile = write_settings(self.project, "rubin_tower", {"resolution": 64, "look": "standard"})

        def dispatch(request):
            if request["action"] == "sprites":
                self.assertEqual(self.control("resolution").int_value, 64)
                self.assertEqual(self.control("look").enum_value, "standard")
                self.assertEqual(self.settings.sprite_revision, profile["revision"])
                return {"status": "ok", "asset": "rubin_tower"}
            return execute(request)

        with patch("game_asset_tools.operations.execute", side_effect=dispatch):
            self.assertEqual(bpy.ops.game_asset_tools.sprites(action="preview"), {"FINISHED"})
        self.assertEqual(read_settings(self.project, "rubin_tower")["revision"], profile["revision"])

    def test_manual_preview_atlas_and_image_open_work_without_codex(self):
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
        self.control("resolution").int_value = 64
        self.control("directions").int_value = 4
        self.control("look").enum_value = "toon"
        area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        try:
            for action, kind in (("preview", "preview"), ("export", "atlas")):
                self.assertEqual(bpy.ops.game_asset_tools.sprites(action=action), {"FINISHED"})
                result = json.loads(bpy.data.texts[self.settings.report_text].as_string())
                profile = read_settings(self.project, "rubin_tower")
                self.assertEqual(result["settings"], profile["settings"])
                self.assertEqual(result["profile"]["revision"], profile["revision"])
                self.assertEqual(len(result["frames"]), 1 if action == "preview" else 4)
                path = Path(getattr(self.settings, f"sprite_{kind}_path"))
                self.assertTrue(path.is_file())
                with bpy.context.temp_override(area=area):
                    self.assertEqual(bpy.ops.game_asset_tools.open_sprite_image(kind=kind), {"FINISHED"})
                self.assertEqual(area.type, "IMAGE_EDITOR")
                self.assertEqual(Path(area.spaces.active.image.filepath), path)
                image = next(image for image in bpy.data.images if image.source == "FILE" and Path(image.filepath) == path)
                self.assertGreater(image.size[0], 0)
                bpy.data.images.remove(image)
        finally:
            area.type = "VIEW_3D"

    def test_installed_bundled_examples_cannot_be_modified_by_ui(self):
        bundled = self.project / "bundled"
        shutil.copytree(self.project / "game_assets", bundled / "game_assets")
        self.settings.project = str(bundled)
        path = Path(self.settings.sprite_path)
        original = path.read_bytes()
        with patch.object(operators, "__file__", str(self.project / "operators.py")):
            with self.assertRaises(RuntimeError):
                bpy.ops.game_asset_tools.sprites(action="save")
            self.control("resolution").int_value = 128
            with self.assertRaises(RuntimeError):
                bpy.ops.game_asset_tools.sprites(action="preview")
        self.assertIn("editable project", self.settings.sprite_status)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SpriteUITests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_SPRITE_UI_TESTS_OK", result.testsRun)
