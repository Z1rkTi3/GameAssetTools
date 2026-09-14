"""Isolated Eevee sprite rendering and a portable, untrimmed PNG atlas.

Both Blender UI and CLI call this module with the same resolved sprite profile.
The source scene is evaluated at its current frame, never opened, saved or edited.
"""

from array import array
import json
import math
from pathlib import Path
import re
import tempfile

import bpy
from mathutils import Vector

from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.inspection import bounds


def _direction(azimuth, elevation):
    yaw, pitch = math.radians(azimuth), math.radians(elevation)
    return Vector((math.sin(yaw) * math.cos(pitch),
                   -math.cos(yaw) * math.cos(pitch), math.sin(pitch)))


def _framing(box, anchor, angles, settings):
    """One scale and ground pivot, including every requested camera direction."""
    corners = [Vector((x, y, z)) - anchor
               for x in (box["min"][0], box["max"][0])
               for y in (box["min"][1], box["max"][1])
               for z in (box["min"][2], box["max"][2])]
    horizontal, vertical = [], []
    for angle in angles:
        orientation = (-_direction(angle, settings["elevation"])).to_track_quat("-Z", "Y")
        right, up = orientation @ Vector((1, 0, 0)), orientation @ Vector((0, 1, 0))
        horizontal.extend(point.dot(right) for point in corners)
        vertical.extend(point.dot(up) for point in corners)
    low, high = min(vertical), max(vertical)
    offset = (low + high) / 2
    extent = max(max(abs(value) for value in horizontal), (high - low) / 2, .001)
    scale = extent * 2 / (1 - 2 * settings["margin"])
    pivot = [0.5, 0.5 + offset / scale]
    return {"projection": "orthographic", "ortho_scale": scale,
            "anchor_world": list(anchor), "vertical_offset": offset,
            "pivot_normalized": pivot,
            "pivot_pixels": [value * settings["resolution"] for value in pivot],
            "bounds": box, "margin": settings["margin"]}


def _toon_material(source, steps):
    """Shade copied base-color inputs with discrete light bands; keep source nodes."""
    material = source.copy() if source else bpy.data.materials.new("GAT_Sprite_Default")
    material.name = "GAT_Sprite_Toon_" + (source.name if source else "Default")
    material.use_nodes = True
    tree = material.node_tree
    principled = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    tint = tuple(source.diffuse_color) if source else (.8, .8, .8, 1)
    alpha = tint[3]
    color_socket, alpha_socket = None, None
    if principled:
        base, opacity = principled.inputs["Base Color"], principled.inputs["Alpha"]
        tint, alpha = tuple(base.default_value), opacity.default_value
        color_socket = base.links[0].from_socket if base.is_linked else None
        alpha_socket = opacity.links[0].from_socket if opacity.is_linked else None
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"]
    for node in outputs:
        tree.nodes.remove(node)
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    diffuse = tree.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    diffuse.inputs["Roughness"].default_value = 0
    shader_rgb = tree.nodes.new("ShaderNodeShaderToRGB")
    tree.links.new(diffuse.outputs[0], shader_rgb.inputs[0])
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.label = f"{steps} cel light bands"
    ramp.color_ramp.interpolation = "CONSTANT"
    while len(ramp.color_ramp.elements) > 1:
        ramp.color_ramp.elements.remove(ramp.color_ramp.elements[-1])
    for index in range(steps):
        element = ramp.color_ramp.elements[0] if index == 0 else ramp.color_ramp.elements.new(index / steps)
        level = .22 + .78 * index / (steps - 1)
        element.position = index / steps
        element.color = (level, level, level, 1)
    tree.links.new(shader_rgb.outputs["Color"], ramp.inputs["Fac"])
    tint_node = tree.nodes.new("ShaderNodeMixRGB")
    tint_node.blend_type = "MULTIPLY"
    tint_node.inputs[0].default_value = 1
    tint_node.inputs[1].default_value = tint
    if color_socket:
        tree.links.new(color_socket, tint_node.inputs[1])
    tree.links.new(ramp.outputs["Color"], tint_node.inputs[2])
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(tint_node.outputs[0], emission.inputs["Color"])
    if alpha_socket or alpha < 1:
        transparent = tree.nodes.new("ShaderNodeBsdfTransparent")
        mix = tree.nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = alpha
        if alpha_socket:
            tree.links.new(alpha_socket, mix.inputs[0])
        tree.links.new(transparent.outputs[0], mix.inputs[1])
        tree.links.new(emission.outputs[0], mix.inputs[2])
        tree.links.new(mix.outputs[0], output.inputs["Surface"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        elif hasattr(material, "blend_method"):
            material.blend_method = "HASHED"
    else:
        tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def _pack_atlas(frame_paths, destination, resolution, padding, columns):
    """Copy byte-image pixels without a second display/color transform.

    Blender byte images expose the PNG's encoded channels. Saving a byte image
    with Image.save (not save_render) preserves them. Rectangles use top-left
    image coordinates; Blender's pixel storage is bottom-up.
    """
    columns = min(columns, len(frame_paths))
    rows = math.ceil(len(frame_paths) / columns)
    cell = resolution + 2 * padding
    width, height = columns * cell, rows * cell
    pixels = array("f", [0.0]) * (width * height * 4)
    rectangles = []
    for index, path in enumerate(frame_paths):
        source = bpy.data.images.load(str(path), check_existing=False)
        try:
            if tuple(source.size) != (resolution, resolution):
                raise ValueError("Rendered sprite dimensions do not match the profile")
            values = array("f", [0.0]) * (resolution * resolution * 4)
            source.pixels.foreach_get(values)
            x = (index % columns) * cell + padding
            y = (index // columns) * cell + padding
            rectangles.append({"x": x, "y": y, "width": resolution, "height": resolution})
            bottom = height - y - resolution
            for row in range(resolution):
                start = ((bottom + row) * width + x) * 4
                pixels[start:start + resolution * 4] = values[row * resolution * 4:(row + 1) * resolution * 4]
        finally:
            bpy.data.images.remove(source)
    atlas = bpy.data.images.new("GAT_Sprite_Atlas", width=width, height=height,
                                alpha=True, float_buffer=False)
    try:
        atlas.alpha_mode = "STRAIGHT"
        atlas.colorspace_settings.name = "sRGB"
        atlas.pixels.foreach_set(pixels)
        atlas.file_format = "PNG"
        atlas.filepath_raw = str(destination)
        atlas.save()
    finally:
        bpy.data.images.remove(atlas)
    return {"width": width, "height": height, "columns": columns, "rows": rows,
            "padding": padding, "order": "row-major, top-left", "rectangles": rectangles}


def _write_frame(scene):
    bpy.ops.render.render(write_still=True, scene=scene.name)


def _render_frames(sources, paths, angles, settings, frame):
    """Reuse preview's evaluated-copy isolation, including OBJECT-linked shaders."""
    scene = bpy.data.scenes.new("GAT_Sprites")
    created_objects, meshes, materials, lights = [], [], [], []
    camera_data = world = None
    # Rendering another scene is context-sensitive in Blender. Keep the original
    # window scene even if an operator/render handler switches it during failure.
    window = bpy.context.window
    original_scene = window.scene if window else None
    try:
        graph = bpy.context.evaluated_depsgraph_get()
        try:
            scene.render.engine = "BLENDER_EEVEE"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.render.resolution_x = scene.render.resolution_y = settings["resolution"]
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        scene.render.film_transparent = True
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0
        scene.view_settings.gamma = 1
        world = bpy.data.worlds.new("GAT_Sprite_World")
        scene.world = world
        world.use_nodes = True
        background_node = next(node for node in world.node_tree.nodes if node.type == "BACKGROUND")
        background_node.inputs["Strength"].default_value = .15 if settings["look"] == "standard" else 0
        toon_cache = {}
        for source in sources:
            evaluated = source.evaluated_get(graph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=graph)
            meshes.append(mesh)
            for index, slot in enumerate(evaluated.material_slots):
                if slot.link == "OBJECT" and index < len(mesh.materials):
                    mesh.materials[index] = slot.material
            if settings["look"] == "toon":
                originals = list(mesh.materials) or [None]
                mesh.materials.clear()
                for original in originals:
                    key = original.as_pointer() if original else 0
                    if key not in toon_cache:
                        material = _toon_material(original, settings["cel_steps"])
                        materials.append(material)
                        toon_cache[key] = material
                    mesh.materials.append(toon_cache[key])
            obj = bpy.data.objects.new("GAT_Sprite_" + source.name, mesh)
            created_objects.append(obj)
            scene.collection.objects.link(obj)
            obj.matrix_world = evaluated.matrix_world.copy()
        camera_data = bpy.data.cameras.new("GAT_Sprite_Camera")
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = frame["ortho_scale"]
        camera = bpy.data.objects.new("GAT_Sprite_Camera", camera_data)
        created_objects.append(camera)
        scene.collection.objects.link(camera)
        scene.camera = camera
        distance = frame["ortho_scale"] * 4
        camera_data.clip_start = max(distance / 10000, .0001)
        camera_data.clip_end = distance * 4
        light_data = bpy.data.lights.new("GAT_Sprite_Key", "SUN")
        lights.append(light_data)
        light_data.energy = 3.0
        light_data.angle = .035
        light = bpy.data.objects.new("GAT_Sprite_Key", light_data)
        created_objects.append(light)
        scene.collection.objects.link(light)
        light.rotation_euler = (-_direction(settings["light_azimuth"], settings["light_elevation"])).to_track_quat("-Z", "Y").to_euler()
        anchor = Vector(frame["anchor_world"])
        for angle, path in zip(angles, paths):
            direction = _direction(angle, settings["elevation"])
            rotation = (-direction).to_track_quat("-Z", "Y")
            center = anchor + (rotation @ Vector((0, 1, 0))) * frame["vertical_offset"]
            camera.location = center + direction * distance
            camera.rotation_euler = rotation.to_euler()
            scene.render.filepath = str(path)
            _write_frame(scene)
    finally:
        if window and original_scene:
            window.scene = original_scene
        for obj in created_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for data in lights:
            bpy.data.lights.remove(data)
        if camera_data:
            bpy.data.cameras.remove(camera_data)
        bpy.data.scenes.remove(scene)
        if world:
            bpy.data.worlds.remove(world)
        for material in materials:
            bpy.data.materials.remove(material)


def _publish(staging, directory, destinations, overwrite):
    """Replace only declared artifacts, restoring the previous export on failure."""
    backups, published = [], []
    try:
        if overwrite:
            # Remove the old success manifest from view before replacing any
            # frames. A failed replacement cannot leave a misleading manifest.
            for destination in reversed(destinations):
                if destination.exists():
                    backup = staging / "backup" / destination.relative_to(directory)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    destination.replace(backup)
                    backups.append((backup, destination))
        for destination in destinations:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = staging / destination.relative_to(directory)
            if overwrite:
                source.replace(destination)
            else:
                # Exclusive creation works on Windows and POSIX. The manifest
                # is last; an interrupted copy never advertises a complete set.
                import shutil
                with destination.open("xb") as stream:
                    published.append(destination)
                    with source.open("rb") as content:
                        shutil.copyfileobj(content, stream)
                continue
            published.append(destination)
    except BaseException:
        for destination in reversed(published):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            backup.replace(destination)
        raise


def render_sprites(asset_id, output, settings, *, overwrite=False, preview=False, dry_run=False):
    """Render current-frame asset directions using one already validated profile.

    Render and packing failures only affect a temporary staging directory. All
    declared destinations are preflighted before rendering. The successful JSON
    manifest is published last, after every PNG has been prepared.
    """
    from .settings import validate_settings
    settings = validate_settings(settings)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", asset_id):
        raise ValueError("Invalid asset identifier for sprite output")
    root = find_root(asset_id)
    if bpy.context.mode != "OBJECT":
        raise ValueError("Sprite rendering requires Object Mode; finish the edit before exporting")
    sources = [obj for obj in asset_objects(root, helpers=False)
               if obj.type in {"MESH", "CURVE", "SURFACE", "FONT"}]
    if not sources:
        raise ValueError("Sprite target contains no renderable geometry")
    directory = Path(output).expanduser().resolve() / "sprites" / asset_id
    if preview:
        directory = directory / "preview"
    all_angles = [(settings["azimuth"] + 360 * index / settings["directions"]) % 360
                  for index in range(settings["directions"])]
    angles = all_angles[:1] if preview else all_angles
    relative = [Path("frames") / f"direction_{index:03d}.png" for index in range(len(angles))]
    destinations = [directory / path for path in relative]
    manifest = directory / "sprites.json"
    atlas_path = directory / "atlas.png"
    all_paths = destinations + ([] if preview else [atlas_path]) + [manifest]
    for path in all_paths:
        if path.exists() and (not overwrite or not path.is_file()):
            raise FileExistsError(f"Output exists: {path}; explicitly request overwrite")
    box = bounds(sources)
    anchor = root_object(root).matrix_world.translation.copy()
    anchor.z = box["min"][2]
    frame = _framing(box, anchor, all_angles, settings)
    result = {"schema_version": 1, "status": "planned" if dry_run else "passed",
              "asset": asset_id, "stage": root.get("gat_stage"), "preview": preview,
              "settings": dict(settings), "source_frame": bpy.context.scene.frame_current,
              "framing": frame, "coordinate_origin": "top-left", "alpha": "straight",
              "report": str(manifest), "frames": [], "atlas": None}
    for index, (angle, path, rel) in enumerate(zip(angles, destinations, relative)):
        result["frames"].append({"name": f"direction_{index:03d}", "index": index,
                                 "azimuth": angle, "elevation": settings["elevation"],
                                 "file": rel.as_posix(), "path": str(path),
                                 "pivot_normalized": list(frame["pivot_normalized"]),
                                 "pivot_pixels": list(frame["pivot_pixels"]),
                                 "width": settings["resolution"], "height": settings["resolution"]})
    if dry_run:
        return result
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gat_sprites_", dir=directory.parent) as staging:
        staging = Path(staging)
        (staging / "frames").mkdir()
        staged_frames = [staging / path for path in relative]
        _render_frames(sources, staged_frames, angles, settings, frame)
        if not preview:
            atlas = _pack_atlas(staged_frames, staging / "atlas.png", settings["resolution"],
                                settings["padding"], settings["atlas_columns"])
            for item, rectangle in zip(result["frames"], atlas.pop("rectangles")):
                item["rect"] = rectangle
            result["atlas"] = {**atlas, "file": "atlas.png", "path": str(atlas_path)}
        (staging / "sprites.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        # Recheck after rendering in case another exporter wrote these files.
        for path in all_paths:
            if path.exists() and (not overwrite or not path.is_file()):
                raise FileExistsError(f"Sprite output changed while rendering: {path}")
        _publish(staging, directory, all_paths, overwrite)
    return result
