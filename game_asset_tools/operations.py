"""Small shared command surface for Blender UI, scripts, and headless requests."""

import json
import logging
from pathlib import Path

from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.parameters import load_config, merge_values, read_json, set_value, validate_config
from game_asset_tools.style import load_style


def execute(request: dict) -> dict:
    """Execute in the current Blender scene. Errors are actionable exceptions.

    This API never opens files or starts a subprocess. The headless runner owns
    those process-level concerns; the add-on operates on the current document.
    """
    from game_asset_tools.asset.scene import find_root
    from game_asset_tools.asset.lifecycle import build, set_status, delete_generated
    project = Path(request["project"]).resolve()
    action, asset_id = request["action"], request["asset"]
    logging.getLogger("game_asset_tools").debug("Dispatch %s for %s", action, asset_id)
    entry = Registry(project).get(asset_id)
    output = Path(request.get("output") or project / "output").resolve()
    components = request.get("components") or None
    overwrite = bool(request.get("overwrite"))
    if request.get("dry_run") and action in {"save", "export", "preview"}:
        find_root(asset_id)
        from game_asset_tools.export.paths import artifact_path
        kind, suffix = {"save": ("blend", ".blend"), "export": ("glb", ".glb"),
                        "preview": ("previews", "")}[action]
        return {"asset": asset_id, "status": "planned", "action": action,
                "output": str(artifact_path(output, kind, asset_id, suffix)), "overwrite": overwrite}
    if action in ("build", "rebuild"):
        root = find_root(asset_id, required=False)
        if root and action == "rebuild":
            config = json.loads(root["gat_config"])
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
            return {"asset": asset_id, "components": [inspect_asset(asset_id,c) for c in components]}
        return inspect_asset(asset_id, components[0] if components else None)
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
        from game_asset_tools.export.paths import artifact_path, write_json
        report = validate_asset(asset_id, entry)
        if request.get("dry_run"):
            return report
        report["report"] = write_json(artifact_path(output,"reports",asset_id,"_validation.json"),report,overwrite=overwrite)
        return report
    if action == "save":
        from game_asset_tools.export import save_asset
        return save_asset(asset_id,output,overwrite=overwrite)
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
