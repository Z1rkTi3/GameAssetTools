"""Общий пользовательский workflow библиотеки поверх проверенных Core API.

Контракты и явные ссылки сохраняются в component record самого .blend.
Регистрация не принимает геометрию за новую и не обновляет fingerprints.
"""
from dataclasses import asdict, replace
import json
from pathlib import Path

from game_asset_tools.asset.metadata import encode
from game_asset_tools.asset.scene import component_records, find_root
from .contracts import Issue, check_compatibility, part_from_dict, rig_from_dict, slot_from_dict
from .inspection import ObjectRef, inspect_part
from .library import LibraryError, publish_part

INTERFACE_KEY = "assembly_interface"
FIELDS = {"part", "slot", "rig", "armature", "objects", "sockets", "contacts"}


def _error(component, field, message):
    raise LibraryError((Issue("error", "authoring_document", component, field, "проверенное явное описание", None,
                             message, "Исправьте manifest и повторите регистрацию; сборка сохранена"),))


def _reference(value, component, field):
    if (not isinstance(value, dict) or set(value) != {"component", "local_name"}
            or any(not isinstance(v, str) or not v.strip() for v in value.values())):
        _error(component, field, "Нужен ObjectRef с непустыми component и local_name")
    return ObjectRef(**value)


def interface_to_dict(part, slot, rig, *, armature, objects, sockets, contacts):
    """Единый сохраняемый формат для регистрации и результата установки."""
    return {"part": asdict(part), "slot": asdict(slot), "rig": asdict(rig), "armature": asdict(armature),
            **{kind: {key: asdict(ref) for key, ref in mapping.items()}
               for kind, mapping in (("objects", objects), ("sockets", sockets), ("contacts", contacts))}}


def _parse(value, component):
    if not isinstance(value, dict) or set(value) != FIELDS:
        _error(component, "interface", "Набор полей интерфейса не соответствует схеме")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        _error(component, "interface", "Manifest должен содержать только конечные JSON-значения")
    part, slot, rig = part_from_dict(value["part"]), slot_from_dict(value["slot"]), rig_from_dict(value["rig"])
    mappings = {"armature": _reference(value["armature"], component, "armature")}
    for kind in ("objects", "sockets", "contacts"):
        mapping = value[kind]
        if not isinstance(mapping, dict) or any(not isinstance(key, str) or not key for key in mapping):
            _error(component, kind, "Ожидается таблица явных ObjectRef по стабильным ID")
        mappings[kind] = {key: _reference(ref, component, kind + "." + key) for key, ref in mapping.items()}
    issues = check_compatibility(part, slot, rig)
    if issues:
        raise LibraryError(issues)
    return part, slot, rig, mappings


def _inspect(asset_id, component, interface):
    part, _, rig, mappings = interface
    report = inspect_part(asset_id, component, part, rig, **mappings)
    if report["status"] != "pass":
        raise LibraryError(Issue(**issue) for issue in report["issues"])
    return report


def register_document(asset_id, document, component=None):
    """Проверяет документ .parts.json до единственной атомарной записи records.

component=None регистрирует все interfaces; явное имя — только выбранный узел.
Дополнительные поля отчёта (source hashes, paths) не исполняются и не записываются.
"""
    if not isinstance(document, dict) or not isinstance(document.get("interfaces"), dict) or not document["interfaces"]:
        _error(component or "assembly", "interfaces", "Нужен непустой объект interfaces")
    if "schema_version" in document and (type(document["schema_version"]) is not int or document["schema_version"] != 1):
        _error(component or "assembly", "schema_version", "Неподдерживаемая версия документа")
    if document.get("asset", asset_id) != asset_id:
        _error(component or "assembly", "asset", "Документ принадлежит другому asset")
    root = find_root(asset_id)
    records = component_records(root)
    names = [component] if component is not None else list(document["interfaces"])
    parsed = {}
    for name in names:
        if not isinstance(name, str) or name not in records or name not in document["interfaces"] or records[name].get("persistent"):
            _error(str(name), "component", "Компонент отсутствует в документе/сборке либо является постоянным")
        parsed[name] = _parse(document["interfaces"][name], name)
        _inspect(asset_id, name, parsed[name])
    for name, (part, slot, rig, mappings) in parsed.items():
        records[name] = {**records[name], INTERFACE_KEY: interface_to_dict(part, slot, rig, **mappings)}
    before = root["gat_components"]
    try:
        root["gat_components"] = encode(records)
    except BaseException:
        root["gat_components"] = before
        raise
    return {"status": "registered", "asset": asset_id, "components": names}


def load_document(path):
    """Только JSON: путь не загружает Python-код и не выбирает asset автоматически."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def get_interface(asset_id, component):
    record = component_records(find_root(asset_id)).get(component, {})
    if INTERFACE_KEY not in record:
        _error(component, INTERFACE_KEY, "Сначала загрузите и зарегистрируйте manifest этого компонента")
    return _parse(record[INTERFACE_KEY], component)


def _library_root(value, component):
    if value is None or not str(value).strip():
        _error(component, "library_root", "Укажите явную папку библиотеки")
    return Path(value)


def validate_component(asset_id, component):
    return _inspect(asset_id, component, get_interface(asset_id, component))


def publish_component(library_root, asset_id, component, part_id, revision):
    """Публикует текущую форму под явным ID/revision без принятия ручных правок."""
    part, _, rig, mappings = get_interface(asset_id, component)
    _inspect(asset_id, component, (part, None, rig, mappings))
    entry = publish_part(_library_root(library_root, component), asset_id, component,
                         replace(part, id=part_id, revision=revision), rig, **mappings)
    return {"status": "published", "asset": asset_id, "component": component,
            "part": asdict(entry.part), "payload_sha256": entry.payload_sha256}


def install_component(library_root, asset_id, component, candidate_id, candidate_revision, *, dry_run=False):
    from .replacement import replace_part
    part, slot, rig, mappings = get_interface(asset_id, component)
    return replace_part(_library_root(library_root, component), asset_id, component, part, slot, rig, candidate_id, candidate_revision,
                        **mappings, dry_run=dry_run)
