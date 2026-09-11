"""Semantic modeling helpers. Blender modules load only when a helper is used."""

from importlib import import_module

from .naming import semantic_name

_EXPORTS = {
    "geometry": (
        "create_mesh", "add_box", "add_beveled_box", "add_cylinder", "add_cone",
        "add_sphere", "add_plane", "add_torus", "add_pipe", "create_panel",
        "create_support", "create_frame",
    ),
    "modifiers": (
        "apply_bevel", "mirror_object", "array_object", "boolean_cut",
        "boolean_union", "solidify", "apply_modifier", "weighted_normals",
    ),
    "materials": ("get_material", "project_material", "assign_material"),
    "collections": ("create_collection", "link_object"),
    "transforms": ("parent_object", "set_origin", "add_socket"),
}
__all__ = ["semantic_name", *(name for names in _EXPORTS.values() for name in names)]


def __getattr__(name: str):
    for module, names in _EXPORTS.items():
        if name in names:
            value = getattr(import_module(f"{__name__}.{module}"), name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
