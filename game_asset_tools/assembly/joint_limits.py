"""Явное native ограничение target-local шарниров без изменения rest и Actions.

Модуль не включается при чтении старых RigContract. Вызывающий адаптер сам
выбирает настоящий Armature, целевые кости и их локальные оси.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from collections.abc import Sequence

from .contracts import JointLimit, TOLERANCE, _joint

RECORD = "gat_joint_limits_v1"
_AXES = "xyz"
_IK_FIELDS = tuple(name + axis for axis in _AXES
                   for name in ("use_ik_limit_", "ik_min_", "ik_max_", "lock_ik_"))
_FK_FIELDS = ("owner_space", "euler_order", "use_transform_limit", "use_legacy_behavior", "mute", "influence",
              *(prefix + axis for axis in _AXES for prefix in ("use_limit_", "min_", "max_")))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _profile(limits, ik_bones):
    if not isinstance(limits, Sequence) or isinstance(limits, (str, bytes)):
        raise ValueError("Нужна последовательность JointLimit")
    if not isinstance(ik_bones, (tuple, list, set, frozenset)) or any(not isinstance(b, str) for b in ik_bones):
        raise ValueError("ik_bones должен содержать явные имена костей")
    if len(ik_bones) != len(set(ik_bones)):
        raise ValueError("Повторная IK-кость")
    result, seen = [], set()
    for value in limits:
        if not isinstance(value, JointLimit): raise ValueError("Нужны JointLimit, а не произвольные поля RNA")
        joint = _joint(asdict(value), "joint")
        if joint.bone in seen: raise ValueError("Повторный JointLimit: " + joint.bone)
        seen.add(joint.bone)
        axis = max(range(3), key=lambda i: abs(joint.axis[i]))
        if any(abs(abs(joint.axis[i]) - 1) > TOLERANCE if i == axis else abs(joint.axis[i]) > TOLERANCE for i in range(3)):
            raise ValueError("Native adapter поддерживает только signed cardinal axes")
        # Один оборот однозначен для этого hinge adapter. IK RNA шире ±π
        # не принимает; FK не получает скрытую иную интерпретацию того же профиля.
        if joint.lower < -math.pi or joint.upper > math.pi:
            raise ValueError("Native adapter принимает диапазон только внутри [-pi, pi]; clamp запрещён")
        lower, upper = ((joint.lower, joint.upper) if joint.axis[axis] > 0 else (-joint.upper, -joint.lower))
        result.append({"bone": joint.bone, "axis": list(joint.axis), "lower": joint.lower, "upper": joint.upper,
                       "native_axis": axis, "native_lower": lower, "native_upper": upper})
    if not result: raise ValueError("Пустой профиль не включает enforcement; используйте remove_joint_limits")
    if set(ik_bones) - seen: raise ValueError("IK subset содержит кость вне профиля")
    return sorted(result, key=lambda item: item["bone"]), tuple(sorted(ik_bones))


def _armature(obj):
    if getattr(obj, "type", None) != "ARMATURE" or obj.library is not None or obj.data.library is not None:
        raise ValueError("Нужен локальный редактируемый Armature Object")
    if obj.mode == "EDIT": raise ValueError("Завершите Edit Mode; rest не изменяется этим инструментом")


def _owner(owner_id):
    if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 200:
        raise ValueError("Нужен непустой явный owner_id")


def _read_record(obj, owner_id):
    if RECORD not in obj: return None
    try:
        record = json.loads(obj[RECORD])
        if (set(record) != {"schema_version", "owner_id", "profile", "ik_bones", "constraints", "previous_ik", "last_ik"}
                or type(record["schema_version"]) is not int or record["schema_version"] != 1 or not isinstance(record["owner_id"], str)):
            raise ValueError("schema")
        raw = [JointLimit(p["bone"], tuple(p["axis"]), p["lower"], p["upper"]) for p in record["profile"]]
        profile, subset = _profile(raw, record["ik_bones"])
        if profile != record["profile"] or list(subset) != record["ik_bones"]: raise ValueError("profile")
        if set(record["constraints"]) != {p["bone"] for p in profile}: raise ValueError("constraints")
        if set(record["previous_ik"]) != set(subset) or set(record["last_ik"]) != set(subset): raise ValueError("IK fields")
        for item in profile:
            definition = record["constraints"][item["bone"]]
            if set(definition) != {"name", "last"} or definition["name"] != _constraint_name(record["owner_id"], item["bone"]):
                raise ValueError("constraint owner mapping")
            _record_fields(definition["last"], _FK_FIELDS)
        for group in ("previous_ik", "last_ik"):
            for values in record[group].values(): _record_fields(values, _IK_FIELDS)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Повреждён owner record; автоматическая замена запрещена") from exc
    if record["owner_id"] != owner_id: raise ValueError("Armature уже имеет другого владельца joint limits")
    return record


def _record_fields(values, names):
    if not isinstance(values, dict) or set(values) != set(names): raise ValueError("native field set")
    for name, value in values.items():
        if name in ("owner_space", "euler_order"):
            if not isinstance(value, str): raise ValueError("native enum")
        elif name.startswith(("use_", "lock_")) or name == "mute":
            if type(value) is not bool: raise ValueError("native flag")
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("native finite value")
        elif name.startswith("ik_min_") and not -math.pi-TOLERANCE <= value <= 0:
            raise ValueError("native IK minimum")
        elif name.startswith("ik_max_") and not 0 <= value <= math.pi+TOLERANCE:
            raise ValueError("native IK maximum")


def _constraint_name(owner_id, bone):
    return "GATJoint::" + hashlib.sha256((owner_id + "\0" + bone).encode()).hexdigest()[:20]


def _fields(owner, names):
    return {name: getattr(owner, name) for name in names}


def _animated_paths(obj):
    data = obj.animation_data
    if data is None: return set()
    paths = {curve.data_path for curve in data.drivers}
    actions = {data.action} if data.action else set()
    actions.update(strip.action for track in data.nla_tracks for strip in track.strips if strip.action)
    for action in actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    paths.update(curve.data_path for curve in bag.fcurves)
    return paths


def _pristine(obj, record):
    paths = _animated_paths(obj)
    result = {}
    for bone, definition in record["constraints"].items():
        pb = obj.pose.bones.get(bone)
        if pb is None: raise ValueError("Утрачена managed кость: " + bone)
        constraint = pb.constraints.get(definition.get("name", ""))
        if (constraint is None or constraint.type != "LIMIT_ROTATION" or pb.constraints[-1] != constraint
                or _fields(constraint, _FK_FIELDS) != definition.get("last")):
            raise ValueError("Managed constraint изменён, перемещён или отсутствует: " + bone)
        if any(path.startswith(constraint.path_from_id()) for path in paths):
            raise ValueError("Managed constraint получил авторскую анимацию/driver: " + bone)
        try:
            custom = list(constraint.keys())
        except TypeError:
            custom = []
        if custom: raise ValueError("Managed constraint получил авторские custom properties: " + bone)
        result[bone] = constraint
    for bone, expected in record["last_ik"].items():
        pb = obj.pose.bones[bone]
        if _fields(pb, _IK_FIELDS) != expected or any(pb.path_from_id() + "." + name in paths for name in _IK_FIELDS):
            raise ValueError("Managed IK fields изменены или анимированы: " + bone)
    return result


def _state(obj, profile):
    bones = []
    for item in profile:
        pb = obj.pose.bones[item["bone"]]
        bones.append({"bone": pb.name, "rest": [list(row) for row in pb.bone.matrix_local],
                      "parent": pb.bone.parent.name if pb.bone.parent else None, "mode": pb.rotation_mode,
                      "ik": _fields(pb, _IK_FIELDS),
                      "constraints": [(c.as_pointer(), c.name, c.type,
                                       _fields(c, _FK_FIELDS) if c.type == "LIMIT_ROTATION" else {}) for c in pb.constraints]})
    return _json({"object": obj.as_pointer(), "data": obj.data.as_pointer(), "record": obj.get(RECORD),
                  "bones": bones, "animation_paths": sorted(_animated_paths(obj))})


@dataclass(frozen=True)
class JointLimitPlan:
    armature: object
    owner_id: str
    profile_json: str
    ik_bones: tuple[str, ...]
    source_state: str


def plan_joint_limits(armature, limits, *, owner_id, ik_bones=()):
    """Читает native данные; весь профиль и конфликты проверяются до первой записи."""
    _armature(armature)
    _owner(owner_id)
    profile, subset = _profile(limits, ik_bones)
    record = _read_record(armature, owner_id)
    managed = _pristine(armature, record) if record else {}
    if record and ({p["bone"] for p in record["profile"]} != {p["bone"] for p in profile} or record["ik_bones"] != list(subset)):
        raise ValueError("Изменение bone set/IK subset требует Remove и отдельного Apply")
    paths = _animated_paths(armature)
    for item in profile:
        pb = armature.pose.bones.get(item["bone"])
        if pb is None: raise ValueError("Отсутствует target-local кость: " + item["bone"])
        if any(c.type == "LIMIT_ROTATION" and c != managed.get(pb.name) for c in pb.constraints):
            raise ValueError("Чужой LIMIT_ROTATION на кости: " + pb.name)
        if not record and pb.constraints.get(_constraint_name(owner_id, pb.name)):
            raise ValueError("Имя managed constraint уже занято чужими данными")
        if pb.name in subset:
            if not record and (any(getattr(pb, "use_ik_limit_" + axis) for axis in _AXES)
                               or getattr(pb, "lock_ik_" + _AXES[item["native_axis"]])):
                raise ValueError("Конфликт с авторскими active IK limits/lock: " + pb.name)
            if any(pb.path_from_id() + "." + name in paths for name in _IK_FIELDS):
                raise ValueError("IK limits/locks уже анимированы: " + pb.name)
    return JointLimitPlan(armature, owner_id, _json(profile), subset, _state(armature, profile))


def _desired(item, *, ik=False):
    result = {}
    for index, axis in enumerate(_AXES):
        lower, upper = ((item["native_lower"], item["native_upper"]) if index == item["native_axis"] else (0.0, 0.0))
        result.update({("use_ik_limit_" if ik else "use_limit_") + axis: True,
                       ("ik_min_" if ik else "min_") + axis: lower,
                       ("ik_max_" if ik else "max_") + axis: upper})
        if ik: result["lock_ik_" + axis] = index != item["native_axis"]
    if not ik:
        result.update(owner_space="LOCAL", euler_order=("XYZ", "YZX", "ZXY")[item["native_axis"]],
                      use_transform_limit=True, use_legacy_behavior=False, mute=False, influence=1.0)
    return result


def _write_fields(owner, values):
    for name, value in values.items(): setattr(owner, name, value)


def _restore_fields(owner, values):
    # Отдельный путь rollback позволяет проверить поздний отказ writer без
    # повторного вызова функции, которая только что отказала.
    for name, value in values.items(): setattr(owner, name, value)


def _write_record(obj, value):
    obj[RECORD] = _json(value)


def _restore_record(obj, existed, value):
    if existed: obj[RECORD] = value
    elif RECORD in obj: del obj[RECORD]


def apply_joint_limits(plan):
    """Применяет только свежий план; не меняет mode/rest/pose/Actions/FCurves."""
    if not isinstance(plan, JointLimitPlan): raise ValueError("Нужен результат plan_joint_limits")
    obj, profile = plan.armature, json.loads(plan.profile_json)
    _armature(obj)
    try:
        current_state = _state(obj, profile)
    except (KeyError, ReferenceError) as exc:
        raise ValueError("Stale joint limit plan; утрачены исходные объекты/кости") from exc
    if current_state != plan.source_state: raise ValueError("Stale joint limit plan; выполните Plan заново")
    limits = [JointLimit(p["bone"], tuple(p["axis"]), p["lower"], p["upper"]) for p in profile]
    if _json(_profile(limits, plan.ik_bones)[0]) != plan.profile_json:
        raise ValueError("Поля validated plan изменены; выполните Plan заново")
    plan_joint_limits(obj, limits, owner_id=plan.owner_id, ik_bones=plan.ik_bones)
    previous = _read_record(obj, plan.owner_id)
    if previous and previous["profile"] == profile:
        return {"status": "unchanged", "owner_id": plan.owner_id, "bones": [p["bone"] for p in profile]}
    managed = _pristine(obj, previous) if previous else {}
    old_fields = {bone: _fields(c, _FK_FIELDS) for bone, c in managed.items()}
    old_ik = {bone: _fields(obj.pose.bones[bone], _IK_FIELDS) for bone in plan.ik_bones}
    existed, raw_record, created = RECORD in obj, obj.get(RECORD), []
    record = {"schema_version": 1, "owner_id": plan.owner_id, "profile": profile, "ik_bones": list(plan.ik_bones),
              "constraints": {}, "previous_ik": previous["previous_ik"] if previous else old_ik, "last_ik": {}}
    try:
        for item in profile:
            pb = obj.pose.bones[item["bone"]]
            constraint = managed.get(pb.name)
            if constraint is None:
                name = _constraint_name(plan.owner_id, pb.name)
                if pb.constraints.get(name): raise ValueError("Имя managed constraint уже занято")
                constraint = pb.constraints.new("LIMIT_ROTATION")
                created.append((pb, constraint))
                constraint.name = name
            _write_fields(constraint, _desired(item))
            record["constraints"][pb.name] = {"name": constraint.name, "last": _fields(constraint, _FK_FIELDS)}
            if pb.name in plan.ik_bones:
                _write_fields(pb, _desired(item, ik=True))
                record["last_ik"][pb.name] = _fields(pb, _IK_FIELDS)
        _write_record(obj, record)
        _pristine(obj, record)
    except BaseException:
        for pb, constraint in reversed(created): pb.constraints.remove(constraint)
        for bone, values in old_fields.items(): _restore_fields(managed[bone], values)
        for bone, values in old_ik.items(): _restore_fields(obj.pose.bones[bone], values)
        _restore_record(obj, existed, raw_record)
        raise
    return {"status": "applied" if previous is None else "updated", "owner_id": plan.owner_id,
            "bones": [p["bone"] for p in profile], "ik_bones": list(plan.ik_bones)}


def inspect_joint_limits(armature, *, owner_id):
    """Read-only проверка managed fields, не сертификат геометрии или прочности."""
    _armature(armature)
    _owner(owner_id)
    try:
        record = _read_record(armature, owner_id)
        if record is None: return {"status": "unmanaged", "owner_id": owner_id, "issues": []}
        _pristine(armature, record)
    except ValueError as exc:
        return {"status": "invalid", "owner_id": owner_id, "issues": [str(exc)]}
    return {"status": "valid", "owner_id": owner_id, "profile": record["profile"], "ik_bones": record["ik_bones"], "issues": []}


def remove_joint_limits(armature, *, owner_id):
    """Возвращает прежние IK fields и удаляет только собственные pristine constraints."""
    _armature(armature)
    _owner(owner_id)
    record = _read_record(armature, owner_id)
    if record is None: return {"status": "unchanged", "owner_id": owner_id}
    managed = _pristine(armature, record)
    raw_record = armature[RECORD]
    removed = []
    try:
        for bone, values in record["previous_ik"].items(): _write_fields(armature.pose.bones[bone], values)
        del armature[RECORD]
        for bone, constraint in managed.items():
            armature.pose.bones[bone].constraints.remove(constraint)
            removed.append(bone)
    except BaseException:
        for bone in removed:
            constraint = armature.pose.bones[bone].constraints.new("LIMIT_ROTATION")
            constraint.name = record["constraints"][bone]["name"]
            _restore_fields(constraint, record["constraints"][bone]["last"])
        for bone, values in record["last_ik"].items(): _restore_fields(armature.pose.bones[bone], values)
        armature[RECORD] = raw_record
        raise
    return {"status": "removed", "owner_id": owner_id}
