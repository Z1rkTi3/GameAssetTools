"""Save a framed viewing copy while retaining the current working document."""

from itertools import product
from pathlib import Path

from .paths import artifact_path, prepare_path


# Blender's non-camera viewport uses a 36 mm sensor and a 2x view-plane zoom.
# See BKE_camera_params_from_view3d / BKE_camera_params_compute_viewplane.
_SENSOR_WIDTH = 36.0
_LENS = 50.0
_MARGIN = 1.2


def _viewports():
    """Include inactive spaces and quad views, not only the current window."""
    import bpy
    for screen in bpy.data.screens:
        for area in screen.areas:
            windows = [region for region in area.regions if region.type == "WINDOW"]
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                regions = list(space.region_quadviews) or [space.region_3d]
                for index, region in enumerate(regions):
                    if region is None:
                        continue
                    window = windows[min(index, len(windows) - 1)] if windows else None
                    width = max(window.width if window else area.width, 1)
                    height = max(window.height if window else area.height, 1)
                    yield space, region, width, height


def _capture(target, names):
    import bpy
    values = {}
    for name in names:
        value = getattr(target, name)
        values[name] = value.copy() if hasattr(value, "copy") and not isinstance(value, bpy.types.ID) else value
    return target, values


def _write_copy(path):
    import bpy
    return bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False, copy=True)


def save_view_copy(asset_id, output, *, overwrite=False, view="perspective"):
    """Frame evaluated asset bounds in a separate .blend, without viewport ops.

    ``copy=True`` keeps Blender's current filepath and relative resource paths.
    Viewport RNA is restored in ``finally``, including when saving fails. No
    preferences, geometry, scene cameras, or source file are written.
    """
    import bpy
    from mathutils import Vector
    from game_asset_tools.asset.scene import asset_objects, find_root
    from game_asset_tools.inspection import bounds
    from game_asset_tools.preview import VIEWS

    if view not in VIEWS:
        raise ValueError(f"Unknown viewing-copy view {view!r}; choose {tuple(VIEWS)}")
    sources = [obj for obj in asset_objects(find_root(asset_id), helpers=False)
               if obj.type in {"MESH", "CURVE", "SURFACE", "FONT"}]
    if not sources:
        raise ValueError("Viewing-copy target contains no geometry")
    path = artifact_path(output, "blend", asset_id, "_view.blend")
    source_path = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if source_path and (path == source_path or
                        (path.exists() and source_path.exists() and path.samefile(source_path))):
        raise ValueError("Viewing-copy destination is the current source file; choose another output directory")
    viewports = list(_viewports())
    if not viewports:
        raise ValueError("Scene has no saved VIEW_3D regions to prepare for viewing")
    path = prepare_path(path, overwrite=overwrite)
    box = bounds(sources)
    center = Vector(box["center"])
    corners = [Vector(point) for point in product(*zip(box["min"], box["max"]))]
    radius = max(Vector(box["dimensions"]).length / 2, 0.01)
    direction = Vector(VIEWS[view]).normalized()
    rotation = (-direction).to_track_quat("-Z", "Y")
    relative = [rotation.inverted() @ (point - center) for point in corners]
    states, spaces, local_membership = [], set(), []
    selected = tuple(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    original_filepath = bpy.data.filepath
    distances = []
    try:
        for space, region, width, height in viewports:
            if space.as_pointer() not in spaces:
                spaces.add(space.as_pointer())
                states.append(_capture(space, ("lens", "clip_start", "clip_end", "lock_object",
                                               "lock_bone", "lock_cursor", "lock_camera")))
                states.append(_capture(space.shading, ("type", "use_scene_lights", "use_scene_world")))
                space.lens = _LENS
                space.clip_start = max(radius / 1000, 0.0001)
                space.lock_object = None
                space.lock_bone = ""
                space.lock_cursor = space.lock_camera = False
                space.shading.type = "MATERIAL"
                space.shading.use_scene_lights = space.shading.use_scene_world = False
                if space.local_view:
                    for obj in sources:
                        local_membership.append((obj, space, obj.local_view_get(space)))
                        obj.local_view_set(space, True)
            states.append(_capture(region, ("view_location", "view_rotation", "view_distance",
                                             "view_perspective", "lock_rotation", "show_sync_view",
                                             "use_box_clip", "use_clip_planes")))
            region.lock_rotation = region.show_sync_view = False
            region.use_box_clip = region.use_clip_planes = False
            region.view_perspective = "PERSP" if view == "perspective" else "ORTHO"
            region.view_rotation = rotation
            region.view_location = center
            tangent_x = _SENSOR_WIDTH / _LENS * width / max(width, height)
            tangent_y = _SENSOR_WIDTH / _LENS * height / max(width, height)
            # Perspective depth is included per corner, so wide and tall assets
            # fit as well as a sphere, without shrinking every model to a sphere.
            distance = max(max(abs(p.x) / tangent_x, abs(p.y) / tangent_y) * _MARGIN
                           + (p.z if view == "perspective" else 0) for p in relative)
            distance = max(distance, radius * 0.1, 0.1)
            region.view_distance = distance
            space.clip_end = max(space.clip_end, (distance + radius) * 4, 100)
            distances.append(distance)
        result = _write_copy(path)
        if "FINISHED" not in result or not path.is_file():
            raise RuntimeError("Blender did not save the requested viewing copy")
        if bpy.data.filepath != original_filepath:
            raise RuntimeError("Blender unexpectedly changed the working filepath while saving a copy")
        return {"asset": asset_id, "status": "saved", "blend": str(path), "view_copy": True,
                "view": view, "framing": {"bounds": box, "center": list(center),
                                            "viewport_count": len(viewports), "distances": distances}}
    finally:
        for obj, space, membership in reversed(local_membership):
            obj.local_view_set(space, membership)
        for target, values in reversed(states):
            for name, value in values.items():
                setattr(target, name, value)
        # Saving a copy normally leaves selection alone; preserve it even if an
        # add-on save handler selected a different object while the file saved.
        for obj in bpy.context.selected_objects:
            if obj not in selected:
                obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
