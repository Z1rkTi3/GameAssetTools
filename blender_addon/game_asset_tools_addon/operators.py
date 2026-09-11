"""Thin operation dispatch, explicit confirmations, and compact report handling."""

import json
import math

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import properties


def operation_request(settings, action, *, view="perspective", selected=False, dry_run=False):
    request = {"action": action, "project": str(properties.project_root(settings)), "asset": settings.asset,
               "overwrite": settings.overwrite, "replace_edited": settings.replace_edited, "dry_run": dry_run}
    if settings.output:
        request["output"] = bpy.path.abspath(settings.output)
    if settings.component != properties.ALL:
        request["components"] = [settings.component]
    if selected:
        obj = bpy.context.active_object
        if obj is None or obj.get("gat_asset_id") != settings.asset or not obj.get("gat_component"):
            raise ValueError("Select a generated component object belonging to the chosen asset")
        request["components"] = [obj["gat_component"]]
    if action in ("build", "rebuild"):
        request["stage"] = settings.stage
        request["overrides"] = {}
        for item in settings.parameters:
            value = getattr(item, item.kind + "_value")
            original = json.loads(item.original_json)
            unchanged = math.isclose(value, original, rel_tol=1e-6, abs_tol=1e-7) if item.kind == "float" else value == original
            if not unchanged:
                request["overrides"][item.path] = value
        if action == "build":
            request.pop("components", None)
    if action == "preview":
        request["resolution"] = int(settings.resolution)
        request["views"] = [view] if view != "all" else ["front", "back", "left", "right", "top", "perspective"]
    if action == "status":
        request["state"] = settings.state
    return request


def store_report(settings, result):
    """Keep the full JSON in a Blender Text datablock, not an oversized panel."""
    name = "GameAssetTools_Report"
    report = next((t for t in bpy.data.texts if t.get("gat_report")), None) or bpy.data.texts.new(name)
    report["gat_report"] = True
    report.clear()
    report.write(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    settings.report_text = name
    status = result.get("status", "done")
    errors = result.get("errors", [])
    warnings = result.get("warnings", [])
    settings.last_status = f"{status}: {len(errors)} errors, {len(warnings)} warnings"


class GAT_OT_refresh(bpy.types.Operator):
    bl_idname = "game_asset_tools.refresh"
    bl_label = "Refresh Recipes"
    bl_description = "Rediscover recipes and load the selected asset's saved scene configuration"

    def execute(self, context):
        settings = context.scene.game_asset_tools
        properties.clear_cache()
        items = properties.category_items(settings, context)
        if settings.category not in {item[0] for item in items}:
            settings.category = items[0][0]
        assets = properties.asset_items(settings, context)
        if settings.asset not in {item[0] for item in assets}:
            settings.asset = assets[0][0]
        properties.load_parameters(settings)
        return {"FINISHED"}


class GAT_OT_action(bpy.types.Operator):
    bl_idname = "game_asset_tools.action"
    bl_label = "GameAssetTools Action"
    bl_options = {"REGISTER", "UNDO"}
    action: EnumProperty(items=[(name, name.title(), name) for name in ("build", "rebuild", "delete", "preview", "inspect", "validate", "save", "export", "status")])
    view: StringProperty(default="perspective")
    selected: BoolProperty(default=False)
    plan_text: StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, "game_asset_tools") and context.scene.game_asset_tools.asset not in ("", properties.EMPTY)

    def invoke(self, context, event):
        if self.action in ("rebuild", "delete"):
            try:
                from game_asset_tools.operations import execute
                plan = execute(operation_request(context.scene.game_asset_tools, self.action, selected=self.selected, dry_run=True))
                self.plan_text = json.dumps(plan)
                if plan.get("errors"):
                    store_report(context.scene.game_asset_tools, plan)
                    self.report({"ERROR"}, "; ".join(plan["errors"])[:350])
                    return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return context.window_manager.invoke_props_dialog(self, width=480)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=f"Confirm {self.action} of generated components")
        plan = json.loads(self.plan_text or "{}")
        for component in plan.get("components", []):
            self.layout.label(text=component)
        if context.scene.game_asset_tools.replace_edited:
            self.layout.label(text="Manually edited generated geometry will be replaced", icon="ERROR")

    def execute(self, context):
        settings = context.scene.game_asset_tools
        try:
            from game_asset_tools.operations import execute
            result = execute(operation_request(settings, self.action, view=self.view, selected=self.selected))
            if self.action in ("build", "rebuild") and not result.get("errors"):
                properties.load_parameters(settings)
            store_report(settings, result)
            if result.get("errors") or result.get("status") in ("blocked", "invalid", "error"):
                self.report({"ERROR"}, settings.last_status)
                return {"CANCELLED"}
            self.report({"INFO"}, settings.last_status)
            return {"FINISHED"}
        except Exception as exc:
            store_report(settings, {"status": "error", "errors": [str(exc)]})
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class GAT_OT_report(bpy.types.Operator):
    bl_idname = "game_asset_tools.show_report"
    bl_label = "Open Detailed Report"

    def execute(self, context):
        text = bpy.data.texts.get(context.scene.game_asset_tools.report_text)
        if text is None:
            self.report({"WARNING"}, "Run an action to generate a report")
            return {"CANCELLED"}
        if context.area:
            context.area.type = "TEXT_EDITOR"
            context.area.spaces.active.text = text
        return {"FINISHED"}


CLASSES = (GAT_OT_refresh, GAT_OT_action, GAT_OT_report)
