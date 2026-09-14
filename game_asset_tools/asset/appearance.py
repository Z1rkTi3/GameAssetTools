"""Validated, object-scoped material overrides stored with the asset configuration."""

from copy import deepcopy

from game_asset_tools.style import DEFAULT_STYLE, validate_style


def validate_material_changes(materials):
    if not isinstance(materials, dict) or not materials:
        raise ValueError("materials must map at least one role to material properties")
    for role, values in materials.items():
        if not isinstance(role, str) or not role or not isinstance(values, dict) or not values:
            raise ValueError("Each material role requires a nonempty property mapping")
    validate_style({**deepcopy(DEFAULT_STYLE), "materials": materials})
    return materials


def validate_appearance(appearance, components):
    if not isinstance(appearance, dict):
        raise ValueError("appearance must be a component/object/slot mapping")
    for component, objects in appearance.items():
        if component not in components or not isinstance(objects, dict):
            raise ValueError(f"Unknown or invalid appearance component {component!r}")
        for local_name, slots in objects.items():
            if not isinstance(local_name, str) or not local_name or not isinstance(slots, dict):
                raise ValueError("Appearance object keys must be stable local names")
            for slot, definition in slots.items():
                if (not isinstance(slot, str) or not slot.isdecimal() or str(int(slot)) != slot
                        or not isinstance(definition, dict) or set(definition) != {"role", "values"}):
                    raise ValueError("Appearance slots require a numeric key and role/values")
                if not isinstance(definition["role"], str) or not definition["role"]:
                    raise ValueError("Appearance role must be a nonempty string")
                validate_material_changes({definition["role"]: definition["values"]})
    return appearance
