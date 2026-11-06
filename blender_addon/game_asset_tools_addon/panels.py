"""Recipe-driven sidebar, with explicit scene targets and local translations."""

import json
import bpy

from . import properties
from .i18n import get_preferences, status_text, tr


def action(layout, label, name, *, view=None, selected=False, enabled=True):
    row = layout.row(align=True)
    row.enabled = enabled
    operator = row.operator("game_asset_tools.action", text=tr(label))
    operator.action, operator.selected = name, selected
    if view:
        operator.view = view
    return operator


def prop(layout, data, name, label, **kwargs):
    layout.prop(data, name, text=tr(label), **kwargs)


def parameters(layout, items):
    for item in items:
        field = "choice_value" if json.loads(item.choices_json or "[]") else item.kind + "_value"
        layout.prop(item, field, text=tr(item.label))


def scene_ready(settings, context):
    state = properties.scene_state(settings, context)
    return state["asset_available"] and not state["source_mismatch"]


class GAT_PT_asset(bpy.types.Panel):
    bl_label = "GameAssetTools"
    bl_idname = "GAT_PT_asset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GameAssetTools"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        preferences = get_preferences(context)
        if preferences:
            prop(layout, preferences, "language", "Language")
        row = layout.row(align=True)
        prop(row, settings, "project", "Project")
        row.operator("game_asset_tools.refresh", text="", icon="FILE_REFRESH")
        prop(layout, settings, "category", "Category")
        prop(layout, settings, "asset", "Asset")
        state = properties.scene_state(settings, context)
        row = layout.row()
        row.enabled = bool(state["selected_asset_id"])
        row.operator("game_asset_tools.use_selected_asset", text=tr("Use Selected Asset"), icon="RESTRICT_SELECT_OFF")
        if state["reason"]:
            layout.label(text=tr(state["reason"]), icon="INFO")
        elif state["asset_available"]:
            layout.label(text=tr("Built in this scene"), icon="CHECKMARK")
        prop(layout, settings, "component", "Target")
        if settings.last_status:
            layout.label(text=status_text(settings, "last_status", context))
        row = layout.row()
        row.enabled = bool(settings.report_text)
        row.operator("game_asset_tools.show_report", text=tr("Open Detailed Report"), icon="TEXT")


class AssetSection:
    # Custom headers follow the add-on language independently of Blender.
    bl_label = ""
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GameAssetTools"
    bl_parent_id = "GAT_PT_asset"
    title = ""

    def draw_header(self, context):
        self.layout.label(text=tr(self.title, context))


class GAT_PT_geometry(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_geometry"
    title = "Geometry"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        state = properties.scene_state(settings, context)
        controls = layout.column()
        controls.enabled = state["recipe_available"]
        prop(controls, settings, "stage", "Stage")
        parameters(controls, settings.parameters)
        if state["geometry_dirty"]:
            layout.label(text=tr("Draft kept for this Blender session"), icon="GREASEPENCIL")
        row = controls.row(align=True)
        action(row, "Build", "build", enabled=state["root"] is None)
        action(row, "Rebuild", "rebuild", enabled=scene_ready(settings, context))
        controls.operator("game_asset_tools.reload_geometry", text=tr("Reload Saved Parameters"), icon="FILE_REFRESH")


class GAT_PT_preview(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_preview"
    title = "Preview and Inspection"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        layout.enabled = scene_ready(settings, context)
        prop(layout, settings, "resolution", "Resolution")
        for names in (("front", "back"), ("left", "right"), ("top", "perspective")):
            row = layout.row(align=True)
            for name in names:
                action(row, name.title(), "preview", view=name)
        action(layout, "Render All Views", "preview", view="all")
        row = layout.row(align=True)
        action(row, "Inspect Target", "inspect")
        state = properties.scene_state(settings, context)
        action(row, "Inspect Selected", "inspect", selected=True, enabled=bool(state["selected_component"]))


class GAT_PT_materials(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_materials"
    bl_options = {"DEFAULT_CLOSED"}
    title = "Materials"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        layout.enabled = scene_ready(settings, context)
        prop(layout, settings, "material_role", "Material Role")
        prop(layout, settings, "material_color", "Base Color")
        row = layout.row(align=True)
        plan = action(row, "Plan Change", "recolor", enabled=settings.material_role != properties.EMPTY)
        plan.plan_only = True
        action(row, "Apply Change", "recolor", enabled=settings.material_role != properties.EMPTY)


class GAT_PT_sprites(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_sprites"
    bl_options = {"DEFAULT_CLOSED"}
    title = "Sprites"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        state = properties.scene_state(settings, context)
        layout.label(text=tr("Shared with CLI / Codex"))
        row = layout.row()
        row.enabled = state["recipe_available"]
        row.operator("game_asset_tools.sprites", text=tr("Reload Saved Settings"), icon="FILE_REFRESH").action = "load"
        if not settings.sprite_revision:
            layout.label(text=status_text(settings, "sprite_status", context), icon="INFO")
            return
        if state["bundled_readonly"]:
            layout.label(text=tr("Bundled examples are read-only"), icon="LOCKED")
            layout.label(text=tr("Choose an editable project to save settings"))
        controls = layout.column()
        controls.enabled = not state["bundled_readonly"]
        parameters(controls, settings.sprite_parameters)
        dirty = state["sprite_dirty"]
        layout.label(text=tr("Unsaved panel edits" if dirty else "Panel matches loaded settings"), icon="DOT" if dirty else "CHECKMARK")
        source = layout.row()
        source.enabled = False
        source.prop(settings, "sprite_path", text=tr("Source"))
        controls = layout.column()
        controls.enabled = not state["bundled_readonly"]
        controls.operator("game_asset_tools.sprites", text=tr("Save Settings"), icon="FILE_TICK").action = "save"
        row = layout.row(align=True)
        row.enabled = scene_ready(settings, context) and not (state["bundled_readonly"] and dirty)
        row.operator("game_asset_tools.sprites", text=tr("Save + Preview" if dirty else "Preview")).action = "preview"
        row.operator("game_asset_tools.sprites", text=tr("Save + Export Atlas" if dirty else "Export Atlas")).action = "export"
        if settings.sprite_preview_path:
            layout.operator("game_asset_tools.open_sprite_image", text=tr("Open Last Preview"), icon="IMAGE_DATA").kind = "preview"
        if settings.sprite_atlas_path:
            layout.operator("game_asset_tools.open_sprite_image", text=tr("Open Last Atlas"), icon="IMAGE_DATA").kind = "atlas"
        layout.label(text=status_text(settings, "sprite_status", context))


class GAT_PT_library(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_library"
    bl_options = {"DEFAULT_CLOSED"}
    title = "Component Library"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        layout.enabled = scene_ready(settings, context)
        prop(layout, settings, "library_manifest", "Part Manifest")
        row = layout.row(align=True)
        row.operator("game_asset_tools.library_action", text=tr("Register Interfaces")).action = "register"
        row.operator("game_asset_tools.library_action", text=tr("Validate Component")).action = "validate"
        prop(layout, settings, "library_root", "Part Library")
        prop(layout, settings, "library_part_id", "Part ID")
        prop(layout, settings, "library_revision", "Part Revision")
        layout.label(text=tr("Select one component in Target to publish or install"))
        row = layout.row()
        row.enabled = settings.component not in (properties.ALL, properties.EMPTY)
        row.operator("game_asset_tools.library_action", text=tr("Publish Revision"), icon="EXPORT").action = "publish"
        row = layout.row(align=True)
        row.enabled = settings.component not in (properties.ALL, properties.EMPTY)
        row.operator("game_asset_tools.library_action", text=tr("Check Installation")).action = "plan"
        row.operator("game_asset_tools.library_action", text=tr("Install Component"), icon="IMPORT").action = "install"
        layout.label(text=tr("Install respects manual edits, locks and existing rig"))


class GAT_PT_output(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_output"
    bl_options = {"DEFAULT_CLOSED"}
    title = "Save and Export"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        prop(layout, settings, "output", "Output Folder")
        prop(layout, settings, "overwrite", "Overwrite Output")
        prop(layout, settings, "view_copy", "Save Viewing Copy")
        if settings.view_copy:
            prop(layout, settings, "save_view", "Opening View")
        prop(layout, settings, "export_animations", "Export Animations")
        if settings.export_animations:
            layout.label(text=tr("Preserve owned rig, skin and actions"))
        prop(layout, settings, "export_vertex_color_name", "Vertex Color Attribute")
        if settings.export_vertex_color_name:
            layout.label(text=tr("Named color attribute is required on every mesh"))
        row = layout.row(align=True)
        row.enabled = scene_ready(settings, context)
        action(row, "Save Blend", "save")
        action(row, "Export GLB", "export")


class GAT_PT_management(AssetSection, bpy.types.Panel):
    bl_idname = "GAT_PT_management"
    bl_options = {"DEFAULT_CLOSED"}
    title = "Validation and Protection"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        layout.enabled = scene_ready(settings, context)
        prop(layout, settings, "report_mode", "Validation Report")
        action(layout, "Validate", "validate")
        row = layout.row(align=True)
        prop(row, settings, "state", "State")
        action(row, "Set Target State", "status")
        prop(layout, settings, "replace_edited", "Replace Manually Edited Geometry")
        action(layout, "Delete Generated", "delete")


CLASSES = (GAT_PT_asset, GAT_PT_geometry, GAT_PT_preview, GAT_PT_materials,
           GAT_PT_sprites, GAT_PT_library, GAT_PT_output, GAT_PT_management)
