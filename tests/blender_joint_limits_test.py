"""Native FK/IK limits, Save/Open и rollback в изолированной сцене Blender."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.assembly.contracts import JointLimit
from game_asset_tools.assembly import joint_limits as api


def raw_pose(obj):
    return {pb.name: (pb.rotation_mode, *(tuple(getattr(pb, field)) for field in (
        "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")))
            for pb in obj.pose.bones}


def clips(obj):
    data = obj.animation_data
    if data is None: return None
    actions = {data.action} if data.action else set()
    actions.update(s.action for t in data.nla_tracks for s in t.strips if s.action)
    return (data.action, data.action_slot,
            [(action.as_pointer(), action.name,
              [(curve.data_path, curve.array_index,
                [(tuple(k.co), tuple(k.handle_left), tuple(k.handle_right), k.interpolation) for k in curve.keyframe_points])
               for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves])
             for action in sorted(actions, key=lambda a: a.name)])


class NativeJointLimitsTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        data = bpy.data.armatures.new("SourceRigData")
        self.obj = bpy.data.objects.new("SourceRig", data)
        bpy.context.scene.collection.objects.link(self.obj)
        self.obj.select_set(True)
        bpy.context.view_layer.objects.active = self.obj
        bpy.ops.object.mode_set(mode="EDIT")
        upper = data.edit_bones.new("Upper")
        upper.head, upper.tail = (0, 0, 0), (0, 1, 0)
        lower = data.edit_bones.new("Lower")
        lower.head, lower.tail, lower.parent, lower.use_connect = (0, 1, 0), (0, 2, 0), upper, True
        bpy.ops.object.mode_set(mode="OBJECT")
        for pb in self.obj.pose.bones: pb.rotation_mode = "XYZ"
        self.owner = "fixture_author"
        self.obj["author_note"] = "Не изменять"
        self.limits = [JointLimit("Upper", (1, 0, 0), -.31, .73), JointLimit("Lower", (1, 0, 0), -.8, .6)]

    def snapshot(self):
        return {"record": self.obj.get(api.RECORD), "note": self.obj["author_note"],
                "rest": [(b.name, b.parent.name if b.parent else None, tuple(tuple(r) for r in b.matrix_local))
                         for b in self.obj.data.bones], "pose": raw_pose(self.obj), "clips": clips(self.obj),
                "native": [(pb.name, api._fields(pb, api._IK_FIELDS),
                            [(c.as_pointer(), c.name, c.type, api._fields(c, api._FK_FIELDS) if c.type == "LIMIT_ROTATION" else {})
                             for c in pb.constraints]) for pb in self.obj.pose.bones]}

    def apply(self, limits=None, ik=()):
        return api.apply_joint_limits(api.plan_joint_limits(self.obj, self.limits if limits is None else limits,
                                                            owner_id=self.owner, ik_bones=ik))

    def angle(self, bone, axis, order="XYZ"):
        bpy.context.view_layer.update()
        evaluated = self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        pb, rest = evaluated.pose.bones[bone], self.obj.data.bones[bone]
        options = ({"parent_matrix": evaluated.pose.bones[rest.parent.name].matrix,
                    "parent_matrix_local": rest.parent.matrix_local} if rest.parent else {})
        local = rest.convert_local_to_pose(pb.matrix, rest.matrix_local, invert=True, **options)
        return local.to_euler(order)[axis]

    def test_real_fk_all_signed_axes_hold_both_boundaries(self):
        pb = self.obj.pose.bones["Upper"]
        for axis in range(3):
            for sign in (-1, 1):
                with self.subTest(axis=axis, sign=sign):
                    vector = tuple(sign if index == axis else 0 for index in range(3))
                    self.apply([JointLimit("Upper", vector, -.31, .73)])
                    constraint = pb.constraints[-1]
                    for requested, expected in ((-.8, -.31), (.2, .2), (1.2, .73)):
                        pb.rotation_euler = (0, 0, 0)
                        pb.rotation_euler[axis] = sign*requested
                        self.assertAlmostEqual(sign*self.angle("Upper", axis, constraint.euler_order), expected, delta=2e-5)
                        self.assertAlmostEqual(pb.rotation_euler[axis], sign*requested, delta=1e-6)
                    api.remove_joint_limits(self.obj, owner_id=self.owner)

    def test_idempotence_update_remove_preserve_actions_rest_and_raw_channels(self):
        self.obj.animation_data_create()
        action = bpy.data.actions.new("UserClip")
        self.obj.animation_data.action = action
        self.obj.pose.bones["Upper"].rotation_euler.x = .2
        self.obj.pose.bones["Upper"].keyframe_insert("rotation_euler", index=0, frame=1)
        before = self.snapshot()
        self.assertEqual(self.apply(ik=["Upper"])["status"], "applied")
        pointers = [c.as_pointer() for pb in self.obj.pose.bones for c in pb.constraints]
        self.assertEqual(self.apply(ik=["Upper"])["status"], "unchanged")
        updated = [JointLimit("Upper", (-1, 0, 0), -.4, .6), self.limits[1]]
        self.assertEqual(self.apply(updated, ik=["Upper"])["status"], "updated")
        self.assertEqual([c.as_pointer() for pb in self.obj.pose.bones for c in pb.constraints], pointers)
        api.remove_joint_limits(self.obj, owner_id=self.owner)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(api.remove_joint_limits(self.obj, owner_id=self.owner)["status"], "unchanged")

    def test_native_ik_limits_hold_evaluated_chain(self):
        target = bpy.data.objects.new("UserIKTarget", None)
        bpy.context.scene.collection.objects.link(target)
        ik = self.obj.pose.bones["Lower"].constraints.new("IK")
        ik.target, ik.chain_count, ik.use_stretch, ik.iterations = target, 2, False, 500
        limits = [JointLimit("Upper", (-1, 0, 0), -.2, .4), JointLimit("Lower", (1, 0, 0), -.8, .6)]
        self.apply(limits, ik=["Upper", "Lower"])
        # FK constraint тоже может обрезать результат решателя. Отключаем его,
        # чтобы этот тест доказывал работу именно native IK fields, а не clamp
        # после решения IK с уже недостижимым конечным положением цепи.
        for pb in self.obj.pose.bones:
            for constraint in pb.constraints:
                if constraint.type == "LIMIT_ROTATION": constraint.mute = True
        moved = []
        for position in ((0, 1.2, .7), (0, 1.1, -.5), (0, 1.8, .3)):
            target.location = position
            for joint in limits:
                angle = self.angle(joint.bone, 0)
                contract_angle = angle * joint.axis[0]
                moved.append(abs(angle))
                self.assertGreaterEqual(contract_angle, joint.lower-3e-4)
                self.assertLessEqual(contract_angle, joint.upper+3e-4)
            self.assertEqual(ik.target, target)
        self.assertGreater(max(moved), .01, "IK действительно изменила evaluated pose")

    def test_foreign_constraints_active_limits_and_stale_plan_refuse_before_write(self):
        pb = self.obj.pose.bones["Upper"]
        foreign = pb.constraints.new("LIMIT_ROTATION")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Чужой"):
            api.plan_joint_limits(self.obj, self.limits, owner_id=self.owner)
        self.assertEqual(self.snapshot(), before)
        pb.constraints.remove(foreign)
        pb.use_ik_limit_x = True
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "active IK"):
            api.plan_joint_limits(self.obj, self.limits, owner_id=self.owner, ik_bones=["Upper"])
        self.assertEqual(self.snapshot(), before)
        pb.use_ik_limit_x = False
        plan = api.plan_joint_limits(self.obj, self.limits, owner_id=self.owner)
        pb.ik_min_x = -.5
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Stale"): api.apply_joint_limits(plan)
        self.assertEqual(self.snapshot(), before)

    def test_copy_rotation_and_user_data_are_preserved(self):
        target = bpy.data.objects.new("UserRotationTarget", None)
        bpy.context.scene.collection.objects.link(target)
        foreign = self.obj.pose.bones["Upper"].constraints.new("COPY_ROTATION")
        foreign.target = target
        before = self.snapshot()
        self.apply()
        api.remove_joint_limits(self.obj, owner_id=self.owner)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(foreign.target, target)

    def test_late_apply_update_and_remove_failure_roll_back(self):
        for updating in (False, True):
            if updating: self.apply(ik=["Upper", "Lower"])
            before = self.snapshot()
            changed = [JointLimit(j.bone, j.axis, -.2, .4) for j in self.limits]
            original, count = api._write_fields, 0
            def failure(owner, fields):
                nonlocal count
                original(owner, fields)
                count += 1
                if count == 3: raise RuntimeError("injected late write")
            with patch.object(api, "_write_fields", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "injected late write"):
                    self.apply(changed, ik=["Upper", "Lower"])
            self.assertEqual(self.snapshot(), before)
            if updating:
                def remove_failure(owner, fields):
                    original(owner, fields)
                    raise RuntimeError("injected remove write")
                with patch.object(api, "_write_fields", side_effect=remove_failure):
                    with self.assertRaisesRegex(RuntimeError, "injected remove write"):
                        api.remove_joint_limits(self.obj, owner_id=self.owner)
                self.assertEqual(self.snapshot(), before)
                api.remove_joint_limits(self.obj, owner_id=self.owner)

    def test_owned_record_not_name_guards_authored_edits_and_different_sets(self):
        self.apply(ik=["Upper"])
        before = self.snapshot()
        with self.assertRaises(ValueError):
            api.plan_joint_limits(self.obj, [self.limits[0]], owner_id=self.owner, ik_bones=["Upper"])
        with self.assertRaises(ValueError): api.remove_joint_limits(self.obj, owner_id="different_owner")
        self.assertEqual(self.snapshot(), before)
        constraint = self.obj.pose.bones["Upper"].constraints[-1]
        constraint.min_x -= .01
        before = self.snapshot()
        self.assertEqual(api.inspect_joint_limits(self.obj, owner_id=self.owner)["status"], "invalid")
        with self.assertRaises(ValueError): api.remove_joint_limits(self.obj, owner_id=self.owner)
        self.assertEqual(self.snapshot(), before)

    def test_save_open_keeps_ownership_and_original_ik_values(self):
        original = api._fields(self.obj.pose.bones["Upper"], api._IK_FIELDS)
        self.apply(ik=["Upper"])
        with tempfile.TemporaryDirectory(prefix="gat_native_limits_") as directory:
            path = Path(directory)/"limits.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
            bpy.ops.wm.open_mainfile(filepath=str(path))
            self.obj = bpy.data.objects["SourceRig"]
            self.assertEqual(api.inspect_joint_limits(self.obj, owner_id=self.owner)["status"], "valid")
            api.remove_joint_limits(self.obj, owner_id=self.owner)
            self.assertEqual(api._fields(self.obj.pose.bones["Upper"], api._IK_FIELDS), original)
            self.assertEqual(self.obj["author_note"], "Не изменять")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeJointLimitsTests))
    raise SystemExit(not result.wasSuccessful())
