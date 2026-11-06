"""Read-only сверка modular manifest с настоящими объектами Blender.

Нет переключения кадров/pose_position, применения transforms или записи .blend.
Геометрические пересечения и качество анимации проверяются отдельным этапом.
"""

from dataclasses import asdict, dataclass
import math

from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from .contracts import TOLERANCE, Issue, part_from_dict, rig_from_dict


@dataclass(frozen=True)
class ObjectRef:
    """Стабильный ключ ownership; Blender name можно свободно переименовать."""

    component: str
    local_name: str


def _matrix(frame):
    from mathutils import Matrix
    result = Matrix.Identity(4)
    for row in range(3):
        for column in range(3):
            result[row][column] = frame.basis[row][column]
        result[row][3] = frame.origin[row]
    return result


def _values(matrix):
    return [[value if math.isfinite(value) else str(value) for value in row] for row in matrix]


def _finite(values):
    return all(math.isfinite(v) for v in values)


def _close(first, second):
    return all(abs(first[r][c] - second[r][c]) <= TOLERANCE for r in range(4) for c in range(4))


class _Inspection:
    def __init__(self, asset_id, component):
        import bpy
        self.asset_id, self.component = asset_id, component
        self.issues = []
        self.checked = {"bones": 0, "meshes": 0, "vertices": 0, "sockets": 0, "contacts": 0}
        self.root = self.pivot = None
        self.owned = []
        self.lookup = {}
        # Обновляется только производное состояние depsgraph, не авторские данные.
        bpy.context.view_layer.update()
        self.graph = bpy.context.evaluated_depsgraph_get()
        try:
            self.root = find_root(asset_id)
            self.pivot = root_object(self.root)
            self.owned = asset_objects(self.root)
        except ValueError as error:
            self.error("ownership", "asset", "один зарегистрированный asset root", str(error), "Не найдена однозначная сборка")
            self.root = self.pivot = None
            return
        for obj in self.owned:
            key = (obj.get("gat_component"), obj.get("gat_local_name"))
            self.lookup.setdefault(key, []).append(obj)
        self.rigid_transform(self.pivot, "root")

    def error(self, code, field, expected, actual, message, remedy="Исправьте исходный объект или manifest и повторите проверку; сцена не изменена"):
        self.issues.append(Issue("error", code, self.component, field, expected, actual, message, remedy))

    def report(self):
        return {"asset": self.asset_id, "component": self.component,
                "status": "error" if self.issues else "pass",
                "scope": "ownership_rest_rigid_binding_markers", "read_only": True,
                "checked": dict(self.checked), "issues": [asdict(issue) for issue in self.issues]}

    def resolve(self, reference, field, *, part=False):
        if not isinstance(reference, ObjectRef) or not all(isinstance(v, str) and v for v in (reference.component, reference.local_name)):
            self.error("object_mapping", field, "ObjectRef(component, local_name)", repr(reference), "Некорректная явная ссылка")
            return None
        if part and reference.component != self.component:
            self.error("ownership", field, self.component, reference.component, "Объект принадлежит другому компоненту")
            return None
        matches = self.lookup.get((reference.component, reference.local_name), [])
        if len(matches) != 1:
            self.error("object_mapping", field, "ровно один owned object", len(matches), "Стабильная ссылка отсутствует или неоднозначна")
            return None
        obj = matches[0]
        allowed = {self.root, *self.root.children_recursive}
        if any(collection not in allowed for collection in obj.users_collection):
            self.error("external_usage", field, "объект только внутри сборки", obj.name, "Объект также связан с внешней коллекцией")
        if obj.library is not None or (obj.data is not None and obj.data.library is not None):
            self.error("external_usage", field, "локальные исходные данные", obj.name, "Связанная библиотека требует явной локализации перед заменой")
        return obj

    def rigid_transform(self, obj, field):
        matrix = obj.matrix_world
        numbers = [v for row in matrix for v in row]
        if not _finite(numbers) or not _finite(obj.scale):
            self.error("nonfinite_transform", field, "конечный transform", _values(matrix), "Transform содержит NaN/Infinity")
            return False
        basis = matrix.to_3x3()
        if (any(abs(v - 1.0) > TOLERANCE for v in obj.scale)
                or abs(basis.determinant() - 1.0) > TOLERANCE
                or any(abs(basis.col[i].dot(basis.col[j]) - (1 if i == j else 0)) > TOLERANCE
                       for i in range(3) for j in range(3))):
            self.error("invalid_scale", field, "applied scale=1, ортонормальная правая basis", _values(matrix),
                       "Обнаружен масштаб, shear или отражение")
            return False
        return True

    def mapping(self, mapping, expected, field):
        if not isinstance(mapping, dict):
            self.error("object_mapping", field, sorted(expected), repr(mapping), "Ожидается явное отображение ID → ObjectRef")
            return {}
        if set(mapping) != set(expected):
            self.error("object_mapping", field, sorted(expected), sorted(str(k) for k in mapping), "Набор ссылок не совпадает с manifest")
        return mapping

    def rig(self, contract, reference):
        armature = self.resolve(reference, "armature")
        if armature is None:
            return None
        if armature.type != "ARMATURE":
            self.error("object_type", "armature", "ARMATURE", armature.type, "Ссылка не указывает на скелет")
            return None
        if armature.mode != "OBJECT":
            self.error("object_mode", "armature", "OBJECT", armature.mode, "Выйдите из Edit/Pose Mode перед проверкой неизменяемого rest")
            return None
        if armature.parent != self.pivot or armature.parent_type != "OBJECT":
            self.error("rig_parent", "armature.parent", self.pivot.name, armature.parent.name if armature.parent else None,
                       "Риг должен принадлежать постоянному корню сборки")
        if not self.rigid_transform(armature, "armature.transform"):
            return None
        if (contract.coordinates.units, contract.coordinates.up, contract.coordinates.forward) != ("m", "+Z", "-Y"):
            self.error("coordinates_mismatch", "coordinates", {"units": "m", "up": "+Z", "forward": "-Y"},
                       asdict(contract.coordinates), "Blender-инспекция ожидает исходную систему +Z вверх/-Y вперёд")
        import bpy
        if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > TOLERANCE:
            self.error("scene_units", "scene.unit_settings.scale_length", 1.0, bpy.context.scene.unit_settings.scale_length,
                       "Единица сцены должна соответствовать одному метру")
        expected = {bone.id for bone in contract.bones}
        if set(armature.data.bones.keys()) != expected:
            self.error("bone_set", "armature.bones", sorted(expected), sorted(armature.data.bones.keys()), "Состав костей отличается от семейства")
        self.bones(armature, contract.bones)
        return armature

    def bones(self, armature, definitions):
        for expected in definitions:
            bone = armature.data.bones.get(expected.id)
            if bone is None:
                self.error("missing_bone", "bones." + expected.id, expected.id, None, "Кость отсутствует в Blender")
                continue
            self.checked["bones"] += 1
            actual_parent = bone.parent.name if bone.parent else None
            if actual_parent != expected.parent:
                self.error("bone_parent", "bones." + expected.id + ".parent", expected.parent, actual_parent, "Нарушена кинематическая цепь")
            matrix = bone.matrix_local
            if not _finite(v for row in matrix for v in row) or not math.isfinite(bone.length) or bone.length <= TOLERANCE:
                self.error("invalid_bone", "bones." + expected.id, "конечная rest matrix и ненулевая длина", _values(matrix), "Повреждённая rest-кость")
            elif not _close(matrix, _matrix(expected.rest)):
                self.error("bone_rest", "bones." + expected.id + ".rest", asdict(expected.rest), _values(matrix), "Pivot или rest-оси кости отличаются")

    def rest_matrix(self, obj, armature, field, bone=None):
        # Компенсируем текущую позу bone-parent через evaluated matrix; не трогаем
        # frame_current, Actions, constraints, pose_position или matrix_basis.
        if obj.constraints or obj.animation_data is not None:
            self.error("unsupported_transform", field, "нет собственной анимации/constraints объекта", obj.name,
                       "Нельзя доказать постоянный bind/socket transform у анимированного объекта")
            return None
        if not self.rigid_transform(obj, field):
            return None
        evaluated_armature = armature.evaluated_get(self.graph)
        local = evaluated_armature.matrix_world.inverted() @ obj.evaluated_get(self.graph).matrix_world
        if obj.parent_type == "BONE":
            if obj.parent != armature or obj.parent_bone not in armature.data.bones or (bone is not None and obj.parent_bone != bone):
                self.error("bone_binding", field, bone, obj.parent_bone, "Bone-parent не соответствует объявленной кости")
                return None
            pose = evaluated_armature.pose.bones[obj.parent_bone].matrix
            if not _finite(v for row in pose for v in row) or abs(pose.determinant()) <= TOLERANCE:
                self.error("invalid_pose", field, "обратимая текущая pose matrix", _values(pose), "Нельзя восстановить rest из повреждённой позы")
                return None
            local = armature.data.bones[obj.parent_bone].matrix_local @ pose.inverted() @ local
        elif obj.parent not in (armature, self.pivot) or obj.parent_type != "OBJECT":
            self.error("object_parent", field, "прямой parent: rig/root или его кость", obj.parent.name if obj.parent else None,
                       "Неизвестная промежуточная иерархия мешает проверить bind transform")
            return None
        return local

    def mesh(self, obj, expected, armature):
        field = "bindings." + expected.object_id
        if obj.type != "MESH":
            self.error("object_type", field, "MESH", obj.type, "Жёсткая деталь должна ссылаться на mesh")
            return
        self.checked["meshes"] += 1
        if obj.mode != "OBJECT":
            self.error("object_mode", field, "OBJECT", obj.mode, "Нельзя проверять незавершённую геометрию Edit Mode")
            return
        bone = armature.data.bones.get(expected.bone)
        if bone is None:
            return
        rest = self.rest_matrix(obj, armature, field, expected.bone)
        if rest is not None:
            actual = bone.matrix_local.inverted() @ rest
            if not _close(actual, _matrix(expected.bind_frame)):
                self.error("bind_frame", field, asdict(expected.bind_frame), _values(actual), "Origin/ориентация детали относительно rest-кости отличаются")
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
        bone_parented = obj.parent_type == "BONE" and obj.parent == armature and obj.parent_bone == expected.bone
        if bone_parented:
            if modifiers:
                self.error("double_binding", field, "один способ rigid-привязки", "bone parent + Armature", "Привязка применится дважды")
        elif len(modifiers) != 1 or modifiers[0].object != armature:
            self.error("armature_modifier", field, "ровно один modifier текущего рига", [m.object.name if m.object else None for m in modifiers],
                       "Mesh не связан однозначно с нужным ригом")
        else:
            modifier = modifiers[0]
            if not bone.use_deform:
                self.error("nondeforming_bone", field, "use_deform=True для skin-кости", expected.bone,
                           "Единичные веса не двигают mesh: деформация этой костью отключена")
            if bone.bbone_segments != 1:
                self.error("nonrigid_bone", field, "bbone_segments=1", bone.bbone_segments,
                           "Сегментированная B-Bone может изгибать деталь даже с единичными весами")
            if not modifier.show_viewport or not modifier.show_render or not modifier.use_vertex_groups or modifier.use_bone_envelopes or modifier.vertex_group:
                self.error("armature_settings", field, "enabled vertex groups; no envelopes/mask", modifier.name, "Параметры skin меняют жёсткую привязку")
            groups = {group.index: group.name for group in obj.vertex_groups}
            for vertex in obj.data.vertices:
                weights = [(groups.get(g.group), g.weight) for g in vertex.groups if g.weight != 0.0]
                if (len(weights) != 1 or weights[0][0] != expected.bone or not math.isfinite(weights[0][1])
                        or abs(weights[0][1] - 1.0) > TOLERANCE):
                    diagnostic_weights = [[name, weight if math.isfinite(weight) else str(weight)] for name, weight in weights]
                    self.error("rigid_weights", field + f".vertices[{vertex.index}]", [[expected.bone, 1.0]], diagnostic_weights,
                               "Вершина не имеет единственного единичного веса нужной кости")
                    break
        if not obj.data.vertices or not obj.data.polygons:
            self.error("empty_mesh", field, "непустые vertices/faces", len(obj.data.vertices), "Геометрия отсутствует")
        self.checked["vertices"] += len(obj.data.vertices)
        if any(not _finite(vertex.co) for vertex in obj.data.vertices):
            self.error("nonfinite_geometry", field, "конечные координаты", obj.name, "Геометрия содержит NaN/Infinity")
        if obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 1:
            self.error("nonrigid_geometry", field, "жёсткий mesh без shape keys", obj.name, "Shape keys могут деформировать механическую деталь")
        # Даже выключенный деформатор может изменить экспорт при смене настроек.
        extra = [m.type for m in obj.modifiers if m.type != "ARMATURE"]
        if extra:
            self.error("unevaluated_modifiers", field, "проверенная исходная геометрия", extra,
                       "Дополнительные модификаторы пока не проверяются этой инспекцией", "Проверяйте отдельную запечённую копию, сохраняя исходник")

    def marker(self, obj, expected, armature, *, contact=False):
        field = ("contacts." if contact else "sockets.") + expected.id
        tag = "gat_contact" if contact else "gat_socket"
        if obj.type != "EMPTY" or obj.get(tag) != expected.id:
            self.error("marker_identity", field, {"type": "EMPTY", tag: expected.id}, {"type": obj.type, tag: obj.get(tag)},
                       "Точка должна иметь явную семантическую метку")
            return
        if obj.parent_type != "BONE":
            self.error("bone_binding", field, expected.bone, obj.parent_type, "Точка должна следовать объявленной кости")
            return
        rest = self.rest_matrix(obj, armature, field, expected.bone)
        if rest is None:
            return
        if contact:
            actual = armature.data.bones[expected.bone].matrix_local.inverted() @ rest
            if any(abs(a - b) > TOLERANCE for a, b in zip(actual.translation, expected.position)):
                self.error("sole_marker", field, expected.position, list(actual.translation), "Контакт подошвы сдвинут относительно кости")
            self.checked["contacts"] += 1
        else:
            if not _close(rest, _matrix(expected.frame)):
                self.error("socket_frame", field, asdict(expected.frame), _values(rest), "Pivot/ориентация socket отличаются")
            self.checked["sockets"] += 1


def inspect_rig(asset_id, rig, *, armature: ObjectRef):
    """Проверяет все rest-кости и ownership существующего рига без смены позы."""
    rig = rig_from_dict(asdict(rig))
    inspection = _Inspection(asset_id, armature.component if isinstance(armature, ObjectRef) else "Rig")
    if inspection.root is not None:
        inspection.rig(rig, armature)
    return inspection.report()


def inspect_part(asset_id, component, part, rig, *, armature: ObjectRef, objects: dict,
                 sockets: dict, contacts: dict):
    """Проверяет перечисленные реальные объекты одного компонента.

    Manifest-совместимость с целевым SlotContract проверяется отдельно перед swap.
    Здесь mapping обязателен даже для контактов; незаявленные owned-объекты
    компонента отклоняются, чтобы проверка не пропустила скрытую часть сборки.
    """
    part, rig = part_from_dict(asdict(part)), rig_from_dict(asdict(rig))
    inspection = _Inspection(asset_id, component)
    if inspection.root is None:
        return inspection.report()
    actual_rig = inspection.rig(rig, armature)
    if actual_rig is None:
        return inspection.report()
    if (part.rig_id, part.rig_revision, part.coordinates) != (rig.id, rig.revision, rig.coordinates):
        inspection.error("rig_mismatch", "part.rig", [rig.id, rig.revision, asdict(rig.coordinates)],
                         [part.rig_id, part.rig_revision, asdict(part.coordinates)], "Деталь описывает другое семейство/версию/координаты")
    inspection.bones(actual_rig, part.bones)
    used = set()
    mappings = (("objects", objects, part.bindings, "object_id"),
                ("sockets", sockets, (part.input, *part.outputs), "id"),
                ("contacts", contacts, part.contacts, "id"))
    for kind, mapping, definitions, identity in mappings:
        mapping = inspection.mapping(mapping, {getattr(item, identity) for item in definitions}, kind)
        for item in definitions:
            key = getattr(item, identity)
            if key not in mapping:
                continue
            obj = inspection.resolve(mapping[key], kind + "." + key, part=True)
            if obj is None:
                continue
            if obj in used:
                inspection.error("duplicate_mapping", kind + "." + key, "разные объекты для разных ID", obj.name, "Один объект сопоставлен нескольким ролям")
                continue
            used.add(obj)
            if kind == "objects":
                inspection.mesh(obj, item, actual_rig)
            else:
                inspection.marker(obj, item, actual_rig, contact=kind == "contacts")
    unlisted = [obj.name for obj in inspection.owned if obj.get("gat_component") == component and obj not in used]
    if unlisted:
        inspection.error("unmapped_objects", "component", "все owned-объекты представлены mapping", sorted(unlisted), "Часть компонента не проверена")
    return inspection.report()
