"""Thin operation dispatch, explicit confirmations, and compact report handling."""

import json
from dataclasses import asdict
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import properties
from .i18n import LocalizedOperator, set_status, status_text, tr


def operation_request(settings, action, *, view="perspective", selected=False, dry_run=False):
    state = properties.scene_state(settings)
    if not state["recipe_available"]:
        raise ValueError(tr("Choose a project and an available recipe first"))
    if state["source_mismatch"]:
        raise ValueError(tr(state["reason"]))
    request = {"action": action, "project": str(properties.project_root(settings)), "asset": settings.asset,
               "overwrite": settings.overwrite, "replace_edited": settings.replace_edited, "dry_run": dry_run}
    if settings.output:
        request["output"] = bpy.path.abspath(settings.output)
    if settings.component != properties.ALL:
        request["components"] = [settings.component]
    if selected:
        if not state["selected_component"]:
            raise ValueError(tr("Select a generated component object belonging to the chosen asset"))
        request["components"] = [state["selected_component"]]
    if action in ("build", "rebuild"):
        request["stage"] = settings.stage
        request["overrides"] = properties.geometry_updates(settings, check_revision=True)
        if action == "build":
            request.pop("components", None)
    if action == "preview":
        request["resolution"] = int(settings.resolution)
        request["views"] = [view] if view != "all" else ["front", "back", "left", "right", "top", "perspective"]
    if action == "status":
        request["state"] = settings.state
    if action == "recolor":
        if settings.material_role == properties.EMPTY:
            raise ValueError(tr("Build or select an asset with material roles first"))
        request["materials"] = {settings.material_role: {"base_color": list(settings.material_color)}}
    if action == "validate":
        request["report_mode"] = settings.report_mode
    if action == "save":
        request.update(view_copy=settings.view_copy, save_view=settings.save_view)
    if action == "export":
        request["animations"] = settings.export_animations
        request["vertex_color_name"] = settings.export_vertex_color_name
    return request


def store_report(settings, result):
    """Keep the full JSON in a Blender Text datablock, not an oversized panel."""
    name = "GameAssetTools_Report"
    report = next((t for t in bpy.data.texts if t.get("gat_report")), None) or bpy.data.texts.new(name)
    report["gat_report"] = True
    report.clear()
    report.write(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    settings.report_text = report.name
    status = result.get("status", "done")
    errors = result.get("errors", [])
    warnings = result.get("warnings", [])
    set_status(settings, "last_status", "{status}: {errors} errors, {warnings} warnings", status=status, errors=len(errors), warnings=len(warnings))


class GAT_OT_refresh(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.refresh"
    bl_label = "Refresh Recipes"
    bl_description = "Rediscover recipes while preserving unsaved edits for each project and asset"

    def execute(self, context):
        settings = context.scene.game_asset_tools
        properties.refresh_selection(settings, context)
        return {"FINISHED"}


class GAT_OT_use_selected_asset(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.use_selected_asset"
    bl_label = "Use Selected Asset"
    bl_description = "Choose the recipe identified by the selected object's GameAssetTools metadata"

    @classmethod
    def poll(cls, context):
        return bool(context.scene and hasattr(context.scene, "game_asset_tools") and
                    properties.scene_state(context.scene.game_asset_tools, context)["selected_asset_id"])

    def execute(self, context):
        settings = context.scene.game_asset_tools
        try:
            asset = properties.scene_state(settings, context)["selected_asset_id"]
            if not asset:
                raise ValueError(tr("Select an object belonging to a registered GameAssetTools asset"))
            properties.select_asset(settings, asset, context)
            return {"FINISHED"}
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, tr(str(exc)))
            return {"CANCELLED"}


class GAT_OT_reload_geometry(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.reload_geometry"
    bl_label = "Reload Geometry Settings"
    bl_description = "Discard unsaved geometry settings and load the saved scene or recipe values"

    @classmethod
    def poll(cls, context):
        return GAT_OT_action.poll(context)

    def invoke(self, context, event):
        if properties.geometry_dirty(context.scene.game_asset_tools):
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=tr("Discard unsaved geometry settings?", context), icon="ERROR")

    def execute(self, context):
        properties.load_parameters(context.scene.game_asset_tools)
        return {"FINISHED"}


class GAT_OT_sprites(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.sprites"
    bl_label = "Sprite Export"
    bl_description = "Use the shared recipe settings locally; no Codex or network call is required"
    # These actions persist recipe settings and files, which Blender undo cannot reverse.
    action: EnumProperty(items=[("load", "Reload Saved Settings", "Discard panel edits and read config.json"),
                                ("save", "Save Settings", "Save panel edits to the shared recipe config.json"),
                                ("preview", "Save + Preview", "Save settings and render the first direction"),
                                ("export", "Save + Export Atlas", "Save settings and export every direction")])

    @classmethod
    def poll(cls, context):
        return GAT_OT_action.poll(context)

    def invoke(self, context, event):
        if self.action == "load" and properties.sprite_dirty(context.scene.game_asset_tools):
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=tr("Discard unsaved sprite settings?", context), icon="ERROR")

    def execute(self, context):
        settings = context.scene.game_asset_tools
        try:
            from game_asset_tools.operations import execute
            request = {"action": "sprite-settings", "project": str(properties.project_root(settings)), "asset": settings.asset}
            if self.action != "load":
                updates = properties.sprite_updates(settings)
                if (updates or self.action == "save") and properties.is_bundled_readonly(settings, addon_file=__file__):
                    raise ValueError(tr("Select an editable project before saving sprite settings; bundled examples are read-only"))
                # An unchanged render follows the latest file, including CLI edits.
                # Edits must retain their loaded revision so conflicts cannot overwrite them.
                if updates or self.action == "save":
                    request.update(sprite_updates=updates, expected_revision=settings.sprite_revision)
            result = execute(request)
            if result.get("errors") or result.get("status") in ("blocked", "invalid", "error"):
                raise ValueError("; ".join(result.get("errors", [])) or str(result))
            properties.apply_sprite_settings(settings, result)
            if self.action in ("preview", "export"):
                request = operation_request(settings, "sprites")
                request.pop("components", None)
                request.pop("replace_edited", None)
                request["sprite_preview"] = self.action == "preview"
                result = execute(request)
                if result.get("errors") or result.get("status") in ("blocked", "invalid", "error"):
                    raise ValueError("; ".join(result.get("errors", [])) or str(result))
                if self.action == "preview" and result.get("frames"):
                    settings.sprite_preview_path = result["frames"][0]["path"]
                if self.action == "export" and result.get("atlas"):
                    settings.sprite_atlas_path = result["atlas"]["path"]
                set_status(settings, "sprite_status", "Preview rendered from saved settings" if self.action == "preview" else "Atlas exported from saved settings")
            else:
                set_status(settings, "sprite_status", "Loaded saved settings" if self.action == "load" else "Settings saved to recipe config.json")
            store_report(settings, result)
            self.report({"INFO"}, status_text(settings, "sprite_status", context))
            return {"FINISHED"}
        except Exception as exc:
            settings.sprite_status = tr(str(exc))
            store_report(settings, {"status": "error", "errors": [str(exc)]})
            self.report({"ERROR"}, tr(str(exc)))
            return {"CANCELLED"}


class GAT_OT_sprite_image(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.open_sprite_image"
    bl_label = "Open Sprite Image"
    bl_description = "Open the last rendered PNG in Blender's Image Editor"
    kind: EnumProperty(items=[("preview", "Preview", "Last rendered first direction"),
                              ("atlas", "Atlas", "Last exported sprite sheet")])

    def execute(self, context):
        settings = context.scene.game_asset_tools
        path = getattr(settings, f"sprite_{self.kind}_path")
        if not path or not Path(path).is_file():
            self.report({"ERROR"}, tr("Render this sprite image first; the last output file is unavailable"))
            return {"CANCELLED"}
        try:
            image = bpy.data.images.load(path, check_existing=True)
            image.reload()
            if context.area:
                context.area.type = "IMAGE_EDITOR"
                context.area.spaces.active.image = image
                region = next((region for region in context.area.regions if region.type == "WINDOW"), None)
                if region:
                    with context.temp_override(region=region):
                        bpy.ops.image.view_all(fit_view=True)
            self.report({"INFO"}, tr("Opened {name}", name=Path(path).name))
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, tr(str(exc)))
            return {"CANCELLED"}


class GAT_OT_action(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.action"
    bl_label = "GameAssetTools Action"
    bl_options = {"REGISTER", "UNDO"}
    action: EnumProperty(items=[(name, name.title(), name) for name in ("build", "rebuild", "recolor", "delete", "preview", "inspect", "validate", "save", "export", "status")])
    view: StringProperty(default="perspective")
    selected: BoolProperty(default=False)
    plan_text: StringProperty(options={"HIDDEN"})
    plan_only: BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bool(context.scene is not None and hasattr(context.scene, "game_asset_tools") and
                    properties.scene_state(context.scene.game_asset_tools, context)["recipe_available"])

    def invoke(self, context, event):
        if self.action in ("rebuild", "recolor", "delete") and not self.plan_only:
            try:
                from game_asset_tools.operations import execute
                plan = execute(operation_request(context.scene.game_asset_tools, self.action, selected=self.selected, dry_run=True))
                self.plan_text = json.dumps(plan)
                if plan.get("errors"):
                    store_report(context.scene.game_asset_tools, plan)
                    self.report({"ERROR"}, tr("; ".join(plan["errors"]))[:350])
                    return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, tr(str(exc)))
                return {"CANCELLED"}
            return context.window_manager.invoke_props_dialog(self, width=480)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=tr("Confirm {action} of generated components", context, action=tr(self.action, context)))
        plan = json.loads(self.plan_text or "{}")
        for component in plan.get("components", []):
            self.layout.label(text=component)
        for change in plan.get("changes", []):
            self.layout.label(text=f"{change['object']} / slot {change['slot']} / {change['role']}")
        for warning in plan.get("warnings", []):
            self.layout.label(text=tr(warning, context), icon="INFO")
        if context.scene.game_asset_tools.replace_edited:
            self.layout.label(text=tr("Manually edited generated geometry will be replaced", context), icon="ERROR")

    def execute(self, context):
        settings = context.scene.game_asset_tools
        try:
            from game_asset_tools.operations import execute
            result = execute(operation_request(settings, self.action, view=self.view, selected=self.selected, dry_run=self.plan_only))
            successful = not result.get("errors") and result.get("status") not in ("blocked", "invalid", "error")
            if self.action in ("build", "rebuild") and successful and not self.plan_only:
                properties.load_parameters(settings)
            store_report(settings, result)
            if result.get("errors") or result.get("status") in ("blocked", "invalid", "error"):
                self.report({"ERROR"}, status_text(settings, "last_status", context))
                return {"CANCELLED"}
            self.report({"INFO"}, status_text(settings, "last_status", context))
            return {"FINISHED"}
        except Exception as exc:
            store_report(settings, {"status": "error", "errors": [str(exc)]})
            self.report({"ERROR"}, tr(str(exc)))
            return {"CANCELLED"}


class GAT_OT_library(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.library_action"
    bl_label = "Component Library"
    bl_description = "Register checked interfaces, validate, publish or install a compatible component"

    action: EnumProperty(items=[(name, name.title(), name) for name in ("register", "validate", "publish", "plan", "install")])

    @classmethod
    def poll(cls, context):
        return bool(context.scene and hasattr(context.scene, "game_asset_tools"))

    def execute(self, context):
        settings = context.scene.game_asset_tools
        try:
            from game_asset_tools.assembly import authoring
            from game_asset_tools.asset.scene import component_records
            state = properties.scene_state(settings, context)
            if not state["asset_available"] or state["source_mismatch"]:
                raise ValueError(tr(state["reason"] or "Choose a project and an available recipe first"))
            asset, component = settings.asset, settings.component
            if self.action == "register":
                if not settings.library_manifest:
                    raise ValueError(tr("Choose a part manifest first"))
                document = authoring.load_document(bpy.path.abspath(settings.library_manifest))
                result = authoring.register_document(asset, document, None if component == properties.ALL else component)
            elif self.action == "validate":
                names = ([component] if component != properties.ALL else
                         [name for name, record in component_records(state["root"]).items() if authoring.INTERFACE_KEY in record])
                if not names:
                    raise ValueError(tr("Register component interfaces first"))
                result = {"status": "pass", "asset": asset,
                          "components": [authoring.validate_component(asset, name) for name in names]}
            else:
                if component in (properties.ALL, properties.EMPTY):
                    raise ValueError(tr("Choose one component for publication or installation"))
                if not settings.library_root or not settings.library_part_id.strip():
                    raise ValueError(tr("Choose a library folder and a part ID"))
                library_root = Path(bpy.path.abspath(settings.library_root))
                if self.action == "publish":
                    result = authoring.publish_component(library_root, asset, component,
                                                         settings.library_part_id, settings.library_revision)
                else:
                    result = authoring.install_component(library_root, asset, component, settings.library_part_id,
                                                         settings.library_revision, dry_run=self.action == "plan")
            store_report(settings, result)
            self.report({"INFO"}, status_text(settings, "last_status", context))
            return {"FINISHED"}
        except Exception as exc:
            store_report(settings, {"status": "error", "errors": [str(exc)],
                                    "issues": [asdict(issue) for issue in getattr(exc, "issues", ())]})
            self.report({"ERROR"}, tr(str(exc)))
            return {"CANCELLED"}


class GAT_OT_report(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.show_report"
    bl_label = "Open Detailed Report"

    def execute(self, context):
        text = bpy.data.texts.get(context.scene.game_asset_tools.report_text)
        if text is None:
            self.report({"WARNING"}, tr("Run an action to generate a report"))
            return {"CANCELLED"}
        if context.area:
            context.area.type = "TEXT_EDITOR"
            context.area.spaces.active.text = text
        return {"FINISHED"}


CLASSES = (GAT_OT_refresh, GAT_OT_use_selected_asset, GAT_OT_reload_geometry, GAT_OT_action,
           GAT_OT_sprites, GAT_OT_sprite_image, GAT_OT_library, GAT_OT_report)
