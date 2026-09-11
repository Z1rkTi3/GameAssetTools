"""Non-mutating checks for ownership, hierarchy, transforms and export readiness."""

import json
import math
import re

import bpy

from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.parameters import validate_config
from game_asset_tools.asset.recipe import validate_stage
from game_asset_tools.asset.scene import asset_objects, component_records, find_root, root_object
from game_asset_tools.inspection import statistics


def validate_asset(asset_id, entry=None):
    errors, warnings = [], []
    try:
        root = find_root(asset_id)
        pivot = root_object(root)
        records = component_records(root)
        objects = asset_objects(root)
    except ValueError as exc:
        return {"asset": asset_id, "status": "error", "errors": [str(exc)], "warnings": []}
    if not objects:
        errors.append("Asset contains no generated component objects")
    if pivot.parent is not None:
        errors.append("Asset root has an external parent; detach it while preserving world transform before export")
    if any(not math.isfinite(v) or v <= 0 for v in pivot.scale):
        errors.append("Asset root has zero, negative, or nonfinite scale")
    try:
        validate_stage(root.get("gat_stage", ""), entry.supported_stages if entry else ("BLOCKOUT", "REFINE", "DETAIL", "FINALIZE"))
        if entry:
            config = json.loads(root.get("gat_config", "{}"))
            validate_config(entry, config)
            if root.get("gat_recipe_version") != entry.recipe_version:
                warnings.append("Built recipe version differs from current recipe")
            expected = set(entry.load().components(config))
            if set(records) != expected:
                errors.append("Built component records do not match recipe/config")
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
    owned = set(objects) | {pivot}
    identities = set()
    geometries = {}
    for key, record in records.items():
        if record.get("object_count", 1) and not any(c.get("gat_group") == record["collection"] and c.get("gat_asset_id") == asset_id for c in root.children):
            errors.append(f"Missing required collection for {key}")
        if sum(o.get("gat_component") == key for o in objects) != record.get("object_count", 0):
            errors.append(f"Object count differs from generated component {key}")
    for obj in root.all_objects:
        if not obj.get("gat_generated"):
            warnings.append(f"Unmanaged content is preserved but excluded from GLB export: {obj.name}")
        if obj.get("gat_generated") and obj.get("gat_asset_id") != asset_id:
            errors.append(f"Missing or incorrect asset identifier: {obj.name}")
    for obj in objects:
        if re.fullmatch(r"(Cube|Cylinder|Sphere|Plane|Cone|Torus)(\.\d+)?", obj.name):
            errors.append(f"Default Blender name: {obj.name}")
        identity = (obj.get("gat_component"), obj.get("gat_local_name"))
        if identity in identities:
            errors.append(f"Duplicate semantic identity: {identity}")
        identities.add(identity)
        if identity[0] not in records:
            errors.append(f"Unknown component metadata: {obj.name}")
        if obj.parent not in owned:
            errors.append(f"Invalid or external parent: {obj.name}")
        if any(not math.isfinite(v) or v <= 0 for v in obj.scale):
            errors.append(f"Invalid zero, negative, or nonfinite scale: {obj.name}")
        elif any(abs(v-1) > 1e-5 for v in obj.scale):
            warnings.append(f"Unapplied scale: {obj.name}")
        if obj.hide_render or obj.hide_viewport or obj.hide_get():
            warnings.append(f"Hidden generated object: {obj.name}")
        if obj.type in {"MESH", "CURVE"} and not obj.get("gat_helper"):
            if not obj.material_slots or any(s.material is None for s in obj.material_slots):
                warnings.append(f"Missing material: {obj.name}")
        if obj.type == "MESH":
            if not obj.data.vertices or not obj.data.polygons:
                errors.append(f"Empty mesh: {obj.name}")
            if any(not math.isfinite(v) for vertex in obj.data.vertices for v in vertex.co):
                errors.append(f"Nonfinite geometry: {obj.name}")
            signature = (tuple(round(v, 5) for row in obj.matrix_world for v in row),
                         tuple(tuple(round(v, 5) for v in vertex.co) for vertex in obj.data.vertices),
                         tuple(tuple(face.vertices) for face in obj.data.polygons))
            if signature in geometries:
                warnings.append(f"Obvious duplicate geometry: {obj.name} and {geometries[signature]}")
            geometries[signature] = obj.name
        for modifier in obj.modifiers:
            if modifier.type == "BOOLEAN" and modifier.operand_type == "OBJECT" and modifier.object is None:
                errors.append(f"Boolean has no operand: {obj.name}/{modifier.name}")
        if obj.get("gat_fingerprint") != fingerprint(obj):
            warnings.append(f"Manual edits since generation: {obj.name}")
    stats = statistics(objects)
    return {"asset": asset_id, "stage": root.get("gat_stage"), "status": "error" if errors else "warning" if warnings else "pass",
            "errors": errors, "warnings": warnings, "statistics": stats}
