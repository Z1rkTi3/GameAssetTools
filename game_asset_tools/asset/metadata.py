"""Compact ownership metadata and detection of manual edits."""

import hashlib
import json


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _rna_values(value):
    result = {}
    for prop in value.bl_rna.properties:
        key = prop.identifier
        if key in {"rna_type", "name"} or prop.is_readonly:
            continue
        item = getattr(value, key, None)
        if isinstance(item, (str, bool, int, float)):
            result[key] = item
        elif prop.type == "POINTER":
            result[key] = getattr(item, "name", None)
        elif getattr(prop, "is_array", False):
            result[key] = list(item)
    return result


def fingerprint(obj) -> str:
    """Detect mesh, transform, hierarchy, modifier, and material edits.

    This is an edit guard, not a hash of every possible Blender animation system.
    Recipes with animation/constraints should mark those components locked.
    """
    record = {
        "matrix": [list(row) for row in obj.matrix_basis],
        "parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
        "parent": obj.parent.name if obj.parent else None,
        "hidden": [obj.hide_render, obj.hide_viewport],
        "modifiers": [_rna_values(m) for m in obj.modifiers],
        "materials": [],
    }
    if obj.type == "MESH":
        record["vertices"] = [list(v.co) for v in obj.data.vertices]
        record["edges"] = [list(e.vertices) for e in obj.data.edges]
        record["faces"] = [(list(p.vertices), p.material_index, p.use_smooth) for p in obj.data.polygons]
        record["uvs"] = [[list(uv.uv) for uv in layer.data] for layer in obj.data.uv_layers]
    elif obj.type == "CURVE":
        record["curve"] = [_rna_values(obj.data)] + [
            {"type": s.type, "points": [list(p.co) for p in s.points],
             "bezier": [(list(p.co), list(p.handle_left), list(p.handle_right)) for p in s.bezier_points]}
            for s in obj.data.splines]
    for slot in obj.material_slots:
        mat = slot.material
        data = {"name": mat.name if mat else None}
        if mat and mat.use_nodes:
            data["nodes"] = [{"type": n.bl_idname, "values": {
                s.identifier: (list(s.default_value) if hasattr(s.default_value, "__len__") and not isinstance(s.default_value, str) else s.default_value)
                for s in n.inputs if hasattr(s, "default_value") and not hasattr(s.default_value, "bl_rna")}}
                for n in mat.node_tree.nodes]
            data["links"] = [(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in mat.node_tree.links]
        record["materials"].append(data)
    return hashlib.sha256(encode(record).encode()).hexdigest()


def tag(obj, asset_id: str, component: str, stage: str, version: int, *, helper=False):
    obj["gat_asset_id"] = asset_id
    obj["gat_component"] = component
    obj["gat_generated"] = True
    obj["gat_stage"] = stage
    obj["gat_recipe_version"] = version
    obj["gat_status"] = "editable"
    obj["gat_helper"] = helper
