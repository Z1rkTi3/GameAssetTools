"""Saved additive controls through real UI, validation, GLB and guarded rebuild."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "blender_addon")]
import game_asset_tools_addon as addon
from game_asset_tools_addon import geometry_presets, properties
from game_asset_tools.asset.lifecycle import build, plan_build, set_status
from game_asset_tools.asset.metadata import encode, fingerprint
from game_asset_tools.asset.parameters import effective_saved_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.operations import execute
from game_asset_tools.style import load_style
from game_asset_tools.validation import validate_asset

ASSET = "saved_defaults_fixture"
OUTPUT = Path(os.environ.get("GAT_SAVED_DEFAULTS_OUTPUT", PROJECT / "output/saved_parameter_defaults/blender"))
RECIPE = '''from game_asset_tools.asset import ComponentSpec, Parameter

class Recipe:
    parameters = (
        Parameter("body.width", "Width", "float", 2.0, 1.0, 3.0, components=("Chassis",)),
        Parameter("foot.width", "Foot width", "float", 1.0, .5, 2.0, components=("Foot",)),
        Parameter("body.cradle_scale", "Cradle scale", "float", 1.0, 1.0, 1.3, components=("Chassis",)),
        Parameter("body.lower_inset", "Lower inset", "float", 0.0, 0.0, .1, components=("Chassis",)),
    )
    saved_parameter_defaults = ("body.cradle_scale", "body.lower_inset")

    def components(self, config):
        return {"Chassis": ComponentSpec("Structure"), "Foot": ComponentSpec("Structure")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        p = config["parameters"]
        if key == "Chassis":
            size = (p["body"]["width"], p["body"]["cradle_scale"], .5 - p["body"]["lower_inset"])
            at = (0, 0, 1)
        else:
            size, at = (p["foot"]["width"], 1, .2), (0, 0, .1)
        obj = gat.add_box(ctx.name("Block"), size, location=at)
        ctx.add(obj, "Block")
        gat.assign_material(obj, gat.project_material("Painted_Metal", ctx.style))

RECIPE = Recipe()
'''


class SavedParameterDefaultsTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_saved_defaults_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        folder = self.project / "game_assets/tests" / ASSET
        folder.mkdir(parents=True)
        (folder / "asset.py").write_text(RECIPE, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps({"schema_version": 1, "id": ASSET,
            "display_name": "Saved defaults fixture", "category": "tests", "recipe_version": 1,
            "supported_stages": ["BLOCKOUT"]}), encoding="utf-8")
        self.disk_config = {"schema_version": 1, "asset": ASSET,
            "parameters": {"body": {"width": 2.0}, "foot": {"width": 1.0}}, "style": {}}
        self.config_path = folder / "config.json"
        self.config_path.write_text(json.dumps(self.disk_config), encoding="utf-8")
        self.entry = Registry(self.project).get(ASSET)
        self.style = load_style(self.project)
        self.request("build")
        self.root = find_root(ASSET)
        self.legacy = json.loads(self.root["gat_config"])
        del self.legacy["parameters"]["body"]["cradle_scale"]
        del self.legacy["parameters"]["body"]["lower_inset"]
        self.root["gat_config"] = encode(self.legacy)
        addon.register()
        self.addCleanup(addon.unregister)
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(self.project)
        self.settings.output = str(self.project / "output")
        self.settings.overwrite = True
        bpy.ops.game_asset_tools.refresh()
        self.settings.category, self.settings.asset = "tests", ASSET

    def request(self, action, **options):
        return execute({"project": str(self.project), "asset": ASSET, "action": action, **options})

    def snapshot(self):
        return {"metadata": dict(self.root.items()), "objects": {
            obj.name: (obj.as_pointer(), fingerprint(obj), dict(obj.items()))
            for obj in asset_objects(self.root)}}

    def fingerprints(self):
        return {obj.name: fingerprint(obj) for obj in asset_objects(self.root)}

    def control(self, path):
        return next(item for item in self.settings.parameters if item.path == path)

    def test_read_only_controls_json_validation_dry_run_and_export(self):
        before = self.snapshot()
        # Saved geometry values win over later disk defaults, including style.
        disk = deepcopy(self.disk_config)
        disk["parameters"]["foot"]["width"] = 1.8
        disk["style"] = {"unit_scale": 2.0}
        self.config_path.write_text(json.dumps(disk), encoding="utf-8")
        properties.load_parameters(self.settings)
        self.assertEqual(self.control("body.cradle_scale").float_value, 1.0)
        self.assertEqual(self.control("body.lower_inset").float_value, 0.0)
        self.assertEqual(self.control("foot.width").float_value, 1.0)
        self.assertFalse(properties.geometry_dirty(self.settings))
        self.assertEqual(properties.geometry_updates(self.settings, check_revision=True), {})
        draft = geometry_presets.draft_config(self.settings)[1]
        self.assertEqual(draft["style"], {})
        self.assertEqual(self.snapshot(), before)
        preset = self.project / "geometry.json"
        geometry_presets.export_geometry(self.settings, preset)
        geometry_presets.import_geometry(self.settings, preset)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(validate_asset(ASSET, self.entry)["errors"], [])
        for plan in (self.request("rebuild", components=["Foot"], dry_run=True),
                     plan_build(self.entry, self.legacy, rebuild=True, components=["Foot"], style=self.style)):
            self.assertEqual(plan["components"], ["Foot"])
            self.assertEqual(plan["errors"], [])
        self.settings.component = "Foot"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild", plan_only=True), {"FINISHED"})
        self.assertEqual(self.snapshot(), before)
        result = self.request("export", output=str(self.project / "output"))
        self.assertTrue(Path(result["glb"]).is_file())
        self.assertEqual(result["structure"]["meshes"], 2)
        self.assertEqual(self.snapshot(), before)

    def test_default_equality_and_foot_rebuild_preserve_locked_chassis(self):
        set_status(ASSET, "locked", ["Chassis"])
        before = self.snapshot()
        self.assertEqual(self.request("rebuild")["status"], "unchanged")
        self.assertEqual(self.snapshot(), before, "normalization alone must not persist metadata")
        chassis = {obj.name: (obj.as_pointer(), fingerprint(obj), dict(obj.items()))
                   for obj in asset_objects(self.root, "Chassis")}
        self.control("foot.width").float_value = 1.25
        self.settings.component = "Foot"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})
        self.assertEqual(chassis, {obj.name: (obj.as_pointer(), fingerprint(obj), dict(obj.items()))
                                   for obj in asset_objects(self.root, "Chassis")})
        saved = json.loads(self.root["gat_config"])
        self.assertEqual(saved["parameters"]["foot"]["width"], 1.25)
        self.assertEqual(saved["parameters"]["body"]["cradle_scale"], 1.0)
        self.assertEqual(saved["parameters"]["body"]["lower_inset"], 0.0)

    def test_direct_build_accepts_legacy_candidate_only_for_rebuild(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Missing parameter"):
            plan_build(self.entry, self.legacy, style=self.style)
        self.assertEqual(self.snapshot(), before)
        result = build(self.entry, self.legacy, self.style, rebuild=True, components=["Foot"])
        self.assertEqual(result["components"], ["Foot"])
        self.assertEqual(json.loads(self.root["gat_config"]), effective_saved_config(self.entry, self.legacy))

    def test_real_cradle_changes_and_lock_manual_guards_are_not_bypassed(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "also affects Chassis"):
            self.request("rebuild", components=["Foot"], overrides={"body.cradle_scale": 1.2})
        self.assertEqual(self.snapshot(), before)
        set_status(ASSET, "locked", ["Chassis"])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "locked"):
            self.request("rebuild", components=["Chassis"], overrides={"body.cradle_scale": 1.2}, replace_edited=True)
        self.assertEqual(self.snapshot(), before)
        foot = asset_objects(self.root, "Foot")[0]
        foot.data.vertices[0].co.x += .15
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Manual edits"):
            self.request("rebuild", components=["Foot"], overrides={"foot.width": 1.25})
        self.assertEqual(self.snapshot(), before)

    def test_invalid_saved_values_fail_without_mutation(self):
        for path, value in (("cradle_scale", None), ("cradle_scale", 1.4), ("lower_inset", -.01)):
            with self.subTest(path=path, value=value):
                raw = deepcopy(self.legacy)
                raw["parameters"]["body"][path] = value
                self.root["gat_config"] = encode(raw)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.request("rebuild", components=["Foot"])
                self.assertTrue(validate_asset(ASSET, self.entry)["errors"])
                self.assertEqual(self.snapshot(), before)
        raw = deepcopy(self.legacy)
        del raw["parameters"]["foot"]
        self.root["gat_config"] = encode(raw)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Missing parameter"):
            self.request("rebuild", components=["Foot"])
        self.assertEqual(self.snapshot(), before)

    def test_opening_legacy_blend_does_not_persist_defaults(self):
        raw, shapes = self.root["gat_config"], self.fingerprints()
        saved = self.request("save", output=str(self.project / "output"))
        bpy.ops.wm.open_mainfile(filepath=saved["blend"], load_ui=False, use_scripts=False)
        self.root = find_root(ASSET)
        self.settings = bpy.context.scene.game_asset_tools
        properties.load_parameters(self.settings)
        self.assertEqual(self.root["gat_config"], raw)
        self.assertEqual(self.fingerprints(), shapes)
        self.assertEqual(self.control("body.cradle_scale").float_value, 1.0)
        self.assertEqual(validate_asset(ASSET, self.entry)["errors"], [])
        self.assertEqual(self.root["gat_config"], raw)


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SavedParameterDefaultsTests))
    paths = [Path(__file__), *sorted((PROJECT / "game_asset_tools").rglob("*.py")),
             *sorted((PROJECT / "blender_addon/game_asset_tools_addon").rglob("*.py"))]
    (OUTPUT / "test_report.json").write_text(json.dumps({"project_root": str(PROJECT),
        "blender": bpy.app.version_string, "fixture": "Independent temporary Chassis/Foot recipe; no game source loaded",
        "source_sha256": {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "tests": result.testsRun, "passed": result.wasSuccessful(),
        "failures": len(result.failures), "errors": len(result.errors)}, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
