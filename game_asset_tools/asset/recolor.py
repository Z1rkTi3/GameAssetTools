"""Transactional recoloring of owned slots without invoking recipe geometry code."""

from copy import deepcopy
import json

import bpy

from .appearance import validate_material_changes
from .geometry_state import geometry_state
from .metadata import encode, fingerprint
from .scene import asset_objects, component_records, find_root
from game_asset_tools.core.materials import _INPUTS
from game_asset_tools.inspection.materials import material_role, material_usage


def _shader(material):
    nodes = [n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"] if material and material.use_nodes else []
    if len(nodes) != 1:
        raise ValueError("Recolor requires a material with exactly one Principled BSDF")
    if material.library or material.animation_data or material.node_tree.animation_data:
        raise ValueError("Linked or animated shaders must be made local/static before recoloring")
    return nodes[0]


def _properties(material, values):
    shader = _shader(material)
    result = {}
    for key in values:
        socket = shader.inputs.get(_INPUTS[key])
        if socket is None or socket.is_linked:
            raise ValueError(f"Material {material.name}: {key} is unavailable or driven by a node link")
        value = socket.default_value
        result[key] = list(value) if hasattr(value, "__len__") else value
    return result


def _equal(a, b):
    if isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(abs(x-y) < 1e-7 for x,y in zip(a,b))
    return abs(a-b) < 1e-7


def _copy_material(material, role, values):
    # Copy the shader to preserve every unrelated input, node and render setting.
    result = material.copy()
    result.name = f"{material.name}_appearance"
    result["gat_material_role"] = role
    if "gat_material_signature" in result:
        del result["gat_material_signature"]
    shader = _shader(result)
    for key, value in values.items():
        shader.inputs[_INPUTS[key]].default_value = value
        if key == "base_color":
            result.diffuse_color = value
        elif key in {"roughness", "metallic"}:
            setattr(result, key, value)
    return result


def apply_appearance(objects, appearance, style):
    """Apply saved overrides only to newly staged recipe objects before acceptance."""
    for obj in objects:
        definitions = appearance.get(obj.get("gat_component"), {}).get(obj.get("gat_local_name"), {})
        for index, definition in definitions.items():
            slot = int(index)
            if slot >= len(obj.material_slots) or material_role(obj.material_slots[slot].material, style) != definition["role"]:
                raise ValueError(f"Saved appearance no longer matches {obj.name} slot {slot}; update the config")
            material = obj.material_slots[slot].material
            _properties(material, definition["values"])
            new_material = _copy_material(material, definition["role"], definition["values"])
            obj.material_slots[slot].link = "OBJECT"
            obj.material_slots[slot].material = new_material


def recolor(asset_id, materials, *, components=None, objects=None, replace_edited=False, dry_run=False):
    validate_material_changes(materials)
    root = find_root(asset_id)
    owned = asset_objects(root)
    records = component_records(root)
    style = json.loads(root["gat_style"])
    if components and set(components) - set(records):
        raise ValueError("Unknown recolor component")
    if objects and set(objects) - {o.name for o in owned}:
        raise ValueError("Recolor object selectors must be exact names of owned asset objects")
    selected = [o for o in owned if (not components or o.get("gat_component") in components)
                and (not objects or o.name in objects)]
    errors, warnings, changes, targets = [], [], [], []
    used_roles = set()
    usage = {role: group for role, group in material_usage(root, selected).items() if role in materials}
    for role in materials:
        warnings.extend(usage.get(role, {}).get("warnings", []))
    for obj in selected:
        for index, slot in enumerate(obj.material_slots):
            role = material_role(slot.material, style)
            if role not in materials:
                continue
            used_roles.add(role)
            values = materials[role]
            try:
                before = _properties(slot.material, values)
            except ValueError as exc:
                errors.append(f"{obj.name}: {exc}")
                continue
            if all(_equal(before[key], value) for key,value in values.items()):
                continue
            if obj.type != "MESH" or obj.library or obj.data.library:
                errors.append(f"{obj.name}: requires local mesh geometry")
            if obj.mode != "OBJECT":
                errors.append(f"{obj.name}: switch to Object Mode before recoloring")
            state = records.get(obj.get("gat_component"), {}).get("status", "editable")
            if state in {"locked", "approved"} or obj.get("gat_status") in {"locked", "approved"}:
                errors.append(f"Component {obj.get('gat_component')} is {state}; explicitly mark editable first")
            if obj.get("gat_fingerprint") != fingerprint(obj) and not replace_edited:
                errors.append(f"Manual edits detected in {obj.name}; explicitly allow edited content first")
            if any(c not in {root, *root.children_recursive} for c in obj.users_collection):
                errors.append(f"{obj.name} is linked outside this asset")
            changes.append({"role": role, "component": obj.get("gat_component"), "object": obj.name,
                            "local_name": obj.get("gat_local_name"), "slot": index,
                            "material": slot.material.name, "before": before, "after": deepcopy(values)})
            targets.append((obj,index,role,values))
    errors.extend(f"No selected material slots use role {role!r}" for role in set(materials) - used_roles)
    changed_objects = list(dict.fromkeys(o for o,_,_,_ in targets))
    plan = {"asset": asset_id, "status": "blocked" if errors else "planned", "changes": changes,
            "components": sorted({o.get("gat_component") for o in changed_objects}),
            "objects": [o.name for o in changed_objects], "errors": sorted(set(errors)),
            "warnings": sorted(set(warnings)), "material_roles": usage}
    if dry_run:
        return plan
    if errors:
        raise ValueError("; ".join(plan["errors"]))
    if not targets:
        return {**plan, "status": "unchanged", "geometry_unchanged": True}
    before_geometry = geometry_state(changed_objects)
    original_config = root["gat_config"]
    original_fingerprints = {obj: obj.get("gat_fingerprint") for obj in changed_objects}
    originals = [(obj,index,obj.material_slots[index].link,obj.material_slots[index].material)
                 for obj,index,_,_ in targets]
    created = []
    try:
        config = json.loads(original_config)
        appearance = config.setdefault("appearance", {})
        for obj,index,role,values in targets:
            material = _copy_material(obj.material_slots[index].material, role, values)
            created.append(material)
            # Object-linked slots retain both the original mesh datablock and all
            # shared users, including users outside the generated asset.
            obj.material_slots[index].link = "OBJECT"
            obj.material_slots[index].material = material
            slots = appearance.setdefault(obj["gat_component"], {}).setdefault(obj["gat_local_name"], {})
            previous = slots.get(str(index), {})
            slots[str(index)] = {"role": role, "values": {**previous.get("values", {}), **deepcopy(values)}}
        after_geometry = geometry_state(changed_objects)
        if before_geometry != after_geometry:
            raise ValueError("Material edit changed source/evaluated geometry; operation rolled back")
        root["gat_config"] = encode(config)
        for obj in changed_objects:
            obj["gat_fingerprint"] = fingerprint(obj)
        return {**plan, "status": "recolored", "geometry_unchanged": True,
                "geometry_before": before_geometry, "geometry_after": after_geometry}
    except Exception:
        for obj,index,link,material in originals:
            obj.material_slots[index].link = link
            obj.material_slots[index].material = material
        root["gat_config"] = original_config
        for obj, value in original_fingerprints.items():
            obj["gat_fingerprint"] = value
        for material in created:
            if material.users == 0:
                bpy.data.materials.remove(material)
        raise
