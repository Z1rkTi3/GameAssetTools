"""Старые hash принимаются только для двух нетронутых default-входов Blender5.3."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_asset_tools.asset.metadata import encode, fingerprint, fingerprint_matches


def digest(record):
    return hashlib.sha256(encode(record).encode()).hexdigest()


class Object(dict):
    pass


def fixture():
    # Независимый literal представляет прежнюю схему: новых сокетов в ней нет.
    old = {"vertices": [[0.0, 0.0, 0.0]], "matrix": [[1, 0], [0, 1]],
           "modifiers": [{"type": "ARMATURE", "object": "Rig"}],
           "materials": [{"name": "Paint", "nodes": [
               {"type": "ShaderNodeBsdfPrincipled", "values": {"Roughness": 0.7}},
               {"type": "ShaderNodeOutputMaterial", "values": {}}],
               "links": [("Principled BSDF", "BSDF", "Material Output", "Surface")]}]}
    current = deepcopy(old)
    values = current["materials"][0]["nodes"][0]["values"]
    values.update({"Transmission Dispersion Scale": 0.0,
                   "Transmission Dispersion Abbe Number": 20.0})
    inputs = {name: SimpleNamespace(default_value=value, is_linked=False)
              for name, value in values.items()}
    node = SimpleNamespace(bl_idname="ShaderNodeBsdfPrincipled", inputs=inputs)
    material = SimpleNamespace(use_nodes=True, node_tree=SimpleNamespace(nodes=[
        node, SimpleNamespace(bl_idname="ShaderNodeOutputMaterial")]))
    obj = Object(gat_fingerprint=digest(old))
    obj.material_slots = [SimpleNamespace(material=material)]
    return obj, old, current, inputs


class FingerprintCompatibilityTests(unittest.TestCase):
    def matches(self, obj, record, expected=None):
        with patch("game_asset_tools.asset.metadata._fingerprint_record", return_value=record):
            return fingerprint_matches(obj, expected)

    def test_exact_52_record_matches_unchanged_53_defaults_without_mutation(self):
        obj, old, record, _ = fixture()
        before = deepcopy(record), dict(obj)
        self.assertNotEqual(digest(old), digest(record))
        self.assertTrue(self.matches(obj, record))
        self.assertEqual((record, dict(obj)), before)

    def test_current_signature_is_checked_before_legacy_projection(self):
        obj, _, record, inputs = fixture()
        inputs["Transmission Dispersion Scale"].default_value = .25
        record["materials"][0]["nodes"][0]["values"]["Transmission Dispersion Scale"] = .25
        obj["gat_fingerprint"] = digest(record)
        self.assertTrue(self.matches(obj, record))

    def test_fingerprint_remains_complete_and_independent_of_stored_hash(self):
        obj, _, record, _ = fixture()
        with patch("game_asset_tools.asset.metadata._fingerprint_record", return_value=record):
            self.assertEqual(fingerprint(obj), digest(record))
            obj["gat_fingerprint"] = "unrelated"
            self.assertEqual(fingerprint(obj), digest(record))

    def test_changed_geometry_and_transform_still_fail(self):
        for field, value in (("vertices", [[1, 0, 0]]), ("matrix", [[2, 0], [0, 1]])):
            with self.subTest(field=field):
                obj, _, record, _ = fixture()
                record[field] = value
                self.assertFalse(self.matches(obj, record))

    def test_old_material_parameter_and_modifier_edits_still_fail(self):
        for kind in ("roughness", "modifier"):
            with self.subTest(kind=kind):
                obj, _, record, _ = fixture()
                if kind == "roughness": record["materials"][0]["nodes"][0]["values"]["Roughness"] = .2
                else: record["modifiers"][0]["object"] = "OtherRig"
                self.assertFalse(self.matches(obj, record))

    def test_each_new_parameter_edit_fails(self):
        for name, value in (("Transmission Dispersion Scale", .1),
                            ("Transmission Dispersion Abbe Number", 21.0)):
            with self.subTest(name=name):
                obj, _, record, inputs = fixture()
                inputs[name].default_value = value
                record["materials"][0]["nodes"][0]["values"][name] = value
                self.assertFalse(self.matches(obj, record))

    def test_new_parameter_link_fails_even_at_default_value(self):
        for name in ("Transmission Dispersion Scale", "Transmission Dispersion Abbe Number"):
            with self.subTest(name=name):
                obj, _, record, inputs = fixture()
                inputs[name].is_linked = True
                self.assertFalse(self.matches(obj, record))

    def test_new_link_record_is_not_discarded(self):
        obj, _, record, _ = fixture()
        record["materials"][0]["links"].append(("Value", "Value", "Principled BSDF", "Roughness"))
        self.assertFalse(self.matches(obj, record))

    def test_unknown_added_material_input_is_not_ignored(self):
        obj, _, record, _ = fixture()
        record["materials"][0]["nodes"][0]["values"]["Unknown Future Input"] = 0.0
        self.assertFalse(self.matches(obj, record))

    def test_partial_input_schema_is_not_projected(self):
        obj, _, record, inputs = fixture()
        del inputs["Transmission Dispersion Abbe Number"]
        self.assertFalse(self.matches(obj, record))

    def test_non_principled_node_is_not_projected(self):
        obj, _, record, _ = fixture()
        obj.material_slots[0].material.node_tree.nodes[0].bl_idname = "ShaderNodeGroup"
        self.assertFalse(self.matches(obj, record))

    def test_missing_signature_fails_and_explicit_expected_is_supported(self):
        obj, old, record, _ = fixture()
        del obj["gat_fingerprint"]
        self.assertFalse(self.matches(obj, record))
        self.assertTrue(self.matches(obj, record, digest(old)))


if __name__ == "__main__":
    unittest.main()
