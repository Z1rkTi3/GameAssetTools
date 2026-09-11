"""Explicit context passed to a single component builder."""

from game_asset_tools.core.naming import semantic_name
from .metadata import tag


class BuildContext:
    def __init__(self, entry, stage, style, root_object, collection, component, spec, lookup, prefix=""):
        self.entry = entry
        self.asset_id = entry.id
        self.stage = stage
        self.style = style
        self.root_object = root_object
        self.collection = collection
        self.component = component
        self.spec = spec
        self._lookup = lookup
        self._prefix = prefix

    def name(self, local_name: str) -> str:
        return self._prefix + semantic_name(self.asset_id, self.component, local_name)

    def add(self, obj, local_name: str, *, parent=None, helper=None):
        """Register a recipe object; all recipe-owned objects must use this path."""
        import bpy
        from game_asset_tools.core.transforms import parent_object
        key = (self.component, local_name)
        if key in self._lookup and self._lookup[key].get("gat_staging"):
            raise ValueError(f"Duplicate object identity: {key}")
        obj.name = self.name(local_name)
        obj["gat_local_name"] = local_name
        obj["gat_final_name"] = semantic_name(self.asset_id, self.component, local_name)
        obj["gat_staging"] = True
        tag(obj, self.asset_id, self.component, self.stage, self.entry.recipe_version,
            helper=self.spec.helper if helper is None else helper)
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        self.collection.objects.link(obj)
        bpy.context.view_layer.update()
        # Recipe coordinates are asset-local, even when its root was moved manually.
        obj.parent = self.root_object
        bpy.context.view_layer.update()
        if parent is not None:
            parent_object(obj, parent)
        self._lookup[key] = obj
        return obj

    def get(self, component: str, local_name: str):
        """Resolve stable component identity, independent of generated Blender names."""
        if component != self.component and component not in self.spec.depends_on:
            raise ValueError(f"Declare {component!r} in {self.component!r} dependencies before referencing it")
        try:
            return self._lookup[(component, local_name)]
        except KeyError as exc:
            raise ValueError(f"Object {component}/{local_name} is unavailable; declare its dependency") from exc
