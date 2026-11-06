"""Настоящие Blender-проверки ownership/rest/weights/markers без изменения источника."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import bpy
from mathutils import Euler, Matrix, Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.asset.geometry_state import geometry_state
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.assembly.contracts import IDENTITY, part_from_dict, rig_from_dict
from game_asset_tools.assembly.inspection import ObjectRef, inspect_part, inspect_rig
from game_asset_tools.style import load_style

OUTPUT = PROJECT / "output/assembly_inspection"


def frame(origin=(0, 0, 0)):
    return {"origin": list(origin), "basis": IDENTITY}


def manifests():
    bones = [{"id": "Root", "parent": None, "rest": frame()},
             {"id": "LeftFoot", "parent": "Root", "rest": frame((-.67, -.12, .32))}]
    rig = {"schema_version": 1, "id": "inspection_biped", "revision": 1,
           "coordinates": {"units": "m", "up": "+Z", "forward": "-Y"}, "bones": bones,
           "joints": [{"bone": "LeftFoot", "axis": [1, 0, 0], "lower": -.7, "upper": .7}]}
    part = {"schema_version": 1, "id": "inspection_foot", "revision": 1,
            "rig_id": rig["id"], "rig_revision": 1, "coordinates": rig["coordinates"],
            "input": {"id": "ankle", "interface": "ankle_v1", "bone": "LeftFoot", "frame": frame((-.67, -.12, .32))},
            "outputs": [{"id": "service", "interface": "power_v1", "bone": "LeftFoot", "frame": frame((-.67, .20, .32))}],
            "bones": [bones[1]],
            "bindings": [{"object_id": "shoe", "bone": "LeftFoot", "bind_frame": frame((0, -.08, -.23))}],
            "contacts": [{"id": "heel", "bone": "LeftFoot", "position": [0, .39, -.32]},
                         {"id": "toe", "bone": "LeftFoot", "position": [0, -.55, -.32]}],
            "joints": rig["joints"]}
    return part_from_dict(part), rig_from_dict(rig)


def state_snapshot():
    objects = list(bpy.context.scene.objects)
    rigs = [obj for obj in objects if obj.type == "ARMATURE"]
    actions = []
    for action in bpy.data.actions:
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        curves.append((curve.data_path, curve.array_index,
                                       [(list(key.co), list(key.handle_left), list(key.handle_right), key.interpolation)
                                        for key in curve.keyframe_points]))
        actions.append((action.as_pointer(), action.name, curves))
    return {"frame": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
            "selected": [obj.as_pointer() for obj in bpy.context.selected_objects],
            "active": bpy.context.view_layer.objects.active.as_pointer() if bpy.context.view_layer.objects.active else None,
            "objects": [(obj.as_pointer(), obj.name, fingerprint(obj), repr(dict(obj.items()))) for obj in objects],
            "geometry": geometry_state([obj for obj in objects if obj.type == "MESH"]),
            "rigs": [(rig.as_pointer(), rig.data.as_pointer(), rig.data.pose_position,
                      [(bone.name, bone.parent.name if bone.parent else None, [list(row) for row in bone.matrix_local]) for bone in rig.data.bones],
                      [(bone.name, [list(row) for row in bone.matrix_basis]) for bone in rig.pose.bones],
                      rig.animation_data.action.as_pointer() if rig.animation_data and rig.animation_data.action else None) for rig in rigs],
            "actions": actions}


class AssemblyInspectionTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_assembly_inspection_")
        self.addCleanup(self.directory.cleanup)
        project = Path(self.directory.name)
        shutil.copytree(PROJECT / "tests/fixtures/assembly_inspection", project / "game_assets/tests/assembly_fixture")
        shutil.copyfile(PROJECT / "game_style.json", project / "game_style.json")
        entry = Registry(project).get("assembly_fixture")
        build(entry, load_config(entry), load_style(project))
        self.root = find_root(entry.id)
        self.pivot = root_object(self.root)
        self.objects = {(obj["gat_component"], obj["gat_local_name"]): obj for obj in asset_objects(self.root)}
        self.rig = self.objects[("Rig", "Skeleton")]
        self.mesh = self.objects[("Foot", "Shoe")]
        self.part, self.contract = manifests()
        self.meshes = {"shoe": ObjectRef("Foot", "Shoe")}
        self.sockets = {"ankle": ObjectRef("Foot", "AnkleSocket"), "service": ObjectRef("Foot", "ServiceSocket")}
        self.contacts = {"heel": ObjectRef("Foot", "HeelContact"), "toe": ObjectRef("Foot", "ToeContact")}
        self.rig.animation_data_create()
        self.rig.animation_data.action = bpy.data.actions.new("FootMotion")
        pose = self.rig.pose.bones["LeftFoot"]
        pose.rotation_mode = "XYZ"
        for number, angle in ((1, 0.0), (12, .55), (24, -.35)):
            pose.rotation_euler.x = angle
            pose.keyframe_insert("rotation_euler", frame=number)
        bpy.context.scene.frame_set(1)

    def inspect(self):
        return inspect_part("assembly_fixture", "Foot", self.part, self.contract,
                            armature=ObjectRef("Rig", "Skeleton"), objects=self.meshes,
                            sockets=self.sockets, contacts=self.contacts)

    def codes(self):
        return {issue["code"] for issue in self.inspect()["issues"]}

    def test_real_skin_markers_and_moved_rig_are_read_only_at_multiple_frames(self):
        self.mesh.name = "Renamed by artist"
        self.objects[("Foot", "ServiceSocket")].name = "Power socket renamed"
        self.pivot.location = (5, 2, 3)
        self.pivot.rotation_euler.z = .37
        self.rig.location = (.4, -.2, .1)
        self.rig.rotation_euler.y = -.15
        source = Path(self.directory.name) / "authored.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        original_file_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        reports = []
        for number, subframe in ((1, 0.0), (12, 0.0), (7, .375)):
            bpy.context.scene.frame_set(number, subframe=subframe)
            bpy.context.view_layer.update()
            before = state_snapshot()
            report = self.inspect()
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual(report["checked"]["vertices"], len(self.mesh.data.vertices))
            self.assertEqual(report["checked"]["sockets"], 2)
            self.assertEqual(report["checked"]["contacts"], 2)
            self.assertEqual(state_snapshot(), before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_file_hash)
            reports.append({"frame": [number, subframe], "report": report})
        OUTPUT.mkdir(parents=True, exist_ok=True)
        paths = [Path(__file__), PROJECT / "game_style.json", *sorted((PROJECT / "game_asset_tools").rglob("*.py")),
                 *sorted((PROJECT / "tests/fixtures/assembly_inspection").glob("*.*"))]
        (OUTPUT / "report.json").write_text(json.dumps({"project_root": str(PROJECT), "blender": bpy.app.version_string,
            "source_sha256": {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
            "temporary_blend_sha256": original_file_hash, "temporary_blend_unchanged": True,
            "scene_state_unchanged": True, "cases": reports}, indent=2), encoding="utf-8")

    def test_rigid_bone_parent_mesh_is_checked_without_changing_pose(self):
        self.mesh.modifiers.clear()
        world = self.mesh.matrix_world.copy()
        self.mesh.parent_type, self.mesh.parent_bone = "BONE", "LeftFoot"
        bpy.context.view_layer.update()
        self.mesh.matrix_world = world
        bpy.context.scene.frame_set(12)
        before = state_snapshot()
        self.assertEqual(self.inspect()["status"], "pass")
        self.assertEqual(state_snapshot(), before)
        self.mesh.modifiers.new("WrongExtraSkin", "ARMATURE").object = self.rig
        self.assertIn("double_binding", self.codes())

    def test_nondeforming_skin_bone_is_rejected_but_bone_parent_still_works(self):
        self.rig.data.bones["LeftFoot"].use_deform = False
        def positions(number):
            bpy.context.scene.frame_set(number)
            bpy.context.view_layer.update()
            mesh = self.mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
            return (mesh.matrix_world @ mesh.data.vertices[0].co,
                    self.objects[("Foot", "ServiceSocket")].matrix_world.translation.copy())
        rest, bent = positions(1), positions(12)
        self.assertLess((rest[0] - bent[0]).length, 1e-6)
        self.assertGreater((rest[1] - bent[1]).length, .05)
        self.assertIn("nondeforming_bone", self.codes())
        # Bone-parent не использует флаг деформации skin и остаётся допустим.
        bpy.context.scene.frame_set(1)
        self.mesh.modifiers.clear()
        world = self.mesh.matrix_world.copy()
        self.mesh.parent_type, self.mesh.parent_bone = "BONE", "LeftFoot"
        bpy.context.view_layer.update()
        self.mesh.matrix_world = world
        bpy.context.scene.frame_set(12)
        self.assertEqual(self.inspect()["status"], "pass")

    def test_rotated_rest_basis_bind_frame_and_sockets_in_bent_pose(self):
        # Авторская rest basis имеет вращение по трём осям, а не только новый
        # world transform рига; ожидаемые matrices задаём до изменения Blender.
        rest = Matrix.Translation(Vector((-.67, -.12, .32))) @ Euler((.3, .2, .4)).to_matrix().to_4x4()
        def contract_frame(matrix):
            return {"origin": list(matrix.translation), "basis": [list(row)[:3] for row in list(matrix)[:3]]}
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.rig.data.edit_bones["LeftFoot"]
        bone.matrix = rest
        bone.length = .16
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.update()
        self.mesh.matrix_world = self.rig.matrix_world @ rest @ Matrix.Translation(Vector((0, -.08, -.23)))
        transforms = {"AnkleSocket": rest, "ServiceSocket": rest @ Matrix.Translation(Vector((0, .32, 0))),
                      "HeelContact": rest @ Matrix.Translation(Vector((0, .39, -.32))),
                      "ToeContact": rest @ Matrix.Translation(Vector((0, -.55, -.32)))}
        for local_name, transform in transforms.items():
            self.objects[("Foot", local_name)].matrix_world = self.rig.matrix_world @ transform
        part, rig = asdict(self.part), asdict(self.contract)
        part["bones"][0]["rest"] = contract_frame(rest)
        rig["bones"][1]["rest"] = contract_frame(rest)
        part["input"]["frame"] = contract_frame(transforms["AnkleSocket"])
        part["outputs"][0]["frame"] = contract_frame(transforms["ServiceSocket"])
        self.part, self.contract = part_from_dict(part), rig_from_dict(rig)
        bpy.context.scene.frame_set(12)
        before = state_snapshot()
        report = self.inspect()
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(state_snapshot(), before)
        part["bones"][0]["rest"]["basis"] = IDENTITY
        self.part = part_from_dict(part)
        self.assertIn("bone_rest", self.codes())

    def test_wrong_rest_parent_and_extra_bone_are_reported(self):
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.rig.data.edit_bones["LeftFoot"]
        bone.parent = None
        bone.head.x += .1
        bone.tail.x += .1
        extra = self.rig.data.edit_bones.new("Unexpected")
        extra.head, extra.tail = (0, 0, 0), (0, .1, 0)
        bpy.ops.object.mode_set(mode="OBJECT")
        codes = self.codes()
        self.assertTrue({"bone_parent", "bone_rest", "bone_set"} <= codes, codes)

    def test_unweighted_blended_and_wrong_bone_vertices_fail(self):
        group = self.mesh.vertex_groups["LeftFoot"]
        other = self.mesh.vertex_groups.new(name="Root")
        for case in ("unweighted", "blended", "wrong", "partial"):
            group.add([0], 1.0, "REPLACE")
            other.remove([0])
            if case == "unweighted": group.remove([0])
            elif case == "blended": other.add([0], .2, "REPLACE")
            elif case == "wrong":
                group.remove([0])
                other.add([0], 1.0, "REPLACE")
            else: group.add([0], .5, "REPLACE")
            with self.subTest(case=case):
                self.assertIn("rigid_weights", self.codes())

    def test_external_rig_modifier_disabled_skin_and_envelopes_fail(self):
        modifier = self.mesh.modifiers[0]
        external = bpy.data.objects.new("External", bpy.data.armatures.new("ExternalData"))
        bpy.context.scene.collection.objects.link(external)
        modifier.object = external
        self.assertIn("armature_modifier", self.codes())
        modifier.object = self.rig
        modifier.show_viewport = False
        self.assertIn("armature_settings", self.codes())
        modifier.show_viewport = True
        modifier.use_bone_envelopes = True
        self.assertIn("armature_settings", self.codes())
        modifier.use_bone_envelopes = False
        self.rig.data.bones["LeftFoot"].bbone_segments = 4
        self.assertIn("nonrigid_bone", self.codes())

    def test_bind_socket_and_contact_offsets_are_checked_in_bent_pose(self):
        bpy.context.scene.frame_set(12)
        self.mesh.location.x += .08
        self.objects[("Foot", "ServiceSocket")].location.y += .10
        self.objects[("Foot", "HeelContact")].location.z -= .05
        bpy.context.view_layer.update()
        before = state_snapshot()
        codes = self.codes()
        self.assertTrue({"bind_frame", "socket_frame", "sole_marker"} <= codes, codes)
        self.assertEqual(state_snapshot(), before)

    def test_socket_wrong_bone_or_missing_semantic_tag_fails(self):
        socket = self.objects[("Foot", "ServiceSocket")]
        socket.parent_bone = "Root"
        self.assertIn("bone_binding", self.codes())
        socket.parent_bone = "LeftFoot"
        del socket["gat_socket"]
        self.assertIn("marker_identity", self.codes())

    def test_explicit_mapping_does_not_accept_foreign_or_unmapped_objects(self):
        self.meshes["shoe"] = ObjectRef("Rig", "Skeleton")
        self.assertIn("ownership", self.codes())
        self.meshes = {"shoe": ObjectRef("Foot", "Shoe")}
        self.sockets.pop("service")
        self.assertTrue({"object_mapping", "unmapped_objects"} <= self.codes())

    def test_duplicate_semantic_identity_and_external_collection_usage_fail(self):
        duplicate = self.mesh.copy()
        self.root.children[0].objects.link(duplicate)
        self.assertIn("object_mapping", self.codes())
        bpy.data.objects.remove(duplicate, do_unlink=True)
        bpy.context.scene.collection.objects.link(self.mesh)
        self.assertIn("external_usage", self.codes())

    def test_scale_units_nonfinite_geometry_and_unsupported_deformation_fail(self):
        self.mesh.scale.x = 1.5
        self.assertIn("invalid_scale", self.codes())
        self.mesh.scale.x = 1.0
        bpy.context.scene.unit_settings.scale_length = .01
        self.assertIn("scene_units", self.codes())
        bpy.context.scene.unit_settings.scale_length = 1.0
        self.mesh.data.vertices[0].co.x = float("nan")
        self.assertIn("nonfinite_geometry", self.codes())
        self.mesh.data.vertices[0].co.x = 0
        self.mesh.modifiers.new("UnverifiedBend", "SIMPLE_DEFORM")
        self.assertIn("unevaluated_modifiers", self.codes())

    def test_rig_only_and_failed_lookup_are_read_only(self):
        before = state_snapshot()
        report = inspect_rig("assembly_fixture", self.contract, armature=ObjectRef("Rig", "Skeleton"))
        self.assertEqual(report["status"], "pass")
        missing = inspect_rig("assembly_fixture", self.contract, armature=ObjectRef("Rig", "Missing"))
        self.assertEqual(missing["status"], "error")
        invalid = inspect_rig("assembly_fixture", self.contract, armature="Skeleton")
        self.assertEqual(invalid["status"], "error")
        self.assertEqual(state_snapshot(), before)

    def test_missing_owned_root_object_and_nonfinite_transform_return_diagnostics(self):
        self.mesh.location.x = float("nan")
        report = self.inspect()
        self.assertIn("nonfinite_transform", {issue["code"] for issue in report["issues"]})
        # JSON-отчёт должен оставаться допустимым даже при повреждённом transform.
        json.dumps(report, allow_nan=False)
        self.mesh.location.x = 0
        self.pivot["gat_role"] = "not_a_root"
        report = self.inspect()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["issues"][0]["code"], "ownership")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AssemblyInspectionTests))
    report_path = OUTPUT / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["suite"] = {"tests": result.testsRun, "passed": result.wasSuccessful(),
                           "failures": len(result.failures), "errors": len(result.errors)}
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_ASSEMBLY_INSPECTION_OK", result.testsRun, OUTPUT / "report.json")
