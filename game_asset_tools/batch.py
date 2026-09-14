"""Headless variant batches: isolated baselines, shared cameras, explicit results.

Only the process adapter calls ``run_batch``. Unlike ``operations.execute``, it
opens files and deliberately replaces the current headless scene between jobs.
The JSON parser and comparison writer remain usable without Blender.
"""

import base64
from copy import deepcopy
from html import escape
import json
import math
from pathlib import Path
import re
import tempfile

from game_asset_tools.asset.parameters import merge_values, read_json
from game_asset_tools.export.paths import artifact_path, prepare_path, write_json


VIEWS = ("front", "back", "left", "right", "top", "perspective")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def read_batch_config(path):
    """Reject ambiguous manifest structure before opening or writing any scene."""
    data = read_json(Path(path))
    if not isinstance(data, dict) or set(data) != {"schema_version", "variants"}:
        raise ValueError("Batch config requires only schema_version and variants")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported batch schema_version; expected 1")
    variants = data["variants"]
    if not isinstance(variants, list) or not variants:
        raise ValueError("Batch variants must be a nonempty list")
    names = set()
    allowed = {"name", "action", "config", "materials", "components", "objects"}
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) - allowed:
            raise ValueError(f"Invalid batch variant fields: {variant!r}")
        name = variant.get("name")
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
                or name in _RESERVED or name in names):
            raise ValueError(f"Variant name must be a unique safe lowercase name: {name!r}")
        names.add(name)
        action = variant.get("action", "rebuild")
        if action not in ("rebuild", "recolor"):
            raise ValueError(f"Variant {name!r}: action must be rebuild or recolor")
        for key in ("config", "materials"):
            if key in variant and not isinstance(variant[key], dict):
                raise ValueError(f"Variant {name!r}: {key} must be an object")
        for key in ("components", "objects"):
            values = variant.get(key)
            if values is not None and (not isinstance(values, list) or not values
                                       or any(not isinstance(v, str) or not v for v in values)
                                       or len(values) != len(set(values))):
                raise ValueError(f"Variant {name!r}: {key} must be a nonempty list of distinct names")
        if action == "recolor":
            if not variant.get("materials"):
                raise ValueError(f"Variant {name!r}: recolor requires materials")
            if variant.get("config"):
                raise ValueError(f"Variant {name!r}: recolor accepts materials, not geometry config")
        elif "materials" in variant or "objects" in variant:
            raise ValueError(f"Variant {name!r}: materials/objects require action recolor")
    # JSON itself permits NaN in Python; never carry it into Blender or a report.
    try:
        json.dumps(data, allow_nan=False)
    except ValueError as exc:
        raise ValueError("Batch values must be finite JSON values") from exc
    return deepcopy(variants)


def common_framing(boxes, margin=1.15):
    """One enclosing sphere for all evaluated variant bounds, in world space."""
    if not boxes:
        return None
    low = [min(box["min"][i] for box in boxes) for i in range(3)]
    high = [max(box["max"][i] for box in boxes) for i in range(3)]
    center = [(a + b) / 2 for a, b in zip(low, high)]
    radius = max(math.sqrt(sum((b-a)**2 for a, b in zip(low, high))) / 2, .01)
    if not all(math.isfinite(v) for v in (*center, radius, margin)):
        raise ValueError("Cannot frame nonfinite variant bounds")
    return {"center": center, "radius": radius, "ortho_scale": radius * 2 * max(margin, 1.05)}


def write_comparison(path, variants, views, resolution, *, overwrite=False):
    """Write a portable SVG contact sheet with PNG bytes embedded, no dependencies."""
    width, row_height, header = len(views) * resolution, resolution + 44, 44
    height = header + len(variants) * row_height
    rows = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#171b24"/>',
            '<g font-family="sans-serif" font-size="16" fill="#e5e7eb">']
    for column, view in enumerate(views):
        rows.append(f'<text x="{column*resolution+12}" y="28">{escape(view)}</text>')
    for index, variant in enumerate(variants):
        y = header + index * row_height
        label = f'{variant["name"]} — {variant["status"]}'
        rows.append(f'<text x="12" y="{y+25}">{escape(label)}</text>')
        for column, view in enumerate(views):
            x = column * resolution
            image_path = (variant.get("preview") or {}).get("paths", {}).get(view)
            if variant["status"] == "passed" and image_path:
                encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
                rows.append(f'<image x="{x}" y="{y+44}" width="{resolution}" height="{resolution}" '
                            f'href="data:image/png;base64,{encoded}"/>')
            else:
                message = variant.get("error", "No preview")
                rows.append(f'<rect x="{x+4}" y="{y+48}" width="{resolution-8}" '
                            f'height="{resolution-8}" fill="#44262c"/>')
                rows.append(f'<text x="{x+12}" y="{y+76}" fill="#ffbcc7">Preview unavailable</text>')
                # SVG title preserves the complete actionable error without text overflow.
                rows.append(f'<text x="{x+12}" y="{y+102}" font-size="12">'
                            f'<title>{escape(message)}</title>{escape(message[:35])}</text>')
    rows.extend(("</g>", "</svg>"))
    target = prepare_path(path, overwrite=overwrite)
    with target.open("w" if overwrite else "x", encoding="utf-8") as stream:
        stream.write("\n".join(rows) + "\n")
    return str(target)


def _paths(output, asset_id, name, views):
    directory = output / name
    preview = directory / "previews" / asset_id / "asset"
    return {"directory": directory, "config": directory / "config.json",
            "blend": artifact_path(directory, "blend", asset_id, ".blend"),
            "validation": artifact_path(directory, "reports", asset_id, "_validation.json"),
            "previews": [preview / f"{view}.png" for view in views],
            "frame": preview / "framing.json", "preview_report": preview / "preview.json"}


def _preflight(paths, *, overwrite, protected):
    # Do not let an output alias replace a source .blend, manifest or recipe config,
    # even with --overwrite. Resolve symlinks before checking output containment.
    for path in paths:
        resolved = path.resolve()
        if resolved in protected:
            raise ValueError(f"Batch output would overwrite an input: {path}")
        if path.exists() and (not overwrite or not path.is_file()):
            raise FileExistsError(f"Output exists: {path}; explicitly request overwrite")
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir():
            raise NotADirectoryError(f"Output parent is not a directory: {parent}")


def run_batch(request):
    """Run all variants inside this one *headless* Blender process.

    Every variant begins from the same source snapshot. Geometry changes and
    material changes use the usual guarded operations. The first pass builds,
    validates and saves versions; the second renders with their union framing.
    Individual failures are retained and make the aggregate status ``failed``.
    """
    import bpy
    if not bpy.app.background:
        raise ValueError("Batch opens scene files; run it through the headless CLI")
    from game_asset_tools.asset.registry import Registry
    from game_asset_tools.asset.scene import asset_objects, find_root
    from game_asset_tools.inspection import bounds
    from game_asset_tools.operations import execute
    from game_asset_tools.preview import render_preview

    project = Path(request["project"]).resolve()
    asset_id = request["asset"]
    entry = Registry(project).get(asset_id)
    manifest = Path(request["batch_config"]).resolve()
    variants = read_batch_config(manifest)
    source = Path(request["blend"]).resolve() if request.get("blend") else None
    if source and not source.is_file():
        raise FileNotFoundError(f"Input blend not found: {source}")
    views = request.get("views") or ["front", "perspective"]
    views = list(VIEWS) if "all" in views else list(dict.fromkeys(views))
    if set(views) - set(VIEWS):
        raise ValueError(f"Unknown batch preview views: {set(views) - set(VIEWS)}")
    resolution = request.get("resolution") or 512
    if resolution not in (256, 512, 1024):
        raise ValueError("Preview resolution must be 256, 512, or 1024")
    output = Path(request.get("output") or project / "output").resolve() / "batches" / asset_id
    report_path, comparison_path = output / "batch.json", output / "comparison.svg"
    overwrite, dry_run = bool(request.get("overwrite")), bool(request.get("dry_run"))
    targets = {v["name"]: _paths(output, asset_id, v["name"], views) for v in variants}
    protected = {manifest, entry.path / "config.json"}
    if source:
        protected.add(source)
    if request.get("config"):
        protected.add(Path(request["config"]).resolve())
    all_paths = [report_path, comparison_path]
    for paths in targets.values():
        all_paths.extend([paths[k] for k in ("config", "blend", "validation", "frame", "preview_report")])
        all_paths.extend(paths["previews"])
    # No directories, files or scene data are created before this global check.
    _preflight(all_paths, overwrite=overwrite, protected={p.resolve() for p in protected})
    report = {"schema_version": 1, "asset": asset_id, "status": "planned" if dry_run else "passed",
              "source_blend": str(source) if source else None, "batch_config": str(manifest),
              "views": views, "resolution": resolution, "variants": [], "framing": None,
              "report": str(report_path), "comparison": str(comparison_path)}
    shared = {"project": str(project), "asset": asset_id,
              "replace_edited": bool(request.get("replace_edited"))}
    with tempfile.TemporaryDirectory(prefix="gat_batch_") as temporary:
        temporary = Path(temporary)
        baseline = source or temporary / "baseline.blend"
        if source:
            bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
            find_root(asset_id)
        elif dry_run:
            # No geometry is generated for planning. Validate each prospective
            # rebuilt config; scene guards and recolor selectors need a built file.
            from game_asset_tools.asset.parameters import load_config, validate_config
            initial = load_config(entry, request.get("config"), request.get("overrides"))
            from game_asset_tools.style import load_style
            for variant in variants:
                result = {"name": variant["name"], "status": "planned", "action": variant.get("action", "rebuild")}
                try:
                    config = merge_values(initial, variant.get("config", {}))
                    validate_config(entry, config)
                    load_style(project, config.get("style"))
                    if result["action"] == "recolor":
                        from game_asset_tools.asset.appearance import validate_material_changes
                        validate_material_changes(variant["materials"])
                    result["deferred"] = "Scene guards and recolor selectors require the built baseline"
                except Exception as exc:
                    result.update(status="failed", error=str(exc))
                report["variants"].append(result)
            report["status"] = "failed" if any(v["status"] == "failed" for v in report["variants"]) else "planned"
            return report
        else:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            execute({**shared, "action": "build", "config": request.get("config"),
                     "overrides": request.get("overrides"), "stage": request.get("stage")})
            saved = bpy.ops.wm.save_as_mainfile(filepath=str(baseline), check_existing=False, copy=True)
            if "FINISHED" not in saved or not baseline.is_file():
                raise RuntimeError("Could not save the isolated batch baseline")
        boxes, margin = [], 1.05
        try:
            for variant in variants:
                name = variant["name"]
                paths = targets[name]
                result = {"name": name, "action": variant.get("action", "rebuild"), "status": "planned"}
                report["variants"].append(result)
                try:
                    bpy.ops.wm.open_mainfile(filepath=str(baseline), load_ui=False, use_scripts=False)
                    operation = {**shared, "action": result["action"], "components": variant.get("components"),
                                 "objects": variant.get("objects"), "dry_run": dry_run,
                                 "materials": variant.get("materials")}
                    if result["action"] == "rebuild":
                        overlay_path = temporary / f"{name}.json"
                        overlay_path.write_text(json.dumps(variant.get("config", {}), allow_nan=False), encoding="utf-8")
                        operation["config"] = str(overlay_path)
                    result["operation"] = execute(operation)
                    if result["operation"].get("status") in ("blocked", "failed", "error"):
                        raise ValueError("; ".join(result["operation"].get("errors", [])) or "Variant operation was blocked")
                    if dry_run:
                        continue
                    result["validation"] = execute({**shared, "action": "validate", "output": str(paths["directory"]),
                                                    "overwrite": overwrite, "report_mode": "file"})
                    if result["validation"].get("errors") or result["validation"].get("status") in ("error", "failed"):
                        raise ValueError("Validation failed: " + "; ".join(result["validation"].get("errors", [])))
                    root = find_root(asset_id)
                    result["bounds"] = bounds(asset_objects(root, helpers=False))
                    style = json.loads(root.get("gat_style", "{}"))
                    margin = max(margin, float(style.get("preview", {}).get("margin", 1.15)))
                    config = json.loads(root["gat_config"])
                    result["config"] = write_json(paths["config"], config, overwrite=overwrite)
                    result["blend"] = execute({**shared, "action": "save", "output": str(paths["directory"]),
                                               "overwrite": overwrite})["blend"]
                    boxes.append(result["bounds"])
                    result["status"] = "built"
                except Exception as exc:
                    result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            if not dry_run:
                report["framing"] = common_framing(boxes, margin)
                for result in report["variants"]:
                    if result["status"] != "built":
                        continue
                    try:
                        bpy.ops.wm.open_mainfile(filepath=result["blend"], load_ui=False, use_scripts=False)
                        result["preview"] = render_preview(asset_id, targets[result["name"]]["directory"],
                                                           views=views, resolution=resolution, overwrite=overwrite,
                                                           framing=report["framing"])
                        result["status"] = "passed"
                    except Exception as exc:
                        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                report["status"] = "failed" if any(v["status"] == "failed" for v in report["variants"]) else "passed"
                write_comparison(comparison_path, report["variants"], views, resolution, overwrite=overwrite)
                write_json(report_path, report, overwrite=overwrite)
            else:
                report["status"] = "failed" if any(v["status"] == "failed" for v in report["variants"]) else "planned"
            return report
        finally:
            # The source remains the process's active document, never a variant.
            # The caller is headless, so this cannot replace a user's GUI session.
            if source:
                bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
