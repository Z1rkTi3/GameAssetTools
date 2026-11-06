"""Two rigid links and a bone socket, registered through ordinary recipe ownership."""

from game_asset_tools.asset import ComponentSpec


class Recipe:
    parameters = ()

    def components(self, config):
        return {"Rig": ComponentSpec("Structure"),
                "Links": ComponentSpec("Structure", depends_on=("Rig",))}

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
            base = data.edit_bones.new("Base")
            base.head, base.tail = (0, 0, 0), (0, 0, 1)
            hinge = data.edit_bones.new("Hinge")
            hinge.head, hinge.tail = (0, 0, 1), (0, 0, 2)
            hinge.parent, hinge.use_connect = base, True
            bpy.ops.object.mode_set(mode="OBJECT")
            rig.animation_data_create()
            pose = rig.pose.bones["Hinge"]
            pose.rotation_mode = "XYZ"
            for name, angle in [("swing", 0.65), ("fold", -0.45)]:
                action = bpy.data.actions.new(name)
                rig.animation_data.action = action
                for frame, value in [(1, 0.0), (12, angle), (24, 0.0)]:
                    # Сгибание поперёк звена: сокет на его конце должен перемещаться.
                    pose.rotation_euler[0] = value
                    pose.keyframe_insert("rotation_euler", frame=frame)
                track = rig.animation_data.nla_tracks.new()
                track.name = name
                track.strips.new(name, 1, action)
                track.mute = True
            rig.animation_data.action = None
            pose.rotation_euler = (0, 0, 0)
            return
        rig = ctx.get("Rig", "Skeleton")
        for bone, height in [("Base", 0.5), ("Hinge", 1.5)]:
            mesh = ctx.add(gat.add_box(ctx.name(bone + "Link"), (0.3, 0.3, 0.8),
                                      location=(0, 0, height)), bone + "Link", parent=rig)
            gat.assign_material(mesh, gat.project_material("Painted_Metal", ctx.style))
            mesh.vertex_groups.new(name=bone).add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
            mesh.modifiers.new("RigidSkin", "ARMATURE").object = rig
        socket = ctx.add(gat.add_socket(ctx.name("TipSocket"), (0, 0, 2.0)), "TipSocket", parent=rig)
        world = socket.matrix_world.copy()
        socket.parent_type, socket.parent_bone = "BONE", "Hinge"
        bpy.context.view_layer.update()
        socket.matrix_world = world


RECIPE = Recipe()
