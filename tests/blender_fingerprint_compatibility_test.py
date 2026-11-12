"""Реальные edit guards после добавления dispersion-входов Principled в Blender5.3."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset.lifecycle import _guard
from game_asset_tools.asset.metadata import _fingerprint_record, encode, fingerprint, fingerprint_matches
from game_asset_tools.asset.recolor import recolor
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.inspection.materials import material_usage
from game_asset_tools.operations import execute
from game_asset_tools.validation import validate_asset


SCALE = "Transmission Dispersion Scale"
ABBE = "Transmission Dispersion Abbe Number"


def legacy_hash(obj):
    # Независимо строим прежний payload, не вызывая совместимый matcher/projector.
    record = deepcopy(_fingerprint_record(obj))
    found = False
    for material in record["materials"]:
        for node in material.get("nodes", []):
            if node["type"] == "ShaderNodeBsdfPrincipled":
                assert node["values"][SCALE] == 0.0 and node["values"][ABBE] == 20.0
                del node["values"][SCALE]
                del node["values"][ABBE]
                found = True
    assert found, "This fixture requires Blender5.3 Principled inputs"
    return hashlib.sha256(encode(record).encode()).hexdigest()


class FingerprintCompatibilityBlenderTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        execute({"project": str(PROJECT), "asset": "rubin_tower", "action": "build"})
        self.root = find_root("rubin_tower")
        self.objects = asset_objects(self.root)
        self.body = next(obj for obj in self.objects if obj.get("gat_component") == "Body")
        self.shader = next(node for node in self.body.active_material.node_tree.nodes
                           if node.bl_idname == "ShaderNodeBsdfPrincipled")
        self.original = {obj: (obj["gat_fingerprint"], fingerprint(obj)) for obj in self.objects}
        for obj in self.objects:
            obj["gat_fingerprint"] = legacy_hash(obj)
        self.cached = {obj: obj["gat_fingerprint"] for obj in self.objects}
        self.color = {"Rubin_Body": {"base_color": [0.1, 0.2, 0.75, 1]}}

    def assert_guarded(self):
        self.assertFalse(fingerprint_matches(self.body))
        self.assertTrue(any("Manual edits" in error for error in _guard(self.root, {"Body"})))
        self.assertTrue(any("Manual edits" in error for error in recolor("rubin_tower", self.color, dry_run=True)["errors"]))
        self.assertTrue(any("Manual edits" in warning for warning in validate_asset("rubin_tower")["warnings"]))
        self.assertTrue(any(row["manual_edited"] for row in material_usage(self.root)["Rubin_Body"]["components"]["Body"]))

    def test_legacy_default_record_passes_all_readers_without_rewriting_baseline(self):
        self.assertTrue(all(fingerprint_matches(obj) for obj in self.objects))
        self.assertEqual(_guard(self.root, {"Body"}), [])
        self.assertFalse(any("Manual edits" in warning for warning in validate_asset("rubin_tower")["warnings"]))
        rows = material_usage(self.root)["Rubin_Body"]["components"]["Body"]
        self.assertTrue(all(row["manual_edited"] is False for row in rows))
        self.assertEqual(recolor("rubin_tower", self.color, dry_run=True)["errors"], [])
        self.assertEqual({obj: obj["gat_fingerprint"] for obj in self.objects}, self.cached)

    def test_vertex_and_transform_edits_remain_guarded(self):
        coordinate = self.body.data.vertices[0].co.copy()
        self.body.data.vertices[0].co.x += .125
        self.assert_guarded()
        self.body.data.vertices[0].co = coordinate
        self.body.location.x += .125
        self.assert_guarded()

    def test_each_new_dispersion_parameter_edit_remains_guarded(self):
        for name, value in ((SCALE, .1), (ABBE, 21.0)):
            with self.subTest(name=name):
                old = self.shader.inputs[name].default_value
                try:
                    self.shader.inputs[name].default_value = value
                    self.assert_guarded()
                finally:
                    self.shader.inputs[name].default_value = old

    def test_link_to_default_new_input_remains_guarded(self):
        material = self.body.active_material
        value = material.node_tree.nodes.new("ShaderNodeValue")
        material.node_tree.links.new(value.outputs[0], self.shader.inputs[SCALE])
        self.assert_guarded()

    def test_old_material_parameter_edit_remains_guarded(self):
        self.shader.inputs["Roughness"].default_value = .99
        self.assert_guarded()

    def test_new_53_full_signatures_remain_exact_and_detect_changes(self):
        for obj, (stored, current) in self.original.items():
            self.assertEqual(stored, current)
            obj["gat_fingerprint"] = stored
            self.assertTrue(fingerprint_matches(obj))
            self.assertEqual(fingerprint(obj), current)
        self.shader.inputs[SCALE].default_value = .1
        self.assert_guarded()

    def test_rebuild_and_recolor_accept_untouched_legacy_content(self):
        result = execute({"project": str(PROJECT), "asset": "rubin_tower", "action": "rebuild",
                          "overrides": {"body.height": 3.1}})
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(recolor("rubin_tower", self.color)["errors"], [])
        self.assertFalse(any("Manual edits" in warning for warning in validate_asset("rubin_tower")["warnings"]))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FingerprintCompatibilityBlenderTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_FINGERPRINT_COMPATIBILITY_OK", result.testsRun)
