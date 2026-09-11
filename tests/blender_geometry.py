"""Real Blender checks for Core geometry, materials, transforms and context safety."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_asset_tools import core as gat


def volume(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return bm.calc_volume(signed=True)
    finally:
        bm.free()
        evaluated.to_mesh_clear()


class GeometryTests(unittest.TestCase):
    def setUp(self):
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        self.collection = gat.create_collection("Test_Geometry")
        self.objects_before = {obj.as_pointer() for obj in bpy.data.objects}
        self.materials_before = {mat.as_pointer() for mat in bpy.data.materials}

    def tearDown(self):
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in list(bpy.data.objects):
            if obj.as_pointer() not in self.objects_before:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and data.users == 0:
                    if isinstance(data, bpy.types.Mesh):
                        bpy.data.meshes.remove(data)
                    elif isinstance(data, bpy.types.Curve):
                        bpy.data.curves.remove(data)
        bpy.data.collections.remove(self.collection)
        for material in list(bpy.data.materials):
            if material.as_pointer() not in self.materials_before:
                bpy.data.materials.remove(material)

    def box(self, name="Test_Box", size=(2, 2, 2), **kwargs):
        return gat.add_box(name, size, collection=self.collection, **kwargs)

    def assertVector(self, a, b, places=5):
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=places)

    def assertMatrix(self, a, b):
        for row_a, row_b in zip(a, b):
            self.assertVector(row_a, row_b)

    def test_closed_primitives_and_unit_scale(self):
        meshes = [self.box(), gat.add_cylinder("Test_Cylinder", 1, 2, collection=self.collection),
                  gat.add_cone("Test_Cone", 1, 0, 2, collection=self.collection),
                  gat.add_sphere("Test_Sphere", 1, collection=self.collection),
                  gat.add_torus("Test_Torus", 2, 0.5, collection=self.collection),
                  gat.create_frame("Test_Frame", 4, 5, 0.5, 0.2, collection=self.collection)]
        for obj in meshes:
            with self.subTest(name=obj.name):
                self.assertVector(obj.scale, (1, 1, 1))
                self.assertGreater(volume(obj), 0)
                bm = bmesh.new()
                try:
                    bm.from_mesh(obj.data)
                    self.assertTrue(all(edge.is_manifold for edge in bm.edges))
                    self.assertTrue(all(face.calc_area() > 1e-9 for face in bm.faces))
                finally:
                    bm.free()
        self.assertAlmostEqual(volume(meshes[0]), 8)
        self.assertAlmostEqual(volume(meshes[-1]), (4 * 5 - 3 * 4) * 0.2, places=5)

    def test_primitives_leave_context_and_ownership_alone(self):
        active = self.box("Test_Active")
        active.select_set(True)
        bpy.context.view_layer.objects.active = active
        before = list(bpy.context.selected_objects)
        obj = gat.add_beveled_box("Test_Beveled", (2, 3, 4), collection=self.collection)
        panel = gat.create_panel("Test_Panel", 2, 4, 0.2, collection=self.collection)
        plane = gat.add_plane("Test_Plane", (3, 4), collection=self.collection)
        pipe = gat.add_pipe("Test_Pipe", [(0, 0, 0), (0, 0, 1), (1, 0, 2)], collection=self.collection)
        self.assertEqual(bpy.context.view_layer.objects.active, active)
        self.assertEqual(list(bpy.context.selected_objects), before)
        self.assertEqual(len(obj.modifiers), 1)
        self.assertEqual(len(plane.data.polygons), 1)
        self.assertVector(panel.data.vertices[0].co, (-1, -0.1, -2))
        self.assertGreater(volume(pipe), 0)
        for item in (obj, panel, plane, pipe):
            self.assertFalse(item.get("gat_generated", False))
            self.assertEqual(list(item.users_collection), [self.collection])

    def test_support_endpoints(self):
        start, end = Vector((2, -1, 3)), Vector((-4, 5, 7))
        obj = gat.create_support("Test_Beam", start, end, 0.3, collection=self.collection)
        bpy.context.view_layer.update()
        half = (end - start).length / 2
        self.assertVector(obj.matrix_world @ Vector((0, 0, -half)), start)
        self.assertVector(obj.matrix_world @ Vector((0, 0, half)), end)

    def test_rejected_geometry_creates_nothing(self):
        count = len(bpy.data.objects)
        cases = [lambda: self.box(size=(0, 1, 1)),
                 lambda: gat.add_cone("Bad", 0, 0, 1),
                 lambda: gat.add_cylinder("Bad", 1, 2, vertices=2),
                 lambda: gat.add_sphere("Bad", float("nan")),
                 lambda: gat.add_plane("Bad", (1,)),
                 lambda: gat.add_pipe("Bad", [(0, 0, 0), (0, 0, 0)]),
                 lambda: gat.add_torus("Bad", 1, 2),
                 lambda: gat.create_frame("Bad", 1, 1, 0.5, 1),
                 lambda: gat.create_mesh("Bad", [(0, 0, 0)], [(0, 1, 2)])]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                case()
        self.assertEqual(len(bpy.data.objects), count)

    def test_modifiers_have_real_geometry_effects(self):
        bevel = self.box("Test_Bevel")
        self.assertAlmostEqual(volume(bevel), 8)
        gat.apply_bevel(bevel, width=0.1, segments=1, apply=True)
        self.assertLess(volume(bevel), 8)
        self.assertGreater(volume(bevel), 7)
        array = self.box("Test_Array")
        gat.array_object(array, 3, (3, 0, 0), apply=True)
        self.assertAlmostEqual(volume(array), 24)
        self.assertEqual(len(array.data.vertices), 24)
        mirrored = self.box("Test_Mirror")
        for vertex in mirrored.data.vertices:
            vertex.co.x += 2
        gat.mirror_object(mirrored, "X", apply=True)
        self.assertAlmostEqual(volume(mirrored), 16)
        sheet = gat.add_plane("Test_Sheet", (2, 3), collection=self.collection)
        gat.solidify(sheet, 0.4, apply=True)
        self.assertAlmostEqual(volume(sheet), 2.4, places=5)
        normals = self.box("Test_Normals")
        for polygon in normals.data.polygons:
            polygon.use_smooth = True
        gat.weighted_normals(normals, apply=True)
        self.assertEqual(len(normals.modifiers), 0)

    def test_booleans_keep_operand_and_geometry_valid(self):
        cut = self.box("Test_Cut")
        cutter = self.box("Test_Cutter", location=(1, 0, 0))
        gat.boolean_cut(cut, cutter, apply=True)
        self.assertAlmostEqual(volume(cut), 4, places=5)
        self.assertIn(cutter.name, bpy.data.objects)
        union = self.box("Test_Union")
        gat.boolean_union(union, cutter, apply=True)
        self.assertAlmostEqual(volume(union), 12, places=5)
        self.assertFalse(cutter.hide_render)

    def test_apply_restores_edit_context_and_shared_mesh(self):
        edit = self.box("Test_Edit")
        target = self.box("Test_Target")
        shared = bpy.data.objects.new("Test_Shared", target.data)
        self.collection.objects.link(shared)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        edit.select_set(True)
        bpy.context.view_layer.objects.active = edit
        bpy.ops.object.mode_set(mode="EDIT")
        gat.apply_bevel(target, 0.1, apply=True)
        self.assertEqual(edit.mode, "EDIT")
        self.assertEqual(bpy.context.view_layer.objects.active, edit)
        self.assertEqual(list(bpy.context.selected_objects), [edit])
        self.assertNotEqual(target.data, shared.data)
        self.assertEqual(len(shared.data.vertices), 8)

    def test_material_reuse_variation_and_manual_preservation(self):
        material = gat.get_material("Test_Surface", (0.2, 0.3, 0.4, 1), metallic=0.7)
        self.assertIs(material, gat.get_material("Test_Surface", (0.2, 0.3, 0.4, 1), metallic=0.7))
        changed = gat.get_material("Test_Surface", (0.9, 0.3, 0.4, 1), metallic=0.7)
        self.assertNotEqual(material, changed)
        self.assertVector(material.diffuse_color, (0.2, 0.3, 0.4, 1))
        principled = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        principled.inputs["Roughness"].default_value = 0.123
        rebuilt = gat.get_material("Test_Surface", (0.2, 0.3, 0.4, 1), metallic=0.7)
        self.assertNotEqual(material, rebuilt)
        self.assertAlmostEqual(principled.inputs["Roughness"].default_value, 0.123, places=5)
        manual = bpy.data.materials.new("MAT_Test_User")
        owned = gat.get_material("Test_User")
        self.assertNotEqual(manual, owned)
        obj = self.box()
        copy = bpy.data.objects.new("Test_Copy", obj.data)
        self.collection.objects.link(copy)
        gat.assign_material(obj, rebuilt)
        self.assertEqual(list(copy.data.materials), [])
        self.assertEqual(obj.data.materials[0], rebuilt)

    def test_transparent_emissive_and_project_materials(self):
        material = gat.get_material("Test_Light", (1, 0, 0, 0.4), transmission=0.2,
                                    emission=(1, 0, 0, 1), emission_strength=2)
        node = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        self.assertAlmostEqual(node.inputs["Alpha"].default_value, 0.4, places=5)
        self.assertAlmostEqual(node.inputs["Emission Strength"].default_value, 2)
        self.assertAlmostEqual(node.inputs["Transmission Weight"].default_value, 0.2, places=5)
        for role in ("Stone", "Metal_Silver", "Metal_Bronze", "Glass_Clear", "Ruby", "Rubber", "Painted_Metal"):
            mat = gat.project_material(role)
            self.assertIs(mat, gat.project_material(role))
        custom = gat.project_material("Custom", {"materials": {"Custom": {"roughness": 0.17}}})
        self.assertAlmostEqual(custom.roughness, 0.17, places=5)

    def test_parent_origin_and_socket_world_placement(self):
        parent = self.box("Test_Parent", location=(3, 4, 5), rotation=(0.2, 0.3, 0.4))
        parent.scale = (1.5, 1.5, 1.5)
        child = self.box("Test_Child", location=(-3, 1, 4), rotation=(0.3, -0.4, 0.1))
        bpy.context.view_layer.update()
        before = child.matrix_world.copy()
        gat.parent_object(child, parent)
        self.assertMatrix(child.matrix_world, before)
        with self.assertRaises(ValueError):
            gat.parent_object(parent, child)
        points = [child.matrix_world @ vertex.co for vertex in child.data.vertices]
        socket = gat.add_socket("Test_Muzzle", (7, 2, 1), parent=child, collection=self.collection)
        socket_world = socket.matrix_world.copy()
        sibling = bpy.data.objects.new("Test_Sibling", child.data)
        self.collection.objects.link(sibling)
        gat.set_origin(child, (0, 0, 0))
        self.assertVector(child.matrix_world.translation, (0, 0, 0))
        for point, vertex in zip(points, child.data.vertices):
            self.assertVector(point, child.matrix_world @ vertex.co)
        self.assertMatrix(socket.matrix_world, socket_world)
        self.assertVector(socket.matrix_world.translation, (7, 2, 1))
        self.assertNotEqual(child.data, sibling.data)
        self.assertEqual(socket["gat_socket"], "Test_Muzzle")
        self.assertFalse(socket.get("gat_generated", False))
        gat.parent_object(child, None)
        self.assertIsNone(child.parent)

    def test_collection_names_do_not_claim_user_collection(self):
        duplicate = gat.create_collection(self.collection.name, parent=self.collection)
        try:
            self.assertNotEqual(duplicate, self.collection)
            self.assertFalse(duplicate.get("gat_generated", False))
            obj = self.box()
            gat.link_object(obj, duplicate)
            gat.link_object(obj, duplicate)
            self.assertEqual(len(obj.users_collection), 2)
        finally:
            bpy.data.collections.remove(duplicate)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GeometryTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)
