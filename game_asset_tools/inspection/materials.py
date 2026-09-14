"""Read material roles, color samples, and shared users without changing a scene."""

from __future__ import annotations

import json

import bpy

from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.scene import asset_objects, component_records
from game_asset_tools.style import DEFAULT_MATERIALS


def material_role(material, style=None):
    """Resolve explicit roles or known legacy palette tags, never display names."""
    if material is None:
        return None
    explicit = material.get("gat_material_role")
    if isinstance(explicit, str) and explicit:
        return explicit
    legacy = material.get("gat_material_name")
    if not isinstance(legacy, str):
        return None
    role = legacy[4:] if legacy.startswith("MAT_") else legacy
    known = set(DEFAULT_MATERIALS) | set((style or {}).get("materials", {}))
    return role if role in known else None


def _color_sample(material):
    color = list(material.diffuse_color)
    source = "diffuse_color"
    approximate = False
    alpha = color[3]
    if material.use_nodes and material.node_tree:
        nodes = material.node_tree.nodes
        principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if principled is not None:
            socket = principled.inputs.get("Base Color")
            color = list(socket.default_value)
            alpha = float(principled.inputs["Alpha"].default_value)
            source = "principled_base_color"
            approximate = socket.is_linked or len(nodes) != 2 or len(material.node_tree.links) != 1
        else:
            approximate = True
    def srgb(value):
        value = max(0.0, min(1.0, value))
        return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    rgb = [srgb(value) for value in color[:3]]
    return {"linear_rgba": color, "srgb_rgba": [*rgb, color[3]],
            "srgb_hex": "#" + "".join(f"{round(value * 255):02X}" for value in rgb),
            "alpha": alpha, "source": source, "approximate": approximate}


def material_usage(root, objects=None):
    """Map role → components → slots, with color and preservation warnings.

    Unknown roles are grouped under ``__unassigned__``. ``other_users`` lists
    object slots outside the selected set sharing these exact material datablocks.
    Color samples describe base color, not lighting or a rendered appearance.
    """
    selected = list(asset_objects(root) if objects is None else objects)
    selected_set = set(selected)
    style = json.loads(root.get("gat_style", "{}"))
    roots = [collection for collection in bpy.data.collections
             if collection.get("gat_role") == "asset_root"]
    state_cache = {}

    def state(obj):
        if obj in state_cache:
            return state_cache[obj]
        owner = next((collection for collection in roots
                      if collection.get("gat_asset_id") == obj.get("gat_asset_id")
                      and obj.name in collection.all_objects), None)
        component = obj.get("gat_component")
        owned = bool(owner and obj.get("gat_generated") and component)
        status = component_records(owner).get(component, {}).get("status", "editable") if owned else "unmanaged"
        object_status = obj.get("gat_status", "editable") if owned else "unmanaged"
        warnings = []
        if not owned:
            warnings.append("Unmanaged object; preserve its material assignment")
        if status in {"approved", "locked"} or object_status in {"approved", "locked"}:
            warnings.append("Component or object is approved/locked")
        manual = None
        expected = obj.get("gat_fingerprint")
        if owned and expected:
            try:
                manual = expected != fingerprint(obj)
            except (TypeError, ValueError, ReferenceError):
                warnings.append("Could not verify the saved edit fingerprint")
            if manual:
                warnings.append("Manual edits detected")
        elif owned:
            warnings.append("No saved edit fingerprint; manual edits cannot be verified")
        linked = obj.library is not None or (obj.data is not None and obj.data.library is not None)
        if linked:
            warnings.append("Linked library object or geometry")
        outside = bool(owned and any(collection not in {owner, *owner.children_recursive}
                                     for collection in obj.users_collection))
        if outside:
            warnings.append("Object is linked to a collection outside its asset")
        result = {"asset": obj.get("gat_asset_id"), "component": component,
                  "status": status, "object_status": object_status,
                  "manual_edited": manual,
                  "protected": bool(warnings), "warnings": warnings}
        state_cache[obj] = result
        return result

    def detail(obj, index, slot):
        material = slot.material
        result = {**state(obj), "object": obj.name, "local_name": obj.get("gat_local_name"),
                  "slot": index, "link": slot.link, "material": material.name,
                  "role": material_role(material, style), "color": _color_sample(material),
                  "material_users": material.users,
                  "shared_data_users": obj.data.users if obj.data is not None else 0}
        result["warnings"] = list(result["warnings"])
        if result["role"] is None:
            result["warnings"].append("No recorded palette role; display names are not role identifiers")
        if result["color"]["approximate"]:
            result["warnings"].append("Color sample is approximate for this shader")
        if material.library is not None:
            result["warnings"].append("Linked library material")
        return result

    result = {}
    role_materials = {}
    for obj in sorted(selected, key=lambda value: value.name):
        for index, slot in enumerate(obj.material_slots):
            if slot.material is None:
                continue
            row = detail(obj, index, slot)
            role = row["role"] or "__unassigned__"
            group = result.setdefault(role, {"components": {}, "materials": [],
                                            "shared": False, "other_users": [], "warnings": []})
            component = row["component"] or "__unmanaged__"
            group["components"].setdefault(component, []).append(row)
            role_materials.setdefault(role, set()).add(slot.material)
    for role, group in result.items():
        materials = role_materials[role]
        group["materials"] = sorted(material.name for material in materials)
        for obj in sorted(bpy.data.objects, key=lambda value: value.name):
            if obj in selected_set:
                continue
            for index, slot in enumerate(obj.material_slots):
                if slot.material in materials:
                    group["other_users"].append(detail(obj, index, slot))
        rows = [row for slots in group["components"].values() for row in slots]
        group["shared"] = len(rows) > 1 or bool(group["other_users"])
        if len(group["components"]) > 1:
            group["warnings"].append("Role is used by multiple selected components")
        if group["other_users"]:
            group["warnings"].append("Material datablocks are also used outside the selection; preserve those users")
        if any(row["protected"] for row in group["other_users"]):
            group["warnings"].append("Shared material has protected or unmanaged users")
    return dict(sorted(result.items()))


def write_material_swatches(usage, path, *, overwrite=False):
    """A portable visual companion to inspect's numerical linear RGBA map."""
    from html import escape
    from game_asset_tools.export.paths import prepare_path
    rows = []
    for role, group in usage.items():
        for component, slots in group["components"].items():
            for slot in slots:
                rows.append((role, component, slot))
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="{60+len(rows)*74}">',
             '<rect width="100%" height="100%" fill="#202630"/>',
             '<g fill="#f3f4f6" font-family="sans-serif" font-size="14">',
             '<text x="18" y="32">Material roles — sRGB samples / linear RGBA values (base color, without lighting)</text>']
    for index, (role, component, slot) in enumerate(rows):
        color, y = slot["color"], 60 + index * 74
        title = f"{role} → {component} → {slot['object']} / slot {slot['slot']}"
        rgba = ", ".join(f"{v:.5g}" for v in color["linear_rgba"])
        detail = f"linear RGBA ({rgba}) · {color['srgb_hex']} · alpha {color['alpha']:.3g}"
        if color["approximate"]:
            detail += " · approximate shader sample"
        if slot["protected"]:
            detail += " · PROTECTED"
        lines += [f'<rect x="18" y="{y}" width="76" height="52" fill="{color["srgb_hex"]}"/>',
                  f'<text x="110" y="{y+18}">{escape(title)}</text>',
                  f'<text x="110" y="{y+42}" fill="#bdc7d6">{escape(detail)}</text>']
    lines += ["</g>", "</svg>"]
    path = prepare_path(path, overwrite=overwrite)
    with path.open("w" if overwrite else "x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return str(path)
