"""Проверяет описания замен на координатах существующего промышленного шагохода.

Rest-позиции: MechBattler2 art/walkers/finish_walkers.py, armature();
размеры GroundShoe: art/walkers/walker_recipe.py. Это не Blender pose QA.
"""

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from game_asset_tools.assembly.contracts import (
    ContractError, IDENTITY, check_compatibility, part_from_dict,
    read_contract, rig_from_dict, slot_from_dict,
)


def frame(origin=(0, 0, 0)):
    return {"origin": list(origin), "basis": [list(row) for row in IDENTITY]}


def walker_rig():
    # Все кости источника направлены вдоль +Y Blender с roll=0; rest basis единичная.
    definitions = [("Root", None, (0, 0, 0)), ("Chassis", "Root", (0, 0, 1.95))]
    for side, prefix in ((-1, "Left"), (1, "Right")):
        x, parent = side * .67, "Chassis"
        for suffix, position in (("Hip", (x, 0, 1.90)), ("UpperLeg", (x, 0, 1.90)),
                                 ("Knee", (x, .38, 1.10)), ("LowerLeg", (x, .38, 1.10)),
                                 ("Ankle", (x, -.12, .32)), ("Foot", (x, -.12, .32))):
            name = prefix + suffix
            definitions.append((name, parent, position))
            parent = name
    definitions += [("WeaponMountLeft", "Chassis", (-1.13, -.1, 2.5)),
                    ("WeaponMountRight", "Chassis", (1.13, -.1, 2.5))]
    return {"schema_version": 1, "id": "industrial_biped", "revision": 1,
            "coordinates": {"units": "m", "up": "+Z", "forward": "-Y"},
            "bones": [{"id": name, "parent": parent, "rest": frame(position)} for name, parent, position in definitions],
            # Источник вращает LowerLeg вокруг X. Числа ниже — контрольное
            # требование теста, а не уже утверждённые механические limits игры.
            "joints": [{"bone": "LeftLowerLeg", "axis": [1, 0, 0], "lower": -1.1, "upper": .9}]}


def fixture(kind):
    rig = walker_rig()
    bones = {bone["id"]: bone for bone in rig["bones"]}
    def port(name, bone, interface):
        return {"id": name, "interface": interface, "bone": bone, "frame": deepcopy(bones[bone]["rest"])}
    outputs, contacts, joints = [], [], []
    if kind == "foot":
        anchor = port("ankle", "LeftFoot", "ankle_v1")
        bound = "LeftFoot"
        # Подошва GroundShoe: y=-.20 +/- .47, z=0; относительно ankle (-.12,.32).
        contacts = [{"id": "heel", "bone": bound, "position": [0, .39, -.32]},
                    {"id": "toe", "bone": bound, "position": [0, -.55, -.32]}]
        binding_frame = frame((0, -.08, -.23))
    elif kind == "knee":
        anchor = port("upper", "LeftKnee", "knee_axle_v1")
        bound = "LeftKnee"
        outputs = [port("shin", "LeftLowerLeg", "shin_v1")]
        joints = deepcopy(rig["joints"])
        binding_frame = frame()
    else:
        anchor = port("body", "Chassis", "chassis_v1")
        bound = "Chassis"
        outputs = [port("hip_left", "LeftHip", "hip_v1"), port("hip_right", "RightHip", "hip_v1"),
                   port("weapon_left", "WeaponMountLeft", "weapon_v1"), port("weapon_right", "WeaponMountRight", "weapon_v1")]
        binding_frame = frame((0, 0, .55))
    referenced = {bound, anchor["bone"]} | {p["bone"] for p in outputs} | {j["bone"] for j in joints}
    part = {"schema_version": 1, "id": kind + "_standard", "revision": 1,
            "rig_id": rig["id"], "rig_revision": rig["revision"], "coordinates": deepcopy(rig["coordinates"]),
            "input": anchor, "outputs": outputs, "bones": [deepcopy(bones[b]) for b in sorted(referenced)],
            "bindings": [{"object_id": kind + "_mesh", "bone": bound, "bind_frame": binding_frame}],
            "contacts": contacts, "joints": joints}
    slot = {"schema_version": 1, "slot_id": "left_" + kind if kind != "hull" else "body",
            "rig_id": rig["id"], "rig_revision": 1, "input": deepcopy(anchor), "outputs": deepcopy(outputs),
            "binding_bones": [bound], "contacts": deepcopy(contacts), "joints": deepcopy(joints)}
    return part, slot, rig


class AssemblyContractTests(unittest.TestCase):
    def compatible(self, part, slot, rig):
        return check_compatibility(part_from_dict(part), slot_from_dict(slot), rig_from_dict(rig))

    def test_distinct_library_parts_fit_same_slot_without_mutation(self):
        for kind in ("foot", "knee", "hull"):
            with self.subTest(kind=kind):
                part, slot, rig = fixture(kind)
                before = deepcopy((part, slot, rig))
                self.assertEqual(self.compatible(part, slot, rig), ())
                variant = deepcopy(part)
                variant.update(id=kind + "_armored", revision=2)
                # Иной набор объектов допустим при сохранении механического интерфейса.
                variant["bindings"].append({**deepcopy(variant["bindings"][0]), "object_id": "extra_panel"})
                self.assertEqual(self.compatible(variant, slot, rig), ())
                self.assertEqual((part, slot, rig), before)

    def test_roundtrip_and_duplicate_json_keys(self):
        part, _, _ = fixture("foot")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.json"
            path.write_text(json.dumps(part), encoding="utf-8")
            self.assertEqual(read_contract(path, "part"), part_from_dict(part))
            path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
            with self.assertRaises(ContractError) as error:
                read_contract(path, "part")
            self.assertEqual(error.exception.issue.code, "duplicate_key")
            self.assertEqual(error.exception.issue.component, str(path))
            path.write_text('{"bad":NaN}', encoding="utf-8")
            with self.assertRaises(ContractError):
                read_contract(path, "part")
            path.write_text('{"broken":', encoding="utf-8")
            with self.assertRaises(ContractError) as error:
                read_contract(path, "part")
            self.assertEqual(error.exception.issue.code, "invalid_json")
            with self.assertRaises(ContractError):
                read_contract(Path(directory) / "missing.json", "part")

    def test_rejects_schema_boolean_versions_unknown_fields_and_units(self):
        original, _, _ = fixture("foot")
        for field, value in (("schema_version", 2), ("schema_version", True), ("revision", True),
                             ("revision", 0), ("rig_revision", 1.0), ("unknown", 1), ("id", "../part")):
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                part_from_dict({**original, field: value})
        for coordinates in ({"units": "cm", "up": "+Z", "forward": "-Y"},
                            {"units": "m", "up": "+Z", "forward": "-Z"}):
            with self.assertRaises(ContractError):
                part_from_dict({**original, "coordinates": coordinates})

    def test_rejects_nonfinite_scale_shear_mirror_and_invalid_vector(self):
        for change in ("nan", "huge", "bool", "short", "scale", "shear", "mirror"):
            part, _, _ = fixture("foot")
            transform = part["input"]["frame"]
            if change == "nan": transform["origin"][0] = float("nan")
            elif change == "huge": transform["origin"][0] = 10 ** 1000
            elif change == "bool": transform["origin"][0] = True
            elif change == "short": transform["origin"] = [0, 0]
            elif change == "scale": transform["basis"][0][0] = 2
            elif change == "shear": transform["basis"][1][0] = .2
            else: transform["basis"][0][0] = -1
            with self.subTest(change=change), self.assertRaises(ContractError):
                part_from_dict(part)

    def test_rejects_bone_cycles_missing_parents_and_duplicate_ids(self):
        for change in ("cycle", "parent", "duplicate", "roots"):
            rig = walker_rig()
            if change == "cycle": rig["bones"][0]["parent"] = "LeftFoot"
            elif change == "parent": rig["bones"][2]["parent"] = "Absent"
            elif change == "duplicate": rig["bones"].append(deepcopy(rig["bones"][0]))
            else: rig["bones"][1]["parent"] = None
            with self.subTest(change=change), self.assertRaises(ContractError):
                rig_from_dict(rig)

    def test_rejects_unbound_or_duplicate_objects_and_bad_joint_range(self):
        for change in ("missing", "duplicate", "empty", "axis", "range"):
            part, _, _ = fixture("knee")
            if change == "missing": part["bindings"][0]["bone"] = "Absent"
            elif change == "duplicate": part["bindings"].append(deepcopy(part["bindings"][0]))
            elif change == "empty": part["bindings"] = []
            elif change == "axis": part["joints"][0]["axis"] = [2, 0, 0]
            else: part["joints"][0]["lower"] = .2
            with self.subTest(change=change), self.assertRaises(ContractError):
                part_from_dict(part)

    def test_reports_specific_rig_rest_and_coordinate_mismatch(self):
        part, slot, rig = fixture("foot")
        part["rig_revision"] = 2
        part["coordinates"].update(up="+Y", forward="+Z")
        part["bones"][0]["rest"]["origin"][2] += .1
        issues = self.compatible(part, slot, rig)
        self.assertEqual({i.code for i in issues}, {"rig_mismatch", "coordinates_mismatch", "rest_mismatch"})
        for issue in issues:
            self.assertEqual(issue.component, "left_foot")
            self.assertEqual(issue.severity, "error")
            self.assertTrue(issue.field and issue.message and issue.remedy)
            self.assertNotEqual(issue.expected, issue.actual)

    def test_rejects_knee_pivot_axis_narrow_range_and_missing_shin_socket(self):
        for change, code in (("pivot", "pivot_mismatch"), ("axis", "joint_mismatch"),
                             ("range", "joint_mismatch"), ("output", "missing_output"), ("interface", "interface_mismatch")):
            part, slot, rig = fixture("knee")
            if change == "pivot": part["outputs"][0]["frame"]["origin"][2] += .12
            elif change == "axis": part["joints"][0]["axis"] = [-1, 0, 0]
            elif change == "range": part["joints"][0]["lower"] = -.5
            elif change == "output": part["outputs"] = []
            else: part["input"]["interface"] = "other_axle"
            with self.subTest(change=change):
                self.assertIn(code, {i.code for i in self.compatible(part, slot, rig)})

    def test_rejects_wrong_sole_or_missing_contact_but_allows_different_mesh_frame(self):
        part, slot, rig = fixture("foot")
        part["bindings"][0]["bind_frame"]["origin"][1] += .1
        self.assertEqual(self.compatible(part, slot, rig), ())
        part["contacts"][0]["position"][2] -= .05
        part["contacts"].pop()
        issues = self.compatible(part, slot, rig)
        self.assertEqual([i.code for i in issues], ["sole_mismatch", "sole_mismatch"])

    def test_knee_output_joint_cannot_override_rig_axis_even_if_slot_agrees(self):
        part, slot, rig = fixture("knee")
        part["joints"][0]["axis"] = [0, 1, 0]
        slot["joints"][0]["axis"] = [0, 1, 0]
        self.assertIn("joint_mismatch", {i.code for i in self.compatible(part, slot, rig)})
        part, slot, rig = fixture("knee")
        rig["joints"] = []
        self.assertIn("unexpected_joint", {i.code for i in self.compatible(part, slot, rig)})
        part, slot, rig = fixture("knee")
        part["joints"][0].update(lower=-1.3, upper=1.1)
        self.assertEqual(self.compatible(part, slot, rig), ())

    def test_omitted_input_or_output_joint_still_requires_rig_axis_and_limits(self):
        for port_kind in ("input", "output"):
            part, slot, rig = fixture("knee")
            part["joints"] = []
            slot["joints"] = []
            if port_kind == "input":
                # Та же подвижная кость может служить входом отдельного модуля.
                # Умолчание joint в двух manifest не отменяет требования рига.
                part["input"]["bone"] = "LeftLowerLeg"
                slot["input"]["bone"] = "LeftLowerLeg"
                part["outputs"] = []
                slot["outputs"] = []
            with self.subTest(port=port_kind):
                issues = self.compatible(part, slot, rig)
                self.assertEqual([i.code for i in issues], ["joint_mismatch"])
                self.assertEqual(issues[0].field, "joints.LeftLowerLeg")
                self.assertIsNone(issues[0].actual)

    def test_hull_cannot_move_preserved_hip_or_swap_bound_side(self):
        part, slot, rig = fixture("hull")
        part["outputs"][0]["frame"]["origin"][0] += .2
        self.assertIn("pivot_mismatch", {i.code for i in self.compatible(part, slot, rig)})
        part, slot, rig = fixture("foot")
        right = next(b for b in rig["bones"] if b["id"] == "RightFoot")
        part["bones"].append(deepcopy(right))
        part["bindings"][0]["bone"] = "RightFoot"
        self.assertIn("binding_mismatch", {i.code for i in self.compatible(part, slot, rig)})

    def test_slot_references_missing_bone_and_manual_dataclass_is_revalidated(self):
        part, slot, rig = fixture("foot")
        slot["binding_bones"] = ["Absent"]
        self.assertIn("missing_bone", {i.code for i in self.compatible(part, slot, rig)})
        parsed = part_from_dict(part)
        invalid = replace(parsed, revision=True)
        with self.assertRaises(ContractError):
            check_compatibility(invalid, slot_from_dict(slot), rig_from_dict(rig))

    def test_serialization_is_detached_from_source_and_does_not_import_blender(self):
        import sys
        part, _, _ = fixture("foot")
        parsed = part_from_dict(part)
        part["input"]["frame"]["origin"][2] += 100
        self.assertAlmostEqual(parsed.input.frame.origin[2], .32)
        self.assertEqual(part_from_dict(asdict(parsed)), parsed)
        self.assertNotIn("bpy", sys.modules)


if __name__ == "__main__":
    unittest.main()
