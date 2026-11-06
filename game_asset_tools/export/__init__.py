"""Shared .blend persistence and selected asset GLB export."""

import json
import os
from pathlib import Path
import struct
import tempfile

from .paths import artifact_path, prepare_path


def inspect_glb(path):
    """Check GLB container and summarize the actual JSON scene payload."""
    blob = Path(path).read_bytes()
    if len(blob) < 20:
        raise ValueError("Truncated GLB file")
    magic, version, length = struct.unpack_from("<4sII", blob)
    if magic != b"glTF" or version != 2 or length != len(blob):
        raise ValueError("Invalid GLB header or length")
    size, kind = struct.unpack_from("<I4s", blob, 12)
    if kind != b"JSON" or size+20 > len(blob):
        raise ValueError("Invalid GLB JSON chunk")
    content = json.loads(blob[20:20+size])
    if not content.get("meshes") or not content.get("nodes"):
        raise ValueError("GLB has no geometry")
    nodes = content["nodes"]
    skins = content.get("skins", [])
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if type(child) is not int or not 0 <= child < len(nodes) or child in parents:
                raise ValueError("GLB has an invalid node hierarchy")
            parents[child] = index
    # Проверяем всю иерархию, включая обычные сокеты, а не только предков skin joints.
    for index in range(len(nodes)):
        seen = set()
        current = index
        while current in parents:
            if current in seen:
                raise ValueError("GLB has a cyclic node hierarchy")
            seen.add(current)
            current = parents[current]
    skin_details, bindings, animations = [], [], []
    for skin in skins:
        joints = skin.get("joints", [])
        if not joints or any(type(j) is not int or not 0 <= j < len(nodes) for j in joints):
            raise ValueError("GLB skin has invalid joints")
        ancestors = set()
        for joint in joints:
            seen = set()
            current = joint
            while current in parents:
                if current in seen:
                    raise ValueError("GLB has a cyclic bone hierarchy")
                seen.add(current)
                current = parents[current]
                ancestors.add(nodes[current].get("name"))
        skin_details.append({"name": skin.get("name"), "joints": len(joints),
                             "joint_names": [nodes[j].get("name") for j in joints],
                             "ancestors": sorted(name for name in ancestors if name is not None)})
    for node in nodes:
        if "skin" not in node:
            continue
        skin, mesh = node["skin"], node.get("mesh")
        if type(skin) is not int or not 0 <= skin < len(skins) or type(mesh) is not int or not 0 <= mesh < len(content["meshes"]):
            raise ValueError("GLB has an invalid skinned mesh binding")
        primitives = content["meshes"][mesh].get("primitives", [])
        weighted = bool(primitives) and all("JOINTS_0" in p.get("attributes", {}) and "WEIGHTS_0" in p.get("attributes", {}) for p in primitives)
        bindings.append({"node": node.get("name"), "skin": skin, "weighted": weighted})
    for animation in content.get("animations", []):
        channels = animation.get("channels", [])
        samplers = animation.get("samplers", [])
        for channel in channels:
            target = channel.get("target", {}).get("node")
            sampler = channel.get("sampler")
            if type(target) is not int or not 0 <= target < len(nodes) or type(sampler) is not int or not 0 <= sampler < len(samplers):
                raise ValueError("GLB animation has an invalid target or sampler")
        animations.append({"name": animation.get("name"), "channels": len(channels),
                           "targets": sorted({nodes[c["target"]["node"]].get("name", "") for c in channels})})
    return {"bytes": len(blob), "meshes": len(content["meshes"]), "nodes": len(nodes),
            "materials": len(content.get("materials", [])), "node_names": [n.get("name") for n in nodes],
            "node_parents": {nodes[index].get("name"): nodes[parent].get("name") for index, parent in parents.items()},
            "skins": len(skins), "joints": sum(s["joints"] for s in skin_details),
            "skin_details": skin_details, "skin_bindings": bindings,
            "animations": len(animations), "animation_names": [a["name"] for a in animations],
            "animation_details": animations}


def save_asset(asset_id, output, *, overwrite=False, view_copy=False, view="perspective"):
    import bpy
    from game_asset_tools.asset.scene import find_root
    find_root(asset_id)
    if view_copy:
        from .view_copy import save_view_copy
        return save_view_copy(asset_id, output, overwrite=overwrite, view=view)
    path = prepare_path(artifact_path(output, "blend", asset_id, ".blend"), overwrite=overwrite)
    result = bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    if "FINISHED" not in result or not path.is_file():
        raise RuntimeError("Blender did not save the requested file")
    return {"asset": asset_id, "status": "saved", "blend": str(path)}


def _vertex_color_options(objects, vertex_color_name):
    """Выбирает один явный цветовой слой без подмены отсутствующих данных белым."""
    if type(vertex_color_name) is not str:
        raise ValueError("vertex_color_name must be a string")
    if not vertex_color_name:
        # Пустая строка сохраняет прежний выбор цветов штатного glTF exporter.
        return {}
    missing = [obj.name for obj in objects if obj.type == "MESH"
               and obj.data.color_attributes.get(vertex_color_name) is None]
    if missing:
        raise ValueError(f"Vertex color attribute {vertex_color_name!r} is missing on export meshes: "
                         + ", ".join(sorted(missing)))
    return {"export_vertex_color": "NAME", "export_vertex_color_name": vertex_color_name,
            "export_all_vertex_colors": False}


def _recipe_export_context(function):
    """Необязательный reversible hook рецепта; обычный экспорт не меняется."""
    from functools import wraps

    @wraps(function)
    def wrapped(asset_id, output, **options):
        entry = options.get("entry")
        factory = getattr(entry.load(), "export_context", None) if entry is not None else None
        if not callable(factory):
            return function(asset_id, output, **options)
        with factory(asset_id, animations=options.get("animations", False)):
            return function(asset_id, output, **options)
    return wrapped


@_recipe_export_context
def export_asset(asset_id, output, *, entry=None, overwrite=False, animations=False,
                 vertex_color_name=""):
    import bpy
    from game_asset_tools.asset.scene import asset_objects, find_root, root_object
    from game_asset_tools.validation import validate_asset
    if type(animations) is not bool:
        raise ValueError("animations must be a boolean")
    report = validate_asset(asset_id, entry)
    if report["errors"]:
        raise ValueError("Export validation failed: " + "; ".join(report["errors"]))
    root = find_root(asset_id)
    objects = [root_object(root), *asset_objects(root, helpers=False)]
    color_options = _vertex_color_options(objects, vertex_color_name)
    from .rig import animation_contract, verify_animation_contract
    contract = animation_contract(objects) if animations else None
    path = prepare_path(artifact_path(output, "glb", asset_id, ".glb"), overwrite=overwrite)
    # Include sockets (empties), but no preview or construction helpers.
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    scene_scale = bpy.context.scene.unit_settings.scale_length
    states = {obj: (obj.hide_get(), obj.hide_viewport, obj.hide_select) for obj in objects}
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before exporting")
    frame, subframe = bpy.context.scene.frame_current, bpy.context.scene.frame_subframe
    temporary = None
    try:
        # Asset coordinates/root scale define meters, regardless of UI unit settings.
        bpy.context.scene.unit_settings.scale_length = 1.0
        for obj in selected:
            obj.select_set(False)
        for obj in objects:
            obj.hide_set(False)
            obj.hide_viewport = False
            obj.hide_select = False
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        # Validate the resulting payload before replacing an existing delivery.
        with tempfile.NamedTemporaryFile(prefix=f".{asset_id}_", suffix=".glb", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
        options = dict(filepath=str(temporary), check_existing=False, export_format="GLB",
                       use_selection=True, export_apply=True, export_yup=True,
                       export_extras=True, export_animations=animations, export_cameras=False,
                       export_lights=False)
        options.update(color_options)
        if animations:
            options.update(export_skins=True, export_animation_mode="ACTIONS", export_force_sampling=True,
                           export_anim_single_armature=False, export_def_bones=False,
                           export_armature_object_remove=False, export_frame_range=False)
        result = bpy.ops.export_scene.gltf(**options)
        if "FINISHED" not in result:
            raise RuntimeError("Blender GLB exporter did not finish")
        summary = inspect_glb(temporary)
        if animations:
            verify_animation_contract(contract, summary)
        if overwrite:
            os.replace(temporary, path)
        else:
            # Same-directory link publishes the validated file without clobbering
            # a concurrent writer that created the destination after preflight.
            os.link(temporary, path)
            temporary.unlink()
        return {"asset": asset_id, "status": "exported", "glb": str(path), "structure": summary,
                "animations_requested": animations, "animation_contract": contract,
                "vertex_color_name": vertex_color_name,
                "warnings": report["warnings"]}
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        bpy.context.scene.frame_set(frame, subframe=subframe)
        bpy.context.scene.unit_settings.scale_length = scene_scale
        for obj in objects:
            obj.select_set(False)
            hidden, viewport, select = states[obj]
            obj.hide_set(hidden)
            obj.hide_viewport = viewport
            obj.hide_select = select
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
