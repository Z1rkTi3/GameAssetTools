"""Recipe-driven controls with project/asset/scene-bound session drafts."""

import hashlib
import json
import math
from pathlib import Path
import zlib

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

from game_asset_tools.asset.parameters import get_value, load_config
from game_asset_tools.asset.registry import Registry

from . import session
from .i18n import set_status, tr

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
    # Enum strings remain alive while Blender can still borrow their pointers.


def is_bundled_readonly(settings, *, addon_file=None):
    bundled = Path(addon_file or __file__).resolve().parent / "bundled"
    return project_root(settings) == bundled.resolve()


def _enum_number(identifier):
    # Stable numeric values survive discovery order and UI language changes.
    return zlib.crc32(identifier.encode("utf-8")) & 0x7fffffff


def _items(key, items, context=None):
    return _remember(key, [(identifier, tr(label, context), tr(description, context),
                            _enum_number(identifier) if key in {"choices", "stages"} else index)
                           for index, (identifier, label, description) in enumerate(items)])


def _remember(key, items):
    value = tuple(items)
    return _enum_storage.setdefault((key, value), value)


def category_items(self, context):
    try:
        categories = sorted({entry.category for entry in registry(self).list()})
        return _items("categories", [(name, name.replace("_", " ").title(), name) for name in categories], context) or _items("empty", [(EMPTY, "No recipes", "Set a project containing game_assets")], context)
    except (OSError, ValueError) as exc:
        self.last_status = str(exc)
        return _items("error", [(EMPTY, "Cannot discover recipes", str(exc))], context)


def asset_items(self, context):
    try:
        entries = [entry for entry in registry(self).list() if entry.category == self.category]
        if entries:
            choices = list(_items("assets", [(entry.id, entry.display_name, entry.id) for entry in entries], context))
            choices.append((EMPTY, tr("Choose an asset", context), tr("Choose an asset explicitly", context), -1))
            return _remember("assets-with-placeholder", choices)
        return _items("empty-assets", [(EMPTY, "No recipes", "Refresh after adding a recipe")], context)
    except (OSError, ValueError) as exc:
        self.last_status = str(exc)
        return _items("error-assets", [(EMPTY, "Cannot discover recipes", str(exc))], context)


def component_items(self, context):
    items = [(ALL, "Whole Asset", "Operate on the full asset or changed components")]
    try:
        entry = registry(self).get(self.asset)
        specs = entry.load().components(load_config(entry))
        items += [(key, key.replace("_", " "), spec.collection) for key, spec in specs.items()]
    except (OSError, ValueError):
        pass
    return _items("components", items, context)


def stage_items(self, context):
    try:
        stages = registry(self).get(self.asset).supported_stages
    except (OSError, ValueError):
        stages = ("BLOCKOUT",)
    return _items("stages", [(stage, stage.title(), stage) for stage in stages], context)


def material_role_items(self, context):
    from game_asset_tools.asset.scene import asset_objects
    from game_asset_tools.inspection.materials import material_role
    try:
        root = scene_root(self)
    except ValueError:
        root = None
    style = json.loads(root.get("gat_style", "{}")) if root else {}
    roles = {material_role(slot.material, style) for obj in asset_objects(root) for slot in obj.material_slots} if root else set()
    return _items("material-roles", [(role, role, "Recorded material role") for role in sorted(roles - {None})], context) or _items("empty-roles", [(EMPTY, "Build an asset first", "No assigned roles")], context)


def choice_items(self, context):
    choices = json.loads(self.choices_json or "[]")
    return _items("choices", [(str(value), str(value).replace("_", " "), str(value)) for value in choices], context) or _items("empty-choice", [(EMPTY, "None", "No choices")], context)


def _choice_get(self):
    choices = json.loads(self.choices_json or "[]")
    default = choices[0] if choices else EMPTY
    return _enum_number(str(session.get_value(self, default)))


def _choice_set(self, value):
    for choice in json.loads(self.choices_json or "[]"):
        if _enum_number(str(choice)) == value:
            session.set_value(self, int(choice) if self.kind == "int" else float(choice) if self.kind == "float" else choice)
            break


def _stage_get(self):
    return _enum_number(session.stages.get(session.scene_id(self), "BLOCKOUT"))


def _stage_set(self, value):
    for identifier, *_ in stage_items(self, None):
        if _enum_number(identifier) == value:
            session.stages[session.scene_id(self)] = identifier
            break


def _key(settings):
    return session.scene_id(settings), str(project_root(settings)), settings.asset


def scene_roots(settings):
    return [collection for collection in settings.id_data.collection.children_recursive
            if collection.get("gat_role") == "asset_root" and collection.get("gat_asset_id")]


def scene_root(settings):
    roots = [root for root in scene_roots(settings) if root.get("gat_asset_id") == settings.asset]
    if len(roots) > 1:
        raise ValueError(tr("Multiple asset roots; resolve duplicate identity"))
    return roots[0] if roots else None


def _root_source(settings, root, *, bind=False):
    if root is None:
        return None
    key = session.scene_id(settings), root.as_pointer()
    project = str(project_root(settings))
    if bind and settings.project:
        return session.root_projects.setdefault(key, project)
    return session.root_projects.get(key, project)


def _geometry_source(settings, entry, scene_values=True):
    config = load_config(entry)
    stage = "BLOCKOUT" if "BLOCKOUT" in entry.supported_stages else entry.supported_stages[0]
    root = scene_root(settings)
    if scene_values and root and _root_source(settings, root) == str(project_root(settings)):
        config = json.loads(root["gat_config"])
        stage = root.get("gat_stage", stage)
    # Sprite-only edits must not invalidate geometry drafts.
    data = {"parameters": config["parameters"], "stage": stage,
            "recipe": hashlib.sha256((entry.path / "asset.py").read_bytes()).hexdigest()}
    revision = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return config, stage, revision


def parameter_updates(items):
    result = {}
    for item in items:
        value, original = getattr(item, item.kind + "_value"), json.loads(item.original_json)
        unchanged = math.isclose(value, original, rel_tol=1e-6, abs_tol=1e-7) if item.kind == "float" else value == original
        if not unchanged:
            result[item.path] = value
    return result


def geometry_updates(settings, *, check_revision=False):
    source = session.geometry_sources.get(session.scene_id(settings))
    if not source or source["key"] != _key(settings):
        raise ValueError(tr("Load geometry settings for the selected project and asset first"))
    updates = parameter_updates(settings.parameters)
    entry = registry(settings).get(settings.asset)
    if check_revision:
        if source["revision"] != _geometry_source(settings, entry)[2]:
            raise ValueError(tr("Geometry settings conflict: the source changed; reload geometry settings before rebuilding"))
    # RNA хранит FloatProperty как float32. Точная UI-копия объявленной границы
    # может оказаться чуть вне её float64-значения (.18 → .180000007...).
    # Узнаём именно этот round-trip, без допуска/обрезания произвольных чисел.
    # JSON/CLI по-прежнему проходят строгий Parameter.validate без этой поправки.
    import struct
    for parameter in entry.load().parameters:
        if parameter.type != "float" or parameter.path not in updates:
            continue
        for bound in (parameter.min, parameter.max):
            if bound is None:
                continue
            try:
                rna_bound = struct.unpack("<f", struct.pack("<f", float(bound)))[0]
            except OverflowError:
                continue
            if updates[parameter.path] == rna_bound:
                updates[parameter.path] = float(bound)
                break
    return updates


def geometry_dirty(settings):
    source = session.geometry_sources.get(session.scene_id(settings))
    return bool(source and (parameter_updates(settings.parameters) or settings.stage != source["stage"]))


def sprite_dirty(settings):
    return bool(settings.sprite_revision and parameter_updates(settings.sprite_parameters))


def _snapshot(items):
    return [{"path": item.path, "label": item.label, "kind": item.kind, "bounds": item.bounds,
             "choices_json": item.choices_json, "original_json": item.original_json,
             "value": getattr(item, item.kind + "_value")} for item in items]


def _restore(items, records):
    session.clear_parameters(items)
    for record in records:
        item = items.add()
        for key, value in record.items():
            if key != "value":
                setattr(item, key, value)
        setattr(item, item.kind + "_value", record["value"])


def stash_drafts(settings):
    """Snapshot the old selection even when its RNA selector already changed."""
    key = session.active.get(session.scene_id(settings))
    if not key:
        return
    draft = session.drafts.setdefault(key, {})
    if geometry_dirty(settings):
        draft["geometry"] = {"items": _snapshot(settings.parameters), "stage": settings.stage,
                             "source": dict(session.geometry_sources[session.scene_id(settings)])}
    else:
        draft.pop("geometry", None)
    if sprite_dirty(settings):
        draft["sprite"] = {"items": _snapshot(settings.sprite_parameters),
                           **{name: getattr(settings, name) for name in ("sprite_revision", "sprite_path", "sprite_project", "sprite_asset")}}
    else:
        draft.pop("sprite", None)
    if not draft:
        session.drafts.pop(key, None)


def _load_selection(settings):
    key = _key(settings)
    session.active[session.scene_id(settings)] = key
    load_parameters(settings, preserve_draft=True)
    load_sprite_settings(settings, preserve_draft=True)
    settings.component = ALL
    session.selection[(key[0], key[1])] = (settings.category, settings.asset)


def load_parameters(settings, *, scene_values=True, preserve_draft=False):
    """Load disk defaults, or the last successful scene configuration if available."""
    key = _key(settings)
    draft = session.drafts.get(key, {}).get("geometry") if preserve_draft else None
    if draft:
        _restore(settings.parameters, draft["items"])
        session.stages[session.scene_id(settings)] = draft["stage"]
        session.geometry_sources[session.scene_id(settings)] = dict(draft["source"])
        return
    session.drafts.get(key, {}).pop("geometry", None)
    session.clear_parameters(settings.parameters)
    session.geometry_sources.pop(session.scene_id(settings), None)
    session.stages[session.scene_id(settings)] = "BLOCKOUT"
    if settings.asset == EMPTY:
        return
    try:
        entry = registry(settings).get(settings.asset)
        config, stage, revision = _geometry_source(settings, entry, scene_values)
        if stage not in entry.supported_stages:
            raise ValueError(tr("Saved stage is unavailable in this recipe; select its original project"))
        parameters = entry.load().parameters
        values = [get_value(config["parameters"], parameter.path) for parameter in parameters]
        if scene_values:
            _root_source(settings, scene_root(settings), bind=True)
        settings.stage = stage
        session.geometry_sources[session.scene_id(settings)] = {"key": key, "revision": revision, "stage": stage}
        for parameter, value in zip(parameters, values):
            item = settings.parameters.add()
            item.path, item.label, item.kind = parameter.path, parameter.label, parameter.type
            item.original_json = json.dumps(value)
            item.choices_json = json.dumps(parameter.choices)
            item.bounds = "" if parameter.min is None and parameter.max is None else f"Range: {parameter.min if parameter.min is not None else 'any'} to {parameter.max if parameter.max is not None else 'any'}"
            setattr(item, parameter.type + "_value", value)
        set_status(settings, "last_status", "Loaded {name}", name=entry.display_name)
    except (OSError, ValueError, KeyError) as exc:
        settings.last_status = str(exc)


def apply_sprite_settings(settings, result):
    """Display the canonical Core profile using its field schema."""
    from game_asset_tools.sprites.settings import FIELDS
    if settings.sprite_asset != settings.asset or settings.sprite_project != str(project_root(settings)):
        settings.sprite_preview_path = ""
        settings.sprite_atlas_path = ""
    session.clear_parameters(settings.sprite_parameters)
    for field in FIELDS:
        item = settings.sprite_parameters.add()
        item.path, item.label, item.kind = field["key"], field["label"], field["type"]
        value = result["settings"][field["key"]]
        item.original_json = json.dumps(value)
        item.choices_json = json.dumps(field.get("choices", ()))
        lower, upper = field.get("min"), field.get("max")
        item.bounds = "" if lower is None and upper is None else f"Range: {lower} to {upper}"
        if field.get("choices") and field["type"] != "enum":
            item.bounds = "Choices: " + ", ".join(str(value) for value in field["choices"])
        setattr(item, item.kind + "_value", value)
    settings.sprite_revision = result["revision"]
    settings.sprite_path = str(result["path"])
    settings.sprite_project = str(project_root(settings))
    settings.sprite_asset = settings.asset
    session.drafts.get(_key(settings), {}).pop("sprite", None)
    set_status(settings, "sprite_status", "Loaded saved settings")


def load_sprite_settings(settings, *, preserve_draft=False):
    """Read recipe config.json, independently of the .blend geometry config."""
    draft = session.drafts.get(_key(settings), {}).get("sprite") if preserve_draft else None
    if draft:
        _restore(settings.sprite_parameters, draft["items"])
        for name, value in draft.items():
            if name != "items":
                setattr(settings, name, value)
        set_status(settings, "sprite_status", "Unsaved sprite settings restored")
        settings.sprite_preview_path = ""
        settings.sprite_atlas_path = ""
        return
    session.drafts.get(_key(settings), {}).pop("sprite", None)
    session.clear_parameters(settings.sprite_parameters)
    settings.sprite_revision = ""
    settings.sprite_path = ""
    settings.sprite_project = ""
    settings.sprite_asset = ""
    settings.sprite_preview_path = ""
    settings.sprite_atlas_path = ""
    if settings.asset == EMPTY:
        set_status(settings, "sprite_status", "Select an asset to load sprite settings")
        return
    try:
        from game_asset_tools.sprites.settings import read_settings
        apply_sprite_settings(settings, read_settings(project_root(settings), settings.asset))
    except (OSError, ValueError, KeyError) as exc:
        settings.sprite_status = str(exc)


def sprite_updates(settings):
    """Return edited fields only; Core owns validation and persisted defaults."""
    if not settings.sprite_revision or settings.sprite_asset != settings.asset or settings.sprite_project != str(project_root(settings)):
        raise ValueError(tr("Load sprite settings for the selected project and asset first"))
    return parameter_updates(settings.sprite_parameters)


def _asset_changed(self, context):
    if session.suspended(self):
        return
    stash_drafts(self)
    _load_selection(self)


def _category_changed(self, context):
    if session.suspended(self):
        return
    stash_drafts(self)
    with session.suspend(self):
        self.asset = asset_items(self, context)[0][0]
    _load_selection(self)


def _project_changed(self, context):
    if not session.suspended(self):
        refresh_selection(self, context, project_changed=True)


def refresh_selection(settings, context=None, *, project_changed=False, opening=False):
    stash_drafts(settings)
    clear_cache()
    categories = category_items(settings, context)
    remembered = session.selection.get((session.scene_id(settings), str(project_root(settings))))
    category, asset = remembered if project_changed and remembered else (settings.category, settings.asset)
    entries = []
    try:
        entries = registry(settings).list()
        roots = scene_roots(settings)
        # Multiple roots require the user's explicit recipe/selected-object choice.
        if len(roots) == 1:
            entry = next((entry for entry in entries if entry.id == roots[0]["gat_asset_id"]), None)
            if entry is not None:
                category, asset = entry.category, entry.id
        elif len(roots) > 1 and opening:
            asset = EMPTY
    except (OSError, ValueError):
        pass
    with session.suspend(settings):
        settings.category = category if category in {item[0] for item in categories} else categories[0][0]
        assets = asset_items(settings, context)
        available_ids = {entry.id for entry in entries}
        if asset == EMPTY and not any(root["gat_asset_id"] in available_ids for root in scene_roots(settings)):
            asset = assets[0][0]
        settings.asset = asset if asset in {item[0] for item in assets} else assets[0][0]
    _load_selection(settings)
    if settings.asset == EMPTY:
        set_status(settings, "last_status", "No recipes found. Choose a project containing game_assets, then refresh")


def select_asset(settings, asset_id, context=None):
    entry = registry(settings).get(asset_id)
    stash_drafts(settings)
    with session.suspend(settings):
        settings.category = entry.category
        settings.asset = entry.id
    _load_selection(settings)


def scene_state(settings, context=None):
    context = context or bpy.context
    state = {"recipe_available": False, "root": None, "asset_available": False,
             "selected_component": None, "selected_asset_id": None,
             "bundled_readonly": is_bundled_readonly(settings), "geometry_dirty": geometry_dirty(settings),
             "sprite_dirty": sprite_dirty(settings), "source_mismatch": False, "reason": ""}
    try:
        registry(settings).get(settings.asset)
        state["recipe_available"] = True
        state["root"] = root = scene_root(settings)
        state["source_mismatch"] = bool(root and _root_source(settings, root) != str(project_root(settings)))
        state["asset_available"] = bool(root and not state["source_mismatch"])
        if state["source_mismatch"]:
            state["reason"] = "The scene asset belongs to another project selected in this session"
        elif root is None:
            state["reason"] = "Build the selected asset first"
    except (OSError, ValueError, KeyError) as exc:
        state["reason"] = "Choose an asset explicitly" if settings.asset == EMPTY else str(exc)
    obj = context.active_object
    if obj and obj.get("gat_asset_id"):
        matches = [item for item in scene_roots(settings) if item.get("gat_asset_id") == obj.get("gat_asset_id") and obj.name in item.all_objects]
        if len(matches) == 1:
            state["selected_asset_id"] = obj["gat_asset_id"]
            if state["asset_available"] and obj.get("gat_asset_id") == settings.asset and obj.get("gat_generated"):
                state["selected_component"] = obj.get("gat_component")
    return state


@bpy.app.handlers.persistent
def _load_post(_unused):
    session.clear()
    clear_cache()
    for scene in bpy.data.scenes:
        if hasattr(scene, "game_asset_tools"):
            refresh_selection(scene.game_asset_tools, opening=True)


def register_handlers():
    unregister_handlers()
    bpy.app.handlers.load_post.append(_load_post)
    # Blender restricts scene access while enabling an add-on in Preferences.
    if hasattr(bpy.data, "scenes"):
        _load_post(None)
    else:
        bpy.app.timers.register(_initialize, first_interval=0.0)


def _initialize():
    _load_post(None)
    return None


def unregister_handlers():
    if bpy.app.timers.is_registered(_initialize):
        bpy.app.timers.unregister(_initialize)
    for handler in list(bpy.app.handlers.load_post):
        if handler is _load_post or (getattr(handler, "__module__", None) == __name__ and getattr(handler, "__name__", None) == "_load_post"):
            bpy.app.handlers.load_post.remove(handler)
    session.clear()
    clear_cache()
    _enum_storage.clear()


class GAT_Parameter(bpy.types.PropertyGroup):
    path: StringProperty()
    label: StringProperty()
    kind: StringProperty()
    bounds: StringProperty()
    choices_json: StringProperty(default="[]")
    original_json: StringProperty(default="null")
    float_value: FloatProperty(name="Value", precision=3, get=lambda self: float(session.get_value(self, 0.0)), set=session.set_value)
    int_value: IntProperty(name="Value", get=lambda self: int(session.get_value(self, 0)), set=session.set_value)
    bool_value: BoolProperty(name="Value", get=lambda self: bool(session.get_value(self, False)), set=session.set_value)
    str_value: StringProperty(name="Value", get=lambda self: str(session.get_value(self, "")), set=session.set_value)
    enum_value: EnumProperty(name="Value", items=choice_items, get=_choice_get, set=_choice_set)
    choice_value: EnumProperty(name="Value", items=choice_items, get=_choice_get, set=_choice_set)


def state_items(self, context):
    return _items("states", [(state, state.title(), state) for state in ("editable", "approved", "locked")], context)


def report_mode_items(self, context):
    return _items("report-modes", [(value, label, "Validation output only") for value, label in
                  (("stdout", "In-app report"), ("unique", "New report file"),
                   ("replace", "Replace report only"), ("file", "Protected report file"))], context)


def view_items(self, context):
    return _items("views", [(view, view.title(), view) for view in ("front", "back", "left", "right", "top", "perspective")], context)


class GAT_Settings(bpy.types.PropertyGroup):
    project: StringProperty(name="Project", subtype="DIR_PATH", description="Folder containing game_assets and game_style.json; empty uses bundled examples", update=_project_changed)
    category: EnumProperty(name="Category", items=category_items, update=_category_changed)
    asset: EnumProperty(name="Asset", items=asset_items, update=_asset_changed)
    stage: EnumProperty(name="Stage", items=stage_items, get=_stage_get, set=_stage_set)
    component: EnumProperty(name="Target", items=component_items)
    parameters: CollectionProperty(type=GAT_Parameter)
    sprite_parameters: CollectionProperty(type=GAT_Parameter)
    sprite_revision: StringProperty(options={"HIDDEN"})
    sprite_path: StringProperty(name="Settings File", options={"HIDDEN"})
    sprite_project: StringProperty(options={"HIDDEN"})
    sprite_asset: StringProperty(options={"HIDDEN"})
    sprite_preview_path: StringProperty(options={"HIDDEN"})
    sprite_atlas_path: StringProperty(options={"HIDDEN"})
    sprite_status: StringProperty(name="Sprite Status", default="Load saved sprite settings to begin")
    output: StringProperty(name="Output Folder", subtype="DIR_PATH", description="Empty uses the project's output folder")
    overwrite: BoolProperty(name="Overwrite Output", default=False, description="Allow save, preview and export to replace existing output files")
    replace_edited: BoolProperty(name="Replace Manually Edited Geometry", default=False, description="Explicitly replace edited generated geometry; locked or approved components remain protected")
    resolution: EnumProperty(name="Resolution", items=[(str(n), f"{n} × {n}", str(n)) for n in (256, 512, 1024)], default="512")
    state: EnumProperty(name="Component State", items=state_items)
    last_status: StringProperty(name="Status", default="Refresh recipes to begin")
    report_text: StringProperty(name="Report Text")
    material_role: EnumProperty(name="Material Role", items=material_role_items)
    material_color: FloatVectorProperty(name="Base Color", subtype="COLOR", size=4, min=0, max=1, default=(0.2, 0.4, 0.6, 1))
    report_mode: EnumProperty(name="Validation Report", items=report_mode_items, default=0)
    view_copy: BoolProperty(name="Save Viewing Copy", default=False)
    save_view: EnumProperty(name="Opening View", items=view_items, default=5)


CLASSES = (GAT_Parameter, GAT_Settings)
