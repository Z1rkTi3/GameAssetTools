"""Shared .blend persistence and selected asset GLB export."""

import json
from pathlib import Path
import struct

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
    return {"bytes": len(blob), "meshes": len(content["meshes"]), "nodes": len(content["nodes"]),
            "materials": len(content.get("materials", [])), "node_names": [n.get("name") for n in content["nodes"]]}


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


def export_asset(asset_id, output, *, entry=None, overwrite=False):
    import bpy
    from game_asset_tools.asset.scene import asset_objects, find_root, root_object
    from game_asset_tools.validation import validate_asset
    report = validate_asset(asset_id, entry)
    if report["errors"]:
        raise ValueError("Export validation failed: " + "; ".join(report["errors"]))
    path = prepare_path(artifact_path(output, "glb", asset_id, ".glb"), overwrite=overwrite)
    root = find_root(asset_id)
    objects = [root_object(root), *asset_objects(root, helpers=False)]
    # Include sockets (empties), but no preview or construction helpers.
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    scene_scale = bpy.context.scene.unit_settings.scale_length
    states = {obj: (obj.hide_get(), obj.hide_viewport, obj.hide_select) for obj in objects}
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before exporting")
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
        result = bpy.ops.export_scene.gltf(filepath=str(path), check_existing=False, export_format="GLB",
                                          use_selection=True, export_apply=True, export_yup=True,
                                          export_extras=True, export_animations=False, export_cameras=False,
                                          export_lights=False)
        if "FINISHED" not in result:
            raise RuntimeError("Blender GLB exporter did not finish")
        summary = inspect_glb(path)
        return {"asset": asset_id, "status": "exported", "glb": str(path), "structure": summary,
                "warnings": report["warnings"]}
    finally:
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
