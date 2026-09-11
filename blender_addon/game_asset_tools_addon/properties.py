"""Recipe-driven controls and persistent UI state; no asset-specific branches."""

import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from game_asset_tools.asset.parameters import get_value, load_config
from game_asset_tools.asset.registry import Registry

# Blender borrows callback string storage. Keep enum tuples alive until unregister.
_enum_storage = {}
_registries = {}
EMPTY = "__NONE__"
ALL = "__ALL__"


def default_project():
    here = Path(__file__).resolve().parent
    return here / "bundled" if (here / "bundled" / "game_assets").is_dir() else here.parents[1]


def project_root(settings):
    return Path(bpy.path.abspath(settings.project)).resolve() if settings.project else default_project()


def registry(settings):
    path = str(project_root(settings))
    if path not in _registries:
        _registries[path] = Registry(Path(path))
    return _registries[path]


def clear_cache():
    _registries.clear()
    _enum_storage.clear()


def _remember(key, items):
    value = tuple(items)
    return _enum_storage.setdefault((key, value), value)


def category_items(self, context):
    try:
        categories = sorted({entry.category for entry in registry(self).list()})
        return _remember("categories", [(name, name.replace("_", " ").title(), name) for name in categories]) or _remember("empty", [(EMPTY, "No recipes", "Set a project containing game_assets")])
    except (OSError, ValueError) as exc:
        self.last_status = str(exc)
        return _remember("error", [(EMPTY, "Cannot discover recipes", str(exc))])


def asset_items(self, context):
    try:
        entries = [entry for entry in registry(self).list() if entry.category == self.category]
        return _remember("assets", [(entry.id, entry.display_name, entry.id) for entry in entries]) or _remember("empty-assets", [(EMPTY, "No recipes", "Refresh after adding a recipe")])
    except (OSError, ValueError) as exc:
        self.last_status = str(exc)
        return _remember("error-assets", [(EMPTY, "Cannot discover recipes", str(exc))])


def component_items(self, context):
    items = [(ALL, "Whole Asset", "Operate on the full asset or changed components")]
    try:
        entry = registry(self).get(self.asset)
        specs = entry.load().components(load_config(entry))
        items += [(key, key.replace("_", " "), spec.collection) for key, spec in specs.items()]
    except (OSError, ValueError):
        pass
    return _remember("components", items)


def stage_items(self, context):
    try:
        stages = registry(self).get(self.asset).supported_stages
    except (OSError, ValueError):
        stages = ("BLOCKOUT",)
    return _remember("stages", [(stage, stage.title(), stage) for stage in stages])


def choice_items(self, context):
    choices = json.loads(self.choices_json or "[]")
    return _remember("choices", [(value, value.replace("_", " "), value) for value in choices]) or _remember("empty-choice", [(EMPTY, "None", "No choices")])


def load_parameters(settings, *, scene_values=True):
    """Load disk defaults, or the last successful scene configuration if available."""
    settings.parameters.clear()
    if settings.asset == EMPTY:
        return
    try:
        entry = registry(settings).get(settings.asset)
        config = load_config(entry)
        if scene_values:
            from game_asset_tools.asset.scene import find_root
            root = find_root(entry.id, required=False)
            if root:
                config = json.loads(root["gat_config"])
                settings.stage = root.get("gat_stage", "BLOCKOUT")
            else:
                settings.stage = "BLOCKOUT"
        for parameter in entry.load().parameters:
            item = settings.parameters.add()
            item.path, item.label, item.kind = parameter.path, parameter.label, parameter.type
            item.original_json = json.dumps(get_value(config["parameters"], parameter.path))
            item.choices_json = json.dumps(parameter.choices)
            item.bounds = "" if parameter.min is None and parameter.max is None else f"Range: {parameter.min if parameter.min is not None else 'any'} to {parameter.max if parameter.max is not None else 'any'}"
            setattr(item, parameter.type + "_value", get_value(config["parameters"], parameter.path))
        settings.last_status = f"Loaded {entry.display_name}"
    except (OSError, ValueError, KeyError) as exc:
        settings.last_status = str(exc)


def _asset_changed(self, context):
    load_parameters(self)
    self.component = ALL


def _category_changed(self, context):
    items = asset_items(self, context)
    self.asset = items[0][0]


def _project_changed(self, context):
    _registries.clear()
    self.category = category_items(self, context)[0][0]


class GAT_Parameter(bpy.types.PropertyGroup):
    path: StringProperty()
    label: StringProperty()
    kind: StringProperty()
    bounds: StringProperty()
    choices_json: StringProperty(default="[]")
    original_json: StringProperty(default="null")
    float_value: FloatProperty(name="Value", precision=3)
    int_value: IntProperty(name="Value")
    bool_value: BoolProperty(name="Value")
    str_value: StringProperty(name="Value")
    enum_value: EnumProperty(name="Value", items=choice_items)


class GAT_Settings(bpy.types.PropertyGroup):
    project: StringProperty(name="Project", subtype="DIR_PATH", description="Folder containing game_assets and game_style.json; empty uses bundled examples", update=_project_changed)
    category: EnumProperty(name="Category", items=category_items, update=_category_changed)
    asset: EnumProperty(name="Asset", items=asset_items, update=_asset_changed)
    stage: EnumProperty(name="Stage", items=stage_items)
    component: EnumProperty(name="Target", items=component_items)
    parameters: CollectionProperty(type=GAT_Parameter)
    output: StringProperty(name="Output Folder", subtype="DIR_PATH", description="Empty uses the project's output folder")
    overwrite: BoolProperty(name="Overwrite Output", default=False, description="Allow save, preview and export to replace existing output files")
    replace_edited: BoolProperty(name="Replace Manually Edited Geometry", default=False, description="Explicitly replace edited generated geometry; locked or approved components remain protected")
    resolution: EnumProperty(name="Resolution", items=[(str(n), f"{n} × {n}", str(n)) for n in (256, 512, 1024)], default="512")
    state: EnumProperty(name="Component State", items=[(s, s.title(), s) for s in ("editable", "approved", "locked")])
    last_status: StringProperty(name="Status", default="Refresh recipes to begin")
    report_text: StringProperty(name="Report Text")


CLASSES = (GAT_Parameter, GAT_Settings)
