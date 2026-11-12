"""Compact ownership metadata and detection of manual edits."""

import hashlib
import json
from copy import deepcopy


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


def _fingerprint_record(obj):
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
    return record


def fingerprint(obj) -> str:
    """Return the current complete edit signature without legacy normalization."""
    return hashlib.sha256(encode(_fingerprint_record(obj)).encode()).hexdigest()


def _legacy_principled_record(obj, record):
    """Проекция только двух новых default-входов Blender 5.3 в схему 5.2.

    Не переписывает сохранённую подпись и не принимает изменения параметров.
    Связанный или нестандартный новый вход требует обычной полной подписи.
    """
    defaults = {"Transmission Dispersion Scale": 0.0,
                "Transmission Dispersion Abbe Number": 20.0}
    result = deepcopy(record)
    projected = False
    for slot_index, slot in enumerate(obj.material_slots):
        material = slot.material
        if not material or not material.use_nodes:
            continue
        for node_index, node in enumerate(material.node_tree.nodes):
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            sockets = [node.inputs.get(name) for name in defaults]
            if not any(socket is not None for socket in sockets):
                continue
            if any(socket is None for socket in sockets):
                return None
            values = result["materials"][slot_index]["nodes"][node_index]["values"]
            for (name, default), socket in zip(defaults.items(), sockets):
                value = values.get(name)
                if socket.is_linked or type(value) not in (int, float) or value != default:
                    return None
                if type(socket.default_value) not in (int, float) or socket.default_value != default:
                    return None
            for name in defaults:
                del values[name]
            projected = True
    return result if projected else None


def fingerprint_matches(obj, expected=None) -> bool:
    """Сверяет полный hash; старый hash допускается лишь при точной default-миграции.

    fingerprint() остаётся независимым полным hash для новых baseline и снимков.
    Остальные поля старого record, включая links/mesh/modifiers, сравниваются целиком.
    """
    expected = obj.get("gat_fingerprint") if expected is None else expected
    if not isinstance(expected, str):
        return False
    record = _fingerprint_record(obj)
    if hashlib.sha256(encode(record).encode()).hexdigest() == expected:
        return True
    legacy = _legacy_principled_record(obj, record)
    return legacy is not None and hashlib.sha256(encode(legacy).encode()).hexdigest() == expected


def tag(obj, asset_id: str, component: str, stage: str, version: int, *, helper=False):
    obj["gat_asset_id"] = asset_id
    obj["gat_component"] = component
    obj["gat_generated"] = True
    obj["gat_stage"] = stage
    obj["gat_recipe_version"] = version
    obj["gat_status"] = "editable"
    obj["gat_helper"] = helper
