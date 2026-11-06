"""Чистые проверки геометрии и ограничений нового рецепта, без Blender."""

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from game_asset_tools.asset.parameters import changed_components, load_config, set_value
from game_asset_tools.asset.registry import Registry


PROJECT = Path(__file__).resolve().parents[1]


class MechGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entry = Registry(PROJECT).get("industrial_walker")
        cls.recipe = cls.entry.load()
        # RecipeEntry импортирует asset.py как уникальный модуль; функции ниже
        # намеренно доступны без bpy и без запуска процессов Blender.
        import sys
        cls.module = sys.modules[cls.recipe.__class__.__module__]
        cls.original = load_config(cls.entry)

    def setUp(self):
        self.config = deepcopy(self.original)

    def change(self, **updates):
        for path, value in updates.items():
            set_value(self.config["parameters"], path, value)
        return self.config

    def test_default_report_is_nonmutating_and_explicit_about_approximations(self):
        before = deepcopy(self.config)
        report = self.recipe.mechanical_report(self.config)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(self.config, before)
        self.assertGreater(report["support"]["minimum_margin"], 0.05)
        self.assertTrue(report["support"]["projection_inside"])
        self.assertAlmostEqual(report["comApprox"]["position"][0], 0.0, places=12)
        self.assertGreater(report["comApprox"]["solid_volume_proxy"], 0)
        self.assertEqual(report["comApprox"]["mass_model"], "equal_density_closed_solids")
        self.assertGreaterEqual(len(report["assumptions"]), 4)
        self.assertEqual(set(self.recipe.components(self.config)), {"Body", "Leg_Left", "Leg_Right"})

    def test_hull_is_one_profile_mesh_and_all_meshes_are_closed(self):
        parts = self.module.geometry_data(self.config)
        hulls = [part for part in parts if part["name"] == "Hull"]
        self.assertEqual(len(hulls), 1)
        self.assertEqual(len(hulls[0]["vertices"]), 24)
        for part in parts:
            with self.subTest(part=part["component"] + "/" + part["name"]):
                vertices = part["vertices"]
                self.assertTrue(all(math.isfinite(v) for vertex in vertices for v in vertex))
                directed = Counter()
                for face in part["faces"]:
                    self.assertGreaterEqual(len(face), 3)
                    self.assertEqual(len(face), len(set(face)))
                    for a, b in zip(face, face[1:] + face[:1]):
                        self.assertIn(a, range(len(vertices)))
                        directed[a, b] += 1
                self.assertTrue(all(directed[b, a] == count == 1 for (a, b), count in directed.items()))
                volume, center = self.module._mass_proxy(part)
                self.assertGreater(volume, 0)
                self.assertTrue(all(math.isfinite(value) for value in center))

    def test_second_leg_is_actual_reflection_with_outward_winding(self):
        parts = self.module.geometry_data(self.config)
        left = {p["name"]: p for p in parts if p["component"] == "Leg_Left"}
        right = {p["name"]: p for p in parts if p["component"] == "Leg_Right"}
        self.assertEqual(set(left), {"HipPivot", "UpperLink", "KneePivot", "LowerLink", "AnklePivot", "Foot"})
        self.assertEqual(set(left), set(right))
        for name in left:
            self.assertEqual(right[name]["origin"], (-left[name]["origin"][0], *left[name]["origin"][1:]))
            self.assertEqual(right[name]["vertices"], [(-x, y, z) for x, y, z in left[name]["vertices"]])
            self.assertEqual(right[name]["faces"], [tuple(reversed(face)) for face in left[name]["faces"]])

    def test_link_lengths_and_hinge_origins_match_the_parameters(self):
        report = self.recipe.mechanical_report(self.config)
        parts = self.module.geometry_data(self.config)
        for label in ("Left", "Right"):
            joints = report["joints"][label]
            self.assertAlmostEqual(math.dist(joints["hip"], joints["knee"]), 0.75, places=12)
            self.assertAlmostEqual(math.dist(joints["knee"], joints["ankle"]), 0.9, places=12)
            by_name = {p["name"]: p for p in parts if p["component"] == "Leg_" + label}
            for name, joint in (("UpperLink", "hip"), ("LowerLink", "knee"), ("Foot", "ankle")):
                self.assertEqual(by_name[name]["origin"], joints[joint])
            for name, start, end in (("UpperLink", "hip", "knee"), ("LowerLink", "knee", "ankle")):
                mesh = by_name[name]
                centers = [tuple(sum(v[i] for v in ring) / len(ring) + mesh["origin"][i] for i in range(3))
                           for ring in (mesh["vertices"][:8], mesh["vertices"][-8:])]
                self.assertLess(math.dist(centers[0], joints[start]), 1e-12)
                self.assertLess(math.dist(centers[1], joints[end]), 1e-12)

    def test_dimension_and_joint_changes_keep_the_real_sole_at_zero(self):
        self.change(**{"body.width": 2.8, "body.length": 3.0, "legs.upper_length": 0.95,
                       "legs.lower_length": 1.1, "legs.hip_angle": 22.0, "legs.knee_angle": 45.0,
                       "feet.height": 0.3})
        report = self.recipe.mechanical_report(self.config)
        self.assertEqual(report["errors"], [])
        self.assertAlmostEqual(report["metrics"]["upper_length"], 0.95, places=12)
        self.assertAlmostEqual(report["metrics"]["lower_length"], 1.1, places=12)
        self.assertNotEqual(report["metrics"]["hip_height"], self.recipe.mechanical_report(self.original)["metrics"]["hip_height"])
        for part in self.module.geometry_data(self.config):
            if part["name"] == "Foot":
                self.assertAlmostEqual(min(v[2] + part["origin"][2] for v in part["vertices"]), 0.0, places=12)

    def test_zero_bevel_has_no_degenerate_duplicate_corners(self):
        self.change(**{"body.bevel": 0.0})
        hull = next(p for p in self.module.geometry_data(self.config) if p["name"] == "Hull")
        self.assertEqual(len(hull["vertices"]), 12)
        self.assertEqual(len(set(hull["vertices"])), 12)
        self.assertGreater(self.module._mass_proxy(hull)[0], 0)

    def test_sockets_declare_opposing_axes_and_the_same_fit(self):
        report = self.recipe.mechanical_report(self.config)
        self.assertEqual(len(report["sockets"]), 2)
        for socket in report["sockets"]:
            self.assertEqual(socket["standard"], "hinge_v1")
            self.assertEqual(socket["origin"], report["joints"][socket["side"]]["hip"])
            self.assertEqual(socket["body_OUT_axis"], tuple(-v for v in socket["leg_IN_axis"]))
            self.assertGreater(socket["bore_diameter"], socket["pin_diameter"])
            self.assertAlmostEqual(socket["bore_diameter"] - socket["pin_diameter"], 0.004)

    def test_bad_values_fail_before_any_blender_build(self):
        cases = [{"legs.upper_length": float("nan")}, {"body.width": True},
                 {"mounts.standard": "unknown"}, {"feet.width": 0.4, "legs.upper_thickness": 0.34},
                 {"legs.hip_angle": -10.0, "legs.knee_angle": 110.0},
                 {"legs.upper_length": 0.45, "body.height": 1.4}]
        for updates in cases:
            self.config = deepcopy(self.original)
            self.change(**updates)
            with self.subTest(updates=updates):
                report = self.recipe.mechanical_report(self.config)
                self.assertTrue(report["errors"])
                with self.assertRaises(ValueError):
                    self.recipe.components(self.config)

    def test_single_leg_preview_is_explicit_and_preserves_the_other_recipe_components(self):
        self.change(**{"symmetry.mirror": False})
        report = self.recipe.mechanical_report(self.config)
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("Одноногий" in warning for warning in report["warnings"]))
        self.assertEqual(set(report["joints"]), {"Left"})
        self.assertEqual(set(self.recipe.components(self.config)), {"Body", "Leg_Left", "Leg_Right"})
        self.assertFalse(any(p["component"] == "Leg_Right" for p in self.module.geometry_data(self.config)))

    def test_json_still_rejects_float32_values_outside_declared_bounds(self):
        import struct
        for path, bound in [("body.bevel", 0.18), ("legs.upper_thickness", 0.12), ("legs.upper_thickness", 0.34)]:
            outside = struct.unpack("<f", struct.pack("<f", bound))[0]
            with self.subTest(path=path, value=outside):
                # Исправление относится только к Blender controls: числовой
                # JSON payload за пределами диапазона остаётся некорректным.
                with self.assertRaises(ValueError):
                    load_config(self.entry, overrides={path: outside})

    def test_json_round_trip_and_rebuild_dependencies(self):
        restored = json.loads(json.dumps(self.config))
        self.assertEqual(self.recipe.mechanical_report(restored), self.recipe.mechanical_report(self.config))
        wider = load_config(self.entry, overrides={"body.width": 2.8})
        self.assertEqual(changed_components(self.recipe, self.config, wider), {"Body", "Leg_Left", "Leg_Right"})
        feet = load_config(self.entry, overrides={"feet.width": 0.8})
        self.assertEqual(changed_components(self.recipe, self.config, feet), {"Leg_Left", "Leg_Right"})


if __name__ == "__main__":
    unittest.main()
