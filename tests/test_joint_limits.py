"""Математика signed-axis adapter и legacy contract без импорта Blender."""

import importlib
import json
import math
from pathlib import Path
import sys
import unittest

from game_asset_tools.assembly.contracts import JointLimit, rig_from_dict
from game_asset_tools.assembly.joint_limits import _desired, _profile


class JointLimitMathTests(unittest.TestCase):
    def test_import_does_not_require_bpy(self):
        importlib.import_module("game_asset_tools.assembly.joint_limits")
        self.assertNotIn("bpy", sys.modules)

    def test_signed_axes_preserve_asymmetric_endpoints_and_membership(self):
        for axis in range(3):
            for sign in (-1, 1):
                vector = tuple(sign if index == axis else 0 for index in range(3))
                profile, subset = _profile([JointLimit("Hinge", vector, -.31, .73)], ["Hinge"])
                item = profile[0]
                for angle in (-.4, -.31, 0, .4, .73, .8):
                    in_contract = -.31 <= angle <= .73
                    in_native = item["native_lower"] <= sign*angle <= item["native_upper"]
                    self.assertEqual(in_contract, in_native, (axis, sign, angle))
                self.assertEqual(subset, ("Hinge",))
                fk, ik = _desired(item), _desired(item, ik=True)
                self.assertEqual(fk["euler_order"][0].lower(), "xyz"[axis])
                for index, name in enumerate("xyz"):
                    self.assertEqual(ik["lock_ik_"+name], index != axis)
                    if index != axis:
                        self.assertEqual((fk["min_"+name], fk["max_"+name]), (0, 0))
                        self.assertEqual((ik["ik_min_"+name], ik["ik_max_"+name]), (0, 0))

    def test_invalid_contract_or_unsupported_native_cases_are_not_clamped(self):
        cases = [JointLimit("Hinge", (1, 1, 0), -.2, .2),
                 JointLimit("Hinge", (math.sqrt(.5), math.sqrt(.5), 0), -.2, .2),
                 JointLimit("Hinge", (0, 0, 0), -.2, .2),
                 JointLimit("Hinge", (1, 0, 0), math.nan, .2),
                 JointLimit("Hinge", (1, 0, 0), -.2, math.inf),
                 JointLimit("Hinge", (1, 0, 0), .1, .2),
                 JointLimit("Hinge", (1, 0, 0), -.2, -.1),
                 JointLimit("Hinge", (1, 0, 0), True, .2),
                 JointLimit("Hinge", (1, 0, 0), -math.pi-.01, .2),
                 JointLimit("Hinge", (1, 0, 0), -.2, math.pi+.01)]
        for joint in cases:
            with self.subTest(joint=joint), self.assertRaises(ValueError): _profile([joint], ())
        valid = JointLimit("Hinge", (1, 0, 0), -.2, .2)
        for limits, subset in (([valid, valid], ()), ([valid], ["Missing"]),
                               ([valid], ["Hinge", "Hinge"]), ([{}], ()), ([], ()), ("invalid", ())):
            with self.subTest(limits=limits, subset=subset), self.assertRaises(ValueError): _profile(limits, subset)

    def test_single_turn_boundaries_and_fixed_hinge_are_allowed(self):
        for lower, upper in ((-math.pi, math.pi), (0, 0)):
            item = _profile([JointLimit("Hinge", (1, 0, 0), lower, upper)], ())[0][0]
            self.assertEqual((item["native_lower"], item["native_upper"]), (lower, upper))

    def test_existing_rig_with_empty_joints_keeps_schema_one(self):
        project = Path(__file__).resolve().parents[1]
        value = json.loads((project/"game_assets/weapons/industrial_biped.rig.json").read_text(encoding="utf-8"))
        rig = rig_from_dict(value)
        self.assertEqual(rig.schema_version, 1)
        self.assertEqual(rig.joints, ())
        self.assertEqual(value["joints"], [])


if __name__ == "__main__": unittest.main()
