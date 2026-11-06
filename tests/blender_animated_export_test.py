"""Real recipe -> registered rigid skin -> static/animated GLB -> Blender round trip."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.export import export_asset, save_asset
from game_asset_tools.operations import execute
from game_asset_tools.style import load_style

OUTPUT = PROJECT / "output/animated_export"
FIXTURE = OUTPUT / "project"


class AnimatedExportTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        target = FIXTURE / "game_assets/tests/rig_fixture"
        shutil.copytree(PROJECT / "tests/fixtures/animated_rig", target, dirs_exist_ok=True)
        shutil.copyfile(PROJECT / "game_style.json", FIXTURE / "game_style.json")
        self.entry = Registry(FIXTURE).get("rig_fixture")
        build(self.entry, load_config(self.entry), load_style(FIXTURE))
        self.objects = asset_objects(find_root(self.entry.id), helpers=False)
        self.rig = next(obj for obj in self.objects if obj.type == "ARMATURE")
        self.mesh = next(obj for obj in self.objects if obj.type == "MESH")

    def test_static_default_and_animated_round_trip(self):
        source = save_asset(self.entry.id, OUTPUT / "source", overwrite=True)
        source_hash = hashlib.sha256(Path(source["blend"]).read_bytes()).hexdigest()
        static = export_asset(self.entry.id, OUTPUT / "static", entry=self.entry, overwrite=True)
        self.assertFalse(static["animations_requested"])
        self.assertEqual(static["structure"]["animations"], 0)
        unrelated = bpy.data.actions.new("UnrelatedRigAction")
        # Даже подходящий непустой Action не должен автоматически попасть на этот риг.
        self.rig.animation_data.action = unrelated
        hinge = self.rig.pose.bones["Hinge"]
        for frame, angle in [(1, 0.0), (12, 1.2)]:
            hinge.rotation_euler[0] = angle
            hinge.keyframe_insert("rotation_euler", frame=frame)
        self.rig.animation_data.action = None
        hinge.rotation_euler = (0, 0, 0)
        unrelated.use_fake_user = True
        bpy.context.scene.frame_set(7, subframe=0.25)
        self.mesh.hide_set(True)
        selected = list(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        before_actions = (self.rig.animation_data.action, [(t.name, t.mute) for t in self.rig.animation_data.nla_tracks])
        result = execute({"project": str(FIXTURE), "action": "export", "asset": self.entry.id,
                          "output": str(OUTPUT / "animated"), "animations": True, "overwrite": True})
        self.assertEqual(set(result["structure"]["animation_names"]), {"swing", "fold"})
        self.assertEqual(len(result["structure"]["skin_bindings"]), 2)
        self.assertGreaterEqual(result["structure"]["skins"], 1)
        self.assertTrue(all(set(s["joint_names"]) == {"Base", "Hinge"} for s in result["structure"]["skin_details"]))
        self.assertIn("rig_fixture_Links_TipSocket", result["structure"]["node_names"])
        self.assertEqual(bpy.context.scene.frame_current, 7)
        self.assertAlmostEqual(bpy.context.scene.frame_subframe, 0.25)
        self.assertEqual(bpy.context.selected_objects, selected)
        self.assertEqual(bpy.context.view_layer.objects.active, active)
        self.assertTrue(self.mesh.hide_get())
        self.assertEqual(before_actions, (self.rig.animation_data.action, [(t.name, t.mute) for t in self.rig.animation_data.nla_tracks]))
        self.assertEqual(source_hash, hashlib.sha256(Path(source["blend"]).read_bytes()).hexdigest())
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=result["glb"])
        rig = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
        mesh = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and "HingeLink" in obj.name)
        self.assertEqual(set(rig.data.bones.keys()), {"Base", "Hinge"})
        self.assertEqual(next(m for m in mesh.modifiers if m.type == "ARMATURE").object, rig)
        for vertex in mesh.data.vertices:
            weights = [g.weight for g in vertex.groups if g.weight > 0.00001]
            self.assertEqual(len(weights), 1)
            self.assertAlmostEqual(weights[0], 1.0, places=5)
        # Real playback: choose the imported action/slot, evaluate skin and socket.
        action = next(action for action in bpy.data.actions if action.name == "swing")
        rig.animation_data.action = action
        if action.slots:
            rig.animation_data.action_slot = next(slot for slot in action.slots if slot.target_id_type == "OBJECT")
        for track in rig.animation_data.nla_tracks:
            track.mute = True
        socket = next(obj for obj in bpy.context.scene.objects if "TipSocket" in obj.name)
        def points(frame):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
            return evaluated.matrix_world @ evaluated.data.vertices[0].co, socket.matrix_world.translation.copy()
        start = points(1)
        bent = points(12)
        self.assertGreater((bent[0] - start[0]).length, 0.1)
        self.assertGreater((bent[1] - start[1]).length, 0.1)
        report = {"project_root": str(PROJECT), "blender": bpy.app.version_string, "source_blend": source,
                  "source_blend_sha256": source_hash, "static": static, "animated": result,
                  "rigid_weights_preserved": True, "skin_and_socket_playback": True,
                  "glb_sha256": hashlib.sha256(Path(result["glb"]).read_bytes()).hexdigest()}
        (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def test_external_armature_and_unweighted_vertices_fail_before_output(self):
        external = bpy.data.objects.new("UnmanagedRig", bpy.data.armatures.new("UnmanagedData"))
        bpy.context.scene.collection.objects.link(external)
        self.mesh.modifiers[0].object = external
        with self.assertRaisesRegex(ValueError, "external or excluded armature"):
            export_asset(self.entry.id, OUTPUT / "invalid", entry=self.entry, animations=True, overwrite=True)
        self.mesh.modifiers[0].object = self.rig
        self.mesh.vertex_groups.clear()
        with self.assertRaisesRegex(ValueError, "unweighted or invalid vertex"):
            export_asset(self.entry.id, OUTPUT / "invalid", entry=self.entry, animations=True, overwrite=True)

    def test_silent_loss_rejected_without_replacing_delivery(self):
        result = export_asset(self.entry.id, OUTPUT / "preserved", entry=self.entry, animations=True, overwrite=True)
        path = Path(result["glb"])
        previous = path.read_bytes()
        from game_asset_tools.export import inspect_glb
        socket = "rig_fixture_Links_TipSocket"
        for damage, message in [("clips", "lost action clips"), ("skin", "lost skin/weights"),
                                ("joints", "lost joints"), ("socket", "lost socket parent")]:
            with self.subTest(damage=damage):
                def damaged_payload(candidate):
                    summary = inspect_glb(candidate)
                    if damage == "clips":
                        summary["animation_details"] = []
                    elif damage == "skin":
                        summary["skin_bindings"] = []
                    elif damage == "joints":
                        summary["skin_details"][0]["joint_names"] = ["Base"]
                    else:
                        summary["node_parents"][socket] = "Base"
                    return summary
                with patch("game_asset_tools.export.inspect_glb", side_effect=damaged_payload):
                    with self.assertRaisesRegex(ValueError, message):
                        export_asset(self.entry.id, OUTPUT / "preserved", entry=self.entry, animations=True, overwrite=True)
                self.assertEqual(path.read_bytes(), previous)
                self.assertFalse(list(path.parent.glob(".rig_fixture_*.glb")))

    def test_bevel_and_skin_survive_together_without_editing_source(self):
        mesh = next(obj for obj in self.objects if obj.type == "MESH" and "HingeLink" in obj.name)
        modifier = mesh.modifiers.new("AuthoredBevel", "BEVEL")
        modifier.width, modifier.segments = 0.04, 2
        count = len(mesh.data.vertices)
        result = export_asset(self.entry.id, OUTPUT / "animated_bevel", entry=self.entry,
                              animations=True, overwrite=True)
        self.assertEqual(len(mesh.data.vertices), count)
        self.assertIn("AuthoredBevel", mesh.modifiers)
        self.assertTrue(mesh.modifiers["RigidSkin"].show_viewport)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=result["glb"])
        imported = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and "HingeLink" in obj.name)
        self.assertGreater(len(imported.data.vertices), count)
        self.assertGreater(len(imported.data.polygons), 12)
        self.assertEqual(len([mod for mod in imported.modifiers if mod.type == "ARMATURE"]), 1)
        for vertex in imported.data.vertices:
            weights = [group.weight for group in vertex.groups if group.weight > 0.00001]
            self.assertEqual(len(weights), 1)
            self.assertAlmostEqual(weights[0], 1.0, places=5)

    def test_shape_keys_are_rejected_before_losing_authored_data(self):
        self.mesh.shape_key_add(name="Basis")
        self.mesh.shape_key_add(name="AuthoredShape")
        with self.assertRaisesRegex(ValueError, "cannot preserve shape keys"):
            export_asset(self.entry.id, OUTPUT / "invalid", entry=self.entry, animations=True, overwrite=True)

    def test_unassigned_actions_and_invalid_flag_rejected(self):
        self.rig.animation_data_clear()
        with self.assertRaisesRegex(ValueError, "active or stashed action"):
            export_asset(self.entry.id, OUTPUT / "invalid", entry=self.entry, animations=True, overwrite=True)
        with self.assertRaisesRegex(ValueError, "boolean"):
            execute({"project": str(FIXTURE), "action": "export", "asset": self.entry.id, "animations": "true"})


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AnimatedExportTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_ANIMATED_EXPORT_OK", result.testsRun, OUTPUT / "report.json")
