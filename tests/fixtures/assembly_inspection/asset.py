"""Независимая factory-fixture: rigid стопа, сокеты и контактные маркеры."""

from game_asset_tools.asset import ComponentSpec


class Recipe:
    parameters = ()

    def components(self, config):
        return {"Rig": ComponentSpec("Structure"), "Foot": ComponentSpec("Modules", depends_on=("Rig",))}

    def build_component(self, ctx, key, config):
        import bpy
        from game_asset_tools import core as gat
        if key == "Rig":
            data = bpy.data.armatures.new(ctx.name("SkeletonData"))
            rig = ctx.add(bpy.data.objects.new(ctx.name("Skeleton"), data), "Skeleton")
            for obj in bpy.context.selected_objects:
                obj.select_set(False)
            rig.select_set(True)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode="EDIT")
            root = data.edit_bones.new("Root")
            root.head, root.tail = (0, 0, 0), (0, .16, 0)
            foot = data.edit_bones.new("LeftFoot")
            foot.head, foot.tail = (-.67, -.12, .32), (-.67, .04, .32)
            foot.parent = root
            bpy.ops.object.mode_set(mode="OBJECT")
            # Имена, ось X и размер стопы соответствуют текущей walker-конвенции.
            # Двухкостная fixture намеренно не выдаётся за полноценный игровой риг.
            return
        rig = ctx.get("Rig", "Skeleton")
        mesh = ctx.add(gat.add_box(ctx.name("Shoe"), (.65, .94, .18), (-.67, -.20, .09)), "Shoe", parent=rig)
        gat.assign_material(mesh, gat.project_material("Painted_Metal", ctx.style))
        mesh.vertex_groups.new(name="LeftFoot").add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
        mesh.modifiers.new("RigidSkin", "ARMATURE").object = rig
        for local, identity, position, contact in (
                ("AnkleSocket", "ankle", (-.67, -.12, .32), False),
                ("ServiceSocket", "service", (-.67, .20, .32), False),
                ("HeelContact", "heel", (-.67, .27, 0), True),
                ("ToeContact", "toe", (-.67, -.67, 0), True)):
            marker = ctx.add(gat.add_socket(ctx.name(local), position), local, parent=rig, helper=True)
            marker["gat_contact" if contact else "gat_socket"] = identity
            if contact:
                del marker["gat_socket"]
            world = marker.matrix_world.copy()
            marker.parent_type, marker.parent_bone = "BONE", "LeftFoot"
            bpy.context.view_layer.update()
            marker.matrix_world = world


RECIPE = Recipe()
