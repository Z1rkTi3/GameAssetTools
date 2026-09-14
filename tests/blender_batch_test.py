"""Real headless batch isolation, material/shape variants and shared renders."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.batch import run_batch
from game_asset_tools.operations import execute


class BlenderBatchTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="gat_batch_test_")
        self.directory = Path(self.temporary.name)
        self.project = self.directory / "project"
        recipe = self.project / "game_assets" / "props" / "batch_block"
        recipe.mkdir(parents=True)
        (recipe / "asset.py").write_text('''from game_asset_tools.asset import ComponentSpec, Parameter
class Recipe:
    parameters = (Parameter("body.width", "Width", "float", 2., min=.1, max=10., components=("Body",)),)
    def components(self, config):
        return {"Body": ComponentSpec("Structure")}
    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        obj = gat.add_box(ctx.name("Block"), (config["parameters"]["body"]["width"], 1., 2.), location=(0, 0, 1.))
        ctx.add(obj, "Block")
        gat.assign_material(obj, gat.project_material("Painted_Metal", ctx.style))
RECIPE = Recipe()
''', encoding="utf-8")
        (recipe / "metadata.json").write_text(json.dumps({"schema_version": 1, "id": "batch_block", "display_name": "Batch Block",
                                                          "category": "props", "recipe_version": 1,
                                                          "supported_stages": ["BLOCKOUT"]}), encoding="utf-8")
        (recipe / "config.json").write_text(json.dumps({"schema_version": 1, "asset": "batch_block",
                                                        "parameters": {"body": {"width": 2.}}}), encoding="utf-8")
        self.shared = {"project": str(self.project), "asset": "batch_block"}
        execute({**self.shared, "action": "build"})
        self.source = self.directory / "original.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source), check_existing=False)
        self.original = self.source.read_bytes()
        self.request = {**self.shared, "blend": str(self.source), "output": str(self.directory / "output"),
                        "batch_config": str(self.directory / "variants.json"), "views": ["front", "perspective"], "resolution": 256}

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temporary.cleanup()

    def manifest(self, variants):
        Path(self.request["batch_config"]).write_text(json.dumps({"schema_version": 1, "variants": variants}), encoding="utf-8")

    def test_four_palettes_one_process_independent_baselines_common_views_and_failed_member(self):
        colors = {"red": [.7, .015, .025, 1], "blue": [.02, .12, .7, 1],
                  "green": [.03, .6, .08, 1], "gold": [.7, .42, .025, 1]}
        variants = [{"name": name, "action": "recolor", "materials": {"Painted_Metal": {"base_color": color}}}
                    for name, color in colors.items()]
        # The wide variant comes first. Every following recolor must still have
        # the source width, and every camera must include the widest variant.
        variants[0] = {"name": "red", "config": {"parameters": {"body": {"width": 5.}},
                                                     "style": {"materials": {"Painted_Metal": {"base_color": colors["red"]}}}}}
        variants.insert(1, {"name": "broken", "config": {"parameters": {"body": {"width": -1}}}})
        self.manifest(variants)
        result = run_batch(self.request)
        self.assertEqual(result["status"], "failed")
        results = {v["name"]: v for v in result["variants"]}
        self.assertEqual(results["broken"]["status"], "failed")
        self.assertIn("must be >=", results["broken"]["error"])
        self.assertNotIn("preview", results["broken"])
        for name, color in colors.items():
            variant = results[name]
            self.assertEqual(variant["status"], "passed", variant)
            self.assertEqual(variant["preview"]["framing"], result["framing"])
            self.assertEqual(set(variant["preview"]["paths"]), {"front", "perspective"})
            self.assertEqual(variant["validation"]["errors"], [])
            self.assertEqual(variant["bounds"]["dimensions"][0], 5. if name == "red" else 2.)
            for path in variant["preview"]["paths"].values():
                self.assertEqual(Path(path).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            image = bpy.data.images.load(variant["preview"]["paths"]["front"], check_existing=False)
            try:
                center = ((image.size[1] // 2) * image.size[0] + image.size[0] // 2) * 4
                rgb = list(image.pixels[center:center+3])
                # Pure palette blocks fill the center pixel; compare channel
                # order rather than lighting-dependent absolute brightness.
                self.assertEqual(sorted(range(3), key=lambda i: rgb[i]),
                                 sorted(range(3), key=lambda i: color[i]), (name, rgb))
            finally:
                bpy.data.images.remove(image)
            bpy.ops.wm.open_mainfile(filepath=variant["blend"], load_ui=False, use_scripts=False)
            block = asset_objects(find_root("batch_block"), "Body")[0]
            for actual, expected in zip(block.material_slots[0].material.diffuse_color, color):
                self.assertAlmostEqual(actual, expected, places=5)
        self.assertEqual(self.source.read_bytes(), self.original)
        report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        images = ET.parse(result["comparison"]).getroot().findall(".//{http://www.w3.org/2000/svg}image")
        self.assertEqual(len(images), 8)

    def test_all_outputs_preflight_before_opening_or_modifying_scene(self):
        self.manifest([{"name": "one"}, {"name": "two"}])
        sentinel = Path(self.request["output"]) / "batches/batch_block/two/previews/batch_block/asset/front.png"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b"preserve")
        root = find_root("batch_block")
        objects = tuple(asset_objects(root))
        with self.assertRaises(FileExistsError):
            run_batch(self.request)
        self.assertEqual(tuple(asset_objects(root)), objects)
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertFalse(sentinel.parents[3].joinpath("one").exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_locked_variant_fails_and_dry_run_does_not_save(self):
        execute({**self.shared, "action": "status", "state": "locked", "components": ["Body"]})
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source), check_existing=False)
        original = self.source.read_bytes()
        self.manifest([{"name": "red", "action": "recolor", "materials": {"Painted_Metal": {"base_color": [1, 0, 0, 1]}}}])
        result = run_batch({**self.request, "dry_run": True})
        self.assertEqual(result["status"], "failed")
        self.assertIn("locked", result["variants"][0]["error"])
        self.assertFalse(Path(self.request["output"]).exists())
        self.assertEqual(self.source.read_bytes(), original)

    def test_batch_without_blend_builds_once_and_planning_creates_no_geometry(self):
        self.manifest([{"name": "one", "config": {"parameters": {"body": {"width": 3}}}}, {"name": "two"}])
        request = {k: v for k, v in self.request.items() if k != "blend"}
        bpy.ops.wm.read_factory_settings(use_empty=True)
        result = run_batch({**request, "dry_run": True})
        self.assertEqual(result["status"], "planned")
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertFalse(Path(self.request["output"]).exists())
        operations = []
        def record_execute(value):
            operations.append(value["action"])
            return execute(value)
        # Rendering is already verified above. Here the failure is deliberate to
        # exercise per-variant render errors and baseline build count cheaply.
        with patch("game_asset_tools.operations.execute", side_effect=record_execute), \
             patch("game_asset_tools.preview.render_preview", side_effect=RuntimeError("test render failure")):
            result = run_batch(request)
        self.assertEqual(operations.count("build"), 1)
        self.assertEqual(operations.count("rebuild"), 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual([v["bounds"]["dimensions"][0] for v in result["variants"]], [3., 2.])
        self.assertTrue(all("test render failure" in v["error"] for v in result["variants"]))
        self.manifest([{"name": "invalid_color", "action": "recolor",
                        "materials": {"Painted_Metal": {"alpha": -1}}}])
        invalid = run_batch({**request, "dry_run": True, "output": str(Path(self.request["output"]).parent / "invalid")})
        self.assertEqual(invalid["status"], "failed")
        self.assertIn("outside", invalid["variants"][0]["error"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlenderBatchTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
