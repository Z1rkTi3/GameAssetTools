"""Семейство сменных payload: численная геометрия, настоящий Rig и IN/OUT.

Это recipe-код двух конкретных ассетов, а не новый геометрический Core.
Контракт совпадает с industrial_biped игры; физическая прочность не моделируется.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from game_asset_tools.asset.parameters import Parameter
from game_asset_tools.asset.recipe import ComponentSpec
from game_asset_tools.assembly.contracts import part_from_dict, rig_from_dict, slot_from_dict

PROFILE = Path(__file__).with_name("industrial_biped.rig.json")
COMPONENT = "WeaponPayload"
INPUT_INTERFACE = "walker_weapon_payload_v1"
MUZZLE_INTERFACE = "walker_weapon_muzzle_v1"
IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
KINDS = ("industrial_cannon", "industrial_emitter")
# Вход остаётся в bone-origin. Реальная посадка находится снаружи на X=±.215.
CONNECTOR = {"male_radius": .09, "male_depth": .035, "outset": .215,
             "inner_apothem": .092, "outer_radius": .13, "depth": .041, "sides": 12}
ROLES = {"Receiver": "Painted_Metal", "Connector": "Metal_Silver", "Barrel": "Metal_Silver",
         "MuzzleRim": "Rubber", "EmitterCore": "Metal_Bronze", "EmitterShroud": "Rubber",
         "Lens": "Glass_Clear"}


def frame(origin=(0, 0, 0)):
    return {"origin": list(origin), "basis": [row[:] for row in IDENTITY]}


def rig_contract():
    """JSON содержит неизменяемые rest-матрицы всех 16 костей, без joint limits."""
    return rig_from_dict(json.loads(PROFILE.read_text(encoding="utf-8")))


def _volume(vertices, faces):
    value = 0.0
    for face in faces:
        a = vertices[face[0]]
        for i in range(1, len(face) - 1):
            b, c = vertices[face[i]], vertices[face[i + 1]]
            cross = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
            value += sum(x*y for x, y in zip(a, cross)) / 6
    return value


def _outward(vertices, faces):
    # Отражение стороны меняет winding данных, никогда не scale Blender object.
    if _volume(vertices, faces) < 0:
        faces = [tuple(reversed(face)) for face in faces]
    return vertices, faces


def _box(size):
    x, y, z = (v/2 for v in size)
    vertices = [(a*x, b*y, c*z) for a, b, c in
                ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                 (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))]
    return vertices, [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]


def _round(axis, start, end, outer, inner=0.0, sides=12):
    """Замкнутый цилиндр или настоящая полая втулка с торцевыми кольцами."""
    def point(t, radius, i):
        a, b = radius*math.cos(i*math.tau/sides), radius*math.sin(i*math.tau/sides)
        return (t, a, b) if axis == "x" else (a, t, b)
    vertices = [point(t, outer, i) for t in (start, end) for i in range(sides)]
    faces = [(i, (i+1)%sides, sides+(i+1)%sides, sides+i) for i in range(sides)]
    if inner:
        vertices += [point(t, inner, i) for t in (start, end) for i in range(sides)]
        for i in range(sides):
            j = (i+1)%sides
            faces += [(2*sides+i, 3*sides+i, 3*sides+j, 2*sides+j),
                      (i, 2*sides+i, 2*sides+j, j),
                      (sides+i, sides+j, 3*sides+j, 3*sides+i)]
    else:
        faces += [tuple(reversed(range(sides))), tuple(range(sides, 2*sides))]
    return _outward(vertices, faces)


def parameters(kind):
    if kind not in KINDS:
        raise ValueError("Неизвестный weapon recipe")
    return (
        Parameter("payload.side", "Payload Side", "enum", "left", choices=("left", "right"), components=(COMPONENT,)),
        Parameter("payload.length", "Barrel / Emitter Length", "float", .85 if kind == KINDS[0] else .65,
                  .25, 1.5, components=(COMPONENT,)),
        Parameter("receiver.width", "Receiver Width", "float", .34 if kind == KINDS[0] else .38,
                  .30, .60, components=(COMPONENT,)),
        Parameter("receiver.height", "Receiver Height", "float", .30 if kind == KINDS[0] else .34,
                  .28, .55, components=(COMPONENT,)),
    )


def geometry(kind, config):
    """Чистый layout в метрах: локальные сетки, origins и измеренный muzzle."""
    from game_asset_tools.asset.parameters import get_value
    values = {}
    for parameter in parameters(kind):
        value = get_value(config["parameters"], parameter.path)
        parameter.validate(value)
        values[parameter.path] = value
    side = -1 if values["payload.side"] == "left" else 1
    bone = "WeaponMountLeft" if side < 0 else "WeaponMountRight"
    rig = rig_contract()
    origin = next(b.rest.origin for b in rig.bones if b.id == bone)
    width, height, length = (values[key] for key in ("receiver.width", "receiver.height", "payload.length"))
    receiver_length = .62 if kind == KINDS[0] else .58
    near = CONNECTOR["outset"] + CONNECTOR["depth"]/2
    cx, front = side*(near+width/2), -.12-receiver_length/2
    parts = []
    def add(name, shape, offset):
        vertices, faces = shape
        parts.append({"id": name, "origin": tuple(origin[i]+offset[i] for i in range(3)),
                      "vertices": vertices, "faces": faces, "role": ROLES[name]})
    add("Receiver", _box((width, receiver_length, height)), (cx, -.12, 0))
    # Внутренний радиус выбран по apothem, чтобы плоские грани не пересекли male.
    inner = CONNECTOR["inner_apothem"]/math.cos(math.pi/CONNECTOR["sides"])
    add("Connector", _round("x", -CONNECTOR["depth"]/2, CONNECTOR["depth"]/2,
                            CONNECTOR["outer_radius"], inner, CONNECTOR["sides"]),
        (side*CONNECTOR["outset"], 0, 0))
    if kind == KINDS[0]:
        add("Barrel", _round("y", 0, -length, .075, .052), (cx, front, 0))
        add("MuzzleRim", _round("y", -length+.055, -length, .105, .052), (cx, front, 0))
    else:
        add("EmitterCore", _round("y", 0, -length+.03, .10), (cx, front, 0))
        add("EmitterShroud", _round("y", 0, -length+.04, .15, .118), (cx, front, 0))
        add("Lens", _round("y", -length+.03, -length, .108), (cx, front, 0))
    muzzle = (origin[0]+cx, origin[1]+front-length, origin[2])
    return {"bone": bone, "input": frame(origin), "muzzle": frame(muzzle), "parts": parts,
            "connector": dict(CONNECTOR), "side": values["payload.side"]}


def _matrix_frame(matrix):
    return {"origin": list(matrix.translation), "basis": [list(row)[:3] for row in list(matrix)[:3]]}


class Recipe:
    def __init__(self, kind):
        self.kind, self.parameters = kind, parameters(kind)

    def components(self, config):
        geometry(self.kind, config)  # Ошибка диапазона/профиля должна возникнуть до Blender ID.
        return {"Rig": ComponentSpec("Rig", persistent=True),
                COMPONENT: ComponentSpec("Weapons", depends_on=("Rig",))}

    def build_component(self, ctx, key, config):
        import bpy
        from mathutils import Matrix, Vector
        from game_asset_tools import core as gat
        layout = geometry(self.kind, config)
        if key == "Rig":
            data = bpy.data.armatures.new(ctx.name("SkeletonData"))
            rig = ctx.add(bpy.data.objects.new(ctx.name("Skeleton"), data), "Skeleton")
            active, selected = bpy.context.view_layer.objects.active, list(bpy.context.selected_objects)
            try:
                for obj in selected: obj.select_set(False)
                rig.select_set(True)
                bpy.context.view_layer.objects.active = rig
                bpy.ops.object.mode_set(mode="EDIT")
                for definition in rig_contract().bones:
                    bone = data.edit_bones.new(definition.id)
                    bone.head = definition.rest.origin
                    bone.tail = Vector(definition.rest.origin) + Vector((0, .16, 0))
                    if definition.parent: bone.parent = data.edit_bones[definition.parent]
                    bone.use_connect = False
                bpy.ops.object.mode_set(mode="OBJECT")
            finally:
                if rig.mode != "OBJECT": bpy.ops.object.mode_set(mode="OBJECT")
                rig.select_set(False)
                for obj in selected: obj.select_set(True)
                bpy.context.view_layer.objects.active = active
            return
        if key != COMPONENT:
            raise ValueError("Неизвестный компонент оружия")
        rig = ctx.get("Rig", "Skeleton")
        for part in layout["parts"]:
            obj = gat.create_mesh(ctx.name(part["id"]), part["vertices"], part["faces"])
            obj.location = part["origin"]
            ctx.add(obj, part["id"], parent=rig)
            # Parent не меняет rest-space geometry; единичный skin сохраняет жёсткость.
            obj.vertex_groups.new(name=layout["bone"]).add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
            obj.modifiers.new("RigidSkeletonSkin", "ARMATURE").object = rig
            gat.assign_material(obj, gat.project_material(part["role"], ctx.style))
            for polygon in obj.data.polygons: polygon.use_smooth = False
        for name, identity, port in (("Input", "payload", layout["input"]), ("Muzzle", "muzzle", layout["muzzle"])):
            marker = ctx.add(bpy.data.objects.new(ctx.name(name), None), name, parent=rig, helper=False)
            marker["gat_socket"] = identity
            marker.empty_display_type, marker.empty_display_size = "ARROWS", .08
            marker.parent_type, marker.parent_bone = "BONE", layout["bone"]
            bone = rig.data.bones[layout["bone"]]
            marker.matrix_parent_inverse = Matrix.Translation((0, -bone.length, 0))
            marker.matrix_basis = bone.matrix_local.inverted() @ Matrix.Translation(port["origin"])

    def describe(self, asset_id):
        """Измеряет текущие объекты, включая уже установленный библиотечный payload."""
        from game_asset_tools.asset.scene import asset_objects, component_records, find_root
        from game_asset_tools.assembly.authoring import get_interface, validate_component
        from game_asset_tools.assembly.inspection import ObjectRef, inspect_part
        from game_asset_tools.assembly.contracts import Issue
        from game_asset_tools.assembly.library import LibraryError
        root = find_root(asset_id)
        record = component_records(root)[COMPONENT]
        if record.get("assembly_interface"):
            validate_component(asset_id, COMPONENT)
            part, slot, rig, mappings = get_interface(asset_id, COMPONENT)
        else:
            layout = geometry(self.kind, json.loads(root["gat_config"]))
            rig = rig_contract()
            objects = asset_objects(root, COMPONENT)
            local = {obj.get("gat_local_name"): obj for obj in objects}
            names = {p["id"] for p in layout["parts"]}
            if len(local) != len(objects) or set(local) != names | {"Input", "Muzzle"}:
                raise ValueError("Payload имеет неизвестный состав; нужна явная регистрация")
            arm = next(obj for obj in asset_objects(root, "Rig") if obj.get("gat_local_name") == "Skeleton")
            bone = layout["bone"]
            input_port = {"id": "payload", "interface": INPUT_INTERFACE, "bone": bone, "frame": layout["input"]}
            part = part_from_dict({"schema_version": 1, "id": asset_id+"_payload", "revision": 1,
                "rig_id": rig.id, "rig_revision": rig.revision, "coordinates": asdict(rig.coordinates),
                "input": input_port,
                "outputs": [{"id": "muzzle", "interface": MUZZLE_INTERFACE, "bone": bone, "frame": layout["muzzle"]}],
                "bones": [asdict(b) for b in rig.bones if b.id == bone],
                "bindings": [{"object_id": name, "bone": bone,
                              "bind_frame": _matrix_frame(arm.data.bones[bone].matrix_local.inverted() @ arm.matrix_world.inverted() @ local[name].matrix_world)}
                             for name in sorted(names)], "contacts": [], "joints": []})
            slot = slot_from_dict({"schema_version": 1, "slot_id": COMPONENT, "rig_id": rig.id,
                "rig_revision": rig.revision, "input": input_port, "outputs": [],
                "binding_bones": [bone], "contacts": [], "joints": []})
            mappings = {"armature": ObjectRef("Rig", "Skeleton"),
                        "objects": {name: ObjectRef(COMPONENT, name) for name in sorted(names)},
                        "sockets": {"payload": ObjectRef(COMPONENT, "Input"), "muzzle": ObjectRef(COMPONENT, "Muzzle")}, "contacts": {}}
            report = inspect_part(asset_id, COMPONENT, part, rig, **mappings)
            if report["status"] != "pass":
                raise LibraryError(Issue(**issue) for issue in report["issues"])
        self._measure(asset_id, part, mappings)
        return part, slot, rig, mappings

    @staticmethod
    def _measure(asset_id, part, mappings):
        """Дополняет generic skin-проверку конкретными размерами посадки и дула."""
        from game_asset_tools.asset.scene import asset_objects, find_root
        from mathutils import Matrix
        rig = rig_contract()
        bone = next((b for b in rig.bones if b.id == part.input.bone and b.id.startswith("WeaponMount")), None)
        if (bone is None or part.input.interface != INPUT_INTERFACE or part.input.frame != bone.rest
                or (part.rig_id, part.rig_revision, part.coordinates) != (rig.id, rig.revision, rig.coordinates)
                or any(b.bone != bone.id for b in part.bindings)):
            raise ValueError("Payload не соответствует industrial_biped / bone-origin IN")
        lookup = {(o.get("gat_component"), o.get("gat_local_name")): o for o in asset_objects(find_root(asset_id))}
        meshes = {}
        bindings = {b.object_id: b for b in part.bindings}
        for identity, reference in mappings["objects"].items():
            obj = lookup[(reference.component, reference.local_name)]
            # Bind frame — постоянная матрица относительно кости, не текущая pose.
            bind = bindings[identity].bind_frame
            transform = Matrix.Identity(4)
            for row in range(3):
                transform[row][3] = bind.origin[row]
                for column in range(3): transform[row][column] = bind.basis[row][column]
            meshes[identity] = [transform @ v.co for v in obj.data.vertices]
        if "Connector" not in meshes:
            raise ValueError("Отсутствует реальная female-посадка")
        points = meshes["Connector"]
        tolerance = 1e-5
        radii = sorted({round(math.hypot(p.y, p.z), 6) for p in points})
        expected = sorted((CONNECTOR["inner_apothem"]/math.cos(math.pi/CONNECTOR["sides"]), CONNECTOR["outer_radius"]))
        # Посадка обязана находиться снаружи соответствующего борта: один модуль
        # расстояния от IN ошибочно разрешал втулку по другую сторону кости.
        expected_x = (-1 if bone.id == "WeaponMountLeft" else 1) * CONNECTOR["outset"]
        if (len(points) != 4*CONNECTOR["sides"] or len(radii) != 2
                or any(abs(a-b) > tolerance for a, b in zip(radii, expected))
                or abs(max(p.x for p in points)-min(p.x for p in points)-CONNECTOR["depth"]) > tolerance
                or abs((max(p.x for p in points)+min(p.x for p in points))/2-expected_x) > tolerance):
            raise ValueError("Female connector не соответствует фиксированной посадке")
        muzzle = next((p for p in part.outputs if p.id == "muzzle" and p.interface == MUZZLE_INTERFACE), None)
        if (muzzle is None or len(part.outputs) != 1 or muzzle.bone != bone.id
                or muzzle.frame.basis != bone.rest.basis):
            raise ValueError("Требуется muzzle OUT с identity basis и направлением -Y")
        relative = tuple(muzzle.frame.origin[i]-part.input.frame.origin[i] for i in range(3))
        front = min(p.y for points in meshes.values() for p in points)
        if abs(front-relative[1]) > tolerance:
            raise ValueError("Muzzle не совпадает с реальным передним торцом")
        front_points = [p for points in meshes.values() for p in points if abs(p.y-front) < tolerance]
        for axis in (0, 2):
            center = (min(p[axis] for p in front_points)+max(p[axis] for p in front_points))/2
            if abs(center-relative[axis]) > tolerance:
                raise ValueError("Muzzle смещён с оси ствола")

    def authoring_tools(self):
        return [{"id": "register_interface", "label": "Check and Register IN/OUT"}]

    def run_authoring_tool(self, asset_id, tool_id):
        if tool_id != "register_interface":
            raise ValueError("Неизвестный инструмент weapon recipe")
        from game_asset_tools.assembly.authoring import interface_to_dict, register_document
        part, slot, rig, mappings = self.describe(asset_id)
        return register_document(asset_id, {"schema_version": 1, "asset": asset_id,
            "interfaces": {COMPONENT: interface_to_dict(part, slot, rig, **mappings)}})

    @contextmanager
    def export_context(self, asset_id, *, animations=False):
        """Только статический rest payload; авторские pose/Actions не переписываются."""
        if animations:
            raise ValueError("Weapon delivery — статический rest payload; экспорт Actions не поддерживается")
        import bpy
        from game_asset_tools.asset.scene import asset_objects, find_root
        _, _, _, mappings = self.describe(asset_id)
        owned = asset_objects(find_root(asset_id))
        lookup = {(o.get("gat_component"), o.get("gat_local_name")): o for o in owned}
        rig_ref = mappings["armature"]
        rig = lookup[(rig_ref.component, rig_ref.local_name)]
        sockets = [lookup[(ref.component, ref.local_name)] for ref in mappings["sockets"].values()]
        flags = [(obj, "gat_helper" in obj, obj.get("gat_helper")) for obj in sockets]
        pose_position = rig.data.pose_position
        try:
            rig.data.pose_position = "REST"
            # Generic Library хранит markers как helpers. Только два declared
            # delivery-порта временно включаются в GLB, исходные flags сохраняются.
            for obj in sockets: obj["gat_helper"] = False
            bpy.context.view_layer.update()
            yield
        finally:
            rig.data.pose_position = pose_position
            for obj, existed, value in flags:
                if existed: obj["gat_helper"] = value
                elif "gat_helper" in obj: del obj["gat_helper"]
            bpy.context.view_layer.update()

    def delivery_manifest(self, asset_id, glb_path):
        """Фиксирует SHA реального GLB и точные node names текущей установленной формы."""
        from game_asset_tools.asset.scene import asset_objects, find_root
        from game_asset_tools.export import inspect_glb
        part, _, rig, mappings = self.describe(asset_id)
        path = Path(glb_path)
        summary = inspect_glb(path)
        lookup = {(o.get("gat_component"), o.get("gat_local_name")): o for o in asset_objects(find_root(asset_id))}
        def name(reference):
            return lookup[(reference.component, reference.local_name)].name
        nodes = {"armature": name(mappings["armature"]), "input": name(mappings["sockets"]["payload"]),
                 "muzzle": name(mappings["sockets"]["muzzle"]),
                 "meshes": {key: name(reference) for key, reference in mappings["objects"].items()}}
        required = [nodes["armature"], nodes["input"], nodes["muzzle"], *nodes["meshes"].values()]
        if any(summary["node_names"].count(value) != 1 for value in required):
            raise ValueError("GLB nodes не совпадают с текущими owned objects")
        weighted = {b["node"] for b in summary["skin_bindings"] if b["weighted"]}
        if not set(nodes["meshes"].values()) <= weighted:
            raise ValueError("GLB потерял жёсткие skin bindings")
        roles = {identity: ROLES[identity] for identity in nodes["meshes"]}
        return {"schema_version": 1, "kind": "weapon_payload", "asset": asset_id, "component": COMPONENT,
                "glb_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "part": asdict(part), "rig": asdict(rig),
                "nodes": nodes, "heat_nodes": sorted(set(nodes["meshes"])-{"Connector"}),
                "material_roles": roles, "connector": dict(CONNECTOR)}
