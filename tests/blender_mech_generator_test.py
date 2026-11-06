"""Проверяет MVP через настоящий Blender UI, guarded Rebuild, JSON и glTF."""

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
import bmesh
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "blender_addon"))
import game_asset_tools_addon as addon
from game_asset_tools_addon import geometry_presets, properties
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.inspection import inspect_asset
from game_asset_tools.operations import execute
from game_asset_tools.preview import render_preview
from game_asset_tools.validation import validate_asset

ASSET = "industrial_walker"
OUTPUT = Path(os.environ.get("MECH_MVP_OUTPUT", PROJECT / "output/mech_generator_mvp/blender"))


class MechGeneratorTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon.register()
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(PROJECT)
        self.settings.output = str(OUTPUT)
        self.settings.overwrite = True
        bpy.ops.game_asset_tools.refresh()
        self.settings.category = "mechs"
        self.settings.asset = ASSET
        self.entry = Registry(PROJECT).get(ASSET)

    def tearDown(self):
        addon.unregister()

    def control(self, path, value):
        item = next(item for item in self.settings.parameters if item.path == path)
        setattr(item, item.kind + "_value", value)

    def build(self):
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
        return find_root(ASSET)

    def identities(self, root):
        return {(obj["gat_component"], obj["gat_local_name"]) for obj in asset_objects(root)}

    def snapshot(self, root):
        return {obj.name: fingerprint(obj) for obj in asset_objects(root)}

    def test_registration_real_controls_json_draft_and_rebuild(self):
        self.assertIsNotNone(bpy.types.Panel.bl_rna_get_subclass_py("GAT_PT_geometry_presets"))
        root = self.build()
        original_config = json.loads(root["gat_config"])
        before = self.snapshot(root)
        identities = self.identities(root)
        width = original_config["parameters"]["body"]["width"] + 0.2
        self.control("body.width", width)
        user = bpy.data.objects.new("User_Do_Not_Replace", None)
        bpy.context.scene.collection.objects.link(user)
        user.location = (20, 30, 40)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "walker.json"
            self.assertEqual(bpy.ops.game_asset_tools.geometry_export(filepath=str(path)), {"FINISHED"})
            self.assertAlmostEqual(load_config(self.entry, path)["parameters"]["body"]["width"], width, delta=1e-6)
            self.assertEqual(self.snapshot(root), before, "JSON export не перестраивает модель")
            self.control("body.width", original_config["parameters"]["body"]["width"])
            self.assertEqual(bpy.ops.game_asset_tools.geometry_import(filepath=str(path)), {"FINISHED"})
            self.assertEqual(self.snapshot(root), before, "Импорт меняет только draft")
            self.assertAlmostEqual(geometry_presets.draft_config(self.settings)[1]["parameters"]["body"]["width"], width, delta=1e-6)
            bad = deepcopy(original_config)
            bad["parameters"]["legs"]["upper_length"] = -2
            invalid_path = Path(folder) / "invalid.json"
            invalid_path.write_text(json.dumps(bad), encoding="utf-8")
            draft_before = geometry_presets.draft_config(self.settings)[1]
            with self.assertRaises(ValueError):
                geometry_presets.import_geometry(self.settings, invalid_path)
            self.assertEqual(geometry_presets.draft_config(self.settings)[1], draft_before)
            self.assertEqual(self.snapshot(root), before)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})
        self.assertEqual(self.identities(root), identities)
        self.assertEqual(len(asset_objects(root)), len(identities))
        self.assertAlmostEqual(json.loads(root["gat_config"])["parameters"]["body"]["width"], width, delta=1e-6)
        self.assertNotEqual(self.snapshot(root), before)
        self.assertEqual(tuple(user.location), (20, 30, 40))
        once = self.snapshot(root)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})
        self.assertEqual(self.snapshot(root), once, "Повторный Rebuild идемпотентен")
        self.assertEqual(validate_asset(ASSET, self.entry)["errors"], [])

    def test_leg_lengths_joint_controls_symmetry_and_manifold(self):
        root = self.build()
        config = json.loads(root["gat_config"])
        old = inspect_asset(ASSET)
        self.control("legs.upper_length", config["parameters"]["legs"]["upper_length"] + 0.1)
        self.control("legs.lower_length", config["parameters"]["legs"]["lower_length"] + 0.1)
        self.control("legs.hip_angle", config["parameters"]["legs"]["hip_angle"] + 1.0)
        self.control("legs.knee_angle", config["parameters"]["legs"]["knee_angle"] + 2.0)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})
        self.assertNotEqual(inspect_asset(ASSET), old)
        self.assertEqual(bpy.ops.game_asset_tools.mech_report(), {"FINISHED"})
        report = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        self.assertEqual(report["errors"], [], report)
        self.assertTrue(report["assumptions"])
        by_identity = {(obj["gat_component"], obj["gat_local_name"]): obj for obj in asset_objects(root)}
        for side in ("Left", "Right"):
            out = by_identity[("Body", "Mount_OUT_" + side)]
            incoming = by_identity[("Leg_" + side, "Mount_IN")]
            self.assertLess((out.matrix_world.translation - incoming.matrix_world.translation).length, 1e-6)
            out_axis = (out.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
            in_axis = (incoming.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
            self.assertLess(out_axis.dot(in_axis), -0.99999)
            self.assertEqual(out["mech_interface"], incoming["mech_interface"])
            self.assertGreater(incoming["mech_bore_diameter"], out["mech_pin_diameter"])
            for name, joint in [("UpperLink", "hip"), ("LowerLink", "knee"), ("Foot", "ankle")]:
                obj = by_identity[("Leg_" + side, name)]
                self.assertLess((obj.matrix_world.translation - Vector(report["joints"][side][joint])).length, 1e-6)
        meshes = [obj for obj in asset_objects(root) if obj.type == "MESH"]
        self.assertGreater(len(meshes), 5)
        all_points = []
        for obj in meshes:
            self.assertTrue(all(abs(value - 1.0) < 1e-6 for value in obj.scale))
            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                self.assertTrue(all(edge.is_manifold for edge in bm.edges), obj.name)
                self.assertGreater(bm.calc_volume(signed=True), 0.0, obj.name)
            finally:
                bm.free()
            all_points.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
        self.assertAlmostEqual(min(point.z for point in all_points), 0.0, places=5)
        # Сравниваются реальные мировые вершины, а не две одинаковые формулы.
        points = {(round(p.x, 5), round(p.y, 5), round(p.z, 5)) for p in all_points}
        mirrored = {(-x, y, z) for x, y, z in points}
        self.assertEqual(points, mirrored)
        identities = self.identities(root)
        self.assertEqual(len(asset_objects(root)), len(identities))

    def test_guarded_rebuild_preserves_locked_and_user_content(self):
        root = self.build()
        before = self.snapshot(root)
        result = execute({"action": "status", "project": str(PROJECT), "asset": ASSET, "state": "locked"})
        self.assertNotEqual(result.get("status"), "error")
        self.control("body.width", load_config(self.entry)["parameters"]["body"]["width"] + 0.1)
        with self.assertRaisesRegex(ValueError, "locked"):
            execute({"action": "rebuild", "project": str(PROJECT), "asset": ASSET,
                     "overrides": properties.geometry_updates(self.settings, check_revision=True)})
        self.assertEqual(self.snapshot(root), before)

    def test_invalid_mechanical_draft_report_does_not_change_scene(self):
        root = self.build()
        before = self.snapshot(root)
        # Оба значения входят в отдельные UI-диапазоны, но их сочетание
        # нарушает механический предел голени. Отчёт должен объяснить причину.
        self.control("legs.hip_angle", -10.0)
        self.control("legs.knee_angle", 110.0)
        self.assertEqual(bpy.ops.game_asset_tools.mech_report(), {"FINISHED"})
        report = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        self.assertEqual(report["status"], "error")
        self.assertTrue(report["errors"])
        self.assertEqual(self.snapshot(root), before)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            with self.assertRaises(ValueError):
                geometry_presets.export_geometry(self.settings, path)
            self.assertFalse(path.exists())
            # Валидный preset должен позволять восстановить ошибочный draft.
            valid = Path(folder) / "valid.json"
            valid.write_text(root["gat_config"], encoding="utf-8")
            self.assertEqual(bpy.ops.game_asset_tools.geometry_import(filepath=str(valid)), {"FINISHED"})
            self.assertEqual(self.snapshot(root), before)
            self.assertEqual(geometry_presets.draft_config(self.settings)[1]["parameters"], json.loads(root["gat_config"])["parameters"])

    def test_declared_float_boundaries_work_in_real_ui(self):
        self.build()
        for path, boundary in [("body.bevel", 0.18), ("legs.upper_thickness", 0.12), ("legs.upper_thickness", 0.34)]:
            self.control(path, boundary)
            _entry, config = geometry_presets.draft_config(self.settings)
            from game_asset_tools.asset.parameters import get_value
            self.assertEqual(get_value(config["parameters"], path), boundary)
            self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})

    def test_local_module_frames_survive_moved_root_and_rebuild(self):
        root = self.build()
        pivot = root_object(root)
        pivot.location = (7.0, -3.0, 2.0)
        pivot.rotation_euler = (0.11, -0.2, 0.4)
        bpy.context.view_layer.update()
        self.control("body.width", load_config(self.entry)["parameters"]["body"]["width"] + 0.1)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="rebuild"), {"FINISHED"})
        self.assertEqual(bpy.ops.game_asset_tools.mech_report(), {"FINISHED"})
        report = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        by_identity = {(obj["gat_component"], obj["gat_local_name"]): obj for obj in asset_objects(root)}
        for side in ("Left", "Right"):
            out = by_identity[("Body", "Mount_OUT_" + side)]
            incoming = by_identity[("Leg_" + side, "Mount_IN")]
            expected = pivot.matrix_world @ Vector(report["joints"][side]["hip"])
            self.assertLess((out.matrix_world.translation - expected).length, 2e-6)
            self.assertLess((incoming.matrix_world.translation - expected).length, 2e-6)

    def test_static_glb_and_real_reimport(self):
        root = self.build()
        expected_meshes = sum(obj.type == "MESH" for obj in asset_objects(root))
        self.assertEqual(bpy.ops.game_asset_tools.action(action="export"), {"FINISHED"})
        report = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        path = Path(report["glb"])
        self.assertGreater(path.stat().st_size, 1000)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
        self.assertEqual(sum(obj.type == "MESH" for obj in bpy.context.scene.objects), expected_meshes)

    def test_existing_towers_still_work_through_ui(self):
        for category, asset in [("towers", "rubin_tower"), ("buildings", "watchtower")]:
            self.settings.category = category
            self.settings.asset = asset
            self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
            entry = Registry(PROJECT).get(asset)
            report = validate_asset(asset, entry)
            self.assertEqual(report["errors"], [], report)
            self.assertEqual(report["warnings"], [], report)
            self.assertGreater(len(asset_objects(find_root(asset))), 5)

    def test_blockout_previews_and_saved_source(self):
        self.build()
        OUTPUT.mkdir(parents=True, exist_ok=True)
        result = render_preview(ASSET, OUTPUT, views=["front", "right", "perspective"],
                                resolution=512, overwrite=True)
        self.assertEqual(set(result["paths"]), {"front", "right", "perspective"})
        for path in result["paths"].values():
            self.assertGreater(Path(path).stat().st_size, 2000)
        self.assertEqual(bpy.ops.game_asset_tools.action(action="save"), {"FINISHED"})


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MechGeneratorTests))
    sources = [PROJECT / "game_assets/mechs/industrial_walker/asset.py", Path(__file__),
               PROJECT / "blender_addon/game_asset_tools_addon/geometry_presets.py"]
    (OUTPUT / "test_report.json").write_text(json.dumps({
        "project_root": str(PROJECT), "blender": bpy.app.version_string,
        "sources_sha256": {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "passed": result.wasSuccessful()}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
