"""Пользовательский workflow: register/publish/install/reopen через Core и Blender UI."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "tests"), str(PROJECT / "blender_addon")]
import blender_assembly_replacement_test as fixtures
from game_asset_tools.asset.lifecycle import set_status
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from game_asset_tools.assembly import authoring, replacement
from game_asset_tools.assembly.inspection import ObjectRef
from game_asset_tools.assembly.library import LibraryError, read_part


class AssemblyAuthoringTests(unittest.TestCase):
    # Fixture уже создаёт настоящий rigid skin, Action, markers, соседей и две
    # опубликованные формы. Новые проверки не копируют реализацию publish/replace.
    publish = fixtures.AssemblyReplacementTests.publish

    def setUp(self):
        fixtures.AssemblyReplacementTests.setUp(self)
        self.document = {"interfaces": {"Foot": authoring.interface_to_dict(self.part, self.slot, self.contract,
            armature=ObjectRef("Rig", "Skeleton"), objects=self.meshes, sockets=self.sockets, contacts=self.contacts)}}

    def register(self):
        return authoring.register_document("assembly_fixture", self.document)

    def install(self, revision=2, **options):
        return authoring.install_component(self.library, "assembly_fixture", "Foot", self.part.id, revision, **options)

    def neighbors(self):
        return [(o.as_pointer(), fingerprint(o), repr(dict(o.items()))) for o in asset_objects(find_root("assembly_fixture"))
                if o.get("gat_component") != "Foot"]

    def test_registration_preserves_geometry_protection_and_is_idempotent(self):
        state = fixtures.state_snapshot()
        self.assertEqual(self.register()["status"], "registered")
        self.assertEqual(fixtures.state_snapshot(), state)
        self.assertEqual(authoring.validate_component("assembly_fixture", "Foot")["status"], "pass")
        records = self.root["gat_components"]
        self.register()
        self.assertEqual(self.root["gat_components"], records)
        self.assertEqual(fixtures.state_snapshot(), state)

    def test_invalid_documents_are_rejected_atomically(self):
        for case in ("fields", "reference", "asset", "component", "nonfinite", "partial"):
            with self.subTest(case=case):
                document = deepcopy(self.document)
                interface = document["interfaces"]["Foot"]
                if case == "fields":
                    del interface["slot"]
                elif case == "reference":
                    interface["objects"]["shoe"]["component"] = "Rig"
                elif case == "asset":
                    document["asset"] = "another_asset"
                elif case == "component":
                    document["interfaces"]["Absent"] = document["interfaces"].pop("Foot")
                elif case == "nonfinite":
                    origin = interface["part"]["input"]["frame"]["origin"]
                    interface["part"]["input"]["frame"]["origin"] = [float("nan"), *origin[1:]]
                else:
                    document["interfaces"]["Rig"] = deepcopy(interface)
                before = fixtures.snapshot()
                with self.assertRaises(ValueError):
                    authoring.register_document("assembly_fixture", document)
                self.assertEqual(fixtures.snapshot(), before)

    def test_publish_manual_new_revision_does_not_accept_fingerprints(self):
        self.register()
        for vertex in self.mesh.data.vertices:
            if vertex.co.z > 0:
                vertex.co.z += .03
        stored, actual = self.mesh["gat_fingerprint"], fingerprint(self.mesh)
        self.assertNotEqual(stored, actual)
        before = fixtures.snapshot()
        result = authoring.publish_component(self.library, "assembly_fixture", "Foot", "manual_foot", 1)
        self.assertEqual(result["status"], "published")
        self.assertEqual(read_part(self.library, "manual_foot", 1).part.id, "manual_foot")
        self.assertEqual(fixtures.snapshot(), before)
        self.assertEqual((self.mesh["gat_fingerprint"], fingerprint(self.mesh)), (stored, actual))
        with self.assertRaises(LibraryError):
            self.install()
        self.assertEqual(fixtures.snapshot(), before)

    def test_install_repeat_dry_run_and_reopen_use_persisted_references(self):
        self.register()
        before = fixtures.snapshot()
        self.assertEqual(self.install(dry_run=True)["status"], "planned")
        self.assertEqual(fixtures.snapshot(), before)
        neighbors = self.neighbors()
        self.assertEqual(self.install()["status"], "replaced")
        self.assertEqual(self.neighbors(), neighbors)

        state = authoring.get_interface("assembly_fixture", "Foot")
        self.assertEqual(state[0].revision, 2)
        self.assertTrue(state[3]["objects"]["shoe"].local_name.startswith("Mesh_"))
        self.assertEqual(authoring.validate_component("assembly_fixture", "Foot")["status"], "pass")
        path = Path(self.directory.name) / "installed.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path))
        self.assertEqual(authoring.get_interface("assembly_fixture", "Foot")[0].revision, 2)
        self.assertEqual(authoring.validate_component("assembly_fixture", "Foot")["status"], "pass")
        neighbors = self.neighbors()
        self.assertEqual(self.install(revision=1)["status"], "replaced")
        self.assertEqual(self.neighbors(), neighbors)
        self.assertEqual(authoring.get_interface("assembly_fixture", "Foot")[0].revision, 1)
        self.assertEqual(self.install()["status"], "replaced")
        self.assertEqual(self.neighbors(), neighbors)

    def test_library_path_must_be_explicit(self):
        self.register()
        before = fixtures.snapshot()
        with self.assertRaises(LibraryError):
            authoring.publish_component("", "assembly_fixture", "Foot", "new_foot", 1)
        with self.assertRaises(LibraryError):
            authoring.install_component("", "assembly_fixture", "Foot", self.part.id, 2)
        self.assertEqual(fixtures.snapshot(), before)

    def test_metadata_after_mutation_rolls_back_with_scene(self):
        self.register()
        before = fixtures.snapshot()
        with patch.object(replacement, "fingerprint", side_effect=RuntimeError("injected metadata postflight")):
            with self.assertRaisesRegex(RuntimeError, "injected metadata postflight"):
                self.install()
        self.assertEqual(fixtures.snapshot(), before)
        self.assertEqual(authoring.get_interface("assembly_fixture", "Foot")[0].revision, 1)

    def test_install_respects_component_locks_and_approval(self):
        self.register()
        for status in ("locked", "approved"):
            set_status("assembly_fixture", status, ["Foot"])
            before = fixtures.snapshot()
            with self.assertRaises(LibraryError):
                self.install()
            self.assertEqual(fixtures.snapshot(), before)

    def test_blender_sidebar_operators_execute_same_saved_workflow(self):
        import game_asset_tools_addon as addon
        from game_asset_tools_addon import panels, properties
        addon.register()
        self.addCleanup(addon.unregister)
        settings = bpy.context.scene.game_asset_tools
        settings.project = self.directory.name
        bpy.ops.game_asset_tools.refresh()
        settings.category, settings.asset, settings.component = "tests", "assembly_fixture", "Foot"
        path = Path(self.directory.name) / "interfaces.parts.json"
        path.write_text(json.dumps(self.document), encoding="utf-8")
        settings.library_manifest, settings.library_root = str(path), str(self.library)
        settings.library_part_id, settings.library_revision = self.part.id, 2
        self.assertIn(panels.GAT_PT_library, addon._CLASSES)
        self.assertEqual(properties.scene_state(settings)["root"], self.root)
        for action in ("register", "validate", "plan", "install", "validate"):
            self.assertEqual(bpy.ops.game_asset_tools.library_action(action=action), {"FINISHED"}, action)
        settings.library_revision = 3
        self.assertEqual(bpy.ops.game_asset_tools.library_action(action="publish"), {"FINISHED"})
        self.assertEqual(read_part(self.library, self.part.id, 3).part.revision, 3)
        # UI не знает старых ObjectRef: повторная установка получает их из .blend records.
        settings.library_revision = 1
        self.assertEqual(bpy.ops.game_asset_tools.library_action(action="install"), {"FINISHED"})
        settings.component = properties.ALL
        self.assertEqual(bpy.ops.game_asset_tools.library_action(action="validate"), {"FINISHED"})


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AssemblyAuthoringTests))
    output = PROJECT / "output/assembly_authoring"
    output.mkdir(parents=True, exist_ok=True)
    paths = [Path(__file__), *sorted((PROJECT / "game_asset_tools").rglob("*.py")),
             *sorted((PROJECT / "blender_addon/game_asset_tools_addon").rglob("*.py"))]
    (output / "report.json").write_text(json.dumps({"project_root": str(PROJECT), "blender": bpy.app.version_string,
        "source_sha256": {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "suite": {"tests": result.testsRun, "passed": result.wasSuccessful(), "errors": len(result.errors), "failures": len(result.failures)}}, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
