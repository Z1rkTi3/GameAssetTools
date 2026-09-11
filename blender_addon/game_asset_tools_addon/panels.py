"""The generic asset sidebar; controls are derived from recipe metadata."""

import bpy


def action(layout, label, name, *, view=None, selected=False):
    operator = layout.operator("game_asset_tools.action", text=label)
    operator.action, operator.selected = name, selected
    if view:
        operator.view = view


class GAT_PT_asset(bpy.types.Panel):
    bl_label = "GameAssetTools"
    bl_idname = "GAT_PT_asset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GameAssetTools"

    def draw(self, context):
        layout, settings = self.layout, context.scene.game_asset_tools
        layout.prop(settings, "project")
        layout.operator("game_asset_tools.refresh")
        layout.prop(settings, "category")
        layout.prop(settings, "asset")
        layout.prop(settings, "stage")
        row = layout.row(align=True)
        action(row, "Build", "build")
        action(row, "Rebuild", "rebuild")
        layout.prop(settings, "component")
        action(layout, "Delete Generated", "delete")
        layout.prop(settings, "replace_edited")
        box = layout.box()
        box.label(text="Parameters")
        for item in settings.parameters:
            box.prop(item, item.kind + "_value", text=item.label)
            if item.bounds:
                box.label(text=item.bounds)
        box = layout.box()
        box.label(text="Preview")
        box.prop(settings, "resolution")
        for names in (("front", "back"), ("left", "right"), ("top", "perspective")):
            row = box.row(align=True)
            for name in names:
                action(row, name.title(), "preview", view=name)
        action(box, "Render All Views", "preview", view="all")
        row = layout.row(align=True)
        action(row, "Inspect Target", "inspect")
        action(row, "Inspect Selected", "inspect", selected=True)
        action(layout, "Validate", "validate")
        row = layout.row(align=True)
        row.prop(settings, "state", text="")
        action(row, "Set Target State", "status")
        layout.prop(settings, "output")
        layout.prop(settings, "overwrite")
        row = layout.row(align=True)
        action(row, "Save Blend", "save")
        action(row, "Export GLB", "export")
        layout.label(text=settings.last_status)
        layout.operator("game_asset_tools.show_report")


CLASSES = (GAT_PT_asset,)
