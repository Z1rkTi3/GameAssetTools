"""Small shared command surface for Blender UI, scripts, and headless requests."""

import json
import logging
from pathlib import Path

from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.parameters import effective_saved_config, load_config, merge_values, read_json, set_value, validate_config
from game_asset_tools.style import load_style


def execute(request: dict) -> dict:
    """Execute in the current Blender scene. Errors are actionable exceptions.

    This API never opens a .blend or starts a subprocess. The headless runner owns
    those process-level concerns; the add-on operates on the current document.
    """
    project = Path(request["project"]).resolve()
    action, asset_id = request["action"], request["asset"]
    logging.getLogger("game_asset_tools").debug("Dispatch %s for %s", action, asset_id)
    entry = Registry(project).get(asset_id)
    if action == "sprite-settings":
        from game_asset_tools.sprites.settings import FIELDS, read_settings, write_settings
        if "sprite_updates" in request:
            result = write_settings(project, asset_id, request["sprite_updates"],
                                    expected_revision=request.get("expected_revision"),
                                    dry_run=bool(request.get("dry_run")))
        else:
            result = read_settings(project, asset_id)
        if request.get("schema"):
            result["fields"] = list(FIELDS)
        return result
    if action == "sprites":
        forbidden = ("config", "overrides", "stage", "components", "views", "debug",
                     "reframe", "replace_edited", "state", "materials", "objects")
        if (any(request.get(key) for key in forbidden) or request.get("resolution") is not None
                or "sprite_updates" in request):
            raise ValueError("sprites uses the whole asset and its saved profile; edit sprite-settings first")
        if type(request.get("sprite_preview", False)) is not bool:
            raise ValueError("sprite_preview must be a boolean")
    from game_asset_tools.asset.scene import find_root
    from game_asset_tools.asset.lifecycle import build, set_status, delete_generated
    output = Path(request.get("output") or project / "output").resolve()
    components = request.get("components") or None
    overwrite = bool(request.get("overwrite"))
    if action == "sprites":
        from game_asset_tools.sprites.settings import read_settings
        from game_asset_tools.sprites.render import render_sprites
        profile = read_settings(project, asset_id)
        result = render_sprites(asset_id, output, profile["settings"], overwrite=overwrite,
                                preview=bool(request.get("sprite_preview")),
                                dry_run=bool(request.get("dry_run")))
        result["profile"] = {key: profile[key] for key in ("path", "revision")}
        return result
    if action == "recolor":
        from game_asset_tools.asset.recolor import recolor
        if request.get("config") or request.get("overrides") or request.get("stage"):
            raise ValueError("recolor accepts material changes only; use rebuild for geometry/config changes")
        return recolor(asset_id, request.get("materials"), components=components,
                       objects=request.get("objects"), replace_edited=bool(request.get("replace_edited")),
                       dry_run=bool(request.get("dry_run")))
    if request.get("dry_run") and action in {"save", "export", "preview"}:
        find_root(asset_id)
        from game_asset_tools.export.paths import artifact_path
        kind, suffix = {"save": ("blend", "_view.blend" if request.get("view_copy") else ".blend"), "export": ("glb", ".glb"),
                        "preview": ("previews", "")}[action]
        return {"asset": asset_id, "status": "planned", "action": action,
                "output": str(artifact_path(output, kind, asset_id, suffix)), "overwrite": overwrite}
    if action in ("build", "rebuild"):
        root = find_root(asset_id, required=False)
        if root and action == "rebuild":
            config = effective_saved_config(entry, json.loads(root["gat_config"]))
            if request.get("config"):
                config = merge_values(config, read_json(Path(request["config"])))
            for path,value in (request.get("overrides") or {}).items():
                set_value(config["parameters"], path, value)
            validate_config(entry, config)
        else:
            config = load_config(entry, request.get("config"), request.get("overrides"))
        style = load_style(project, config.get("style"))
        return build(entry, config, style, rebuild=action == "rebuild", stage=request.get("stage"),
                     components=components, replace_edited=bool(request.get("replace_edited")),
                     dry_run=bool(request.get("dry_run")))
    if action == "inspect":
        from game_asset_tools.inspection import inspect_asset
        if components and len(components) > 1:
            result = {"asset": asset_id, "components": [inspect_asset(asset_id,c) for c in components]}
        else:
            result = inspect_asset(asset_id, components[0] if components else None)
        if request.get("swatches") and not request.get("dry_run"):
            from game_asset_tools.inspection.materials import material_usage, write_material_swatches
            from game_asset_tools.asset.scene import asset_objects
            from game_asset_tools.export.paths import artifact_path
            root = find_root(asset_id)
            selected = [o for o in asset_objects(root) if not components or o.get("gat_component") in components]
            result["swatches"] = write_material_swatches(material_usage(root, selected),
                artifact_path(output, "reports", asset_id, "_materials.svg"), overwrite=overwrite)
        return result
    if action == "preview":
        from game_asset_tools.preview import render_preview
        root = find_root(asset_id)
        style = json.loads(root.get("gat_style", "{}"))
        results = [render_preview(asset_id, output, component=component, views=request.get("views"),
                                  resolution=request.get("resolution") or style.get("preview", {}).get("resolution",512),
                                  overwrite=overwrite, reframe=bool(request.get("reframe")), debug=bool(request.get("debug")))
                   for component in (components or [None])]
        return results[0] if len(results) == 1 else {"asset": asset_id, "previews": results}
    if action == "validate":
        from game_asset_tools.validation import validate_asset
        from game_asset_tools.export.paths import write_validation_report
        report = validate_asset(asset_id, entry)
        if request.get("dry_run"):
            return report
        return write_validation_report(asset_id, output, report,
                                       mode=request.get("report_mode") or "file", overwrite=overwrite)
    if action == "save":
        from game_asset_tools.export import save_asset
        return save_asset(asset_id,output,overwrite=overwrite, view_copy=bool(request.get("view_copy")),
                          view=request.get("save_view") or "perspective")
    if action == "export":
        from game_asset_tools.export import export_asset
        return export_asset(asset_id,output,entry=entry,overwrite=overwrite)
    if action == "status":
        if request.get("dry_run"):
            return {"asset":asset_id,"status":"planned","state":request.get("state"),"components":components}
        return set_status(asset_id,request.get("state"),components)
    if action == "delete":
        return delete_generated(asset_id,components=components,replace_edited=bool(request.get("replace_edited")),dry_run=bool(request.get("dry_run")))
    raise ValueError(f"Unknown action {action!r}")
