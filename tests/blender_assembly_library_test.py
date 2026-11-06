"""Реальные независимые .blend: source неизменен, payload читается без исходного меха."""

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
from blender_assembly_inspection_test import AssemblyInspectionTests, state_snapshot
from game_asset_tools.assembly import library
from game_asset_tools.assembly.inspection import _matrix
from game_asset_tools.assembly.contracts import part_from_dict, rig_from_dict
from game_asset_tools.core.materials import get_material

OUTPUT = PROJECT / "output/assembly_library"
EVIDENCE = []


def geometry(obj):
    return {"vertices": [tuple(v.co) for v in obj.data.vertices],
            "faces": [(tuple(p.vertices), p.material_index, p.use_smooth) for p in obj.data.polygons],
            "uv": [[tuple(uv.uv) for uv in layer.data] for layer in obj.data.uv_layers],
            "normals": [tuple(n.vector) for n in obj.data.corner_normals],
            "colors": [tuple(slot.material.diffuse_color) for slot in obj.material_slots],
            "roles": [slot.material.get("gat_material_role") for slot in obj.material_slots]}


class AssemblyLibraryTests(unittest.TestCase):
    def setUp(self):
        # Та же обычная GAT recipe, отдельная factory-сцена и TemporaryDirectory.
        AssemblyInspectionTests.setUp(self)
        self.library = Path(self.directory.name) / "library"
        first = get_material("LibraryBlue", (.05, .3, .9, 1), roughness=.9)
        first["gat_material_role"] = "Paint"
        second = get_material("LibraryRed", (.9, .05, .1, 1), roughness=.8)
        second["gat_material_role"] = "Trim"
        self.mesh.data.materials.append(second)
        # OBJECT override важен: эффективный материал не равен mesh.materials[0].
        self.mesh.material_slots[0].link = "OBJECT"
        self.mesh.material_slots[0].material = first
        for face in self.mesh.data.polygons:
            face.material_index = face.index % 2
            face.use_smooth = True
        uv = self.mesh.data.uv_layers.new(name="LibraryUV")
        for i, item in enumerate(uv.data):
            item.uv = ((i % 3) / 2, (i % 2))
        self.mesh.data.normals_split_custom_set([(0.0, 0.0, 1.0)] * len(self.mesh.data.loops))
        bpy.context.scene.frame_set(12, subframe=.25)
        self.pivot.location = (5, -3, 2)
        self.pivot.rotation_euler.z = .45
        self.rig.location = (.3, .5, .8)
        self.rig.rotation_euler.y = -.15
        bpy.context.view_layer.update()

    def publish(self, part=None):
        return library.publish_part(self.library, "assembly_fixture", "Foot", part or self.part, self.contract,
                                    armature=library_ref(), objects=self.meshes, sockets=self.sockets, contacts=self.contacts)

    def assert_unchanged(self, before, ids):
        self.assertEqual(state_snapshot(), before)
        self.assertEqual(library._ids(), ids)

    def test_generated_and_unsaved_file_pixels_survive_publication_without_source_edits(self):
        for index, kind in enumerate(("generated", "generated_float", "dirty_file", "dirty_packed_file")):
            with self.subTest(kind=kind):
                source = bpy.data.images.new("Authored_" + kind, width=2, height=2, float_buffer=kind.endswith("float"))
                source.pixels[:] = ([2.25, .125, .03125, 1.0] if kind.endswith("float") else [1.0, .2, .1, 1.0]) * 4
                disk = None
                if not kind.startswith("generated"):
                    disk = Path(self.directory.name) / (kind + ".png")
                    source.filepath_raw = str(disk)
                    source.file_format = "PNG"
                    source.save()
                    bpy.data.images.remove(source)
                    source = bpy.data.images.load(str(disk), check_existing=False)
                    if kind == "dirty_packed_file":
                        source.pack()
                    # Несохранённая зелёная правка должна победить красный файл
                    # и ранее упакованные красные пиксели, не изменяя исходник.
                    source.pixels[:] = [.1, 1.0, .2, 1.0] * 4
                material = self.mesh.material_slots[0].material
                texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.image = source
                material.node_tree.links.new(texture.outputs["Color"],
                    material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])

                def image_state():
                    return (source.as_pointer(), source.filepath, source.source, source.is_dirty, source.has_data,
                            list(source.pixels), bytes(source.packed_file.data) if source.packed_file else None,
                            disk.read_bytes() if disk else None)

                expected = image_state()
                before, ids = state_snapshot(), library._ids()
                part = replace(self.part, revision=10 + index)
                self.publish(part)
                self.assertEqual(image_state(), expected)
                with library.open_part(self.library, part.id, part.revision) as payload:
                    copied_material = payload.objects["shoe"].material_slots[0].material
                    copied = copied_material.node_tree.nodes[texture.name].image
                    self.assertIsNotNone(copied.packed_file)
                    self.assertEqual(copied.filepath, "")
                    self.assertEqual(list(copied.pixels), expected[5])
                self.assertEqual(image_state(), expected)
                self.assert_unchanged(before, ids)
                material.node_tree.nodes.remove(texture)

    def test_publish_standalone_and_reuse_in_two_fresh_animated_assemblies(self):
        source = Path(self.directory.name) / "source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        before, ids, expected_geometry = state_snapshot(), library._ids(), geometry(self.mesh)
        entry = self.publish()
        self.assert_unchanged(before, ids)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
        with library.open_part(self.library, self.part.id, 1) as payload:
            self.assertEqual(geometry(payload.objects["shoe"]), expected_geometry)
            self.assertEqual(len(payload.collection.objects), 5)
            self.assertAlmostEqual(payload.objects["shoe"].matrix_basis.translation.z, .09, places=6)
        self.assert_unchanged(before, ids)

        # Полностью удалён исходник: остаются только файлы библиотеки и manifest.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with library.open_part(self.library, self.part.id, 1) as first, library.open_part(self.library, self.part.id, 1) as second:
            self.assertNotEqual(first.objects["shoe"].data.as_pointer(), second.objects["shoe"].data.as_pointer())
            self.assertNotEqual(first.objects["shoe"].material_slots[0].material.as_pointer(), second.objects["shoe"].material_slots[0].material.as_pointer())
            rigs = []
            for index, payload in enumerate((first, second)):
                bpy.context.scene.collection.children.link(payload.collection)
                data = bpy.data.armatures.new(f"FreshRig{index}")
                rig = bpy.data.objects.new(f"FreshRig{index}", data)
                bpy.context.scene.collection.objects.link(rig)
                bpy.context.view_layer.objects.active = rig
                rig.select_set(True)
                bpy.ops.object.mode_set(mode="EDIT")
                for spec in self.contract.bones:
                    bone = data.edit_bones.new(spec.id)
                    bone.head = spec.rest.origin
                    bone.tail = (spec.rest.origin[0], spec.rest.origin[1] + .16, spec.rest.origin[2])
                    if spec.parent:
                        bone.parent = data.edit_bones[spec.parent]
                bpy.ops.object.mode_set(mode="OBJECT")
                rig.location.x = index * 4
                bpy.context.view_layer.update()
                for role, mapping in (("mesh", payload.objects), ("socket", payload.sockets), ("contact", payload.contacts)):
                    for key, obj in mapping.items():
                        rest = obj.matrix_basis.copy()
                        obj.parent, obj.parent_type, obj.parent_bone = rig, "BONE", "LeftFoot"
                        bpy.context.view_layer.update()
                        obj.matrix_world = rig.matrix_world @ rest
                pose = rig.pose.bones["LeftFoot"]
                pose.rotation_mode = "XYZ"
                pose.rotation_euler.x = 0
                pose.keyframe_insert("rotation_euler", frame=1)
                pose.rotation_euler.x = .4 + index * .15
                pose.keyframe_insert("rotation_euler", frame=10)
                rigs.append(rig)
            bpy.context.scene.frame_set(10)
            bpy.context.view_layer.update()
            for payload, rig in zip((first, second), rigs):
                mesh = payload.objects["shoe"]
                expected = rig.matrix_world @ rig.pose.bones["LeftFoot"].matrix @ _matrix(self.part.bindings[0].bind_frame)
                self.assertLess(max(abs(mesh.matrix_world[r][c] - expected[r][c]) for r in range(4) for c in range(4)), 1e-5)
                self.assertEqual(geometry(mesh), expected_geometry)
            # Изменение геометрии одного экземпляра не меняет другой.
            original = second.objects["shoe"].data.vertices[0].co.copy()
            first.objects["shoe"].data.vertices[0].co.x += .1
            self.assertEqual(second.objects["shoe"].data.vertices[0].co, original)
        # Контекст чтения не удаляет новые rig/Actions, созданные вызывающим кодом.
        self.assertEqual(len(bpy.data.armatures), 2)
        self.assertEqual(len(bpy.data.actions), 2)
        EVIDENCE.append({"case": "standalone_two_fresh_assemblies", "payload_sha256": entry.payload_sha256,
                         "source_blend_sha256": source_hash, "source_unchanged": True,
                         "independent_mesh_material_data": True, "animated_binding": True})

    def test_external_image_is_packed_on_copy_and_nested_shader_group_survives(self):
        material = self.mesh.material_slots[1].material
        generated = bpy.data.images.new("source_pixels", width=2, height=2)
        generated.pixels[:] = [1, .2, .1, 1] * 4
        texture_path = Path(self.directory.name) / "artist_texture.png"
        generated.save_render(str(texture_path))
        bpy.data.images.remove(generated)
        image = bpy.data.images.load(str(texture_path))
        expected_pixels = tuple(image.pixels)
        tree = bpy.data.node_groups.new("ImageColor", "ShaderNodeTree")
        tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        output = tree.nodes.new("NodeGroupOutput")
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        tree.links.new(texture.outputs["Color"], output.inputs["Color"])
        group = material.node_tree.nodes.new("ShaderNodeGroup")
        group.node_tree = tree
        principled = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        material.node_tree.links.new(group.outputs["Color"], principled.inputs["Base Color"])
        before, ids = state_snapshot(), library._ids()
        self.publish()
        self.assert_unchanged(before, ids)
        self.assertIsNone(image.packed_file)
        self.assertEqual(image.filepath, str(texture_path))
        # Удаление единственного исходного файла не мешает чтению payload.
        texture_path.unlink()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with library.open_part(self.library, self.part.id, 1) as payload:
            mat = payload.objects["shoe"].material_slots[1].material
            imported = next(n for n in mat.node_tree.nodes if n.type == "GROUP").node_tree
            packed = next(n for n in imported.nodes if n.type == "TEX_IMAGE").image
            self.assertIsNotNone(packed.packed_file)
            self.assertEqual(packed.filepath, "")
            self.assertEqual(tuple(packed.size), (2, 2))
            self.assertEqual(tuple(packed.pixels), expected_pixels)

    def test_rotated_rest_and_bone_parent_source_preserve_full_local_frames(self):
        bpy.context.scene.frame_set(1)
        rest = Matrix.Translation((-.67, -.12, .32)) @ Euler((.3, .2, .4)).to_matrix().to_4x4()
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        self.rig.data.edit_bones["LeftFoot"].matrix = rest
        self.rig.data.edit_bones["LeftFoot"].length = .16
        bpy.ops.object.mode_set(mode="OBJECT")
        self.mesh.modifiers.clear()
        self.mesh.parent_type, self.mesh.parent_bone = "BONE", "LeftFoot"
        bpy.context.view_layer.update()
        self.mesh.matrix_world = self.rig.matrix_world @ rest @ _matrix(self.part.bindings[0].bind_frame)
        transforms = {"AnkleSocket": rest, "ServiceSocket": rest @ Matrix.Translation((0, .32, 0)),
                      "HeelContact": rest @ Matrix.Translation((0, .39, -.32)),
                      "ToeContact": rest @ Matrix.Translation((0, -.55, -.32))}
        for key, transform in transforms.items():
            self.objects[("Foot", key)].matrix_world = self.rig.matrix_world @ transform
        def frame(matrix):
            return {"origin": list(matrix.translation), "basis": [list(row)[:3] for row in list(matrix)[:3]]}
        part, rig = asdict(self.part), asdict(self.contract)
        part["bones"][0]["rest"] = rig["bones"][1]["rest"] = frame(rest)
        part["input"]["frame"], part["outputs"][0]["frame"] = frame(rest), frame(transforms["ServiceSocket"])
        self.part, self.contract = part_from_dict(part), rig_from_dict(rig)
        bpy.context.scene.frame_set(12, subframe=.375)
        before, ids = state_snapshot(), library._ids()
        self.publish()
        self.assert_unchanged(before, ids)
        with library.open_part(self.library, self.part.id, 1) as payload:
            for actual, expected in ((payload.objects["shoe"].matrix_basis, rest @ _matrix(self.part.bindings[0].bind_frame)),
                                     (payload.sockets["service"].matrix_basis, transforms["ServiceSocket"])):
                self.assertLess(max(abs(actual[r][c] - expected[r][c]) for r in range(4) for c in range(4)), 1e-5)
        self.assert_unchanged(before, ids)

    def test_duplicate_revision_invalid_source_and_writer_failure_preserve_source(self):
        before, ids = state_snapshot(), library._ids()
        entry = self.publish()
        stored = {p.name: p.read_bytes() for p in entry.directory.iterdir()}
        with self.assertRaises(library.LibraryError) as error:
            self.publish()
        self.assertEqual(error.exception.issues[0].code, "revision_exists")
        self.assertEqual({p.name: p.read_bytes() for p in entry.directory.iterdir()}, stored)
        self.mesh.vertex_groups[0].remove([0])
        invalid_before = state_snapshot()
        with self.assertRaises(library.LibraryError) as error:
            self.publish(replace(self.part, revision=2))
        self.assertIn("rigid_weights", {i.code for i in error.exception.issues})
        self.assert_unchanged(invalid_before, ids)
        self.mesh.vertex_groups[0].add([0], 1, "REPLACE")
        with patch.object(library, "_create_payload", side_effect=RuntimeError("controlled staging failure")):
            with self.assertRaisesRegex(RuntimeError, "controlled staging failure"):
                self.publish(replace(self.part, revision=2))
        with patch.object(library, "_open_entry", side_effect=RuntimeError("controlled post-write failure")):
            with self.assertRaisesRegex(RuntimeError, "controlled post-write failure"):
                self.publish(replace(self.part, revision=2))
        self.assert_unchanged(before, ids)
        self.assertEqual({p.name for p in entry.directory.parent.iterdir()}, {"1"})

    def test_read_failure_and_body_failure_clean_only_loaded_ids(self):
        entry = self.publish()
        before, ids = state_snapshot(), library._ids()
        with patch.object(library, "_validate_payload", side_effect=RuntimeError("bad loaded payload")):
            with self.assertRaisesRegex(RuntimeError, "bad loaded payload"):
                with library.open_part(self.library, self.part.id, 1):
                    pass
        self.assert_unchanged(before, ids)
        with self.assertRaisesRegex(RuntimeError, "consumer failure"):
            with library.open_part(self.library, self.part.id, 1):
                retained = bpy.data.meshes.new("ConsumerOwnsThis")
                raise RuntimeError("consumer failure")
        self.assertIn(retained, library._ids())
        bpy.data.meshes.remove(retained)
        self.assert_unchanged(before, ids)
        (entry.directory / "payload.blend").write_bytes(b"changed")
        with self.assertRaises(library.LibraryError) as error:
            with library.open_part(self.library, self.part.id, 1):
                pass
        self.assertEqual(error.exception.issues[0].code, "library_hash")
        self.assert_unchanged(before, ids)

    def test_unsupported_scene_material_reference_and_modifiers_fail_before_publication(self):
        material = self.mesh.material_slots[0].material
        coord = material.node_tree.nodes.new("ShaderNodeTexCoord")
        coord.object = self.rig
        before, ids = state_snapshot(), library._ids()
        with self.assertRaises(library.LibraryError) as error:
            self.publish()
        self.assertEqual(error.exception.issues[0].code, "material_dependency")
        self.assert_unchanged(before, ids)
        self.assertFalse((self.library / self.part.id / "1").exists())
        material.node_tree.nodes.remove(coord)
        ies = material.node_tree.nodes.new("ShaderNodeTexIES")
        ies.mode, ies.filepath = "EXTERNAL", str(Path(self.directory.name) / "external.ies")
        before = state_snapshot()
        with self.assertRaises(library.LibraryError) as error:
            self.publish()
        self.assertEqual(error.exception.issues[0].code, "material_dependency")
        self.assert_unchanged(before, ids)
        material.node_tree.nodes.remove(ies)
        self.mesh.modifiers.new("UnsupportedBevel", "BEVEL")
        before = state_snapshot()
        with self.assertRaises(library.LibraryError) as error:
            self.publish()
        self.assertIn("unevaluated_modifiers", {i.code for i in error.exception.issues})
        self.assert_unchanged(before, ids)

    def test_tampered_blend_dependency_and_socket_transform_rejected_even_with_valid_hash(self):
        entry = self.publish()
        for failure in ("action", "socket", "identity", "orphan", "nested_metadata", "node_metadata"):
            with self.subTest(failure=failure):
                # Фабричный повреждённый payload, не source/user blend.
                with library.open_part(self.library, self.part.id, 1) as payload:
                    datablocks = {payload.collection}
                    if failure == "action":
                        action = bpy.data.actions.new("ForbiddenAction")
                        datablocks.add(action)
                    elif failure == "socket":
                        payload.sockets["ankle"].location.x += 1
                    elif failure == "identity":
                        payload.sockets["service"]["gat_library_id"] = "ankle"
                    elif failure == "orphan":
                        orphan = bpy.data.meshes.new("UnlistedMesh")
                        datablocks.add(orphan)
                    else:
                        hidden = bpy.data.meshes.new("HiddenMetadataMesh")
                        if failure == "nested_metadata":
                            payload.objects["shoe"].data["nested"] = {"hidden": hidden}
                        else:
                            mat = payload.objects["shoe"].material_slots[0].material
                            mat.node_tree.nodes[0]["hidden"] = hidden
                    bad = Path(self.directory.name) / (failure + ".blend")
                    bpy.data.libraries.write(str(bad), datablocks, fake_user=False)
                    if failure == "action":
                        bpy.data.actions.remove(action)
                    if failure == "orphan":
                        bpy.data.meshes.remove(orphan)
                    if failure in {"nested_metadata", "node_metadata"}:
                        bpy.data.meshes.remove(hidden)
                original = (entry.directory / "payload.blend").read_bytes()
                (entry.directory / "payload.blend").write_bytes(bad.read_bytes())
                manifest_path = entry.directory / "manifest.json"
                document = json.loads(manifest_path.read_text(encoding="utf-8"))
                original_manifest = manifest_path.read_bytes()
                document["payload"]["sha256"] = hashlib.sha256(bad.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(document), encoding="utf-8")
                before, ids = state_snapshot(), library._ids()
                with self.assertRaises(library.LibraryError):
                    with library.open_part(self.library, self.part.id, 1):
                        pass
                self.assert_unchanged(before, ids)
                (entry.directory / "payload.blend").write_bytes(original)
                manifest_path.write_bytes(original_manifest)

    def test_file_change_between_hash_and_blender_load_is_detected(self):
        self.publish()
        before, ids = state_snapshot(), library._ids()
        def changed_copy(source, target):
            Path(target).write_bytes(b"changed between validation and load")
        with patch.object(library.shutil, "copyfile", side_effect=changed_copy):
            with self.assertRaises(library.LibraryError) as error:
                with library.open_part(self.library, self.part.id, 1):
                    pass
        self.assertEqual(error.exception.issues[0].code, "library_hash")
        self.assert_unchanged(before, ids)

    def test_invalid_blend_with_matching_hash_returns_diagnostic_without_scene_mutation(self):
        entry = self.publish()
        data = b"this is not a blend file"
        (entry.directory / "payload.blend").write_bytes(data)
        manifest = json.loads((entry.directory / "manifest.json").read_text(encoding="utf-8"))
        manifest["payload"]["sha256"] = hashlib.sha256(data).hexdigest()
        (entry.directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        before, ids = state_snapshot(), library._ids()
        with self.assertRaises(library.LibraryError) as error:
            with library.open_part(self.library, self.part.id, 1):
                pass
        self.assertEqual(error.exception.issues[0].code, "payload_read")
        self.assert_unchanged(before, ids)


def library_ref():
    from game_asset_tools.assembly.inspection import ObjectRef
    return ObjectRef("Rig", "Skeleton")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AssemblyLibraryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    paths = [Path(__file__), *sorted((PROJECT / "game_asset_tools").rglob("*.py")),
             PROJECT / "tests/blender_assembly_inspection_test.py", PROJECT / "tests/test_assembly_library.py",
             *sorted((PROJECT / "tests/fixtures/assembly_inspection").glob("*.*"))]
    (OUTPUT / "report.json").write_text(json.dumps({"project_root": str(PROJECT), "blender": bpy.app.version_string,
        "source_sha256": {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "suite": {"tests": result.testsRun, "passed": result.wasSuccessful(), "failures": len(result.failures), "errors": len(result.errors)},
        "cases": EVIDENCE}, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
