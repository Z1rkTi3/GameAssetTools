"""Verify the saved blockout and disposable rebuilds; never save test mutations.

Run from the project root with Blender --background --factory-startup
--python-exit-code 1 --python game_assets/towers/rubin_tower/verify_blender.py.
"""

import json
from pathlib import Path
import sys
import unittest

import bmesh
import bpy
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))

from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.style import load_style
from game_asset_tools.validation import validate_asset

BLEND = PROJECT / "output/blend/rubin_tower.blend"
REPORTS = []
TOLERANCE = 1e-5


class BlockoutTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.open_mainfile(filepath=str(BLEND))
        self.entry = Registry(PROJECT).get("rubin_tower")

    def check_geometry(self, label):
        root = find_root("rubin_tower")
        pivot = root_object(root)
        p = json.loads(root["gat_config"])["parameters"]
        self.assertEqual(root["gat_stage"], "BLOCKOUT")
        validation = validate_asset("rubin_tower", self.entry)
        self.assertEqual(validation["errors"], [], validation)
        self.assertEqual(validation["warnings"], [], validation)
        objects = asset_objects(root)
        self.assertEqual(len(objects), 17)
        groups = {}
        points = {}
        for obj in objects:
            self.assertEqual(obj.type, "MESH")
            self.assertEqual(len(obj.modifiers), 0)
            groups.setdefault(obj["gat_component"], []).append(obj)
            transform = pivot.matrix_world.inverted() @ obj.matrix_world
            points[obj] = [transform @ vertex.co for vertex in obj.data.vertices]
            mesh = bmesh.new()
            try:
                mesh.from_mesh(obj.data)
                self.assertTrue(all(edge.is_manifold for edge in mesh.edges), obj.name)
                self.assertGreater(mesh.calc_volume(signed=True), 0, obj.name)
            finally:
                mesh.free()
            material = obj.material_slots[0].material
            shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            self.assertEqual(shader.inputs["Emission Strength"].default_value, 0)

        self.assertEqual({k: len(v) for k, v in groups.items()},
                         {"Base": 1, "Door": 1, "Body": 1, "Window": 1, "Supports": 12, "Gem": 1})

        def bounds(component):
            vertices = [v for obj in groups[component] for v in points[obj]]
            return (Vector(tuple(min(v[i] for v in vertices) for i in range(3))),
                    Vector(tuple(max(v[i] for v in vertices) for i in range(3))))

        def close(a, b):
            self.assertAlmostEqual(a, b, delta=TOLERANCE)

        base_min, base_max = bounds("Base")
        body_min, body_max = bounds("Body")
        close(base_min.z, 0)
        close(body_min.z, base_max.z)
        self.assertGreater(base_max.x, body_max.x)
        self.assertGreater(base_max.y, body_max.y)
        for component, parameter in (("Base", "base"), ("Body", "body"), ("Gem", "gem")):
            low, high = bounds(component)
            close(low.x + high.x, 0)
            close(low.y + high.y, 0)
            for axis, name in enumerate(("width", "depth", "height")):
                close(high[axis] - low[axis], p[parameter][name])
        for component, parent, thickness, offset in (("Door", "Base", 0.06, 0.02),
                                                       ("Window", "Body", 0.04, 0.015)):
            low, high = bounds(component)
            parent_low, parent_high = bounds(parent)
            close((low.x + high.x) / 2, (parent_low.x + parent_high.x) / 2)
            close((low.y + high.y) / 2, parent_low.y - offset)
            self.assertLess(low.y, parent_low.y)
            self.assertGreater(high.y, parent_low.y)
            close(high.y - low.y, thickness)
            close(high.x - low.x, p[component.lower()]["width"])
            close(high.z - low.z, p[component.lower()]["height"])
            self.assertGreaterEqual(low.z + TOLERANCE, parent_low.z)
            self.assertLess(high.z, parent_high.z)
        low, high = bounds("Window")
        close(low.z + high.z, body_min.z + body_max.z)
        self.assertLess(high.x - low.x, high.z - low.z)

        def symmetry_error(transformed, target):
            self.assertEqual(len(transformed), len(target))
            error = max(min((a - b).length for b in target) for a in transformed)
            self.assertLess(error, TOLERANCE)
            return error

        def mirror_error(source, target, axis):
            reflected = [Vector(tuple(-v[i] if i == axis else v[i] for i in range(3))) for v in source]
            return symmetry_error(reflected, target)

        support_errors = []
        rotation_errors = []
        for index in range(1, 4):
            sides = {side: next(obj for obj in groups["Supports"]
                               if obj["gat_local_name"] == f"{side}_{index:02d}")
                     for side in ("Left", "Right", "Front", "Back")}
            for negative, positive, axis in (("Left", "Right", 0), ("Front", "Back", 1)):
                support_errors.append(mirror_error(points[sides[negative]], points[sides[positive]], axis))
                self.assertLess(max(v[axis] for v in points[sides[negative]]), 0)
                self.assertGreater(min(v[axis] for v in points[sides[positive]]), 0)
            for source, target in (("Right", "Back"), ("Back", "Left"),
                                   ("Left", "Front"), ("Front", "Right")):
                rotated = [Vector((-v.y, v.x, v.z)) for v in points[sides[source]]]
                rotation_errors.append(symmetry_error(rotated, points[sides[target]]))
        support_low, support_high = bounds("Supports")
        for axis in (0, 1):
            self.assertGreaterEqual(support_low[axis] + TOLERANCE, body_min[axis])
            self.assertLessEqual(support_high[axis] - TOLERANCE, body_max[axis])
        gem = groups["Gem"][0]
        self.assertEqual(len(gem.data.polygons), 8)
        self.assertTrue(all(len(face.vertices) == 3 for face in gem.data.polygons))
        gem_errors = [mirror_error(points[gem], points[gem], axis) for axis in (0, 1)]
        gem_shader = next(n for n in gem.material_slots[0].material.node_tree.nodes
                          if n.type == "BSDF_PRINCIPLED")
        ruby_color = list(gem_shader.inputs["Base Color"].default_value)
        self.assertGreater(ruby_color[0], 3 * max(ruby_color[1:3]))
        clearance = bounds("Gem")[0].z - bounds("Supports")[1].z
        close(clearance, p["gem"]["hover_gap"])
        self.assertGreater(clearance, 0)
        REPORTS.append({"case": label, "status": "pass", "stage": root["gat_stage"],
                        "objects": len(objects), "supports_mirror_error": max(support_errors),
                        "supports_quarter_turn_error": max(rotation_errors),
                        "gem_mirror_error": max(gem_errors), "vertical_clearance": clearance,
                        "gem_dimensions": {name: p["gem"][name] for name in ("width", "depth", "height")},
                        "gem_base_color": ruby_color,
                        "door_center_x": sum(v.x for v in points[groups["Door"][0]]) / 8,
                        "window_center_x": sum(v.x for v in points[groups["Window"][0]]) / 8,
                        "validation": validation["status"]})

    def test_saved_blockout(self):
        p = json.loads(find_root("rubin_tower")["gat_config"])["parameters"]
        self.assertEqual(p, load_config(self.entry)["parameters"])
        self.assertGreater(p["gem"]["width"], 0.65 * p["body"]["width"])
        self.assertGreater(p["gem"]["depth"], 0.65 * p["body"]["depth"])
        self.assertGreater(p["gem"]["height"], p["body"]["height"])
        self.check_geometry("saved_blockout")

    def test_changed_proportions_and_moved_root_rebuild(self):
        pivot = root_object(find_root("rubin_tower"))
        pivot.location = (10, -8, 3)
        pivot.rotation_euler.z = 0.4
        bpy.context.view_layer.update()
        config = load_config(self.entry, overrides={"base.height": 2.1, "body.height": 3.2, "body.depth": 4.6,
                             "supports.height": 2.2, "supports.inward_offset": 0.8,
                             "gem.width": 3.9, "gem.depth": 3.4, "gem.hover_gap": 0.2})
        build(self.entry, config, load_style(PROJECT, config.get("style", {})), rebuild=True)
        self.check_geometry("changed_proportions_moved_root")

    def test_selective_dependencies_and_invalid_config(self):
        # An archived .blend may have an older source digest. Establish the
        # current recipe baseline in this disposable scene before testing scope.
        baseline = load_config(self.entry)
        build(self.entry, baseline, load_style(PROJECT, baseline.get("style", {})), rebuild=True)
        for overrides, expected in (({"gem.width": 3.9}, {"Gem"}),
                                    ({"window.width": 0.5}, {"Window"}),
                                    ({"supports.spacing": 3.8}, {"Supports", "Gem"}),
                                    ({"body.height": 3.1}, {"Body", "Window", "Supports", "Gem"})):
            config = load_config(self.entry, overrides=overrides)
            plan = build(self.entry, config, load_style(PROJECT, config.get("style", {})), rebuild=True, dry_run=True)
            self.assertEqual(set(plan["components"]), expected)
        for overrides in ({"base.width": 4.0}, {"body.depth": 3.8},
                          {"window.width": 2.0}, {"door.height": 2.0},
                          {"supports.inward_offset": 1.7}):
            with self.assertRaises(ValueError):
                load_config(self.entry, overrides=overrides)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlockoutTests))
    report = PROJECT / "output/reports/rubin_tower_geometry.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"status": "pass" if result.wasSuccessful() else "fail",
                                 "tests": result.testsRun, "cases": REPORTS}, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
