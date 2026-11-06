"""Параметрический промышленный шагоход: профильные сетки и явная кинематика.

MVP использует только опубликованный Recipe API. Расчёт до создания Blender ID
доступен через mechanical_report; массы и опоры являются приближённой оценкой.
"""

import math

from game_asset_tools.asset.parameters import Parameter, get_value
from game_asset_tools.asset.recipe import ComponentSpec


LEGS = ("Leg_Left", "Leg_Right")
STANDARD = {"id": "hinge_v1", "pin_diameter": 0.28, "bore_diameter": 0.284,
            "axial_span": 0.32, "housing_radius": 0.18}
PARAMETERS = (
    Parameter("body.length", "Hull Length", "float", 2.6, 1.4, 4.0, components=("Body",)),
    Parameter("body.width", "Hull Width", "float", 2.4, 1.4, 4.0, components=("Body",)),
    Parameter("body.height", "Hull Height", "float", 0.95, 0.45, 1.4, components=("Body",)),
    Parameter("body.bevel", "Hull Edge Bevel", "float", 0.08, 0.0, 0.18, components=("Body",)),
    Parameter("body.front_taper", "Hull Front Taper", "float", 0.8, 0.55, 1.0, components=("Body",)),
    Parameter("legs.upper_length", "Upper Link Length", "float", 0.75, 0.45, 1.3, components=("Body",)),
    Parameter("legs.lower_length", "Lower Link Length", "float", 0.9, 0.45, 1.4, components=("Body",)),
    Parameter("legs.upper_thickness", "Upper Link Thickness", "float", 0.28, 0.12, 0.34, components=LEGS),
    Parameter("legs.lower_thickness", "Lower Link Thickness", "float", 0.28, 0.12, 0.34, components=LEGS),
    Parameter("legs.hip_angle", "Hip Angle Degrees", "float", 28.0, -10.0, 55.0, components=("Body",)),
    Parameter("legs.knee_angle", "Knee Flexion Degrees", "float", 58.0, 15.0, 110.0, components=("Body",)),
    Parameter("feet.width", "Foot Width", "float", 0.68, 0.4, 1.1, components=LEGS),
    Parameter("feet.length", "Foot Length", "float", 1.05, 0.65, 1.8, components=LEGS),
    Parameter("feet.height", "Foot Height", "float", 0.24, 0.16, 0.4, components=("Body",)),
    Parameter("mounts.outset", "Hull Mount Outset", "float", 0.18, 0.17, 0.5, components=("Body",)),
    Parameter("mounts.standard", "Hinge Standard", "enum", "hinge_v1", choices=("hinge_v1",), components=("Body",)),
    Parameter("symmetry.mirror", "Mirror Second Leg", "bool", True, components=("Leg_Right",)),
)


def _values(config):
    if not isinstance(config, dict) or not isinstance(config.get("parameters"), dict):
        raise ValueError("Ожидается JSON-конфигурация с разделом parameters")
    values = {}
    for parameter in PARAMETERS:
        value = get_value(config["parameters"], parameter.path)
        parameter.validate(value)
        values[parameter.path] = value
    return values


def _layout(p):
    upper, lower = p["legs.upper_length"], p["legs.lower_length"]
    a = math.radians(p["legs.hip_angle"])
    b = a - math.radians(p["legs.knee_angle"])
    # Высота таза зависимая: изменение длин/углов сохраняет подошву на Z=0.
    hip_z = p["feet.height"] + upper * math.cos(a) + lower * math.cos(b)
    hip = (-p["body.width"] / 2 - p["mounts.outset"], 0.0, hip_z)
    knee = (hip[0], upper * math.sin(a), hip_z - upper * math.cos(a))
    ankle = (hip[0], knee[1] + lower * math.sin(b), p["feet.height"])
    return {"hip": hip, "knee": knee, "ankle": ankle,
            "body": (0.0, 0.0, hip_z + 0.22 * p["body.height"])}


def _ring(width, height, bevel):
    x, z = width / 2, height / 2
    if bevel == 0:
        return [(-x, -z), (x, -z), (x, z), (-x, z)]
    return [(-x + bevel, -z), (x - bevel, -z), (x, -z + bevel),
            (x, z - bevel), (x - bevel, z), (-x + bevel, z),
            (-x, z - bevel), (-x, -z + bevel)]


def _loft(rings):
    """Замкнутая сетка: кольца ориентированы наружу со стороны начала оси."""
    count = len(rings[0])
    vertices = [tuple(vertex) for ring in rings for vertex in ring]
    faces = [tuple(range(count))]
    for section in range(len(rings) - 1):
        for index in range(count):
            next_index = (index + 1) % count
            faces.append((section * count + index, (section + 1) * count + index,
                          (section + 1) * count + next_index, section * count + next_index))
    faces.append(tuple(reversed(range((len(rings) - 1) * count, len(rings) * count))))
    return vertices, faces


def _beam(start, end, thickness):
    vector = tuple(b - a for a, b in zip(start, end))
    length = math.dist(start, end)
    direction = tuple(value / length for value in vector)
    # Боковая ось X общая; вторая ось поперечника перпендикулярна звену в YZ.
    normal = (0.0, -direction[2], direction[1])
    rings = []
    for fraction, scale in ((0.0, 0.82), (0.45, 1.0), (1.0, 0.72)):
        ring = _ring(thickness * scale, thickness * scale, thickness * 0.1)
        rings.append([(x, direction[1] * length * fraction + normal[1] * z,
                       direction[2] * length * fraction + normal[2] * z) for x, z in ring])
    return _loft(rings)


def _hub(radius, depth):
    # Реальный шарнир имеет ось X; восьми граней достаточно для силуэта MVP.
    return _loft([[(x, radius * math.cos(i * math.tau / 8),
                    -radius * math.sin(i * math.tau / 8)) for i in range(8)]
                  for x in (-depth / 2, depth / 2)])


def _part(component, name, shape, origin, material, parent=None):
    vertices, faces = shape
    return {"component": component, "name": name, "vertices": vertices, "faces": faces,
            "origin": origin, "material": material, "parent": parent}


def _parts(p, layout):
    rings = []
    for y, scale in ((-p["body.length"] / 2, p["body.front_taper"]),
                     (-p["body.length"] * 0.23, 1.0), (p["body.length"] / 2, 0.95)):
        rings.append([(x, y, z) for x, z in _ring(p["body.width"] * scale,
                                                  p["body.height"] * scale, p["body.bevel"])])
    parts = [_part("Body", "Hull", _loft(rings), layout["body"], "Painted_Metal")]
    for side, label in ((-1, "Left"), (1, "Right")):
        origin = (side * (p["body.width"] / 2 + p["mounts.outset"] / 2), 0, layout["hip"][2])
        parts.append(_part("Body", "MountAxle_" + label,
                           _hub(STANDARD["pin_diameter"] / 2, p["mounts.outset"] + 0.08),
                           origin, "Metal_Silver", ("Body", "Hull")))
    hip, knee, ankle = (layout[key] for key in ("hip", "knee", "ankle"))
    leg = [_part("Leg_Left", "HipPivot", _hub(STANDARD["housing_radius"], STANDARD["axial_span"]), hip,
                 "Metal_Bronze", ("Body", "Mount_OUT_Left")),
           _part("Leg_Left", "UpperLink", _beam(hip, knee, p["legs.upper_thickness"]), hip,
                 "Metal_Silver", ("Leg_Left", "HipPivot")),
           _part("Leg_Left", "KneePivot", _hub(STANDARD["housing_radius"], STANDARD["axial_span"]), knee,
                 "Metal_Bronze", ("Leg_Left", "UpperLink")),
           _part("Leg_Left", "LowerLink", _beam(knee, ankle, p["legs.lower_thickness"]), knee,
                 "Metal_Silver", ("Leg_Left", "KneePivot")),
           _part("Leg_Left", "AnklePivot", _hub(STANDARD["housing_radius"] * 0.85, STANDARD["axial_span"]), ankle,
                 "Metal_Bronze", ("Leg_Left", "LowerLink"))]
    foot_rings = []
    for y, width, height in ((-0.62, 0.82, 0.65), (-0.38, 1.0, 1.0), (0.38, 0.9, 1.0)):
        foot_rings.append([(x, y * p["feet.length"], z - p["feet.height"] * 0.5)
                           for x, z in _ring(p["feet.width"] * width, p["feet.height"] * height,
                                             p["feet.height"] * 0.1)])
    leg.append(_part("Leg_Left", "Foot", _loft(foot_rings), ankle, "Rubber", ("Leg_Left", "AnklePivot")))
    parts.extend(leg)
    if p["symmetry.mirror"]:
        # Отражаем координаты и winding, а не scale объекта: нормали остаются наружу.
        for item in leg:
            mirrored = dict(item, component="Leg_Right", origin=(-item["origin"][0], *item["origin"][1:]),
                            vertices=[(-x, y, z) for x, y, z in item["vertices"]],
                            faces=[tuple(reversed(face)) for face in item["faces"]])
            parent = item["parent"]
            mirrored["parent"] = (parent[0].replace("Left", "Right"), parent[1].replace("Left", "Right"))
            parts.append(mirrored)
    return parts


def _mass_proxy(part):
    """Объём и центр однородного замкнутого тела, без плотностей и пустот."""
    vertices, volume, moment = part["vertices"], 0.0, [0.0, 0.0, 0.0]
    for face in part["faces"]:
        a = vertices[face[0]]
        for index in range(1, len(face) - 1):
            b, c = vertices[face[index]], vertices[face[index + 1]]
            cross = (b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0])
            signed = sum(x * y for x, y in zip(a, cross)) / 6
            volume += signed
            for axis in range(3):
                moment[axis] += signed * (a[axis] + b[axis] + c[axis]) / 4
    if volume <= 1e-10:
        raise ValueError("Сетка имеет нулевой/обратный объём: " + part["name"])
    return volume, tuple(moment[i] / volume + part["origin"][i] for i in range(3))


def _support(p, layout):
    points = []
    for side in (-1, 1) if p["symmetry.mirror"] else (-1,):
        center = (side * abs(layout["ankle"][0]), layout["ankle"][1])
        points.extend((center[0] + x * p["feet.width"], center[1] + y * p["feet.length"])
                      for x, y in ((-0.35, -0.32), (0.35, -0.32), (0.35, 0.28), (-0.35, 0.28)))
    ordered = sorted(set(points))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def mechanical_report(config):
    """Немутабельный отчёт доступен CLI, Blender UI и обычным Python-тестам."""
    report = {"errors": [], "warnings": [], "metrics": {}, "joints": {}, "sockets": [],
              "joint_limits_degrees": {"hip": [-10.0, 55.0], "knee_flexion": [15.0, 110.0],
                                       "lower_absolute": [-75.0, 55.0]},
              "support": {}, "comApprox": {}, "assumptions": [
                  "Метры, +Z вверх, −Y вперёд; углы конфигурации в градусах.",
                  "COM — объёмный центр одинаково плотных сплошных деталей; пустоты, экипировка и нагрузки не учтены.",
                  "Опора — выпуклая оболочка вписанных прямоугольников плоских подошв, статическая оценка.",
                  "Посадки hinge_v1 номинальные; отверстия и прочность подшипников геометрически не моделируются.",
                  "Зазоры проверены выбранными консервативными габаритами; полного поиска пересечений/BVH, FEA и динамики нет."]}
    try:
        p = _values(config)
    except (ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
        return report
    error = report["errors"]
    lower_angle = p["legs.hip_angle"] - p["legs.knee_angle"]
    if not -75 <= lower_angle <= 55:
        error.append("Абсолютный наклон голени должен лежать между −75 и55 градусами")
    if p["body.bevel"] * 2 >= min(p["body.width"], p["body.height"]) * p["body.front_taper"]:
        error.append("Скос уничтожает поперечник носовой секции")
    if max(p["legs.upper_thickness"], p["legs.lower_thickness"]) > STANDARD["housing_radius"] * 1.9:
        error.append("Звено не помещается в объявленный типоразмер шарнира")
    if p["feet.width"] < max(p["legs.upper_thickness"], p["legs.lower_thickness"]) * 1.6:
        error.append("Ступня слишком узкая относительно несущих звеньев")
    layout = _layout(p)
    hip, knee, ankle = (layout[key] for key in ("hip", "knee", "ankle"))
    reach = math.dist(hip, ankle)
    upper, lower = p["legs.upper_length"], p["legs.lower_length"]
    body_clearance = layout["body"][2] - p["body.height"] / 2
    knee_clearance = body_clearance - knee[2] - STANDARD["housing_radius"]
    foot_gap = 2 * abs(hip[0]) - p["feet.width"]
    if not abs(upper - lower) + 0.01 < reach < upper + lower - 0.005:
        error.append("Положение стопы слишком близко к сингулярности или вне досягаемости звеньев")
    if knee_clearance < 0.04:
        error.append("Недостаточный вертикальный зазор между коленным узлом и днищем корпуса")
    if body_clearance < 0.3 or foot_gap < 0.08:
        error.append("Недостаточный зазор корпуса над землёй или между ступнями")
    report["metrics"] = {"upper_length": math.dist(hip, knee), "lower_length": math.dist(knee, ankle),
                         "hip_height": hip[2], "reach": reach, "body_ground_clearance": body_clearance,
                         "knee_vertical_clearance": knee_clearance, "foot_gap": foot_gap,
                         "lower_absolute_angle_degrees": lower_angle, "nominal_pin_clearance": 0.004}
    if error:
        return report
    for side, label in ((-1, "Left"), (1, "Right")):
        if side == 1 and not p["symmetry.mirror"]:
            continue
        points = {key: (side * abs(point[0]), point[1], point[2]) for key, point in layout.items() if key != "body"}
        report["joints"][label] = points
        report["sockets"].append({"side": label, "standard": STANDARD["id"], "origin": points["hip"],
                                  "body_OUT_axis": (side, 0, 0), "leg_IN_axis": (-side, 0, 0),
                                  "pin_diameter": STANDARD["pin_diameter"], "bore_diameter": STANDARD["bore_diameter"],
                                  "axial_span": STANDARD["axial_span"]})
    parts = _parts(p, layout)
    masses = [_mass_proxy(part) for part in parts]
    volume = sum(mass for mass, center in masses)
    center = tuple(sum(mass * point[i] for mass, point in masses) / volume for i in range(3))
    hull = _support(p, layout)
    margins = []
    for a, b in zip(hull, hull[1:] + hull[:1]):
        margins.append(((b[0] - a[0]) * (center[1] - a[1]) - (b[1] - a[1]) * (center[0] - a[0])) / math.dist(a, b))
    report["support"] = {"polygon_xy": hull, "projection_inside": min(margins) >= 0, "minimum_margin": min(margins)}
    report["comApprox"] = {"position": center, "solid_volume_proxy": volume, "mass_model": "equal_density_closed_solids"}
    if not p["symmetry.mirror"]:
        report["warnings"].append("Одноногий режим — только предпросмотр модуля, не законченный шагоход")
    if min(margins) < 0:
        report["warnings"].append("Проекция приблизительного COM находится вне статической опоры")
    return report


def geometry_data(config):
    """Чистые локальные вершины, грани и origins для тестов и штатного build."""
    report = mechanical_report(config)
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))
    p = _values(config)
    return _parts(p, _layout(p))


class Recipe:
    parameters = PARAMETERS

    def mechanical_report(self, config):
        return mechanical_report(config)

    def components(self, config):
        report = mechanical_report(config)
        if report["errors"]:
            raise ValueError("; ".join(report["errors"]))
        return {"Body": ComponentSpec("Structure"), "Leg_Left": ComponentSpec("Legs", ("Body",)),
                "Leg_Right": ComponentSpec("Legs", ("Body",))}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        p = _values(config)
        layout = _layout(p)
        for part in geometry_data(config):
            if part["component"] != key:
                continue
            parent = ctx.get(*part["parent"]) if part["parent"] else None
            obj = gat.create_mesh(ctx.name(part["name"]), part["vertices"], part["faces"], location=part["origin"])
            ctx.add(obj, part["name"], parent=parent)
            gat.assign_material(obj, gat.project_material(part["material"], ctx.style))
            if part["name"].startswith("MountAxle"):
                label = part["name"].split("_")[-1]
                self._socket(ctx, "Mount_OUT_" + label, layout["hip"] if label == "Left" else (-layout["hip"][0], *layout["hip"][1:]), obj, "OUT", label)
        if key in LEGS and (key == "Leg_Left" or p["symmetry.mirror"]):
            label = "Left" if key == "Leg_Left" else "Right"
            hip = layout["hip"] if label == "Left" else (-layout["hip"][0], *layout["hip"][1:])
            self._socket(ctx, "Mount_IN", hip, ctx.get(key, "HipPivot"), "IN", label)

    @staticmethod
    def _socket(ctx, name, origin, parent, direction, side):
        from game_asset_tools import core as gat
        axis = (-1 if side == "Left" else 1) * (1 if direction == "OUT" else -1)
        # Локальная Z-ось Empty обозначает ось пальца и совпадает с номинальной посадкой.
        obj = gat.add_socket(ctx.name(name), origin, (0, axis * math.pi / 2, 0), display_size=0.12)
        ctx.add(obj, name, parent=parent)
        obj["mech_interface"] = STANDARD["id"]
        obj["mech_direction"] = direction
        obj["mech_pin_diameter"] = STANDARD["pin_diameter"]
        obj["mech_bore_diameter"] = STANDARD["bore_diameter"]
        obj["mech_axial_span"] = STANDARD["axial_span"]


RECIPE = Recipe()
