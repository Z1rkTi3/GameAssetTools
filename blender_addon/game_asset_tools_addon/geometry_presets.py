"""JSON-пресеты геометрии и отчёт меха поверх существующих controls и Rebuild."""

from copy import deepcopy
import json
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from game_asset_tools.asset.parameters import effective_saved_config, get_value, load_config, set_value, validate_config
from game_asset_tools.export.paths import write_json
from . import properties
from .i18n import LocalizedOperator, tr
from .operators import store_report


def draft_config(settings, *, validate=True):
    """Собирает проверенную конфигурацию без перестройки и записи в recipe."""
    state = properties.scene_state(settings)
    if not state["recipe_available"] or state["source_mismatch"]:
        raise ValueError(state.get("reason") or "Choose an available recipe first")
    entry = properties.registry(settings).get(settings.asset)
    root = state["root"]
    config = effective_saved_config(entry, json.loads(root["gat_config"])) if root is not None else load_config(entry)
    # Сохраняем ту же revision-защиту, что обычная кнопка Rebuild.
    updates = properties.geometry_updates(settings, check_revision=True)
    for path, value in updates.items():
        set_value(config["parameters"], path, value)
    if validate:
        validate_config(entry, config)
    return entry, config


def import_geometry(settings, path):
    """Валидация всего файла предшествует изменению хотя бы одного control."""
    entry, current = draft_config(settings, validate=False)
    imported = load_config(entry, Path(path))
    parameters = entry.load().parameters
    items = {item.path: item for item in settings.parameters}
    if set(items) != {parameter.path for parameter in parameters}:
        raise ValueError("Recipe controls changed; reload geometry settings first")
    changes = [(items[p.path], get_value(imported["parameters"], p.path)) for p in parameters]
    original = [(item, getattr(item, item.kind + "_value")) for item, _value in changes]
    try:
        for item, value in changes:
            setattr(item, item.kind + "_value", value)
    except Exception:
        for item, value in original:
            setattr(item, item.kind + "_value", value)
        raise
    # Пресет Geometry не меняет материалы, sprite-профиль и содержимое сцены.
    preserved = [key for key in ("style", "appearance", "sprites")
                 if imported.get(key) != current.get(key)]
    return {"status": "draft", "asset": entry.id, "parameters": len(changes),
            "scene_changed": False, "preserved_sections": preserved,
            "message": "Geometry loaded into controls; use Build or Rebuild to apply"}


def export_geometry(settings, path, *, overwrite=False):
    entry, config = draft_config(settings)
    # Обычный config envelope можно передать существующему CLI через --config.
    # Негеометрические разделы сохраняются из текущей конфигурации без изменений.
    result = deepcopy(config)
    saved = write_json(Path(path), result, overwrite=overwrite)
    return {"status": "saved", "asset": entry.id, "path": saved}


def _ready(context):
    settings = getattr(context.scene, "game_asset_tools", None)
    if settings is None:
        return False
    state = properties.scene_state(settings, context)
    return state["recipe_available"] and not state["source_mismatch"]


class GAT_OT_geometry_import(LocalizedOperator, bpy.types.Operator, ImportHelper):
    bl_idname = "game_asset_tools.geometry_import"
    bl_label = "Import Geometry JSON"
    bl_description = "Load validated geometry parameters into controls; use Rebuild to change the model"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _ready(context)

    def execute(self, context):
        try:
            result = import_geometry(context.scene.game_asset_tools, bpy.path.abspath(self.filepath))
            store_report(context.scene.game_asset_tools, result)
            self.report({"INFO"}, tr("Geometry loaded into controls; use Build or Rebuild to apply", context))
            return {"FINISHED"}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class GAT_OT_geometry_export(LocalizedOperator, bpy.types.Operator, ExportHelper):
    bl_idname = "game_asset_tools.geometry_export"
    bl_label = "Export Geometry JSON"
    bl_description = "Save validated geometry settings to a JSON file usable by the CLI"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _ready(context)

    def execute(self, context):
        try:
            # ExportHelper показывает штатное подтверждение существующего файла.
            result = export_geometry(context.scene.game_asset_tools,
                                     bpy.path.abspath(self.filepath), overwrite=True)
            store_report(context.scene.game_asset_tools, result)
            return {"FINISHED"}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class GAT_OT_mech_report(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.mech_report"
    bl_label = "Check Mech Geometry"
    bl_description = "Check the current parameter design, mount standards and approximate support; no strength or dynamics simulation"

    @classmethod
    def poll(cls, context):
        if not _ready(context):
            return False
        settings = context.scene.game_asset_tools
        return callable(getattr(properties.registry(settings).get(settings.asset).load(), "mechanical_report", None))

    def execute(self, context):
        try:
            entry, config = draft_config(context.scene.game_asset_tools, validate=False)
            result = entry.load().mechanical_report(config)
            result.update(asset=entry.id, status="error" if result["errors"] else ("warning" if result["warnings"] else "pass"),
                          scope="Parameter design; approximate mass/support, not a strength or dynamics certificate")
            store_report(context.scene.game_asset_tools, result)
            return {"FINISHED"}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class GAT_PT_geometry_presets(bpy.types.Panel):
    bl_label = ""
    bl_idname = "GAT_PT_geometry_presets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GameAssetTools"
    bl_parent_id = "GAT_PT_asset"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text=tr("Geometry Presets", context))

    def draw(self, context):
        layout = self.layout
        layout.enabled = _ready(context)
        row = layout.row(align=True)
        row.operator("game_asset_tools.geometry_import", text=tr("Import Geometry JSON", context))
        row.operator("game_asset_tools.geometry_export", text=tr("Export Geometry JSON", context))
        if GAT_OT_mech_report.poll(context):
            layout.operator("game_asset_tools.mech_report", text=tr("Check Mech Geometry", context))
            layout.label(text=tr("Approximate mass/support; static design only", context), icon="INFO")


def authoring_tools(recipe):
    """Небольшой opt-in hook рецепта; JSON не выбирает исполняемую функцию."""
    provider = getattr(recipe, "authoring_tools", None)
    values = provider() if callable(provider) else []
    if not isinstance(values, (list, tuple)):
        raise ValueError("Recipe authoring_tools must return a list")
    ids = set()
    for item in values:
        if (not isinstance(item, dict) or set(item) != {"id", "label"}
                or any(not isinstance(v, str) or not v.strip() for v in item.values()) or item["id"] in ids):
            raise ValueError("Invalid or duplicate recipe authoring tool")
        ids.add(item["id"])
    if values and not callable(getattr(recipe, "run_authoring_tool", None)):
        raise ValueError("Recipe authoring tools require run_authoring_tool")
    return values


class GAT_OT_recipe_tool(LocalizedOperator, bpy.types.Operator):
    bl_idname = "game_asset_tools.recipe_tool"
    bl_label = "Recipe Authoring Tool"
    bl_description = "Run an explicit authoring tool of the current recipe without rebuilding geometry"
    bl_options = {"REGISTER", "UNDO"}
    tool: StringProperty()

    @classmethod
    def poll(cls, context):
        if not _ready(context): return False
        settings = context.scene.game_asset_tools
        return properties.scene_state(settings, context)["root"] is not None

    def execute(self, context):
        try:
            settings = context.scene.game_asset_tools
            recipe = properties.registry(settings).get(settings.asset).load()
            if self.tool not in {item["id"] for item in authoring_tools(recipe)}:
                raise ValueError("Unknown authoring tool for the selected recipe")
            result = recipe.run_authoring_tool(settings.asset, self.tool)
            if not isinstance(result, dict): raise ValueError("Authoring tool must return a report dictionary")
            store_report(settings, result)
            return {"FINISHED"}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class GAT_PT_recipe_tools(bpy.types.Panel):
    bl_label = "Recipe Authoring"
    bl_idname = "GAT_PT_recipe_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GameAssetTools"
    bl_parent_id = "GAT_PT_asset"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        if not _ready(context): return False
        settings = context.scene.game_asset_tools
        try:
            return bool(authoring_tools(properties.registry(settings).get(settings.asset).load()))
        except (ValueError, KeyError, TypeError):
            return False

    def draw(self, context):
        settings, layout = context.scene.game_asset_tools, self.layout
        recipe = properties.registry(settings).get(settings.asset).load()
        layout.enabled = GAT_OT_recipe_tool.poll(context)
        draw = getattr(recipe, "draw_authoring_tools", None)
        if callable(draw): draw(layout, settings.asset)
        for item in authoring_tools(recipe):
            layout.operator("game_asset_tools.recipe_tool", text=item["label"]).tool = item["id"]


CLASSES = (GAT_OT_geometry_import, GAT_OT_geometry_export, GAT_OT_mech_report, GAT_PT_geometry_presets,
           GAT_OT_recipe_tool, GAT_PT_recipe_tools)
