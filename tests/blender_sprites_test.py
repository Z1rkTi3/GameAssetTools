"""Real Eevee evidence: shared framing, RGBA packing and source-scene isolation."""

from array import array
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from game_asset_tools.asset.geometry_state import geometry_state
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.operations import execute
from game_asset_tools.sprites.render import _framing, _render_frames, render_sprites
from game_asset_tools.sprites.settings import validate_settings


def image_pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = array("f", [0.0]) * (image.size[0] * image.size[1] * 4)
        image.pixels.foreach_get(values)
        return tuple(image.size), values
    finally:
        bpy.data.images.remove(image)


class BlenderSpriteTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        execute({"project": str(PROJECT), "asset": "rubin_tower", "action": "build"})
        self.root = find_root("rubin_tower")
        self.objects = asset_objects(self.root)
        self.body = next(obj for obj in self.objects if obj.get("gat_component") == "Body")
        self.temporary = tempfile.TemporaryDirectory(prefix="gat_sprite_test_")
        self.directory = Path(self.temporary.name)
        self.settings = {"resolution": 128, "directions": 8, "look": "toon"}

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temporary.cleanup()

    def snapshot(self):
        return {"geometry": geometry_state(self.objects),
                "fingerprints": {obj.name: fingerprint(obj) for obj in self.objects},
                "scene": bpy.context.scene.as_pointer(), "mode": bpy.context.mode,
                "selection": sorted(obj.name for obj in bpy.context.selected_objects),
                "active": getattr(bpy.context.view_layer.objects.active, "name", None),
                "camera": getattr(bpy.context.scene.camera, "name", None),
                "world": getattr(bpy.context.scene.world, "name", None),
                "frame": bpy.context.scene.frame_current,
                "datablocks": {name: sorted(item.name for item in getattr(bpy.data, name))
                               for name in ("objects", "meshes", "materials", "scenes", "worlds", "cameras", "lights")}}

    def test_eight_directions_alpha_atlas_exact_pixels_pivot_and_scene_preservation(self):
        for name, datablock in (("User camera", bpy.data.cameras.new("User camera")),
                               ("User light", bpy.data.lights.new("User light", "AREA"))):
            obj = bpy.data.objects.new(name, datablock)
            bpy.context.scene.collection.objects.link(obj)
            obj.location = (30, 20, 10)
            obj.hide_render = True
            if obj.type == "CAMERA":
                bpy.context.scene.camera = obj
        bpy.context.scene.world = bpy.data.worlds.new("User world")
        bpy.context.scene.frame_set(23)
        self.body.select_set(True)
        bpy.context.view_layer.objects.active = self.body
        before = self.snapshot()
        result = render_sprites("rubin_tower", self.directory, self.settings)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["frames"]), 8)
        self.assertEqual([item["azimuth"] for item in result["frames"]], [45., 90., 135., 180., 225., 270., 315., 0.])
        self.assertEqual(result, json.loads(Path(result["report"]).read_text(encoding="utf-8")))
        atlas_size, atlas = image_pixels(result["atlas"]["path"])
        self.assertEqual(atlas_size, (528, 264))
        pivots = {tuple(item["pivot_pixels"]) for item in result["frames"]}
        self.assertEqual(len(pivots), 1)
        pivot = next(iter(pivots))
        self.assertAlmostEqual(pivot[0], 64.)
        self.assertGreater(pivot[1], 64.)
        self.assertLess(pivot[1], 128.)
        for item in result["frames"]:
            size, values = image_pixels(item["path"])
            self.assertEqual(size, (128, 128))
            alphas = values[3::4]
            self.assertEqual(min(alphas), 0.)
            self.assertEqual(max(alphas), 1.)
            # No clipped geometry or alpha contamination at any image border.
            for x, y in [(x, y) for x in range(128) for y in (0, 127)] + [(x, y) for x in (0, 127) for y in range(128)]:
                self.assertEqual(values[(y * 128 + x) * 4 + 3], 0.)
            rect = item["rect"]
            bottom = atlas_size[1] - rect["y"] - 128
            for row in range(128):
                start = ((bottom + row) * atlas_size[0] + rect["x"]) * 4
                # Includes partially transparent antialiased pixels and RGB
                # encoding, catching premultiplication/double-gamma mistakes.
                self.assertEqual(atlas[start:start + 128 * 4], values[row * 128 * 4:(row + 1) * 128 * 4])
        self.assertEqual(atlas[3], 0.)

    def test_toon_smooth_surface_has_three_actual_light_bands(self):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
        sphere = bpy.context.object
        for polygon in sphere.data.polygons:
            polygon.use_smooth = True
        material = bpy.data.materials.new("White sphere")
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 1, 1, 1)
        sphere.data.materials.append(material)
        settings = validate_settings({"resolution": 128, "directions": 1, "azimuth": 0,
                                      "elevation": 0, "light_azimuth": 0, "light_elevation": 55})
        from game_asset_tools.inspection import bounds
        frame = _framing(bounds([sphere]), Vector((0, 0, -1)), [0], settings)
        path = self.directory / "bands.png"
        _render_frames([sphere], [path], [0], settings, frame)
        _, values = image_pixels(path)
        # Count coarse output color bins so PNG rounding/dithering does not turn
        # each display band into several false colors. Antialiasing is excluded.
        bands = Counter(round(values[index] * 255 / 8)
                        for index in range(0, len(values), 4) if values[index + 3] == 1.)
        dominant = [key for key, count in bands.items() if count > 100]
        self.assertEqual(len(dominant), 3, bands)
        self.assertGreater(max(dominant) - min(dominant), 12)

    def test_preview_same_full_series_framing_standard_and_object_material_override(self):
        override = self.body.active_material.copy()
        node = next(node for node in override.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        node.inputs["Base Color"].default_value = (.01, .05, .8, 1)
        override.diffuse_color = (.01, .05, .8, 1)
        self.body.material_slots[0].link = "OBJECT"
        self.body.material_slots[0].material = override
        before = self.snapshot()
        toon = render_sprites("rubin_tower", self.directory, self.settings, preview=True)
        standard = render_sprites("rubin_tower", self.directory / "standard",
                                  {**self.settings, "look": "standard"}, preview=True)
        planned = render_sprites("rubin_tower", self.directory, self.settings, dry_run=True)
        self.assertEqual(toon["framing"], standard["framing"])
        self.assertEqual(toon["framing"], planned["framing"])
        self.assertIsNone(toon["atlas"])
        self.assertEqual(len(toon["frames"]), 1)
        toon_size, toon_pixels = image_pixels(toon["frames"][0]["path"])
        standard_size, standard_pixels = image_pixels(standard["frames"][0]["path"])
        self.assertEqual(toon_size, standard_size)
        self.assertNotEqual(toon_pixels, standard_pixels)
        # A point inside the upper Body region must use the blue OBJECT override.
        for values in (toon_pixels, standard_pixels):
            blues = sum(values[index + 2] > values[index] * 3 and values[index + 3] > .99
                        for index in range(0, len(values), 4))
            self.assertGreater(blues, 250)
        self.assertEqual(before, self.snapshot())

    def test_dry_run_overwrite_and_render_failure_preserve_scene_and_existing_outputs(self):
        before = self.snapshot()
        plan = render_sprites("rubin_tower", self.directory / "planned", self.settings, dry_run=True)
        self.assertEqual(plan["status"], "planned")
        self.assertFalse((self.directory / "planned").exists())
        existing = self.directory / "sprites/rubin_tower/frames/direction_000.png"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"existing PNG")
        manifest = existing.parent.parent / "sprites.json"
        manifest.write_text("existing complete manifest", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            render_sprites("rubin_tower", self.directory, self.settings)
        with patch("game_asset_tools.sprites.render._write_frame", side_effect=RuntimeError("injected render failure")):
            with self.assertRaisesRegex(RuntimeError, "injected render failure"):
                render_sprites("rubin_tower", self.directory, self.settings, overwrite=True)
        self.assertEqual(existing.read_bytes(), b"existing PNG")
        self.assertEqual(manifest.read_text(encoding="utf-8"), "existing complete manifest")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(list(existing.parents[2].glob(".gat_sprites_*")), [])

    def test_edit_mode_invalid_settings_and_asset_id_fail_without_mutation(self):
        before = self.snapshot()
        for settings in ({"resolution": 0}, {"elevation": 100}, {"directions": 3}):
            with self.assertRaises(ValueError):
                render_sprites("rubin_tower", self.directory, settings)
        with self.assertRaises(ValueError):
            render_sprites("../rubin_tower", self.directory, self.settings)
        self.body.select_set(True)
        bpy.context.view_layer.objects.active = self.body
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            with self.assertRaisesRegex(ValueError, "Object Mode"):
                render_sprites("rubin_tower", self.directory, self.settings)
            self.assertEqual(bpy.context.mode, "EDIT_MESH")
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        self.assertEqual(before["geometry"], self.snapshot()["geometry"])

    def test_translated_root_ground_anchor_and_common_pivot(self):
        root = root_object(self.root)
        root.location = (7, -4, 2)
        bpy.context.view_layer.update()
        plan = render_sprites("rubin_tower", self.directory, self.settings, dry_run=True)
        for actual, expected in zip(plan["framing"]["anchor_world"], (7., -4., 2.)):
            self.assertAlmostEqual(actual, expected, places=5)
        self.assertTrue(all(item["pivot_pixels"] == plan["framing"]["pivot_pixels"] for item in plan["frames"]))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderSpriteTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
