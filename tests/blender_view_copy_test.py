"""Verify saved viewport copies with real Blender, including a fresh-file read."""

import hashlib
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.export import save_asset
from game_asset_tools.export.view_copy import _viewports
from game_asset_tools.inspection import bounds
from game_asset_tools.operations import execute


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot():
    state = []
    for space, region, width, height in _viewports():
        state.append((space.as_pointer(), region.as_pointer(), width, height,
                      space.lens, space.clip_start, space.clip_end,
                      space.lock_object, space.lock_bone, space.lock_cursor, space.lock_camera,
                      space.shading.type, space.shading.use_scene_lights, space.shading.use_scene_world,
                      tuple(region.view_location), tuple(region.view_rotation), region.view_distance,
                      region.view_perspective, region.lock_rotation, region.show_sync_view,
                      region.use_box_clip, region.use_clip_planes,
                      tuple(region.view_camera_offset), region.view_camera_zoom))
    return state, tuple(bpy.context.selected_objects), bpy.context.view_layer.objects.active, bpy.data.filepath


def verify_saved_copy(view):
    """Read persisted RNA and project evaluated bounds using Blender's camera API.

    The viewport's default 2x view-plane zoom corresponds to half the camera lens
    in perspective; its ortho scale is 2 * distance * 36 / lens. We deliberately
    do not call RegionView3D.update(): it needs a drawn UI/GPU context in Blender.
    """
    root = find_root("rubin_tower")
    box = bounds(asset_objects(root, helpers=False))
    center = Vector(box["center"])
    corners = [Vector(point) for point in product(*zip(box["min"], box["max"]))]
    camera_data = bpy.data.cameras.new("Projection verifier")
    camera = bpy.data.objects.new("Projection verifier", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    checked = 0
    for space, region, width, height in _viewports():
        assert (region.view_location - center).length < 1e-4
        assert region.view_perspective == ("PERSP" if view == "perspective" else "ORTHO")
        assert space.shading.type == "MATERIAL"
        assert space.lock_object is None and not space.lock_cursor and not space.lock_camera
        camera_data.type = region.view_perspective
        camera_data.sensor_fit = "AUTO"
        camera_data.sensor_width = 36
        camera_data.sensor_height = 24
        camera_data.lens = space.lens / 2
        camera_data.ortho_scale = region.view_distance * 72 / space.lens
        camera_data.clip_start = space.clip_start
        camera_data.clip_end = space.clip_end
        camera.rotation_mode = "QUATERNION"
        camera.rotation_quaternion = region.view_rotation
        camera.location = region.view_location + region.view_rotation @ Vector((0, 0, region.view_distance))
        bpy.context.view_layer.update()
        projection = camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=width, y=height)
        matrix = projection @ camera.matrix_world.inverted()
        for point in corners:
            projected = matrix @ Vector((*point, 1))
            assert projected.w > 0
            ndc = projected.xyz / projected.w
            assert abs(ndc.x) < 0.999 and abs(ndc.y) < 0.999, (view, width, height, tuple(ndc))
            assert -1 < ndc.z < 1, (view, tuple(ndc))
        checked += 1
    assert checked > 1
    print("GAT_VIEW_COPY_REOPEN_PASS", json.dumps({"view": view, "viewports": checked, "bounds": box}))


class ViewCopyTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        execute({"action": "build", "project": str(PROJECT), "asset": "rubin_tower"})
        root = find_root("rubin_tower")
        transform = root_object(root)
        transform.location = (13, -7, 5)
        transform.rotation_euler = (0.12, 0.08, 0.37)
        transform.scale = (1.4, 0.8, 1.2)
        body = asset_objects(root, "Body")[0]
        array = body.modifiers.new("Evaluated bounds fixture", "ARRAY")
        array.count = 2
        array.relative_offset_displace = (1.8, 0, 0)
        for index, (space, region, _, _) in enumerate(_viewports()):
            region.view_location = (index + 100, -index - 200, 70)
            region.view_distance = index + 0.4
            space.shading.type = "WIREFRAME"
            space.clip_start = 0.2
            space.clip_end = 90
            space.lock_cursor = True
            space.lock_object = body
        bpy.context.view_layer.objects.active = body
        body.select_set(True)
        self.source = self.output / "source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source), check_existing=False)
        self.source_hash = digest(self.source)
        self.before = snapshot()

    def assert_preserved(self):
        self.assertEqual(snapshot(), self.before)
        self.assertEqual(digest(self.source), self.source_hash)

    def test_front_and_perspective_reopen_with_full_evaluated_model(self):
        for view in ("front", "perspective"):
            with self.subTest(view=view):
                result = save_asset("rubin_tower", self.output / view, view_copy=True, view=view)
                self.assertEqual(Path(result["blend"]).name, "rubin_tower_view.blend")
                self.assertGreater(result["framing"]["viewport_count"], 1)
                self.assert_preserved()
                child = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", result["blend"],
                                        "--python-exit-code", "1", "--python", str(Path(__file__).resolve()),
                                        "--", "--verify", view], text=True, capture_output=True, timeout=90)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                self.assertIn("GAT_VIEW_COPY_REOPEN_PASS", child.stdout)

    def test_save_failure_restores_view_and_source(self):
        with patch("game_asset_tools.export.view_copy._write_copy", side_effect=RuntimeError("injected disk failure")):
            with self.assertRaisesRegex(RuntimeError, "injected disk failure"):
                save_asset("rubin_tower", self.output, view_copy=True)
        self.assert_preserved()
        self.assertFalse((self.output / "blend" / "rubin_tower_view.blend").exists())

    def test_existing_copy_and_invalid_view_are_protected(self):
        result = save_asset("rubin_tower", self.output, view_copy=True)
        copy_hash = digest(result["blend"])
        with self.assertRaises(FileExistsError):
            save_asset("rubin_tower", self.output, view_copy=True)
        with self.assertRaises(ValueError):
            save_asset("rubin_tower", self.output, view_copy=True, view="bad", overwrite=True)
        self.assertEqual(digest(result["blend"]), copy_hash)
        self.assert_preserved()

    def test_even_overwrite_cannot_replace_current_source(self):
        copy_path = self.output / "blend" / "rubin_tower_view.blend"
        copy_path.parent.mkdir()
        bpy.ops.wm.save_as_mainfile(filepath=str(copy_path), check_existing=False)
        self.source = copy_path
        self.source_hash = digest(copy_path)
        self.before = snapshot()
        with self.assertRaisesRegex(ValueError, "current source file"):
            save_asset("rubin_tower", self.output, view_copy=True, overwrite=True)
        self.assert_preserved()

    def test_normal_save_keeps_existing_behavior(self):
        before_views = snapshot()[:3]
        result = save_asset("rubin_tower", self.output)
        self.assertEqual(Path(result["blend"]).name, "rubin_tower.blend")
        self.assertEqual(bpy.data.filepath, result["blend"])
        self.assertEqual(snapshot()[:3], before_views)
        self.assertEqual(digest(self.source), self.source_hash)


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify_saved_copy(sys.argv[sys.argv.index("--verify") + 1])
    else:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ViewCopyTests))
        if not result.wasSuccessful():
            raise SystemExit(1)
        print("GAT_VIEW_COPY_TESTS_PASS")
