"""Принадлежность каналов Action проверяется по индексам и пути, а не имени кости."""

import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_asset_tools.export import inspect_glb
from game_asset_tools.export.rig import animation_contract, verify_animation_contract


def fixture():
    # Одинаковые Base/Hinge у двух armature — допустимая структура glTF.
    expected = {"rigs": {"RigA": ["Base", "Hinge"], "RigB": ["Base", "Hinge"]},
                "bindings": {"BodyA": "RigA", "BodyB": "RigB"}, "sockets": {},
                "actions": ["walk_a", "walk_b"],
                "action_targets": {
                    "walk_a": [["Asset", "RigA"], ["Asset", "RigA", "Base"],
                               ["Asset", "RigA", "Base", "Hinge"]],
                    "walk_b": [["Asset", "RigB"], ["Asset", "RigB", "Base"],
                               ["Asset", "RigB", "Base", "Hinge"]]}}
    summary = {"node_names": ["Asset", "RigA", "Base", "Hinge", "BodyA",
                              "RigB", "Base", "Hinge", "BodyB", "Foreign"],
               "node_parent_indices": [None, 0, 1, 2, 1, 0, 5, 6, 5, 0],
               "node_parents": {"RigA": "Asset", "RigB": "Asset"},
               "skin_bindings": [{"node": "BodyA", "skin": 0, "weighted": True},
                                 {"node": "BodyB", "skin": 1, "weighted": True}],
               "skin_details": [{"joint_names": ["Base", "Hinge"], "ancestors": ["RigA", "Asset"]},
                                {"joint_names": ["Base", "Hinge"], "ancestors": ["RigB", "Asset"]}],
               "animation_details": [
                   {"name": "walk_a", "channels": 6, "targets": ["Base", "Hinge"], "target_indices": [2, 3]},
                   {"name": "walk_b", "channels": 6, "targets": ["Base", "Hinge"], "target_indices": [6, 7]}]}
    return expected, summary


class AnimationPostflightTests(unittest.TestCase):
    def test_duplicate_bone_names_in_distinct_rigs_are_valid(self):
        verify_animation_contract(*fixture())

    def test_foreign_object_with_correct_clip_name_is_rejected(self):
        expected, summary = fixture()
        summary["animation_details"][0].update(targets=["Foreign"], target_indices=[9])
        with self.assertRaisesRegex(ValueError, "unowned animation target"):
            verify_animation_contract(expected, summary)

    def test_same_bone_name_on_other_rig_is_rejected(self):
        expected, summary = fixture()
        # Имя Hinge и число каналов сохранены: проверка только имён не видит подмену.
        summary["animation_details"][0].update(targets=["Hinge"], target_indices=[7])
        with self.assertRaisesRegex(ValueError, "unowned animation target"):
            verify_animation_contract(expected, summary)

    def test_another_owned_object_is_not_an_action_owner(self):
        expected, summary = fixture()
        summary["animation_details"][0].update(targets=["BodyA"], target_indices=[4])
        with self.assertRaisesRegex(ValueError, "unowned animation target"):
            verify_animation_contract(expected, summary)

    def test_one_action_may_have_multiple_explicit_owners(self):
        expected, summary = fixture()
        expected["action_targets"]["walk_a"] += expected["action_targets"]["walk_b"]
        summary["animation_details"][0]["target_indices"] = [2, 3, 6, 7]
        verify_animation_contract(expected, summary)

    def test_object_animation_allows_only_its_own_object(self):
        expected, summary = fixture()
        expected["actions"].append("body_move")
        expected["action_targets"]["body_move"] = [["Asset", "RigA", "BodyA"]]
        summary["animation_details"].append({"name": "body_move", "channels": 1,
                                              "targets": ["BodyA"], "target_indices": [4]})
        verify_animation_contract(expected, summary)
        summary["animation_details"][-1].update(targets=["Base"], target_indices=[2])
        with self.assertRaisesRegex(ValueError, "unowned animation target"):
            verify_animation_contract(expected, summary)

    def test_path_components_are_not_split_on_slashes(self):
        expected, summary = fixture()
        summary["node_names"][0] = "Asset/with/slashes"
        for paths in expected["action_targets"].values():
            for path in paths:
                path[0] = "Asset/with/slashes"
        verify_animation_contract(expected, summary)

    def test_same_full_path_is_ambiguous_even_if_target_name_matches(self):
        expected, summary = fixture()
        summary["node_names"].append("Hinge")
        summary["node_parent_indices"].append(2)
        with self.assertRaisesRegex(ValueError, "ambiguous animation target"):
            verify_animation_contract(expected, summary)

    def test_missing_new_evidence_never_uses_legacy_name_only_fallback(self):
        for damage in ("contract", "hierarchy", "targets"):
            with self.subTest(damage=damage):
                expected, summary = fixture()
                if damage == "contract":
                    del expected["action_targets"]
                elif damage == "hierarchy":
                    del summary["node_parent_indices"]
                else:
                    del summary["animation_details"][0]["target_indices"]
                with self.assertRaisesRegex(ValueError, "preflight|inspection"):
                    verify_animation_contract(expected, summary)

    def test_nonempty_clip_cannot_have_empty_or_invalid_target_indices(self):
        for indices in ([], [-1], [10], [True], [2.0]):
            with self.subTest(indices=indices):
                expected, summary = fixture()
                summary["animation_details"][0]["target_indices"] = indices
                with self.assertRaisesRegex(ValueError, "animation target"):
                    verify_animation_contract(expected, summary)

    def test_cyclic_or_incomplete_indexed_hierarchy_is_rejected(self):
        for parents in ([None], [3, 0, 1, 2, 1, 0, 5, 6, 5, 0]):
            with self.subTest(parents=parents):
                expected, summary = fixture()
                summary["node_parent_indices"] = parents
                with self.assertRaisesRegex(ValueError, "hierarchy"):
                    verify_animation_contract(expected, summary)


class _Object(SimpleNamespace):
    __hash__ = object.__hash__

    def get(self, key, default=None):
        return getattr(self, key, default)


class _Bones(list):
    def __contains__(self, name):
        return any(bone.name == name for bone in self)

    def __getitem__(self, key):
        if isinstance(key, str):
            return next(bone for bone in self if bone.name == key)
        return super().__getitem__(key)


def source_fixture():
    identity = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
    root = _Object(name="Asset", type="EMPTY", parent=None, parent_type="OBJECT",
                   constraints=[], animation_data=None, gat_role="asset_root")
    base = SimpleNamespace(name="Base", parent=None, length=1, matrix_local=identity)
    hinge = SimpleNamespace(name="Hinge", parent=base, length=1, matrix_local=identity)
    action = SimpleNamespace(name="walk")
    rig = _Object(name="Rig", type="ARMATURE", parent=root, parent_type="OBJECT", constraints=[],
                  pose=SimpleNamespace(bones=[]), data=SimpleNamespace(bones=_Bones([base, hinge])),
                  animation_data=SimpleNamespace(action=action, nla_tracks=[]))
    mesh = _Object(name="Body", type="MESH", parent=rig, parent_type="OBJECT", constraints=[],
                   animation_data=None,
                   data=SimpleNamespace(shape_keys=None, vertices=[SimpleNamespace(index=0, groups=[
                       SimpleNamespace(group=0, weight=1.0)])]),
                   vertex_groups=[SimpleNamespace(index=0, name="Base")],
                   modifiers=[SimpleNamespace(type="ARMATURE", object=rig, show_viewport=True,
                                              show_render=True, use_vertex_groups=True)])
    return [root, rig, mesh]


class AnimationPreflightTests(unittest.TestCase):
    def test_targets_include_owner_and_all_bones_for_exporter_sampling(self):
        contract = animation_contract(source_fixture())
        self.assertEqual(contract["action_targets"], {"walk": [
            ["Asset", "Rig"], ["Asset", "Rig", "Base"], ["Asset", "Rig", "Base", "Hinge"]]})
        self.assertEqual(json.loads(json.dumps(contract)), contract)

    def test_shared_action_collects_only_explicit_object_owners(self):
        objects = source_fixture()
        objects[2].animation_data = SimpleNamespace(action=objects[1].animation_data.action, nla_tracks=[])
        targets = animation_contract(objects)["action_targets"]["walk"]
        self.assertIn(["Asset", "Rig", "Body"], targets)
        self.assertEqual(len(targets), 4)

    def test_bone_parented_socket_action_uses_complete_bone_path(self):
        objects = source_fixture()
        objects.append(_Object(name="Socket", type="EMPTY", parent=objects[1], parent_type="BONE",
                               parent_bone="Hinge", constraints=[], animation_data=SimpleNamespace(
                                   action=SimpleNamespace(name="socket_move"), nla_tracks=[])))
        targets = animation_contract(objects)["action_targets"]["socket_move"]
        self.assertEqual(targets, [["Asset", "Rig", "Base", "Hinge", "Socket"]])

    def test_stashed_action_and_active_action_are_deduplicated(self):
        objects = source_fixture()
        objects[1].animation_data.nla_tracks = [SimpleNamespace(
            strips=[SimpleNamespace(action=objects[1].animation_data.action)])]
        contract = animation_contract(objects)
        self.assertEqual(contract["actions"], ["walk"])
        self.assertEqual(len(contract["action_targets"]["walk"]), 3)


class AnimationInspectionTests(unittest.TestCase):
    def test_indices_preserve_duplicate_names_without_removing_legacy_fields(self):
        content = {"meshes": [{}], "nodes": [
            {"name": "RigA", "children": [1]}, {"name": "Base"},
            {"name": "RigB", "children": [3]}, {"name": "Base"}],
            "animations": [{"name": "walk", "samplers": [{}], "channels": [
                {"sampler": 0, "target": {"node": 3, "path": "rotation"}}]}]}
        payload = json.dumps(content).encode("utf-8")
        payload += b" " * (-len(payload) % 4)
        blob = struct.pack("<4sIII4s", b"glTF", 2, 20 + len(payload), len(payload), b"JSON") + payload
        with patch.object(Path, "read_bytes", return_value=blob):
            summary = inspect_glb("in-memory.glb")
        self.assertEqual(summary["node_names"], ["RigA", "Base", "RigB", "Base"])
        self.assertEqual(summary["node_parent_indices"], [None, 0, None, 2])
        self.assertEqual(summary["animation_details"][0]["targets"], ["Base"])
        self.assertEqual(summary["animation_details"][0]["target_indices"], [3])
        self.assertIn("node_parents", summary)


if __name__ == "__main__":
    unittest.main()
