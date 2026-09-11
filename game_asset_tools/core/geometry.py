"""Low-poly geometry in meters, +Z up and -Y front; Euler angles are radians."""

from __future__ import annotations

import math
from collections.abc import Sequence

import bmesh
import bpy
from mathutils import Vector

from .naming import semantic_name

Vec3 = Sequence[float]


def _vector(value: Vec3, label: str) -> tuple[float, float, float]:
    if len(value) != 3 or not all(math.isfinite(v) for v in value):
        raise ValueError(f"{label} must contain three finite numbers")
    return tuple(float(v) for v in value)


def _positive(value: float, label: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be positive and finite")
    return float(value)


def _segments(value: int, minimum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _object(name, data, location, rotation, collection):
    obj = bpy.data.objects.new(semantic_name(name), data)
    obj.location = location
    obj.rotation_euler = rotation
    (collection if collection is not None else bpy.context.scene.collection).objects.link(obj)
    return obj


def create_mesh(
    name: str, vertices: Sequence[Vec3], faces: Sequence[Sequence[int]],
    *, edges: Sequence[Sequence[int]] = (), location: Vec3 = (0, 0, 0),
    rotation: Vec3 = (0, 0, 0), collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create explicit local-space geometry, without changing active selection.

    Faces use outward winding. Meshes are new single-user datablocks. Caller
    retains ownership of geometry, including intentional disconnected islands.
    """
    safe_name = semantic_name(name)
    location, rotation = _vector(location, "location"), _vector(rotation, "rotation")
    coordinates = [_vector(v, "vertex") for v in vertices]
    for indices in [*faces, *edges]:
        if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(coordinates) for i in indices):
            raise ValueError("Mesh indices must refer to existing vertices")
    if any(len(face) < 3 or len(set(face)) != len(face) for face in faces):
        raise ValueError("Faces need at least three distinct vertices")
    if any(len(edge) != 2 or edge[0] == edge[1] for edge in edges):
        raise ValueError("Edges need two distinct vertices")
    mesh = bpy.data.meshes.new(f"{safe_name}_Mesh")
    try:
        mesh.from_pydata(coordinates, list(edges), list(faces))
        mesh.update()
        return _object(safe_name, mesh, location, rotation, collection)
    except Exception:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


def _from_bmesh(name, builder, location, rotation, collection):
    semantic_name(name)
    location, rotation = _vector(location, "location"), _vector(rotation, "rotation")
    bm = bmesh.new()
    try:
        builder(bm)
        bm.verts.ensure_lookup_table()
        return create_mesh(name, [tuple(v.co) for v in bm.verts],
                           [[v.index for v in face.verts] for face in bm.faces],
                           location=location, rotation=rotation, collection=collection)
    finally:
        bm.free()


def add_box(
    name: str, size: Vec3, location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a centered box with true mesh dimensions and unit object scale."""
    x, y, z = (_positive(v, "size") / 2 for v in _vector(size, "size"))
    vertices = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
                (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return create_mesh(name, vertices, faces, location=location, rotation=rotation, collection=collection)


def add_beveled_box(
    name: str, size: Vec3, location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None, *, bevel: float = 0.03, segments: int = 1,
) -> bpy.types.Object:
    """Create a box with a restrained live bevel (zero width omits the modifier)."""
    from .modifiers import apply_bevel
    if not math.isfinite(bevel) or bevel < 0:
        raise ValueError("bevel must be finite and nonnegative")
    _segments(segments, 1, "segments")
    obj = add_box(name, size, location, rotation, collection)
    if bevel:
        apply_bevel(obj, bevel, segments)
    return obj


def add_cylinder(
    name: str, radius: float, depth: float, vertices: int = 12,
    location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a capped cylinder centered along its local Z axis."""
    return add_cone(name, radius, radius, depth, vertices, location, rotation, collection)


def add_cone(
    name: str, radius_bottom: float, radius_top: float, depth: float, vertices: int = 12,
    location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a capped cone or truncated cone along local Z; either radius may be zero."""
    _positive(depth, "depth")
    _segments(vertices, 3, "vertices")
    if not all(math.isfinite(r) and r >= 0 for r in (radius_bottom, radius_top)) or radius_bottom + radius_top <= 0:
        raise ValueError("Cone radii must be finite, nonnegative, and not both zero")
    return _from_bmesh(name, lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=vertices,
        radius1=radius_bottom, radius2=radius_top, depth=depth), location, rotation, collection)


def add_sphere(
    name: str, radius: float, segments: int = 12, rings: int = 8,
    location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a low-resolution UV sphere with flat shading."""
    _positive(radius, "radius")
    _segments(segments, 3, "segments")
    _segments(rings, 3, "rings")
    return _from_bmesh(name, lambda bm: bmesh.ops.create_uvsphere(
        bm, u_segments=segments, v_segments=rings, radius=radius), location, rotation, collection)


def add_plane(
    name: str, size: Sequence[float] = (1, 1), location: Vec3 = (0, 0, 0),
    rotation: Vec3 = (0, 0, 0), collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a two-sided-size XY plane with normal +Z and no artificial thickness."""
    if len(size) != 2:
        raise ValueError("Plane size requires width and depth")
    x, y = (_positive(v, "size") / 2 for v in size)
    return create_mesh(name, [(-x, -y, 0), (x, -y, 0), (x, y, 0), (-x, y, 0)],
                       [(0, 1, 2, 3)], location=location, rotation=rotation, collection=collection)


def add_torus(
    name: str, major_radius: float, minor_radius: float, major_segments: int = 16,
    minor_segments: int = 6, location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a low-poly ring around local Z; radii are centerline and tube radii."""
    _positive(major_radius, "major_radius")
    _positive(minor_radius, "minor_radius")
    if minor_radius >= major_radius:
        raise ValueError("minor_radius must be less than major_radius")
    _segments(major_segments, 3, "major_segments")
    _segments(minor_segments, 3, "minor_segments")
    vertices, faces = [], []
    for i in range(major_segments):
        u = math.tau * i / major_segments
        for j in range(minor_segments):
            v = math.tau * j / minor_segments
            r = major_radius + minor_radius * math.cos(v)
            vertices.append((r * math.cos(u), r * math.sin(u), minor_radius * math.sin(v)))
            a = i * minor_segments + j
            b = ((i + 1) % major_segments) * minor_segments + j
            c = ((i + 1) % major_segments) * minor_segments + (j + 1) % minor_segments
            d = i * minor_segments + (j + 1) % minor_segments
            faces.append((a, b, c, d))
    return create_mesh(name, vertices, faces, location=location, rotation=rotation, collection=collection)


def add_pipe(
    name: str, points: Sequence[Vec3], radius: float = 0.05, *, cyclic: bool = False,
    bevel_resolution: int = 0, location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a capped polyline tube as a Curve, retaining editable centerline points."""
    safe_name = semantic_name(name)
    _positive(radius, "radius")
    _segments(bevel_resolution, 0, "bevel_resolution")
    coordinates = [_vector(point, "point") for point in points]
    if len(coordinates) < (3 if cyclic else 2):
        raise ValueError("A pipe needs two points, or three for a closed loop")
    if any(a == b for a, b in zip(coordinates, coordinates[1:])):
        raise ValueError("Adjacent pipe points must differ")
    location, rotation = _vector(location, "location"), _vector(rotation, "rotation")
    curve = bpy.data.curves.new(f"{safe_name}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = bevel_resolution
    curve.use_fill_caps = not cyclic
    spline = curve.splines.new("POLY")
    spline.points.add(len(coordinates) - 1)
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (*coordinate, 1)
    spline.use_cyclic_u = cyclic
    return _object(safe_name, curve, location, rotation, collection)


def create_panel(
    name: str, width: float, height: float, thickness: float,
    location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None, *, bevel: float = 0.02,
) -> bpy.types.Object:
    """Create an upright XZ panel whose thickness extends along Y."""
    return add_beveled_box(name, (width, thickness, height), location, rotation, collection, bevel=bevel)


def create_support(
    name: str, start: Vec3, end: Vec3, width: float, depth: float | None = None,
    collection: bpy.types.Collection | None = None, *, bevel: float = 0,
) -> bpy.types.Object:
    """Create a rectangular beam spanning two world-space endpoints."""
    start, end = Vector(_vector(start, "start")), Vector(_vector(end, "end"))
    direction = end - start
    _positive(direction.length, "support length")
    obj = add_beveled_box(name, (width, width if depth is None else depth, direction.length),
                         (start + end) / 2, collection=collection, bevel=bevel)
    obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    return obj


def create_frame(
    name: str, width: float, height: float, bar_width: float, depth: float,
    location: Vec3 = (0, 0, 0), rotation: Vec3 = (0, 0, 0),
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """Create a watertight rectangular XZ frame with a through opening."""
    for value in (width, height, bar_width, depth):
        _positive(value, "frame dimension")
    if 2 * bar_width >= min(width, height):
        raise ValueError("Frame bars must leave a positive opening")
    vertices = []
    for y in (-depth / 2, depth / 2):
        for w, h in ((width / 2, height / 2), (width / 2 - bar_width, height / 2 - bar_width)):
            vertices.extend([(-w, y, -h), (w, y, -h), (w, y, h), (-w, y, h)])
    faces = []
    for i in range(4):
        j = (i + 1) % 4
        faces.extend([(i, j, j + 4, i + 4), (8 + i, 12 + i, 12 + j, 8 + j),
                      (i, 8 + i, 8 + j, j), (4 + i, 4 + j, 12 + j, 12 + i)])
    return create_mesh(name, vertices, faces, location=location, rotation=rotation, collection=collection)
