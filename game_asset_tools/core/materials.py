"""Reusable simple Principled materials without editing existing shared shaders."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence

import bpy

from .naming import semantic_name


def _color(value: Sequence[float], name: str) -> list[float]:
    if len(value) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in value):
        raise ValueError(f"{name} must contain four finite RGBA values in [0, 1]")
    return [float(v) for v in value]


def _fraction(value: float, name: str) -> float:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and in [0, 1]")
    return float(value)


def _same_values(a, b):
    if isinstance(b, list):
        return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))
    return abs(a - b) < 1e-6


_INPUTS = {"base_color": "Base Color", "metallic": "Metallic", "roughness": "Roughness",
           "alpha": "Alpha", "transmission": "Transmission Weight", "emission": "Emission Color",
           "emission_strength": "Emission Strength"}


def _matches(material, definition):
    """A cached tag alone must not make hand-edited material data reusable."""
    if not material.use_nodes or material.node_tree is None:
        return False
    nodes = material.node_tree.nodes
    if len(nodes) != 2 or len(material.node_tree.links) != 1:
        return False
    principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None)
    if principled is None or output is None or not output.is_active_output:
        return False
    link = material.node_tree.links[0]
    if link.from_node != principled or link.to_node != output or link.to_socket.name != "Surface":
        return False
    if not _same_values(material.diffuse_color, definition["base_color"]):
        return False
    return all(_same_values(principled.inputs[label].default_value, definition[key])
               for key, label in _INPUTS.items())


def get_material(name: str, base_color: Sequence[float] = (0.5, 0.5, 0.5, 1),
                 metallic: float = 0, roughness: float = 0.5, alpha: float | None = None,
                 transmission: float = 0, emission: Sequence[float] = (0, 0, 0, 1),
                 emission_strength: float = 0) -> bpy.types.Material:
    """Return an unchanged owned definition, or create a deterministic variation.

    Values use Blender's linear RGBA convention. Alpha defaults to base-color
    alpha. Unowned or manually changed materials are never modified or reused.
    """
    base_color = _color(base_color, "base_color")
    definition = {"base_color": base_color, "metallic": _fraction(metallic, "metallic"),
                  "roughness": _fraction(roughness, "roughness"),
                  "alpha": _fraction(base_color[3] if alpha is None else alpha, "alpha"),
                  "transmission": _fraction(transmission, "transmission"),
                  "emission": _color(emission, "emission")}
    if not math.isfinite(emission_strength) or emission_strength < 0:
        raise ValueError("emission_strength must be nonnegative and finite")
    definition["emission_strength"] = float(emission_strength)
    safe_name = semantic_name(name)
    if not safe_name.startswith("MAT_"):
        safe_name = semantic_name("MAT", safe_name)
    signature = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    for material in bpy.data.materials:
        if (material.get("gat_material_name") == safe_name
                and material.get("gat_material_signature") == signature
                and material.library is None and _matches(material, definition)):
            return material
    if bpy.data.materials.get(safe_name) is not None:
        safe_name = semantic_name(safe_name, signature[:10])
    material = bpy.data.materials.new(safe_name)
    material.use_nodes = True
    material.diffuse_color = base_color
    material.metallic = metallic
    material.roughness = roughness
    nodes = material.node_tree.nodes
    nodes.clear()
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    for key, label in _INPUTS.items():
        principled.inputs[label].default_value = definition[key]
    material.node_tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    if definition["alpha"] < 1:
        material.surface_render_method = "DITHERED"
    material["gat_material_name"] = semantic_name(name) if semantic_name(name).startswith("MAT_") else semantic_name("MAT", name)
    material["gat_material_signature"] = signature
    return material


def project_material(name: str, style: Mapping | None = None) -> bpy.types.Material:
    """Resolve a project palette role, allowing per-style material overrides."""
    from game_asset_tools.style import DEFAULT_MATERIALS

    role = name[4:] if name.startswith("MAT_") else name
    defaults = DEFAULT_MATERIALS.get(role)
    overrides = (style or {}).get("materials", {}).get(role)
    if defaults is None and overrides is None:
        raise ValueError(f"Unknown project material {name!r}")
    material = get_material(role, **{**(defaults or {}), **(overrides or {})})
    material["gat_material_role"] = role
    return material


def assign_material(obj: bpy.types.Object, material: bpy.types.Material,
                    *, slot: int = 0) -> bpy.types.Object:
    """Assign a material slot without changing shared mesh/curve users.

    A copied datablock isolates slot changes. Existing face material indices
    remain unchanged; new geometry normally uses the default slot zero.
    """
    if obj.data is None or not hasattr(obj.data, "materials"):
        raise ValueError(f"Object {obj.name!r} does not support materials")
    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
        raise ValueError("slot must be a nonnegative integer")
    if not isinstance(material, bpy.types.Material):
        raise ValueError("material must be a Blender Material")
    if obj.library is not None or obj.data.library is not None:
        raise ValueError("Linked library geometry must be made local before editing")
    if slot > len(obj.data.materials):
        raise ValueError("slot cannot leave gaps in the material slots")
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    if slot == len(obj.data.materials):
        obj.data.materials.append(material)
    else:
        obj.data.materials[slot] = material
    return obj
