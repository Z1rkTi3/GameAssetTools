"""Small, explicit modifier helpers; construction is live unless apply=True."""

from __future__ import annotations

import math
from collections.abc import Sequence

import bpy


def _mesh(obj: bpy.types.Object) -> None:
    if obj.type != "MESH":
        raise ValueError(f"{obj.name!r} must be a mesh object")
    if obj.library is not None or obj.data.library is not None:
        raise ValueError("Linked library geometry must be made local before editing")


def _number(value: float, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return float(value)


def _count(value: int, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def apply_modifier(obj: bpy.types.Object, modifier: bpy.types.Modifier | str) -> bpy.types.Object:
    """Bake one modifier on local mesh data and restore the interactive context.

    Shared mesh data is copied before baking. The object must be in the current
    view layer. Active object, selection and the previous editing mode survive.
    """
    _mesh(obj)
    name = modifier if isinstance(modifier, str) else modifier.name
    if name not in obj.modifiers or (not isinstance(modifier, str) and obj.modifiers[name] != modifier):
        raise ValueError(f"Modifier {name!r} does not belong to {obj.name!r}")
    layer = bpy.context.view_layer
    layer.update()
    if obj.name not in layer.objects:
        raise ValueError("Modifier target must be in the current view layer")
    active = layer.objects.active
    previous_mode = active.mode if active is not None else "OBJECT"
    selected = list(bpy.context.selected_objects)
    try:
        if active is not None and previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        with bpy.context.temp_override(object=obj, active_object=obj,
                                       selected_objects=[obj], selected_editable_objects=[obj]):
            result = bpy.ops.object.modifier_apply(modifier=name)
        if "FINISHED" not in result:
            raise RuntimeError(f"Could not apply modifier {name!r} to {obj.name!r}")
    finally:
        for item in layer.objects:
            if item.select_get() != (item in selected):
                item.select_set(item in selected)
        layer.objects.active = active
        if active is not None and previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=previous_mode)
    return obj


def _finish(obj, modifier, apply):
    if apply:
        apply_modifier(obj, modifier)
    return modifier if not apply else obj


def weighted_normals(obj: bpy.types.Object, *, weight: int = 50, apply: bool = False):
    """Add a weighted-normal modifier for hard surfaces with smooth face shading.

    The helper does not change the caller's face shading choices.
    """
    _mesh(obj)
    _count(weight, "weight")
    if weight > 100:
        raise ValueError("weight must be <= 100")
    modifier = obj.modifiers.new("GAT_WeightedNormals", "WEIGHTED_NORMAL")
    modifier.keep_sharp = True
    modifier.weight = weight
    return _finish(obj, modifier, apply)


def apply_bevel(obj: bpy.types.Object, width: float = 0.03, segments: int = 1,
                *, angle: float = math.radians(30), weighted: bool = False, apply: bool = False):
    """Add an angle-limited bevel; angles are radians and width uses mesh units."""
    _mesh(obj)
    _number(width, "width")
    _count(segments, "segments")
    if not math.isfinite(angle) or not 0 <= angle <= math.pi:
        raise ValueError("angle must be between zero and pi radians")
    modifier = obj.modifiers.new("GAT_Bevel", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    modifier.angle_limit = angle
    modifier.affect = "EDGES"
    modifier.use_clamp_overlap = True
    result = _finish(obj, modifier, apply)
    if weighted:
        weighted_normals(obj, apply=apply)
    return result


def mirror_object(obj: bpy.types.Object, axes: Sequence[str] = ("X",), *,
                  mirror_object: bpy.types.Object | None = None, merge: bool = True,
                  merge_threshold: float = 0.001, clip: bool = False, apply: bool = False):
    """Mirror mesh geometry around the local origin or an explicit pivot object."""
    _mesh(obj)
    requested = {str(axis).upper() for axis in axes}
    if not requested or not requested <= {"X", "Y", "Z"}:
        raise ValueError("axes must contain X, Y and/or Z")
    _number(merge_threshold, "merge_threshold")
    if mirror_object is obj:
        raise ValueError("A mirror pivot must be a different object")
    modifier = obj.modifiers.new("GAT_Mirror", "MIRROR")
    modifier.use_axis = tuple(axis in requested for axis in ("X", "Y", "Z"))
    modifier.mirror_object = mirror_object
    modifier.use_mirror_merge = merge
    modifier.merge_threshold = merge_threshold
    modifier.use_clip = clip
    return _finish(obj, modifier, apply)


def array_object(obj: bpy.types.Object, count: int, offset: Sequence[float] = (1, 0, 0), *,
                 relative: bool = False, merge: bool = False, apply: bool = False):
    """Repeat geometry with a local-space constant offset (or relative bounds offset)."""
    _mesh(obj)
    _count(count, "count")
    if len(offset) != 3 or not all(math.isfinite(v) for v in offset):
        raise ValueError("offset must contain three finite values")
    modifier = obj.modifiers.new("GAT_Array", "ARRAY")
    modifier.count = count
    modifier.use_relative_offset = relative
    modifier.use_constant_offset = not relative
    if relative:
        modifier.relative_offset_displace = offset
    else:
        modifier.constant_offset_displace = offset
    modifier.use_merge_vertices = merge
    return _finish(obj, modifier, apply)


def _boolean(obj, operand, operation, apply):
    _mesh(obj)
    _mesh(operand)
    if obj is operand:
        raise ValueError("Boolean operands must be different objects")
    modifier = obj.modifiers.new(f"GAT_Boolean_{operation}", "BOOLEAN")
    modifier.operation = operation
    modifier.solver = "EXACT"
    modifier.object = operand
    return _finish(obj, modifier, apply)


def boolean_cut(obj: bpy.types.Object, cutter: bpy.types.Object, *, apply: bool = False):
    """Subtract a mesh; the caller retains and controls the cutter object."""
    return _boolean(obj, cutter, "DIFFERENCE", apply)


def boolean_union(obj: bpy.types.Object, operand: bpy.types.Object, *, apply: bool = False):
    """Union a mesh; the caller retains and controls the operand object."""
    return _boolean(obj, operand, "UNION", apply)


def solidify(obj: bpy.types.Object, thickness: float, *, offset: float = 0,
             even: bool = True, apply: bool = False):
    """Give a surface thickness; negative thickness intentionally reverses direction."""
    _mesh(obj)
    if not math.isfinite(thickness) or thickness == 0:
        raise ValueError("thickness must be finite and nonzero")
    if not math.isfinite(offset) or not -1 <= offset <= 1:
        raise ValueError("offset must be between -1 and 1")
    modifier = obj.modifiers.new("GAT_Solidify", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = offset
    modifier.use_even_offset = even
    return _finish(obj, modifier, apply)
