"""Real Blender regression checks for read-only semantic material inspection."""

import json
from pathlib import Path
import sys
import unittest
import tempfile
from xml.etree import ElementTree

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_asset_tools import core as gat
from game_asset_tools.asset.metadata import encode, fingerprint, tag
from game_asset_tools.inspection import inspect_asset, material_role, material_usage


class MaterialInspectionTests(unittest.TestCase):
    def test_visual_swatches_preserve_colors_escape_names_and_protect_output(self):
        from game_asset_tools.inspection.materials import write_material_swatches
        obj = self.obj("Body <&> sample", material=gat.project_material("Ruby"))
        obj.name = "Body <&> sample"
        before = fingerprint(obj)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "swatches.svg"
            write_material_swatches(material_usage(self.root), path)
            document = ElementTree.parse(path)
            content = " ".join(document.getroot().itertext())
            self.assertIn("Body <&> sample", content)
            self.assertIn("linear RGBA", content)
            self.assertIn("Ruby", content)
            with self.assertRaises(FileExistsError):
                write_material_swatches(material_usage(self.root), path)
        self.assertEqual(fingerprint(obj), before)

    def setUp(self):
        self.before_objects = set(bpy.data.objects)
        self.before_materials = set(bpy.data.materials)
        self.root = bpy.data.collections.new("Material_Inspection_Test")
        bpy.context.scene.collection.children.link(self.root)
        self.root["gat_role"] = "asset_root"
        self.root["gat_asset_id"] = "material_inspection_test"
        self.root["gat_style"] = encode({"materials": {"Custom_Paint": {"base_color": [.2, .3, .4, 1]}}})
        self.root["gat_components"] = encode({key: {"status": "editable"} for key in ("Body", "Corner")})
        self.root["gat_stage"] = "BLOCKOUT"
        self.root["gat_stage_status"] = "editable"

    def tearDown(self):
        for obj in set(bpy.data.objects) - self.before_objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(self.root)
        for material in set(bpy.data.materials) - self.before_materials:
            if material.users == 0:
                bpy.data.materials.remove(material)

    def obj(self, name, component="Body", material=None, *, owned=True):
        obj = gat.add_box(name, (1, 1, 1), collection=self.root)
        if material is not None:
            gat.assign_material(obj, material)
        if owned:
            tag(obj, self.root["gat_asset_id"], component, "BLOCKOUT", 1)
            obj["gat_local_name"] = name
            obj["gat_fingerprint"] = fingerprint(obj)
        return obj

    def test_explicit_and_legacy_roles_ignore_display_names(self):
        tagged = gat.project_material("Ruby")
        self.assertEqual(tagged["gat_material_role"], "Ruby")
        tagged.name = "Artist changed this name"
        self.assertEqual(material_role(tagged), "Ruby")
        legacy = gat.get_material("Stone")
        legacy.name = "Completely renamed legacy material"
        self.assertEqual(material_role(legacy), "Stone")
        custom = gat.get_material("Custom_Paint")
        self.assertIsNone(material_role(custom))
        self.assertEqual(material_role(custom, json.loads(self.root["gat_style"])), "Custom_Paint")
        unknown = bpy.data.materials.new("MAT_Ruby")
        self.assertIsNone(material_role(unknown))
        unknown["gat_material_name"] = "MAT_Unknown"
        self.assertIsNone(material_role(unknown))
        unknown["gat_material_role"] = "Explicit_Custom"
        self.assertEqual(material_role(unknown), "Explicit_Custom")
        self.assertIsNone(material_role(None))

    def test_color_sample_and_empty_slot_indices_are_read_only(self):
        material = gat.project_material("Custom_Paint", {"materials": {
            "Custom_Paint": {"base_color": [.21586050011389926, 0, 1, .5], "alpha": .25}}})
        obj = self.obj("Color_Box")
        obj.data.materials.append(None)
        obj.data.materials.append(material)
        obj["gat_fingerprint"] = fingerprint(obj)
        before = (obj.data.as_pointer(), fingerprint(obj), dict(material.items()))
        report = inspect_asset(self.root["gat_asset_id"], "Body")
        row = report["material_roles"]["Custom_Paint"]["components"]["Body"][0]
        self.assertEqual(row["slot"], 1)
        self.assertEqual(row["color"]["srgb_hex"], "#8000FF")
        self.assertAlmostEqual(row["color"]["linear_rgba"][0], .21586050011389926)
        self.assertAlmostEqual(row["color"]["alpha"], .25)
        self.assertEqual(row["color"]["source"], "principled_base_color")
        self.assertFalse(row["color"]["approximate"])
        self.assertFalse(row["protected"])
        self.assertFalse(row["manual_edited"])
        self.assertEqual(report["objects"][0]["materials"], [material.name])
        self.assertEqual(before, (obj.data.as_pointer(), fingerprint(obj), dict(material.items())))
        json.dumps(report, allow_nan=False)

    def test_shared_role_reports_protected_and_unmanaged_other_users(self):
        material = gat.project_material("Ruby")
        body = self.obj("Body_Box", material=material)
        corner = self.obj("Corner_Box", "Corner", material)
        manual = self.obj("User_Box", material=material, owned=False)
        records = json.loads(self.root["gat_components"])
        records["Corner"]["status"] = "locked"
        self.root["gat_components"] = encode(records)
        usage = material_usage(self.root, [body])["Ruby"]
        self.assertEqual(set(usage["components"]), {"Body"})
        self.assertTrue(usage["shared"])
        others = {row["object"]: row for row in usage["other_users"]}
        self.assertEqual(set(others), {corner.name, manual.name})
        self.assertEqual(others[corner.name]["status"], "locked")
        self.assertTrue(others[corner.name]["protected"])
        self.assertEqual(others[manual.name]["status"], "unmanaged")
        self.assertTrue(others[manual.name]["protected"])
        self.assertTrue(any("protected" in warning for warning in usage["warnings"]))
        full = material_usage(self.root)["Ruby"]
        self.assertEqual(set(full["components"]), {"Body", "Corner"})

    def test_manual_edits_and_missing_baselines_are_visible(self):
        material = gat.project_material("Stone")
        edited = self.obj("Edited_Box", material=material)
        unknown = self.obj("No_Baseline_Box", material=material)
        edited.data.vertices[0].co.x += .1
        del unknown["gat_fingerprint"]
        rows = {row["object"]: row for row in material_usage(self.root)["Stone"]["components"]["Body"]}
        self.assertTrue(rows[edited.name]["manual_edited"])
        self.assertTrue(rows[edited.name]["protected"])
        self.assertIsNone(rows[unknown.name]["manual_edited"])
        self.assertTrue(rows[unknown.name]["protected"])

    def test_unknown_material_and_complex_shader_have_clear_warnings(self):
        material = bpy.data.materials.new("Not a role")
        material.use_nodes = True
        material.node_tree.nodes.new("ShaderNodeTexNoise")
        self.obj("Unknown_Shader_Box", material=material)
        row = material_usage(self.root)["__unassigned__"]["components"]["Body"][0]
        self.assertIsNone(row["role"])
        self.assertTrue(row["color"]["approximate"])
        self.assertTrue(any("No recorded" in warning for warning in row["warnings"]))
        self.assertTrue(any("approximate" in warning for warning in row["warnings"]))

    def test_object_linked_slot_and_shared_mesh_are_reported_without_copying(self):
        material = gat.project_material("Metal_Silver")
        body = self.obj("Data_Box", material=material)
        copy = bpy.data.objects.new("Shared_Data_Box", body.data)
        self.root.objects.link(copy)
        copy.material_slots[0].link = "OBJECT"
        copy.material_slots[0].material = material
        before = body.data.as_pointer()
        usage = material_usage(self.root, [body])["Metal_Silver"]
        self.assertEqual(usage["components"]["Body"][0]["shared_data_users"], 2)
        other = next(row for row in usage["other_users"] if row["object"] == copy.name)
        self.assertEqual(other["link"], "OBJECT")
        self.assertEqual(body.data.as_pointer(), before)
        self.assertEqual(copy.data.as_pointer(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MaterialInspectionTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
