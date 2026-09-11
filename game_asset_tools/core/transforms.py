"""Intentional pivots and hierarchy without selection-dependent operations."""

from __future__ import annotations

from collections.abc import Sequence

import bpy
from mathutils import Matrix, Vector

from .geometry import _vector
from .naming import semantic_name


def parent_object(obj: bpy.types.Object, parent: bpy.types.Object | None,
                  *, keep_world: bool = True) -> bpy.types.Object:
    """Parent or detach an object; preserve its world transform by default."""
    ancestor = parent
    visited = set()
    while ancestor is not None:
        if ancestor is obj or ancestor.as_pointer() in visited:
            raise ValueError("Parenting would create a hierarchy cycle")
        visited.add(ancestor.as_pointer())
        ancestor = ancestor.parent
    bpy.context.view_layer.update()
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    if keep_world:
        obj.matrix_world = matrix
    bpy.context.view_layer.update()
    return obj


def set_origin(obj: bpy.types.Object, location: Sequence[float]) -> bpy.types.Object:
    """Move a mesh/curve origin to a world-space pivot while preserving geometry.

    Children retain their world matrices. Shared data becomes single-user;
    mesh shape keys receive the same transform. Live modifiers still evaluate
    relative to the new origin, which is intentional for mirror/array pivots.
    """
    point = Vector(_vector(location, "origin"))
    if obj.type not in {"MESH", "CURVE", "SURFACE", "FONT"}:
        raise ValueError("set_origin supports mesh and curve geometry")
    if obj.library is not None or obj.data.library is not None:
        raise ValueError("Linked library geometry must be made local before editing")
    if obj.mode != "OBJECT":
        raise ValueError("Leave edit mode before changing an origin")
    bpy.context.view_layer.update()
    old_matrix = obj.matrix_world.copy()
    if abs(old_matrix.determinant()) < 1e-12:
        raise ValueError("Cannot move the origin of a singular transform")
    children = [(child, child.matrix_world.copy()) for child in obj.children]
    new_matrix = old_matrix.copy()
    new_matrix.translation = point
    transform = new_matrix.inverted() @ old_matrix
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    if obj.type == "MESH":
        obj.data.transform(transform, shape_keys=True)
        obj.data.update()
    else:
        obj.data.transform(transform)
    obj.matrix_world = new_matrix
    bpy.context.view_layer.update()
    for child, matrix in children:
        child.matrix_world = matrix
    bpy.context.view_layer.update()
    return obj


def add_socket(name: str, location: Sequence[float] = (0, 0, 0),
               rotation: Sequence[float] = (0, 0, 0), *,
               parent: bpy.types.Object | None = None,
               collection: bpy.types.Collection | None = None,
               display_size: float = 0.15) -> bpy.types.Object:
    """Create a named empty at a world-space mount point (+Z up, Euler radians).

    This marks socket semantics only; asset ownership belongs to AssetContext.
    """
    from .geometry import _positive

    safe_name = semantic_name(name)
    point, angles = _vector(location, "location"), _vector(rotation, "rotation")
    _positive(display_size, "display_size")
    obj = bpy.data.objects.new(safe_name, None)
    (collection if collection is not None else bpy.context.scene.collection).objects.link(obj)
    obj.location = point
    obj.rotation_euler = angles
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = display_size
    obj["gat_socket"] = safe_name
    if parent is not None:
        parent_object(obj, parent)
    return obj
