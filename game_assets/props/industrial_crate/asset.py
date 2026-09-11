"""A small cargo prop with independent shell, frame, lid, and handles."""

from game_asset_tools.asset.parameters import Parameter
from game_asset_tools.asset.recipe import ComponentSpec


class Recipe:
    parameters = (
        Parameter("dimensions.width", "Width", "float", 1.8, 0.6, 6),
        Parameter("dimensions.depth", "Depth", "float", 1.25, 0.6, 6),
        Parameter("dimensions.height", "Height", "float", 1.25, 0.6, 6),
        Parameter("frame.thickness", "Frame Thickness", "float", 0.12, 0.04, 0.25, components=("Body", "Frame")),
        Parameter("lid.thickness", "Lid Thickness", "float", 0.14, 0.04, 0.3, components=("Body", "Frame", "Lid", "Handles")),
        Parameter("finish.bevel", "Bevel Width", "float", 0.025, 0, 0.1),
        Parameter("finish.material", "Shell Material", "enum", "Painted_Metal", choices=("Painted_Metal", "Metal_Silver", "Metal_Bronze"), components=("Body", "Lid")),
        Parameter("details.handles", "Handles", "bool", True, components=("Handles",)),
    )

    def components(self, config):
        return {"Body": ComponentSpec("Structure"), "Frame": ComponentSpec("Structure"),
                "Lid": ComponentSpec("Structure"), "Handles": ComponentSpec("Details")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat

        p = config["parameters"]
        w, d, h = (p["dimensions"][k] for k in ("width", "depth", "height"))
        t, lid = p["frame"]["thickness"], p["lid"]["thickness"]
        bevel = 0 if ctx.stage == "BLOCKOUT" else p["finish"]["bevel"]

        def box(name, size, at, role="Metal_Silver"):
            obj = ctx.add(gat.add_beveled_box(ctx.name(name), size, at, bevel=bevel, segments=ctx.style["bevel"]["segments"]), name)
            gat.assign_material(obj, gat.project_material(role, ctx.style))
            return obj

        if key == "Body":
            box("Shell", (w - t, d - t, h - lid), (0, 0, (h - lid) / 2), p["finish"]["material"])
            if ctx.stage in ("DETAIL", "FINALIZE"):
                box("Identification_Plate", (w * 0.3, 0.035, h * 0.15), (0, -d / 2 - 0.02, h * 0.52), "Rubber")
        elif key == "Lid":
            box("Cover", (w + 0.06, d + 0.06, lid), (0, 0, h - lid / 2), p["finish"]["material"])
            if ctx.stage != "BLOCKOUT":
                for sign, side in ((-1, "Left"), (1, "Right")):
                    box(side + "_Latch", (0.12, 0.08, lid + 0.12), (sign * w * 0.3, -d / 2 - 0.045, h - lid), "Metal_Bronze")
        elif key == "Frame":
            for xs, xname in ((-1, "Left"), (1, "Right")):
                for ys, yname in ((-1, "Front"), (1, "Back")):
                    box(xname + "_" + yname + "_Post", (t, t, h-lid), (xs * (w - t) / 2, ys * (d - t) / 2, (h-lid) / 2))
            for z, label in ((t / 2, "Bottom"), (h - lid - t / 2, "Top")):
                for sign, side in ((-1, "Front"), (1, "Back")):
                    box(label + "_" + side + "_Rail", (w - 2 * t, t, t), (0, sign * (d - t) / 2, z))
                for sign, side in ((-1, "Left"), (1, "Right")):
                    box(label + "_" + side + "_Rail", (t, d - 2 * t, t), (sign * (w - t) / 2, 0, z))
        elif key == "Handles":
            if not p["details"]["handles"]:
                return
            for sign, label in ((-1, "Front"), (1, "Back")):
                at = (0, sign * (d / 2 + 0.09), min(h * 0.65, h - lid - 0.1))
                if ctx.stage == "BLOCKOUT":
                    box(label, (w * 0.26, 0.14, 0.12), at, "Rubber")
                else:
                    obj = ctx.add(gat.create_frame(ctx.name(label), w * 0.28, 0.20, 0.04, 0.10, at), label)
                    gat.assign_material(obj, gat.project_material("Rubber", ctx.style))
        else:
            raise ValueError(f"Unknown crate component {key!r}")


RECIPE = Recipe()
