"""Compact evaluated geometry statistics and semantic scene inspection."""

import bpy
from mathutils import Vector

from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from .materials import material_role, material_usage


def bounds(objects):
    """World-space evaluated bounds, including modifiers and parent transforms."""
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    corners = [obj.matrix_world @ Vector(corner) for source in objects
               if source.type in {"MESH", "CURVE", "SURFACE", "FONT"}
               for obj in [source.evaluated_get(graph)] for corner in obj.bound_box]
    if not corners:
        return {"min": [0.0] * 3, "max": [0.0] * 3, "center": [0.0] * 3, "dimensions": [0.0] * 3}
    low = [min(p[i] for p in corners) for i in range(3)]
    high = [max(p[i] for p in corners) for i in range(3)]
    return {"min": low, "max": high, "center": [(a+b)/2 for a,b in zip(low,high)],
            "dimensions": [b-a for a,b in zip(low,high)]}


def statistics(objects):
    result = {"objects": len(objects), "vertices": 0, "edges": 0, "faces": 0, "triangles": 0}
    graph = bpy.context.evaluated_depsgraph_get()
    materials = set()
    for obj in objects:
        materials.update(slot.material.name for slot in obj.material_slots if slot.material)
        if obj.type not in {"MESH", "CURVE", "SURFACE", "FONT"}:
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            for key, value in (("vertices", mesh.vertices), ("edges", mesh.edges), ("faces", mesh.polygons), ("triangles", mesh.loop_triangles)):
                result[key] += len(value)
        finally:
            evaluated.to_mesh_clear()
    result["materials"] = len(materials)
    return result


def inspect_asset(asset_id, component=None):
    root = find_root(asset_id)
    records = component_records(root)
    if component and component not in records:
        raise ValueError(f"Unknown component {component!r}")
    objects = asset_objects(root, component)
    result = {"asset": asset_id, "stage": root.get("gat_stage"), "stage_status": root.get("gat_stage_status"),
              "statistics": statistics(objects), "bounds": bounds(objects),
              "material_roles": material_usage(root, objects)}
    if component:
        result.update(component=component, **records[component])
        result["objects"] = [{"name": o.name, "local_name": o.get("gat_local_name"), "type": o.type,
                              "location": list(o.location), "rotation": list(o.rotation_euler), "scale": list(o.scale),
                              "materials": [s.material.name for s in o.material_slots if s.material],
                              "parent": o.parent.name if o.parent else None,
                              "collections": [c.name for c in o.users_collection], "helper": bool(o.get("gat_helper"))}
                             for o in objects]
    else:
        result["components"] = {key: {**record, "objects": sum(o.get("gat_component") == key for o in objects)}
                                for key, record in records.items()}
    return result


def scene_summary():
    return {"scene": bpy.context.scene.name,
            "assets": [inspect_asset(c["gat_asset_id"]) for c in bpy.context.scene.collection.children_recursive
                       if c.get("gat_role") == "asset_root"],
            "objects": len(bpy.context.scene.objects)}
