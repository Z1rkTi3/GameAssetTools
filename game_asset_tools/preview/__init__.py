"""Consistent, isolated previews without changing the user's working scene."""

import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from game_asset_tools.export.paths import prepare_path, write_json
from game_asset_tools.inspection import bounds

VIEWS = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (-1, 0, 0),
         "right": (1, 0, 0), "top": (0, 0, 1), "perspective": (1, -1.4, 1)}


def render_preview(asset_id, output, *, component=None, views=None, resolution=512,
                   overwrite=False, reframe=False, debug=False, framing=None):
    """Render six standard views or a targeted subset; return paths and framing."""
    if resolution not in (256, 512, 1024):
        raise ValueError("Preview resolution must be 256, 512, or 1024")
    views = list(VIEWS) if not views or "all" in views else list(dict.fromkeys(views))
    if set(views) - set(VIEWS):
        raise ValueError(f"Unknown preview views: {set(views) - set(VIEWS)}")
    root = find_root(asset_id)
    if component and component not in component_records(root):
        raise ValueError(f"Unknown component {component!r}")
    sources = [o for o in asset_objects(root, component, helpers=False) if o.type in {"MESH", "CURVE", "SURFACE", "FONT"}]
    if not sources:
        raise ValueError("Preview target contains no renderable geometry")
    from game_asset_tools.core.naming import semantic_name
    directory = Path(output).resolve() / "previews" / asset_id / (semantic_name(component) if component else "asset")
    if debug:
        directory = directory / "debug"
    paths = {view: directory / f"{view}.png" for view in views}
    for path in paths.values():
        prepare_path(path, overwrite=overwrite)
    frame_path = directory / "framing.json"
    report_path = directory / "preview.json"
    prepare_path(report_path, overwrite=overwrite)
    box = bounds(sources)
    center = Vector(box["center"])
    radius = max(Vector(box["dimensions"]).length / 2, 0.01)
    reframed = False
    if framing is None and frame_path.exists() and not reframe:
        frame = json.loads(frame_path.read_text(encoding="utf-8"))
        old_center = Vector(frame["center"])
        old_radius = float(frame["radius"])
        if (center-old_center).length + radius <= old_radius * 1.001:
            center, radius = old_center, old_radius
        else:
            reframed = True
    style = json.loads(root.get("gat_style", "{}"))
    settings = style.get("preview", {})
    margin = max(float(settings.get("margin", 1.15)), 1.05)
    frame = {"center": list(center), "radius": radius, "ortho_scale": radius*2*margin}
    if framing is not None:
        # A batch computes this frame from every variant before rendering any of
        # them. Never silently expand it for just one member of a comparison.
        try:
            fixed_center = tuple(float(v) for v in framing["center"])
            fixed_radius = float(framing["radius"])
            fixed_scale = float(framing["ortho_scale"])
            valid = (len(fixed_center) == 3 and fixed_radius > 0
                     and fixed_scale >= fixed_radius * 2 * 1.05
                     and all(math.isfinite(v) for v in (*fixed_center, fixed_radius, fixed_scale)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid explicit preview framing") from exc
        if not valid:
            raise ValueError("Invalid explicit preview framing")
        center, radius = Vector(fixed_center), fixed_radius
        for x in (box["min"][0], box["max"][0]):
            for y in (box["min"][1], box["max"][1]):
                for z in (box["min"][2], box["max"][2]):
                    if (Vector((x, y, z))-center).length > radius * 1.001:
                        raise ValueError("Explicit preview framing does not contain the target")
        margin = fixed_scale / (radius * 2)
        frame = {"center": list(fixed_center), "radius": radius, "ortho_scale": fixed_scale}
    scene = bpy.data.scenes.new("GAT_Preview")
    created_objects, created_meshes, created_materials, labels = [], [], [], []
    world = None
    camera_data = None
    lights = []
    try:
        graph = bpy.context.evaluated_depsgraph_get()
        try:
            scene.render.engine = "BLENDER_EEVEE"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.render.resolution_x = scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = False
        scene.view_settings.view_transform = "Standard"
        world = bpy.data.worlds.new("GAT_Preview_World")
        scene.world = world
        world.use_nodes = True
        background = settings.get("background", [0.065, 0.075, 0.095, 1])
        background_node = next(node for node in world.node_tree.nodes if node.type == "BACKGROUND")
        background_node.inputs["Color"].default_value = (*background[:3], 1)
        background_node.inputs["Strength"].default_value = .5
        debug_materials = {}
        for source in sources:
            evaluated = source.evaluated_get(graph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=graph)
            created_meshes.append(mesh)
            # new_from_object copies mesh-linked materials, not the effective
            # object-linked overrides used by a material-only recolor.
            for index, slot in enumerate(evaluated.material_slots):
                if slot.link == "OBJECT" and index < len(mesh.materials):
                    mesh.materials[index] = slot.material
            obj = bpy.data.objects.new("Preview_" + source.name, mesh)
            created_objects.append(obj)
            scene.collection.objects.link(obj)
            obj.matrix_world = source.matrix_world.copy()
            if debug:
                key = source.get("gat_component", "Object")
                if key not in debug_materials:
                    digest = hashlib.sha256(key.encode()).digest()
                    material = bpy.data.materials.new("GAT_Debug_" + key)
                    created_materials.append(material)
                    material.diffuse_color = tuple(.2+.65*v/255 for v in digest[:3]) + (1,)
                    debug_materials[key] = material
                mesh.materials.clear()
                mesh.materials.append(debug_materials[key])
        if debug:
            # Billboard component names, colored axes, and evaluated target bounds.
            for key in sorted({o.get("gat_component") for o in sources}):
                target_box = bounds([o for o in sources if o.get("gat_component") == key])
                curve = bpy.data.curves.new("GAT_Debug_Label", "FONT")
                curve.body = key
                curve.size = radius * .055
                curve.align_x = "CENTER"
                label = bpy.data.objects.new("GAT_Debug_Label", curve)
                scene.collection.objects.link(label)
                label.location = Vector(target_box["center"]) + Vector((0, 0, target_box["dimensions"][2]/2+radius*.05))
                created_objects.append(label)
                labels.append(label)
            # Axis lines start at the asset's actual origin, with X/Y/Z labels.
            from game_asset_tools.asset.scene import root_object
            origin = root_object(root).matrix_world.translation
            for axis, direction, color in (("X", (1,0,0), (1,.1,.1,1)), ("Y", (0,1,0), (.1,1,.1,1)), ("Z", (0,0,1), (.1,.3,1,1))):
                material = bpy.data.materials.new("GAT_Debug_Axis_"+axis)
                material.diffuse_color = color
                created_materials.append(material)
                curve = bpy.data.curves.new("GAT_Debug_Axis", "CURVE")
                curve.dimensions = "3D"
                curve.bevel_depth = radius*.006
                spline = curve.splines.new("POLY")
                spline.points.add(1)
                end = origin+Vector(direction)*radius*.4
                for point, value in zip(spline.points, (origin, end)):
                    point.co = (*value,1)
                curve.materials.append(material)
                obj = bpy.data.objects.new("GAT_Debug_Axis_"+axis, curve)
                scene.collection.objects.link(obj)
                created_objects.append(obj)
                text = bpy.data.curves.new("GAT_Debug_Axis_Label", "FONT")
                text.body = axis
                text.size = radius*.065
                label = bpy.data.objects.new("GAT_Debug_Axis_Label", text)
                label.location = end
                scene.collection.objects.link(label)
                labels.append(label)
                created_objects.append(label)
            low, high = box["min"], box["max"]
            corners = [Vector((x,y,z)) for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])]
            for a in range(8):
                for bit in (1,2,4):
                    b = a ^ bit
                    if a < b:
                        # Curves remain local temporary preview data.
                        curve = bpy.data.curves.new("GAT_Debug_Bounds", "CURVE")
                        curve.dimensions = "3D"
                        curve.bevel_depth = radius*.002
                        curve.bevel_resolution = 0
                        spline = curve.splines.new("POLY")
                        spline.points.add(1)
                        for point, value in zip(spline.points, (corners[a], corners[b])):
                            point.co = (*value,1)
                        obj = bpy.data.objects.new("GAT_Debug_Bounds", curve)
                        scene.collection.objects.link(obj)
                        created_objects.append(obj)
        camera_data = bpy.data.cameras.new("GAT_Preview_Camera")
        camera = bpy.data.objects.new("GAT_Preview_Camera", camera_data)
        created_objects.append(camera)
        scene.collection.objects.link(camera)
        scene.camera = camera
        for direction, power, scale in (((-3,-4,6), 1000, 4), ((4,-1,3), 600, 3), ((1,4,5), 900, 3)):
            data = bpy.data.lights.new("GAT_Preview_Area", "AREA")
            lights.append(data)
            data.energy = power * radius**2
            data.shape = "DISK"
            data.size = scale * radius
            light = bpy.data.objects.new("GAT_Preview_Light", data)
            created_objects.append(light)
            scene.collection.objects.link(light)
            light.location = center + Vector(direction) * radius
            light.rotation_euler = (center-light.location).to_track_quat("-Z", "Y").to_euler()
        for view in views:
            direction = Vector(VIEWS[view]).normalized()
            camera_data.type = "PERSP" if view == "perspective" else "ORTHO"
            camera_data.lens = 50
            distance = radius * margin / math.sin(camera_data.angle/2) if view == "perspective" else radius*4
            camera.location = center + direction * distance
            camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
            camera_data.ortho_scale = frame["ortho_scale"]
            camera_data.clip_start = max(radius/1000, .0001)
            camera_data.clip_end = radius*100
            for label in labels:
                label.rotation_euler = camera.rotation_euler
            scene.render.filepath = str(paths[view])
            bpy.ops.render.render(write_still=True, scene=scene.name)
        write_json(frame_path, frame, overwrite=True)
        result = {"asset": asset_id, "component": component, "stage": root.get("gat_stage"), "resolution": resolution,
                  "paths": {view: str(path) for view,path in paths.items()}, "framing": frame,
                  "reframed": reframed or reframe, "debug": debug,
                  "warnings": ["Target outgrew previous framing; camera framing expanded"] if reframed else []}
        write_json(report_path, result, overwrite=overwrite)
        return result
    finally:
        for obj in created_objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data and data.users == 0 and isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
        for mesh in created_meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for data in lights:
            bpy.data.lights.remove(data)
        if camera_data:
            bpy.data.cameras.remove(camera_data)
        bpy.data.scenes.remove(scene)
        if world:
            bpy.data.worlds.remove(world)
        for material in created_materials:
            bpy.data.materials.remove(material)
