"""Primitive-based walking scout with independent weapon components."""

import math

from game_asset_tools.asset.parameters import Parameter
from game_asset_tools.asset.recipe import ComponentSpec


class Recipe:
    parameters = (
        Parameter("body.width", "Body Width", "float", 1.6, 0.8, 4.0, components=("Body",)),
        Parameter("body.depth", "Body Depth", "float", 1.2, 0.6, 3.0, components=("Body",)),
        Parameter("legs.length", "Leg Length", "float", 2.0, 0.8, 4.0, components=("Hip", "Body", "Leg_Left", "Leg_Right")),
        Parameter("legs.stance", "Leg Stance", "float", 1.25, 0.6, 3.0, components=("Hip", "Leg_Left", "Leg_Right")),
        Parameter("cockpit.scale", "Cockpit Scale", "float", 1.0, 0.5, 1.5, components=("Cockpit",)),
        Parameter("weapons.left_scale", "Left Weapon Scale", "float", 0.8, 0.3, 2.5, components=("Weapon_Left",)),
        Parameter("weapons.right_scale", "Right Weapon Scale", "float", 1.0, 0.3, 2.5, components=("Weapon_Right",)),
        Parameter("finish.bevel", "Bevel Width", "float", 0.06, 0, 0.15),
    )

    def components(self, config):
        return {"Hip": ComponentSpec("Structure"), "Body": ComponentSpec("Structure", ("Hip",)),
                "Cockpit": ComponentSpec("Structure", ("Body",)),
                "Leg_Left": ComponentSpec("Legs", ("Hip",)), "Leg_Right": ComponentSpec("Legs", ("Hip",)),
                "Weapon_Left": ComponentSpec("Weapons", ("Body",)), "Weapon_Right": ComponentSpec("Weapons", ("Body",))}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat

        p = config["parameters"]
        width, depth, length, stance = p["body"]["width"], p["body"]["depth"], p["legs"]["length"], p["legs"]["stance"]
        hip_z, body_z = length + 0.35, length + 1.0
        bevel = 0 if ctx.stage == "BLOCKOUT" else p["finish"]["bevel"]
        detailed = ctx.stage in ("DETAIL", "FINALIZE")

        def finish(obj, name, role="Painted_Metal", parent=None):
            ctx.add(obj, name, parent=parent)
            gat.assign_material(obj, gat.project_material(role, ctx.style))
            return obj

        def box(name, size, at, role="Painted_Metal", parent=None):
            return finish(gat.add_beveled_box(ctx.name(name), size, at, bevel=bevel, segments=ctx.style["bevel"]["segments"]), name, role, parent)

        def joint(name, radius, depth_, at, parent):
            return finish(gat.add_cylinder(ctx.name(name), radius, depth_, 12, at, (0, math.pi / 2, 0)), name, "Metal_Silver", parent)

        if key == "Hip":
            box("Chassis", (stance + 0.25, 0.65, 0.35), (0, 0, hip_z), "Metal_Silver")
        elif key == "Body":
            box("Hull", (width, depth, 1.0), (0, 0, body_z), parent=ctx.get("Hip", "Chassis"))
            if detailed:
                for i in range(3):
                    box(f"Rear_Vent_{i + 1:02d}", (width * 0.65, 0.08, 0.07),
                        (0, depth / 2 + 0.04, body_z - 0.2 + i * 0.17), "Rubber", ctx.get("Body", "Hull"))
        elif key == "Cockpit":
            s = p["cockpit"]["scale"]
            cockpit = box("Canopy", (width * 0.66 * s, 0.40 * s, 0.52 * s),
                          (0, -depth / 2 - 0.11, body_z + 0.17), "Glass_Opaque", ctx.get("Body", "Hull"))
            if detailed:
                box("Sensor", (0.14, 0.14, 0.16), (0, -depth / 2 - 0.34 * s, body_z + 0.17), "Ruby", cockpit)
        elif key.startswith("Leg_"):
            side = -1 if key == "Leg_Left" else 1
            x = side * stance / 2
            hip = joint("Hip_Joint", 0.24, 0.42, (x, 0, hip_z), ctx.get("Hip", "Chassis"))
            knee_z = 0.3 + length * 0.48
            upper = finish(gat.create_support(ctx.name("Upper"), (x, 0, hip_z - 0.1), (x, -0.20, knee_z),
                                               0.30, 0.38, bevel=bevel), "Upper", parent=hip)
            knee = joint("Knee", 0.24, 0.42, (x, -0.20, knee_z), upper)
            lower = finish(gat.create_support(ctx.name("Lower"), (x, -0.20, knee_z), (x, 0.04, 0.3),
                                               0.27, 0.33, bevel=bevel), "Lower", parent=knee)
            foot = box("Foot", (0.5, 0.85, 0.3), (x, -0.18, 0.15), "Rubber", lower)
            if detailed:
                box("Shin_Armor", (0.37, 0.15, length * 0.28), (x, -0.29, 0.3 + length * 0.22), parent=lower)
                box("Toe_Plate", (0.45, 0.22, 0.08), (x, -0.46, 0.32), "Metal_Silver", foot)
        elif key.startswith("Weapon_"):
            side = -1 if key == "Weapon_Left" else 1
            s = p["weapons"]["left_scale" if side == -1 else "right_scale"]
            x = side * (width / 2 + 0.30 * s)
            mount = joint("Mount", 0.23 * s, 0.28 * s, (x, 0, body_z), ctx.get("Body", "Hull"))
            housing = box("Housing", (0.36 * s, 0.7 * s, 0.4 * s), (x, -0.18 * s, body_z), "Metal_Silver", mount)
            barrel = finish(gat.add_cylinder(ctx.name("Barrel"), 0.11 * s, 1.0 * s, 12,
                                             (x, -0.96 * s, body_z), (math.pi / 2, 0, 0)), "Barrel", "Metal_Silver", housing)
            if ctx.stage != "BLOCKOUT":
                finish(gat.add_cylinder(ctx.name("Muzzle"), 0.15 * s, 0.22 * s, 12,
                                        (x, -1.48 * s, body_z), (math.pi / 2, 0, 0)), "Muzzle", "Rubber", barrel)
        else:
            raise ValueError(f"Unknown mech component {key!r}")


RECIPE = Recipe()
