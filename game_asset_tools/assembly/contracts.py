"""Версионируемые контракты соединений без Blender и без изменения сцены.

Матрицы rest/input/output заданы в пространстве рига, bind_frame — кости.
Проверка описания не заменяет проверку фактического меша и контрольных поз.
"""

from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re

SCHEMA_VERSION = 1
TOLERANCE = 1e-5
Vec3 = tuple[float, float, float]
Basis = tuple[Vec3, Vec3, Vec3]
IDENTITY: Basis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    component: str
    field: str
    expected: object
    actual: object
    message: str
    remedy: str


class ContractError(ValueError):
    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__(f"{issue.component}/{issue.field}: {issue.message}. {issue.remedy}")


@dataclass(frozen=True)
class Frame:
    origin: Vec3
    basis: Basis


@dataclass(frozen=True)
class Coordinates:
    units: str
    up: str
    forward: str


@dataclass(frozen=True)
class Bone:
    id: str
    parent: str | None
    rest: Frame


@dataclass(frozen=True)
class JointLimit:
    bone: str
    axis: Vec3
    lower: float
    upper: float


@dataclass(frozen=True)
class Port:
    id: str
    interface: str
    bone: str
    frame: Frame


@dataclass(frozen=True)
class RigidBinding:
    object_id: str
    bone: str
    bind_frame: Frame


@dataclass(frozen=True)
class SoleContact:
    id: str
    bone: str
    position: Vec3


@dataclass(frozen=True)
class RigContract:
    schema_version: int
    id: str
    revision: int
    coordinates: Coordinates
    bones: tuple[Bone, ...]
    joints: tuple[JointLimit, ...]


@dataclass(frozen=True)
class PartContract:
    schema_version: int
    id: str
    revision: int
    rig_id: str
    rig_revision: int
    coordinates: Coordinates
    input: Port
    outputs: tuple[Port, ...]
    bones: tuple[Bone, ...]
    bindings: tuple[RigidBinding, ...]
    contacts: tuple[SoleContact, ...]
    joints: tuple[JointLimit, ...]


@dataclass(frozen=True)
class SlotContract:
    schema_version: int
    slot_id: str
    rig_id: str
    rig_revision: int
    input: Port
    outputs: tuple[Port, ...]
    binding_bones: tuple[str, ...]
    contacts: tuple[SoleContact, ...]
    joints: tuple[JointLimit, ...]


def _fail(field, expected, actual, message, code="invalid_contract"):
    raise ContractError(Issue("error", code, "contract", field, expected, actual,
                              message, "Исправьте поле в исходном manifest; автоматическая подгонка не выполняется"))


def _object(value, fields, path):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        _fail(path, fields.split(), list(value) if isinstance(value, dict) else value,
              "Набор полей не соответствует схеме")
    return value


def _identifier(value, path):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        _fail(path, "буквы, цифры и _; начало с буквы", value, "Недопустимый стабильный ID")
    return value


def _integer(value, path):
    if type(value) is not int or value < 1:
        _fail(path, "положительное целое", value, "Недопустимая версия")
    return value


def _number(value, path):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _fail(path, "конечное число", value, "Недопустимое числовое значение")
    return float(value)


def _sequence(value, path, *, nonempty=False):
    if not isinstance(value, (list, tuple)) or (nonempty and not value):
        _fail(path, "непустой список" if nonempty else "список", value, "Недопустимая коллекция")
    return value


def _vector(value, path):
    values = _sequence(value, path)
    if len(values) != 3:
        _fail(path, 3, len(values), "Вектор должен содержать три координаты")
    return tuple(_number(v, f"{path}[{i}]") for i, v in enumerate(values))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _near(a, b):
    return all(abs(x - y) <= TOLERANCE for x, y in zip(a, b))


def _same_frame(a, b):
    return _near(a.origin, b.origin) and all(_near(x, y) for x, y in zip(a.basis, b.basis))


def _frame(value, path):
    value = _object(value, "origin basis", path)
    rows = _sequence(value["basis"], path + ".basis")
    if len(rows) != 3:
        _fail(path + ".basis", "3 × 3", rows, "Недопустимая матрица")
    basis = tuple(_vector(row, path + ".basis") for row in rows)
    a, b, c = basis
    determinant = a[0] * (b[1]*c[2] - b[2]*c[1]) - a[1] * (b[0]*c[2] - b[2]*c[0]) + a[2] * (b[0]*c[1] - b[1]*c[0])
    if any(abs(_dot(basis[i], basis[j]) - (1.0 if i == j else 0.0)) > TOLERANCE
           for i in range(3) for j in range(3)) or abs(determinant - 1.0) > TOLERANCE:
        _fail(path + ".basis", "ортонормальная правая basis, determinant=1", basis,
              "Масштаб, сдвиг осей или отражение запрещены", "invalid_basis")
    return Frame(_vector(value["origin"], path + ".origin"), basis)


def _coordinates(value, path):
    value = _object(value, "units up forward", path)
    if value["units"] != "m":
        _fail(path + ".units", "m", value["units"], "Контракт использует метры")
    axes = {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}
    up, forward = value["up"], value["forward"]
    if not isinstance(up, str) or not isinstance(forward, str) or up not in axes or forward not in axes or up[1] == forward[1]:
        _fail(path, "различные перпендикулярные up/forward", value, "Неоднозначная система координат")
    return Coordinates("m", up, forward)


def _bone(value, path):
    value = _object(value, "id parent rest", path)
    return Bone(_identifier(value["id"], path + ".id"),
                None if value["parent"] is None else _identifier(value["parent"], path + ".parent"),
                _frame(value["rest"], path + ".rest"))


def _joint(value, path):
    value = _object(value, "bone axis lower upper", path)
    axis = _vector(value["axis"], path + ".axis")
    if abs(_dot(axis, axis) - 1.0) > TOLERANCE:
        _fail(path + ".axis", "единичная ось", axis, "Ось шарнира не нормализована")
    lower, upper = _number(value["lower"], path + ".lower"), _number(value["upper"], path + ".upper")
    if not lower <= 0.0 <= upper:
        _fail(path, "lower <= 0 <= upper, радианы от rest pose", [lower, upper], "Пределы не включают исходную позу")
    return JointLimit(_identifier(value["bone"], path + ".bone"), axis, lower, upper)


def _port(value, path):
    value = _object(value, "id interface bone frame", path)
    return Port(*(_identifier(value[k], path + "." + k) for k in ("id", "interface", "bone")),
                _frame(value["frame"], path + ".frame"))


def _binding(value, path):
    value = _object(value, "object_id bone bind_frame", path)
    return RigidBinding(_identifier(value["object_id"], path + ".object_id"),
                        _identifier(value["bone"], path + ".bone"), _frame(value["bind_frame"], path + ".bind_frame"))


def _contact(value, path):
    value = _object(value, "id bone position", path)
    return SoleContact(_identifier(value["id"], path + ".id"), _identifier(value["bone"], path + ".bone"),
                       _vector(value["position"], path + ".position"))


def _items(value, parser, path, identity="id", *, nonempty=False):
    result = tuple(parser(item, f"{path}[{i}]") for i, item in enumerate(_sequence(value, path, nonempty=nonempty)))
    names = [getattr(item, identity) for item in result]
    if len(names) != len(set(names)):
        _fail(path, "уникальные ID", names, "Повторная идентичность", "duplicate_id")
    return result


def _header(value, fields):
    value = _object(value, fields, "root")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        _fail("schema_version", SCHEMA_VERSION, value["schema_version"], "Неподдерживаемая версия схемы", "schema_version")
    return value


def _bone_graph(bones, *, complete):
    known = {bone.id: bone for bone in bones}
    for bone in bones:
        visited = set()
        current = bone.id
        while current is not None:
            if current in visited:
                _fail("bones." + bone.id, "иерархия без циклов", current, "Цикл костей", "bone_cycle")
            visited.add(current)
            if current not in known:
                if complete:
                    _fail("bones." + bone.id + ".parent", "существующая кость", current, "Родитель отсутствует", "missing_bone")
                break
            current = known[current].parent
    if complete and sum(b.parent is None for b in bones) != 1:
        _fail("bones", "ровно один корень", [b.id for b in bones if b.parent is None], "Неоднозначный корень рига")


def _references(bones, ports=(), bindings=(), contacts=(), joints=()):
    known = {bone.id for bone in bones}
    for field, items in (("ports", ports), ("bindings", bindings), ("contacts", contacts), ("joints", joints)):
        for item in items:
            if item.bone not in known:
                _fail(field, sorted(known), item.bone, "Для ссылки отсутствует rest-контракт кости", "missing_bone")


def rig_from_dict(value) -> RigContract:
    value = _header(value, "schema_version id revision coordinates bones joints")
    result = RigContract(SCHEMA_VERSION, _identifier(value["id"], "id"), _integer(value["revision"], "revision"),
                         _coordinates(value["coordinates"], "coordinates"),
                         _items(value["bones"], _bone, "bones", nonempty=True),
                         _items(value["joints"], _joint, "joints", "bone"))
    _bone_graph(result.bones, complete=True)
    _references(result.bones, joints=result.joints)
    return result


def part_from_dict(value) -> PartContract:
    value = _header(value, "schema_version id revision rig_id rig_revision coordinates input outputs bones bindings contacts joints")
    result = PartContract(SCHEMA_VERSION, _identifier(value["id"], "id"), _integer(value["revision"], "revision"),
                          _identifier(value["rig_id"], "rig_id"), _integer(value["rig_revision"], "rig_revision"),
                          _coordinates(value["coordinates"], "coordinates"), _port(value["input"], "input"),
                          _items(value["outputs"], _port, "outputs"), _items(value["bones"], _bone, "bones", nonempty=True),
                          _items(value["bindings"], _binding, "bindings", "object_id", nonempty=True),
                          _items(value["contacts"], _contact, "contacts"), _items(value["joints"], _joint, "joints", "bone"))
    _bone_graph(result.bones, complete=False)
    _references(result.bones, (result.input, *result.outputs), result.bindings, result.contacts, result.joints)
    if result.input.id in {p.id for p in result.outputs}:
        _fail("outputs", "ID, отличный от input", result.input.id, "Вход и выход имеют одинаковый ID", "duplicate_id")
    return result


def slot_from_dict(value) -> SlotContract:
    value = _header(value, "schema_version slot_id rig_id rig_revision input outputs binding_bones contacts joints")
    bone_ids = tuple(_identifier(b, "binding_bones") for b in _sequence(value["binding_bones"], "binding_bones", nonempty=True))
    if len(bone_ids) != len(set(bone_ids)):
        _fail("binding_bones", "уникальные ID", bone_ids, "Повторная кость", "duplicate_id")
    result = SlotContract(SCHEMA_VERSION, _identifier(value["slot_id"], "slot_id"),
                          _identifier(value["rig_id"], "rig_id"), _integer(value["rig_revision"], "rig_revision"),
                          _port(value["input"], "input"), _items(value["outputs"], _port, "outputs"), bone_ids,
                          _items(value["contacts"], _contact, "contacts"), _items(value["joints"], _joint, "joints", "bone"))
    if result.input.id in {p.id for p in result.outputs}:
        _fail("outputs", "ID, отличный от input", result.input.id, "Вход и выход имеют одинаковый ID", "duplicate_id")
    return result


def read_contract(path: str | Path, kind: str):
    """Загружает JSON, отклоняя даже повторные ключи и нестандартные NaN/Infinity."""
    parsers = {"rig": rig_from_dict, "part": part_from_dict, "slot": slot_from_dict}
    if not isinstance(kind, str) or kind not in parsers:
        _fail("kind", sorted(parsers), kind, "Неизвестный тип контракта")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail(key, "один JSON-ключ", key, "Повторный JSON-ключ", "duplicate_key")
            result[key] = value
        return result

    def invalid_constant(value):
        _fail("json", "конечное число", value, "Нестандартное число JSON")

    try:
        return parsers[kind](json.loads(Path(path).read_text(encoding="utf-8-sig"),
                                        object_pairs_hook=unique_pairs, parse_constant=invalid_constant))
    except ContractError as error:
        raise ContractError(replace(error.issue, component=str(path))) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(Issue("error", "invalid_json", str(path), "json", "читаемый JSON в UTF-8", str(error),
                                  "Не удалось прочитать manifest", "Проверьте путь, кодировку и синтаксис JSON")) from error


def check_compatibility(part: PartContract, slot: SlotContract, rig: RigContract) -> tuple[Issue, ...]:
    """Сравнивает контракт кандидата с постоянным слотом и ригом; ничего не подгоняет.

    Повторный parse защищает и вызовы с dataclass, созданными вручную в Python.
    Успех означает совместимость описаний, но ещё не измеренных Blender-объектов.
    """
    part, slot, rig = part_from_dict(asdict(part)), slot_from_dict(asdict(slot)), rig_from_dict(asdict(rig))
    issues = []

    def mismatch(code, field, expected, actual, message, remedy="Выберите совместимую деталь или задайте явный адаптер и новый контракт рига"):
        issues.append(Issue("error", code, slot.slot_id, field, expected, actual, message, remedy))

    for label, value in (("part", part), ("slot", slot)):
        if (value.rig_id, value.rig_revision) != (rig.id, rig.revision):
            mismatch("rig_mismatch", label + ".rig", (rig.id, rig.revision), (value.rig_id, value.rig_revision), "Семейство или версия рига не совпадают")
    if part.coordinates != rig.coordinates:
        mismatch("coordinates_mismatch", "coordinates", asdict(rig.coordinates), asdict(part.coordinates), "Система координат детали отличается от рига")
    rig_bones = {b.id: b for b in rig.bones}
    for bone in part.bones:
        expected = rig_bones.get(bone.id)
        if expected is None:
            mismatch("missing_bone", "bones." + bone.id, "кость текущего рига", bone.id, "Кость отсутствует")
        elif expected.parent != bone.parent or not _same_frame(expected.rest, bone.rest):
            mismatch("rest_mismatch", "bones." + bone.id, asdict(expected), asdict(bone), "Rest frame или родитель кости отличаются")
    for bone in set(slot.binding_bones) | {slot.input.bone} | {p.bone for p in slot.outputs} | {c.bone for c in slot.contacts} | {j.bone for j in slot.joints}:
        if bone not in rig_bones:
            mismatch("missing_bone", "slot.bones", "кость текущего рига", bone, "Слот ссылается на отсутствующую кость")
    actual_bindings = {b.bone for b in part.bindings}
    if actual_bindings != set(slot.binding_bones):
        mismatch("binding_mismatch", "bindings", sorted(slot.binding_bones), sorted(actual_bindings), "Набор жёстко привязанных костей не соответствует слоту")

    def compare_port(actual, expected, field):
        if (actual.interface, actual.bone) != (expected.interface, expected.bone):
            mismatch("interface_mismatch", field, asdict(expected), asdict(actual), "Интерфейс или кость точки подключения отличаются")
        if not _same_frame(actual.frame, expected.frame):
            mismatch("pivot_mismatch", field + ".frame", asdict(expected.frame), asdict(actual.frame), "Pivot или ориентация точки подключения отличаются")

    compare_port(part.input, slot.input, "input")
    outputs = {p.id: p for p in part.outputs}
    for expected in slot.outputs:
        if expected.id not in outputs:
            mismatch("missing_output", "outputs." + expected.id, asdict(expected), None, "Утрачивается соединение сохраняемого соседа")
        else:
            compare_port(outputs[expected.id], expected, "outputs." + expected.id)
    contacts = {c.id: c for c in part.contacts}
    for expected in slot.contacts:
        actual = contacts.get(expected.id)
        if actual is None or actual.bone != expected.bone or not _near(actual.position, expected.position):
            mismatch("sole_mismatch", "contacts." + expected.id, asdict(expected), asdict(actual) if actual else None,
                     "Контакт подошвы изменён; прежняя постановка стопы не гарантируется")
    joints = {j.bone: j for j in part.joints}
    # Коленный модуль может ограничивать LowerLeg через выходной порт, хотя его
    # кожух связан с неподвижной Knee. Такая ось тоже обязана соответствовать ригу.
    rig_joints = {j.bone: j for j in rig.joints}
    declared_joints = {j.bone for j in (*part.joints, *slot.joints)}
    # Даже если оба manifest пропустили joints, подвижное соединение остаётся
    # обязательным: источник требований — постоянный риг, а не умолчание детали.
    socket_bones = {port.bone for port in (part.input, slot.input, *part.outputs, *slot.outputs)}
    for bone in sorted(declared_joints - set(rig_joints)):
        mismatch("unexpected_joint", "joints." + bone, "шарнир, объявленный семейством рига", bone,
                 "Сустав не имеет оси и диапазона в контракте рига")
    requirements = [j for j in rig.joints if j.bone in actual_bindings | declared_joints | socket_bones] + list(slot.joints)
    for expected in requirements:
        actual = joints.get(expected.bone)
        if actual is None or not _near(actual.axis, expected.axis) or actual.lower > expected.lower + TOLERANCE or actual.upper < expected.upper - TOLERANCE:
            issue = Issue("error", "joint_mismatch", slot.slot_id, "joints." + expected.bone,
                          asdict(expected), asdict(actual) if actual else None,
                          "Ось или диапазон шарнира не сохраняют допустимые движения",
                          "Сохраните ось и необходимый диапазон либо создайте отдельное семейство рига")
            if issue not in issues:
                issues.append(issue)
    return tuple(issues)
