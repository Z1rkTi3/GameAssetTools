"""Blender user interface for the same Core used by the headless commands."""

from pathlib import Path
import sys

# Blender discovers this literal without importing; packaging checks its version.
bl_info = {
    "name": "GameAssetTools", "author": "GameAssetTools contributors", "version": (0, 4, 0),
    "blender": (4, 2, 0), "location": "View3D > Sidebar > GameAssetTools",
    "description": "Discover, build, inspect, preview, validate and export game asset recipes",
    "category": "Object",
}

# Release ZIPs contain a snapshot of the same source, never a separate Core fork.
_here = Path(__file__).resolve().parent
_source = _here / "bundled" if (_here / "bundled" / "game_asset_tools").is_dir() else _here.parents[1]
if str(_source) not in sys.path:
    sys.path.insert(0, str(_source))

from . import i18n, operators, panels, properties

_CLASSES = (*i18n.CLASSES, *properties.CLASSES, *operators.CLASSES, *panels.CLASSES)


def register():
    import bpy
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.game_asset_tools = bpy.props.PointerProperty(type=properties.GAT_Settings)
    properties.register_handlers()


def unregister():
    import bpy
    properties.unregister_handlers()
    if hasattr(bpy.types.Scene, "game_asset_tools"):
        del bpy.types.Scene.game_asset_tools
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    properties.clear_cache()
