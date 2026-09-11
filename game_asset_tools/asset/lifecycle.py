"""Component-scoped build planning and guarded replacement of owned geometry."""

import json
import hashlib
import logging

import bpy

from game_asset_tools import __version__
from game_asset_tools.core.naming import semantic_name
from .context import BuildContext
from .metadata import encode, fingerprint
from .parameters import changed_components, validate_config
from .recipe import validate_components, validate_stage
from .scene import asset_objects, component_records, find_root, root_object

logger = logging.getLogger("game_asset_tools")


def _ordered(specs):
    result = []
    def visit(key):
        if key not in result:
            for dependency in specs[key].depends_on:
                visit(dependency)
            result.append(key)
    for key in specs:
        visit(key)
    return result


def _closure(specs, selected):
    result = set(selected)
    while True:
        more = {key for key, spec in specs.items() if set(spec.depends_on) & result}
        if more <= result:
            return result
        result.update(more)


def _guard(root, selected, *, replace_edited=False, stage_change=False):
    records = component_records(root)
    objects = asset_objects(root)
    replacing = {obj for obj in objects if obj.get("gat_component") in selected}
    errors = []
    for key in sorted(selected):
        status = records.get(key, {}).get("status", "editable")
        if status == "locked" or (status == "approved" and not stage_change):
            errors.append(f"Component {key} is {status}; explicitly mark editable first")
    for obj in replacing:
        if obj.get("gat_fingerprint") != fingerprint(obj) and not replace_edited:
            errors.append(f"Manual edits detected in {obj.name}; lock it or explicitly replace edited geometry")
        for child in obj.children:
            if child not in replacing:
                errors.append(f"{obj.name} has preserved child {child.name}; include its dependent component or reparent it first")
        if any(c not in {root, *root.children_recursive} for c in obj.users_collection):
            errors.append(f"{obj.name} is linked outside this asset; unlink that shared usage first")
    return errors


def plan_build(entry, config, *, rebuild=False, stage=None, components=None, replace_edited=False, style=None):
    """Return exact affected components and blockers before any scene mutation."""
    validate_config(entry, config)
    recipe = entry.load()
    specs = recipe.components(config)
    validate_components(specs)
    root = find_root(entry.id, required=False)
    if rebuild and root is None:
        raise ValueError(f"Cannot rebuild {entry.id!r}: asset is not built")
    if root and not rebuild:
        raise ValueError(f"Asset {entry.id!r} already exists; use rebuild")
    stage = validate_stage(stage or (root.get("gat_stage") if root else "BLOCKOUT"), entry.supported_stages)
    old_records = component_records(root) if root else {}
    recipe_digest = hashlib.sha256((entry.path / "asset.py").read_bytes()).hexdigest()
    stage_change = bool(root and stage != root.get("gat_stage"))
    old_config = json.loads(root["gat_config"]) if root else None
    all_keys = set(specs) | set(old_records)
    affected = (changed_components(recipe, old_config, config) | (set(specs) - set(old_records))) if root else set(specs)
    if root and (stage_change or root.get("gat_recipe_version") != entry.recipe_version
                 or root.get("gat_recipe_digest") != recipe_digest
                 or json.loads(root.get("gat_style", "{}")) != (style or {})):
        affected = all_keys
    if components:
        unknown = set(components) - all_keys
        if unknown:
            raise ValueError(f"Unknown components: {', '.join(sorted(unknown))}")
        selected = _closure(specs, components)
        if affected - selected:
            raise ValueError(f"Config also affects {', '.join(sorted(affected - selected))}; include these components")
    else:
        selected = affected
    errors = _guard(root, selected, replace_edited=replace_edited, stage_change=stage_change) if root else []
    if root and stage_change:
        from .recipe import STAGES
        if STAGES.index(stage) > STAGES.index(root["gat_stage"]) and root.get("gat_stage_status") != "approved":
            errors.append("Approve the current stage before advancing to refinement/detail/finalization")
    return {"asset": entry.id, "status": "blocked" if errors else "planned", "stage": stage,
            "stage_change": stage_change, "components": sorted(selected),
            "preserved": sorted(all_keys - selected), "errors": errors}


def _remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        for name in ("meshes", "curves", "cameras", "lights", "armatures"):
            container = getattr(bpy.data, name)
            if data.name in container and container[data.name] == data:
                container.remove(data)
                break


def build(entry, config, style, *, rebuild=False, stage=None, components=None,
          replace_edited=False, dry_run=False):
    """Stage affected geometry before replacing objects; preserve unrelated data."""
    plan = plan_build(entry, config, rebuild=rebuild, stage=stage, components=components,
                      replace_edited=replace_edited, style=style)
    if dry_run:
        return plan
    if plan["errors"]:
        logger.warning("Blocked %s: %s", entry.id, "; ".join(plan["errors"]))
        raise ValueError("; ".join(plan["errors"]))
    selected = set(plan["components"])
    if not selected:
        return {**plan, "status": "unchanged"}
    logger.info("Building %s at %s: %s", entry.id, plan["stage"], ", ".join(sorted(selected)))
    root = find_root(entry.id, required=False)
    new_root = root is None
    before_objects = set(bpy.data.objects)
    before_collections = set(bpy.data.collections)
    before_materials = set(bpy.data.materials)
    staging = None
    specs = entry.load().components(config)
    try:
        if root is None:
            root = bpy.data.collections.new(semantic_name("ASSET", entry.id))
            bpy.context.scene.collection.children.link(root)
            root["gat_asset_id"] = entry.id
            root["gat_role"] = "asset_root"
            pivot = bpy.data.objects.new(semantic_name(entry.id, "Root"), None)
            root.objects.link(pivot)
            pivot["gat_asset_id"] = entry.id
            pivot["gat_role"] = "asset_root"
            pivot["gat_generated"] = True
            pivot.scale = (style.get("unit_scale", 1.0),) * 3
        else:
            pivot = root_object(root)
        previous = asset_objects(root)
        lookup = {(o.get("gat_component"), o.get("gat_local_name")): o for o in previous
                  if o.get("gat_component") not in selected}
        staging = bpy.data.collections.new("GAT_Staging")
        root.children.link(staging)
        for key in _ordered(specs):
            if key in selected:
                ctx = BuildContext(entry, plan["stage"], style, pivot, staging, key, specs[key], lookup, "GAT_Stage_")
                entry.load().build_component(ctx, key, config)
        built = list(staging.objects)
        unregistered = (set(bpy.data.objects) - before_objects) - set(built) - {pivot}
        if unregistered:
            raise ValueError("Recipe created unregistered objects; register every generated object with ctx.add")
        replacing = {obj for obj in previous if obj.get("gat_component") in selected}
        finals = [obj["gat_final_name"] for obj in built]
        if len(finals) != len(set(finals)):
            raise ValueError("Semantic naming collision in recipe")
        for name in finals:
            existing = bpy.data.objects.get(name)
            if existing and existing not in replacing:
                raise ValueError(f"Object name {name!r} belongs to preserved content")
        # No scene deletions before the complete replacement has been constructed.
        for obj in replacing:
            _remove_object(obj)
        groups = {c.get("gat_group"): c for c in root.children
                  if c.get("gat_asset_id") == entry.id and c.get("gat_group")}
        for obj in built:
            group = specs[obj["gat_component"]].collection
            if group not in groups:
                collection = bpy.data.collections.new(semantic_name(entry.id, group))
                root.children.link(collection)
                collection["gat_asset_id"] = entry.id
                collection["gat_group"] = group
                groups[group] = collection
            groups[group].objects.link(obj)
            staging.objects.unlink(obj)
            obj.name = obj["gat_final_name"]
            if obj.data and obj.data.users == 1:
                obj.data.name = semantic_name(obj.name, obj.type.title())
            del obj["gat_final_name"]
            del obj["gat_staging"]
        bpy.data.collections.remove(staging)
        staging = None
        records = component_records(root)
        for key in selected:
            records.pop(key, None)
            if key in specs:
                records[key] = {"status": "editable", "stage": plan["stage"], "collection": specs[key].collection,
                                "depends_on": list(specs[key].depends_on),
                                "object_count": sum(o.get("gat_component") == key for o in built)}
        root["gat_components"] = encode(records)
        root["gat_config"] = encode(config)
        root["gat_style"] = encode(style)
        root["gat_recipe_version"] = entry.recipe_version
        root["gat_recipe_digest"] = hashlib.sha256((entry.path / "asset.py").read_bytes()).hexdigest()
        root["gat_version"] = __version__
        root["gat_stage"] = plan["stage"]
        root["gat_stage_status"] = "editable"
        bpy.context.view_layer.update()
        for obj in built:
            obj["gat_fingerprint"] = fingerprint(obj)
        return {**plan, "status": "rebuilt" if rebuild else "built", "objects": len(asset_objects(root))}
    except Exception:
        # Only data created by this build is cleaned up. Recipes are trusted Python;
        # in-place edits to pre-existing objects are outside the recipe contract.
        for obj in set(bpy.data.objects) - before_objects:
            _remove_object(obj)
        for collection in set(bpy.data.collections) - before_collections:
            bpy.data.collections.remove(collection)
        for material in set(bpy.data.materials) - before_materials:
            if material.users == 0:
                bpy.data.materials.remove(material)
        raise


def set_status(asset_id, state, components=None):
    if state not in ("editable", "approved", "locked"):
        raise ValueError("State must be editable, approved, or locked")
    root = find_root(asset_id)
    records = component_records(root)
    selected = set(components or records)
    if selected - set(records):
        raise ValueError("Unknown component in status request")
    for key in selected:
        records[key]["status"] = state
    for obj in asset_objects(root):
        if obj.get("gat_component") in selected:
            obj["gat_status"] = state
    root["gat_components"] = encode(records)
    if not components:
        root["gat_stage_status"] = state
    elif state != "approved":
        root["gat_stage_status"] = "editable"
    return {"asset": asset_id, "status": state, "components": sorted(selected)}


def delete_generated(asset_id, *, components=None, replace_edited=False, dry_run=False):
    root = find_root(asset_id)
    records = component_records(root)
    selected = set(components or records)
    if selected - set(records):
        raise ValueError("Unknown component in delete request")
    errors = _guard(root, selected, replace_edited=replace_edited)
    for key, record in records.items():
        if key not in selected and set(record.get("depends_on", [])) & selected:
            errors.append(f"Preserved component {key} depends on deleted components")
    plan = {"asset": asset_id, "status": "blocked" if errors else "planned", "components": sorted(selected), "errors": errors}
    if dry_run:
        return plan
    if errors:
        raise ValueError("; ".join(errors))
    for obj in asset_objects(root):
        if obj.get("gat_component") in selected:
            _remove_object(obj)
    for key in selected:
        records.pop(key)
    root["gat_components"] = encode(records)
    root["gat_stage_status"] = "editable"
    return {**plan, "status": "deleted"}
