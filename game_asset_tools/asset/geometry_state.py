"""Geometry evidence for material-only edits; deliberately excludes shader values."""

import hashlib

import bpy

from .metadata import _rna_values, encode


def _custom_properties(modifier):
    def serializable(value):
        if isinstance(value, bpy.types.ID):
            return {"name": value.name, "id": value.as_pointer()}
        if hasattr(value, "items"):
            return {key: serializable(item) for key, item in value.items()}
        if not isinstance(value, (str, int, float, bool, type(None))):
            return [serializable(item) for item in value]
        return value
    try:
        items = list(modifier.items())
    except TypeError:
        # Built-in modifiers do not all support ID properties; Geometry Nodes do.
        return {}
    return {key: serializable(value) for key, value in items}


def _mesh_state(mesh):
    # Attributes include UVs, colors, custom normals, weights and named data used
    # by geometry nodes. Material assignments are inspected separately.
    attributes = {}
    for attribute in mesh.attributes:
        values = []
        for item in attribute.data:
            value = next((getattr(item, name) for name in ("value", "vector", "color")
                          if hasattr(item, name)), None)
            values.append(list(value) if hasattr(value, "__len__") and not isinstance(value, str) else value)
        attributes[attribute.name] = [attribute.data_type, attribute.domain, values]
    return {"vertices": [(list(v.co), [(g.group, g.weight) for g in v.groups]) for v in mesh.vertices],
            "edges": [list(e.vertices) for e in mesh.edges],
            "faces": [(list(p.vertices), p.material_index, p.use_smooth) for p in mesh.polygons],
            "attributes": attributes,
            "shape_keys": ({key.name: [list(p.co) for p in key.data] for key in mesh.shape_keys.key_blocks}
                           if mesh.shape_keys else {})}


def geometry_state(objects):
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in objects:
        if obj.type != "MESH":
            raise ValueError(f"Material-only edits currently support mesh objects: {obj.name}")
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
        try:
            state = {"source": _mesh_state(obj.data), "evaluated": _mesh_state(mesh),
                     "object_id": obj.as_pointer(), "mesh_id": obj.data.as_pointer(),
                     "matrix": [list(row) for row in obj.matrix_world],
                     "basis": [list(row) for row in obj.matrix_basis],
                     "parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
                     "parent": obj.parent.as_pointer() if obj.parent else None,
                     "modifiers": [(_rna_values(m), _custom_properties(m)) for m in obj.modifiers],
                     "hidden": [obj.hide_render, obj.hide_viewport, obj.hide_get()]}
            result[obj.name] = hashlib.sha256(encode(state).encode()).hexdigest()
        finally:
            evaluated.to_mesh_clear()
    return result
