"""A modular stone tower: repeated storeys, four window elevations, and roof."""

import math

from game_asset_tools.asset.parameters import Parameter
from game_asset_tools.asset.recipe import ComponentSpec


class Recipe:
    parameters = (
        Parameter("dimensions.width", "Width", "float", 3.8, 1.5, 12, components=("Foundation", "Floors", "Windows", "Roof")),
        Parameter("dimensions.depth", "Depth", "float", 3.2, 1.5, 12, components=("Foundation", "Floors", "Windows", "Roof")),
        Parameter("dimensions.floors", "Floors", "int", 3, 1, 12, components=("Floors", "Windows", "Roof")),
        Parameter("dimensions.floor_height", "Floor Height", "float", 2.4, 1.5, 5, components=("Floors", "Windows", "Roof")),
        Parameter("windows.width", "Window Width", "float", 0.7, 0.15, 2, components=("Windows",)),
        Parameter("windows.height", "Window Height", "float", 1.1, 0.3, 3, components=("Windows",)),
        Parameter("windows.per_side", "Windows per Elevation", "int", 2, 1, 5, components=("Windows",)),
        Parameter("roof.overhang", "Roof Overhang", "float", 0.3, 0.05, 1.5, components=("Roof",)),
        Parameter("finish.bevel", "Bevel Width", "float", 0.04, 0, 0.15),
    )

    def components(self, config):
        return {"Foundation": ComponentSpec("Structure"), "Floors": ComponentSpec("Structure"),
                "Windows": ComponentSpec("Details"), "Roof": ComponentSpec("Structure")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat

        p = config["parameters"]
        w, d, n, h = (p["dimensions"][k] for k in ("width", "depth", "floors", "floor_height"))
        bevel = 0 if ctx.stage == "BLOCKOUT" else p["finish"]["bevel"]
        detailed = ctx.stage in ("DETAIL", "FINALIZE")

        def box(name, size, at, role="Stone", rotation=(0, 0, 0)):
            obj = ctx.add(gat.add_beveled_box(ctx.name(name), size, at, rotation, bevel=bevel, segments=ctx.style["bevel"]["segments"]), name)
            gat.assign_material(obj, gat.project_material(role, ctx.style))
            return obj

        if key == "Foundation":
            box("Plinth", (w + 0.5, d + 0.5, 0.35), (0, 0, 0.175))
            if detailed:
                box("Step", (w * 0.4, 0.5, 0.17), (0, -d / 2 - 0.4, 0.085))
        elif key == "Floors":
            for floor in range(n):
                z = 0.35 + floor * h
                box(f"Floor_{floor + 1:02d}", (w, d, h), (0, 0, z + h / 2))
                if ctx.stage != "BLOCKOUT":
                    box(f"Band_{floor + 1:02d}", (w + 0.14, d + 0.14, 0.12), (0, 0, z + 0.06), "Metal_Bronze")
            box("Door", (min(1.0, w * 0.35), 0.09, min(1.8, h * 0.8)),
                (0, -d / 2 - 0.045, 0.35 + min(1.8, h * 0.8) / 2), "Metal_Bronze")
        elif key == "Windows":
            count = p["windows"]["per_side"]
            wh = min(p["windows"]["height"], h * 0.7)
            for floor in range(n):
                z = 0.35 + (floor + 0.57) * h
                for side, length, offset, angle in (("Front", w, -d / 2, 0), ("Back", w, d / 2, 0),
                                                     ("Left", d, -w / 2, math.pi / 2), ("Right", d, w / 2, math.pi / 2)):
                    ww = min(p["windows"]["width"], length / (count + 1) * 0.65)
                    for index in range(count):
                        t = length * ((index + 1) / (count + 1) - 0.5)
                        if floor == 0 and side == "Front" and abs(t) < 0.6:
                            continue  # Leave the ground-level entrance unobstructed.
                        front_back = side in ("Front", "Back")
                        at = (t, offset * (1 + 0.055 / abs(offset)), z) if front_back else (offset * (1 + 0.055 / abs(offset)), t, z)
                        name = f"{side}_{floor + 1:02d}_{index + 1:02d}"
                        box(name, (ww, 0.10, wh), at, "Glass_Opaque", (0, 0, angle))
                        if ctx.stage != "BLOCKOUT":
                            frame = ctx.add(gat.create_frame(ctx.name(name + "_Frame"), ww + 0.16, wh + 0.16,
                                                            0.08, 0.14, at, (0, 0, angle)), name + "_Frame")
                            gat.assign_material(frame, gat.project_material("Metal_Bronze", ctx.style))
        elif key == "Roof":
            overhang = p["roof"]["overhang"]
            top = 0.35 + n * h
            box("Cap", (w + overhang * 2, d + overhang * 2, 0.25), (0, 0, top + 0.125), "Metal_Bronze")
            if ctx.stage != "BLOCKOUT":
                for sign, side in ((-1, "Front"), (1, "Back")):
                    box(side + "_Parapet", (w + 2 * overhang, 0.16, 0.45), (0, sign * (d / 2 + overhang - 0.08), top + 0.475))
                for sign, side in ((-1, "Left"), (1, "Right")):
                    box(side + "_Parapet", (0.16, d + 2 * overhang - 0.32, 0.45), (sign * (w / 2 + overhang - 0.08), 0, top + 0.475))
        else:
            raise ValueError(f"Unknown tower component {key!r}")


RECIPE = Recipe()
