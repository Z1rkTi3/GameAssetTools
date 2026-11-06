"""Замена библиотечной детали в живой сборке: сохранность рига и rollback."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bpy
from mathutils import Euler, Matrix

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "tests")]
from blender_assembly_inspection_test import state_snapshot
from blender_assembly_library_test import AssemblyLibraryTests, geometry
from game_asset_tools.asset.lifecycle import plan_build
from game_asset_tools.asset.metadata import encode, fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, component_records
from game_asset_tools.assembly import library, replacement
from game_asset_tools.assembly.contracts import part_from_dict, rig_from_dict, slot_from_dict
from game_asset_tools.assembly.inspection import ObjectRef, _matrix, inspect_part
from game_asset_tools.style import load_style

OUTPUT = PROJECT / "output/assembly_replacement"


def snapshot():
    """Проверяем и GAT records/коллекции, которые не входят в scene snapshot."""
    state = state_snapshot()
    # После relink Blender может перечислять те же ID в другом порядке.
    state["objects"].sort(key=lambda record: record[0])
    return (state, library._ids(),
            [(c.as_pointer(), c.name, repr(dict(c.items())), sorted(o.as_pointer() for o in c.objects),
              sorted(child.as_pointer() for child in c.children)) for c in bpy.data.collections])


class AssemblyReplacementTests(unittest.TestCase):
    def setUp(self):
        AssemblyLibraryTests.setUp(self)
        self.slot = slot_from_dict({"schema_version": 1, "slot_id": "left_foot",
            "rig_id": self.contract.id, "rig_revision": self.contract.revision,
            "input": asdict(self.part.input), "outputs": [asdict(p) for p in self.part.outputs],
            "binding_bones": ["LeftFoot"], "contacts": [asdict(p) for p in self.part.contacts],
            "joints": [asdict(p) for p in self.part.joints]})
        self.publish(self.part)
        self.candidate = replace(self.part, revision=2)
        # Другая верхняя геометрия при неизменной подошве, pivot и соединениях.
        vertices = [v.co.copy() for v in self.mesh.data.vertices]
        for vertex in self.mesh.data.vertices:
            if vertex.co.z > 0:
                vertex.co.z += .12
        self.expected = geometry(self.mesh)
        self.publish(self.candidate)
        for vertex, co in zip(self.mesh.data.vertices, vertices):
            vertex.co = co
        # Fixture представляет сохранённую/принятую авторскую исходную деталь.
        # В replace_part переопределения fingerprints для обхода защиты нет.
        for obj in asset_objects(self.root, "Foot"):
            obj["gat_fingerprint"] = fingerprint(obj)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        self.mesh.select_set(True)
        bpy.context.view_layer.objects.active = self.mesh
        bpy.context.view_layer.update()

    def publish(self, part):
        return library.publish_part(self.library, "assembly_fixture", "Foot", part, self.contract,
            armature=ObjectRef("Rig", "Skeleton"), objects=self.meshes, sockets=self.sockets, contacts=self.contacts)

    def swap(self, **options):
        return replacement.replace_part(self.library, "assembly_fixture", "Foot", self.part, self.slot,
            self.contract, self.candidate.id, self.candidate.revision, armature=ObjectRef("Rig", "Skeleton"),
            objects=self.meshes, sockets=self.sockets, contacts=self.contacts, **options)

    def assert_refused_unchanged(self, code=None):
        before = snapshot()
        with self.assertRaises(library.LibraryError) as error:
            self.swap()
        if code:
            self.assertIn(code, {issue.code for issue in error.exception.issues})
        self.assertEqual(snapshot(), before)

    def accept_mappings(self, report):
        self.meshes, self.sockets, self.contacts = [
            {key: ObjectRef(**value) for key, value in report["mappings"][kind].items()}
            for kind in ("objects", "sockets", "contacts")]
        self.part = self.candidate

    def test_swap_preserves_rig_animation_and_installs_geometry_materials_and_selection(self):
        before = state_snapshot()
        old_ids = {obj.as_pointer() for obj in asset_objects(self.root, "Foot")}
        preserved = [(o.as_pointer(), fingerprint(o), repr(dict(o.items()))) for o in asset_objects(self.root)
                     if o.get("gat_component") != "Foot"]
        report = self.swap()
        self.assertEqual(report["status"], "replaced")
        self.accept_mappings(report)
        after = state_snapshot()
        for key in ("frame", "rigs", "actions"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(preserved, [(o.as_pointer(), fingerprint(o), repr(dict(o.items())))
            for o in asset_objects(self.root) if o.get("gat_component") != "Foot"])
        self.assertFalse(old_ids & {obj.as_pointer() for obj in bpy.data.objects})
        objects = {obj["gat_local_name"]: obj for obj in asset_objects(self.root, "Foot")}
        mesh = objects[self.meshes["shoe"].local_name]
        self.assertEqual(geometry(mesh), self.expected)
        self.assertEqual(bpy.context.view_layer.objects.active, mesh)
        self.assertEqual(list(bpy.context.selected_objects), [mesh])
        self.assertEqual(component_records(self.root)["Foot"]["library_part"]["revision"], 2)
        for frame in (1, 7, 12, 24):
            bpy.context.scene.frame_set(frame, subframe=.25)
            bpy.context.view_layer.update()
            self.assertEqual(inspect_part("assembly_fixture", "Foot", self.part, self.contract,
                armature=ObjectRef("Rig", "Skeleton"), objects=self.meshes, sockets=self.sockets,
                contacts=self.contacts)["status"], "pass")
            marker = objects[self.sockets["ankle"].local_name]
            port = self.part.input
            expected = self.rig.matrix_world @ self.rig.pose.bones[port.bone].matrix @ \
                self.rig.data.bones[port.bone].matrix_local.inverted() @ _matrix(port.frame)
            self.assertLess(max(abs(marker.matrix_world[r][c] - expected[r][c])
                for r in range(4) for c in range(4)), 1e-5)
        # Библиотечную деталь разрешено заменить ещё раз, но нельзя случайно
        # потерять её при штатной процедурной пересборке recipe.
        second = self.swap()
        self.assertEqual(second["status"], "replaced")
        entry = Registry(Path(self.directory.name)).get("assembly_fixture")
        plan = plan_build(entry, load_config(entry), rebuild=True, components=["Foot"],
                          style=load_style(Path(self.directory.name)))
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("part library" in error for error in plan["errors"]))

    def test_dry_run_reads_payload_without_scene_or_datablock_changes(self):
        before = snapshot()
        self.assertEqual(self.swap(dry_run=True)["status"], "planned")
        self.assertEqual(snapshot(), before)

    def test_rotated_rest_and_bind_keep_skin_and_markers_aligned_in_animation(self):
        # Ненулевая bind-ориентация отличает настоящий rigid skin от случайно
        # правильного результата на исходных параллельных осях fixture.
        bpy.context.scene.frame_set(1)
        rest = Matrix.Translation((-.67, -.12, .32)) @ Euler((.3, .2, .4)).to_matrix().to_4x4()
        bind = Matrix.Translation((.04, -.08, -.23)) @ Euler((-.2, .15, .1)).to_matrix().to_4x4()
        bpy.context.view_layer.objects.active = self.rig
        self.rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        self.rig.data.edit_bones["LeftFoot"].matrix = rest
        self.rig.data.edit_bones["LeftFoot"].length = .16
        bpy.ops.object.mode_set(mode="OBJECT")
        self.mesh.matrix_basis = rest @ bind
        transforms = {"AnkleSocket": rest, "ServiceSocket": rest @ Matrix.Translation((0, .32, 0)),
                      "HeelContact": rest @ Matrix.Translation((0, .39, -.32)),
                      "ToeContact": rest @ Matrix.Translation((0, -.55, -.32))}
        bpy.context.view_layer.update()
        for key, transform in transforms.items():
            self.objects[("Foot", key)].matrix_world = self.rig.matrix_world @ transform
        def frame(matrix):
            return {"origin": list(matrix.translation), "basis": [list(row)[:3] for row in list(matrix)[:3]]}
        part, rig, slot = asdict(self.part), asdict(self.contract), asdict(self.slot)
        part["revision"] = 3
        part["bones"][0]["rest"] = rig["bones"][1]["rest"] = frame(rest)
        part["bindings"][0]["bind_frame"] = frame(bind)
        part["input"]["frame"] = slot["input"]["frame"] = frame(rest)
        part["outputs"][0]["frame"] = slot["outputs"][0]["frame"] = frame(transforms["ServiceSocket"])
        self.part, self.contract, self.slot = part_from_dict(part), rig_from_dict(rig), slot_from_dict(slot)
        self.candidate = replace(self.part, revision=4)
        self.publish(self.candidate)
        for obj in asset_objects(self.root, "Foot"):
            obj["gat_fingerprint"] = fingerprint(obj)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        self.mesh.select_set(True)
        bpy.context.view_layer.objects.active = self.mesh
        bpy.context.scene.frame_set(7, subframe=.375)
        before = state_snapshot()
        self.accept_mappings(self.swap())
        after = state_snapshot()
        for key in ("rigs", "actions", "frame"):
            self.assertEqual(after[key], before[key], key)
        objects = {obj["gat_local_name"]: obj for obj in asset_objects(self.root, "Foot")}
        mesh = objects[self.meshes["shoe"].local_name]
        for number, subframe in ((1, 0), (7, .375), (24, 0)):
            bpy.context.scene.frame_set(number, subframe=subframe)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(graph)
            expected = self.rig.matrix_world @ self.rig.pose.bones["LeftFoot"].matrix @ bind
            for source, actual in zip(mesh.data.vertices, evaluated.data.vertices):
                self.assertLess(((expected @ source.co) - (evaluated.matrix_world @ actual.co)).length, 1e-5)
            for port in (self.part.input, *self.part.outputs):
                marker = objects[self.sockets[port.id].local_name]
                expected_marker = self.rig.matrix_world @ self.rig.pose.bones[port.bone].matrix @ rest.inverted() @ _matrix(port.frame)
                self.assertLess(max(abs(marker.matrix_world[r][c] - expected_marker[r][c])
                    for r in range(4) for c in range(4)), 1e-5)
            report = inspect_part("assembly_fixture", "Foot", self.part, self.contract,
                armature=ObjectRef("Rig", "Skeleton"), objects=self.meshes, sockets=self.sockets, contacts=self.contacts)
            self.assertEqual(report["status"], "pass", report)

    def test_manual_geometry_is_not_silently_lost(self):
        self.mesh.data.vertices[0].co.x += .01
        self.assert_refused_unchanged("protected_source")

    def test_locked_and_approved_components_are_not_silently_lost(self):
        records = component_records(self.root)
        for status in ("locked", "approved"):
            with self.subTest(status=status):
                records["Foot"]["status"] = status
                self.root["gat_components"] = encode(records)
                self.assert_refused_unchanged("protected_source")

    def test_external_constraint_reference_is_not_broken(self):
        external = bpy.data.objects.new("ExternalFollower", None)
        bpy.context.scene.collection.objects.link(external)
        external.constraints.new("COPY_LOCATION").target = self.mesh
        self.assert_refused_unchanged("external_reference")

    def test_external_driver_reference_is_not_broken(self):
        external = bpy.data.objects.new("DrivenFollower", None)
        bpy.context.scene.collection.objects.link(external)
        curve = external.driver_add("location", 1)
        variable = curve.driver.variables.new()
        variable.name, variable.type = "foot_position", "SINGLE_PROP"
        variable.targets[0].id = self.mesh
        variable.targets[0].data_path = "location.x"
        curve.driver.expression = variable.name
        bpy.context.view_layer.update()
        self.assert_refused_unchanged("external_reference")
        self.assertEqual(variable.targets[0].id, self.mesh)
        self.assertEqual(curve.driver.expression, "foot_position")

    def test_nested_scene_rna_reference_is_not_broken(self):
        # В отличие от IDProperties, эта ссылка хранится в штатных ToolSettings.
        bpy.context.scene.tool_settings.sculpt.gravity_object = self.mesh
        self.assert_refused_unchanged("external_reference")
        self.assertEqual(bpy.context.scene.tool_settings.sculpt.gravity_object, self.mesh)

    def test_external_id_property_reference_is_not_broken(self):
        self.rig["authored_foot_reference"] = self.mesh
        self.assert_refused_unchanged("external_reference")

    def test_collection_and_scene_authored_references_are_not_treated_as_membership(self):
        for container in (self.root, bpy.context.scene):
            with self.subTest(container=container.name):
                container["authored_reference"] = {"target": self.mesh}
                self.assert_refused_unchanged("external_reference")
                del container["authored_reference"]

    def test_incompatible_interface_is_rejected_before_changes(self):
        incompatible = replace(self.part, revision=3, input=replace(self.part.input, interface="other_ankle"))
        self.publish(incompatible)
        self.candidate = incompatible
        self.assert_refused_unchanged()

    def test_name_collision_is_rejected_before_changes(self):
        from game_asset_tools.core.naming import semantic_name
        obj = bpy.data.objects.new(semantic_name("assembly_fixture", "Foot", "Mesh_shoe"), None)
        bpy.context.scene.collection.objects.link(obj)
        self.assert_refused_unchanged("name_collision")

    def test_corrupt_payload_is_rejected_without_changes(self):
        entry = library.read_part(self.library, self.candidate.id, self.candidate.revision)
        (entry.directory / "payload.blend").write_bytes(b"corrupted")
        self.assert_refused_unchanged()

    def test_fingerprint_failure_is_before_commit_and_restores_source(self):
        before = snapshot()
        with patch.object(replacement, "fingerprint", side_effect=RuntimeError("injected fingerprint failure")):
            with self.assertRaisesRegex(RuntimeError, "injected fingerprint"):
                self.swap()
        self.assertEqual(snapshot(), before)

    def test_hidden_or_excluded_destination_preserves_selected_source_on_refusal(self):
        # Прежняя деталь остаётся видимой в другой внутренней коллекции.
        # Новая должна попасть в штатную Modules, скрытую только в ViewLayer.
        destination = next(c for c in self.root.children if c.get("gat_group") == "Modules")
        visible = bpy.data.collections.new("VisibleAuthoredPart")
        self.root.children.link(visible)
        for obj in list(asset_objects(self.root, "Foot")):
            visible.objects.link(obj)
            destination.objects.unlink(obj)
        bpy.context.view_layer.update()
        layer = bpy.context.view_layer.layer_collection.children[self.root.name].children[destination.name]
        for setting in ("exclude", "hide_viewport"):
            with self.subTest(setting=setting):
                setattr(layer, setting, True)
                bpy.context.view_layer.update()
                self.mesh.select_set(True)
                bpy.context.view_layer.objects.active = self.mesh
                self.assertIn(self.mesh, bpy.context.selected_objects)
                before = snapshot()
                with self.assertRaises((library.LibraryError, RuntimeError)):
                    self.swap()
                self.assertEqual(snapshot(), before)
                self.assertTrue(getattr(layer, setting))
                setattr(layer, setting, False)
                bpy.context.view_layer.update()

    def test_repeated_swaps_do_not_accumulate_owned_material_graphs_or_images(self):
        image = bpy.data.images.new("AuthoredReplacementPixels", width=2, height=2)
        image.pixels[:] = [1, .2, .1, 1] * 4
        texture_path = Path(self.directory.name) / "replacement_pixels.png"
        image.save_render(str(texture_path))
        bpy.data.images.remove(image)
        image = bpy.data.images.load(str(texture_path))
        group = bpy.data.node_groups.new("AuthoredReplacementGroup", "ShaderNodeTree")
        group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        output = group.nodes.new("NodeGroupOutput")
        texture = group.nodes.new("ShaderNodeTexImage")
        texture.image = image
        group.links.new(texture.outputs["Color"], output.inputs["Color"])
        material = self.mesh.material_slots[1].material
        shader_group = material.node_tree.nodes.new("ShaderNodeGroup")
        shader_group.node_tree = group
        principled = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        material.node_tree.links.new(shader_group.outputs["Color"], principled.inputs["Base Color"])
        self.candidate = replace(self.part, revision=3)
        self.publish(self.candidate)
        for obj in asset_objects(self.root, "Foot"):
            obj["gat_fingerprint"] = fingerprint(obj)
        # Cleanup должен знать ownership копий, а не удалять все orphan ID сцены.
        authored_orphan = bpy.data.materials.new("KeepAuthoredOrphan")
        originals = {item.as_pointer() for item in (image, group, material, authored_orphan)}
        self.accept_mappings(self.swap())
        def counts():
            return tuple(len(items) for items in (bpy.data.materials, bpy.data.node_groups, bpy.data.images))
        initial_counts = counts()
        for number in range(3):
            with self.subTest(replacement=number + 2):
                self.accept_mappings(self.swap())
                self.assertEqual(counts(), initial_counts)
                self.assertTrue(originals <= {item.as_pointer() for item in library._ids()})
                objects = {obj["gat_local_name"]: obj for obj in asset_objects(self.root, "Foot")}
                installed_material = objects[self.meshes["shoe"].local_name].material_slots[1].material
                installed_group = next(n for n in installed_material.node_tree.nodes if n.type == "GROUP").node_tree
                installed_image = next(n for n in installed_group.nodes if n.type == "TEX_IMAGE").image
                self.assertIsNotNone(installed_image.packed_file)
                self.assertEqual(tuple(installed_image.pixels), tuple(image.pixels))
        # Материал установленной детали может быть намеренно использован ещё
        # одним объектом. Замена должна сохранить весь используемый граф.
        shared_mesh = bpy.data.meshes.new("ArtistSharedMaterialMesh")
        shared_object = bpy.data.objects.new("ArtistSharedMaterialObject", shared_mesh)
        bpy.context.scene.collection.objects.link(shared_object)
        shared_mesh.materials.append(installed_material)
        shared_ids = {item.as_pointer() for item in (installed_material, installed_group, installed_image)}
        self.accept_mappings(self.swap())
        self.assertTrue(shared_ids <= {item.as_pointer() for item in library._ids()})
        self.assertEqual(shared_mesh.materials[0], installed_material)
        shared_counts = counts()
        self.accept_mappings(self.swap())
        self.assertEqual(counts(), shared_counts)
        self.assertTrue(shared_ids <= {item.as_pointer() for item in library._ids()})

    def test_failure_during_staging_and_after_detaching_restores_all_source_ids(self):
        original = replacement.inspect_part
        for failure_call in (2, 3):
            with self.subTest(failure_call=failure_call):
                calls = 0
                def fail(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    result = original(*args, **kwargs)
                    self.assertEqual(result["status"], "pass", result)
                    if calls == failure_call:
                        raise RuntimeError("injected postflight failure")
                    return result
                before = snapshot()
                with patch.object(replacement, "inspect_part", side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, "injected postflight"):
                        self.swap()
                self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AssemblyReplacementTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    paths = [Path(__file__), *sorted((PROJECT / "game_asset_tools").rglob("*.py")),
        PROJECT / "tests/blender_assembly_inspection_test.py", PROJECT / "tests/blender_assembly_library_test.py",
        *sorted((PROJECT / "tests/fixtures/assembly_inspection").glob("*.*"))]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps({"project_root": str(PROJECT),
        "blender": bpy.app.version_string,
        "source_sha256": {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "suite": {"tests": result.testsRun, "passed": result.wasSuccessful(),
                  "failures": len(result.failures), "errors": len(result.errors)}}, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
