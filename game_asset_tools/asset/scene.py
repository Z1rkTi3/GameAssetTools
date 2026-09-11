"""Read asset ownership without relying on user-editable Blender names."""

import json


def find_root(asset_id: str, *, required=True):
    import bpy
    matches = [c for c in bpy.context.scene.collection.children_recursive
               if c.get("gat_asset_id") == asset_id and c.get("gat_role") == "asset_root"]
    if len(matches) > 1:
        raise ValueError(f"Multiple asset roots for {asset_id!r}; resolve duplicate identity")
    if not matches and required:
        raise ValueError(f"Asset {asset_id!r} is not built in this scene")
    return matches[0] if matches else None


def asset_objects(root, component=None, *, helpers=True):
    return [obj for obj in root.all_objects
            if obj.get("gat_asset_id") == root["gat_asset_id"]
            and obj.get("gat_generated") and obj.get("gat_role") != "asset_root"
            and (component is None or obj.get("gat_component") == component)
            and (helpers or not obj.get("gat_helper"))]


def component_records(root) -> dict:
    return json.loads(root.get("gat_components", "{}"))


def root_object(root):
    values = [obj for obj in root.objects if obj.get("gat_role") == "asset_root"
              and obj.get("gat_asset_id") == root["gat_asset_id"]]
    if len(values) != 1:
        raise ValueError("Asset must contain exactly one owned root object")
    return values[0]
