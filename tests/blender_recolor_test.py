"""Real Blender evidence for selective material edits and geometry preservation."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset.geometry_state import geometry_state
from game_asset_tools.asset.lifecycle import set_status
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.recolor import recolor
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.operations import execute


class RecolorTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        execute({"project": str(PROJECT), "asset": "rubin_tower", "action": "build"})
        self.root = find_root("rubin_tower")
        self.objects = asset_objects(self.root)
        self.body = next(o for o in self.objects if o.get("gat_component") == "Body")
        self.color = {"Rubin_Body": {"base_color": [0.02, 0.15, 0.75, 1.0]}}

    def test_exact_target_original_evaluated_geometry_and_unmanaged_sharing(self):
        bevel = self.body.modifiers.new("Existing bevel", "BEVEL")
        bevel.width = 0.07
        bevel.segments = 2
        self.body["gat_fingerprint"] = fingerprint(self.body)
        user = bpy.data.objects.new("Unmanaged shared mesh", self.body.data)
        bpy.context.scene.collection.objects.link(user)
        material = self.body.active_material
        mesh = self.body.data
        before = geometry_state(self.objects + [user])
        shaders = {o.name: fingerprint(o) for o in self.objects if o != self.body}
        count = len(bpy.data.materials)
        plan = recolor("rubin_tower", self.color, components=["Body"], dry_run=True)
        self.assertEqual(plan["errors"], [])
        self.assertEqual(plan["objects"], [self.body.name])
        self.assertEqual(len(bpy.data.materials), count)
        result = recolor("rubin_tower", self.color, components=["Body"])
        self.assertTrue(result["geometry_unchanged"])
        self.assertEqual(before, geometry_state(self.objects + [user]))
        self.assertEqual(self.body.data, mesh)
        self.assertEqual(user.active_material, material)
        self.assertNotEqual(self.body.active_material, material)
        self.assertEqual(shaders, {o.name: fingerprint(o) for o in self.objects if o != self.body})
        old_node = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        new_node = next(n for n in self.body.active_material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        for socket, new_socket in zip(old_node.inputs, new_node.inputs):
            if socket.name != "Base Color" and hasattr(socket, "default_value"):
                a, b = socket.default_value, new_socket.default_value
                self.assertEqual(list(a) if hasattr(a, "__len__") else a,
                                 list(b) if hasattr(b, "__len__") else b)
        self.assertEqual(recolor("rubin_tower", self.color)["status"], "unchanged")

    def test_locked_approved_and_manual_edits_are_guarded(self):
        for status in ("approved", "locked"):
            set_status("rubin_tower", status, ["Body"])
            self.assertEqual(recolor("rubin_tower", self.color, dry_run=True)["status"], "blocked")
            with self.assertRaises(ValueError):
                recolor("rubin_tower", self.color, replace_edited=True)
        set_status("rubin_tower", "editable", ["Body"])
        self.body.data.vertices[0].co.x += 0.2
        with self.assertRaisesRegex(ValueError, "Manual edits"):
            recolor("rubin_tower", self.color)
        before = geometry_state([self.body])
        recolor("rubin_tower", self.color, replace_edited=True)
        self.assertEqual(before, geometry_state([self.body]))

    def test_invalid_roles_properties_and_objects_never_mutate(self):
        before = {o.name: fingerprint(o) for o in self.objects}
        for changes in ({"missing": {"base_color": [1,0,0,1]}},
                        {"Rubin_Body": {"unknown": 1}}, {"Rubin_Body": {"alpha": -1}}):
            with self.assertRaises(ValueError):
                recolor("rubin_tower", changes)
        with self.assertRaises(ValueError):
            recolor("rubin_tower", self.color, objects=["not_owned"])
        self.assertEqual(before, {o.name: fingerprint(o) for o in self.objects})

    def test_edit_mode_requires_flushing_manual_geometry_before_planning(self):
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        self.body.select_set(True)
        bpy.context.view_layer.objects.active = self.body
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            plan = recolor("rubin_tower", self.color, dry_run=True)
            self.assertEqual(plan["status"], "blocked")
            self.assertTrue(any("Object Mode" in error for error in plan["errors"]))
            with self.assertRaisesRegex(ValueError, "Object Mode"):
                recolor("rubin_tower", self.color, replace_edited=True)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

    def test_failed_geometry_check_rolls_back_materials_config_and_baselines(self):
        before = fingerprint(self.body)
        config = self.root["gat_config"]
        source = self.body.active_material
        with patch("game_asset_tools.asset.recolor.geometry_state", side_effect=[{"test": "before"}, {"test": "after"}]):
            with self.assertRaisesRegex(ValueError, "rolled back"):
                recolor("rubin_tower", self.color)
        self.assertEqual(self.body.active_material, source)
        self.assertEqual(self.body.material_slots[0].link, "DATA")
        self.assertEqual(self.root["gat_config"], config)
        self.assertEqual(fingerprint(self.body), before)
        self.assertEqual(self.body["gat_fingerprint"], before)

    def test_saved_appearance_survives_rebuild_without_false_manual_guard(self):
        recolor("rubin_tower", self.color)
        config = json.loads(self.root["gat_config"])
        self.assertEqual(config["appearance"]["Body"]["Block"]["0"]["values"], self.color["Rubin_Body"])
        request = {"project": str(PROJECT), "asset": "rubin_tower", "action": "rebuild"}
        self.assertEqual(execute({**request, "dry_run": True})["components"], [])
        execute({**request, "overrides": {"body.height": 3.1}})
        body = next(o for o in asset_objects(self.root) if o.get("gat_component") == "Body")
        self.assertAlmostEqual(body.active_material.diffuse_color[2], 0.75)
        report = execute({"project": str(PROJECT), "asset": "rubin_tower", "action": "validate", "dry_run": True})
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RecolorTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
