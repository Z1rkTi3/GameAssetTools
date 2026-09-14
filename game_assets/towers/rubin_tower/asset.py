"""Reference-led, symmetric primitive blockout. +Z is up; -Y is front."""

from game_asset_tools.asset import ComponentSpec, Parameter


class Recipe:
    parameters = (
        Parameter("base.width", "Base Width", "float", 6.8, min=0.1, components=("Base",)),
        Parameter("base.depth", "Base Depth", "float", 5.8, min=0.1, components=("Base",)),
        Parameter("base.height", "Base Height", "float", 1.9, min=0.1, components=("Base",)),
        Parameter("body.width", "Body Width", "float", 5.1, min=0.1, components=("Body",)),
        Parameter("body.depth", "Body Depth", "float", 5.1, min=0.1, components=("Body",)),
        Parameter("body.height", "Body Height", "float", 2.9, min=0.1, components=("Body",)),
        Parameter("door.width", "Door Width", "float", 1.15, min=0.05, components=("Door",)),
        Parameter("door.height", "Door Height", "float", 1.45, min=0.05, components=("Door",)),
        Parameter("window.width", "Window Width", "float", 0.45, min=0.05, components=("Window",)),
        Parameter("window.height", "Window Height", "float", 1.3, min=0.05, components=("Window",)),
        Parameter("supports.spacing", "Support Foot Centre Spacing", "float", 3.6, min=0.1, components=("Supports",)),
        Parameter("supports.height", "Support Height", "float", 1.85, min=0.1, components=("Supports",)),
        Parameter("supports.thickness", "Support Thickness", "float", 0.44, min=0.05, components=("Supports",)),
        Parameter("supports.inward_offset", "Support Inward Offset", "float", 0.9, min=0.01, components=("Supports",)),
        Parameter("gem.width", "Gem Width", "float", 3.6, min=0.1, components=("Gem",)),
        Parameter("gem.depth", "Gem Depth", "float", 3.6, min=0.1, components=("Gem",)),
        Parameter("gem.height", "Gem Height", "float", 3.8, min=0.1, components=("Gem",)),
        Parameter("gem.hover_gap", "Gem Vertical Clearance", "float", 0.1, min=0.01, components=("Gem",)),
    )

    def components(self, config):
        p = config["parameters"]
        base, body, door, window, supports = (p[k] for k in ("base", "body", "door", "window", "supports"))
        # Reject incompatible proportions before the lifecycle stages any objects.
        if base["width"] <= body["width"] or base["depth"] <= body["depth"]:
            raise ValueError("Base must be wider and deeper than Body.")
        if door["width"] >= base["width"] or door["height"] >= base["height"]:
            raise ValueError("Door must fit inside the Base front.")
        if not window["width"] < window["height"] < body["height"] or window["width"] >= body["width"]:
            raise ValueError("Window must be vertical and fit inside the Body front.")
        if supports["spacing"] + supports["thickness"] >= min(body["width"], body["depth"]):
            raise ValueError("Support feet must fit on top of Body.")
        if supports["spacing"] - 2 * supports["inward_offset"] <= supports["thickness"]:
            raise ValueError("Supports must leave an open central gap.")
        if supports["thickness"] >= min(supports["height"], body["depth"]):
            raise ValueError("Supports must be slender and fit on Body.")
        return {
            "Base": ComponentSpec("Structure"),
            "Door": ComponentSpec("Details", depends_on=("Base",)),
            "Body": ComponentSpec("Structure", depends_on=("Base",)),
            "Window": ComponentSpec("Details", depends_on=("Body",)),
            "Supports": ComponentSpec("Structure", depends_on=("Body",)),
            "Gem": ComponentSpec("Details", depends_on=("Supports",)),
        }

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat

        p = config["parameters"]
        base, body, door, window, supports, gem = (p[k] for k in ("base", "body", "door", "window", "supports", "gem"))
        body_top = base["height"] + body["height"]
        support_directions = (("Left", -1, 0), ("Right", 1, 0),
                              ("Front", 0, -1), ("Back", 0, 1))

        def register(obj, name, role):
            ctx.add(obj, name)
            gat.assign_material(obj, gat.project_material(role, ctx.style))

        if key == "Base":
            register(gat.add_box(ctx.name("Block"), (base["width"], base["depth"], base["height"]),
                                 (0, 0, base["height"] / 2)), "Block", "Rubin_Base")
        elif key == "Door":
            # Thin panel intersects the front face slightly, preventing coplanar flicker.
            register(gat.create_panel(ctx.name("Panel"), door["width"], door["height"], 0.06,
                                      (0, -base["depth"] / 2 - 0.02, door["height"] / 2), bevel=0),
                     "Panel", "Rubin_Door")
        elif key == "Body":
            register(gat.add_box(ctx.name("Block"), (body["width"], body["depth"], body["height"]),
                                 (0, 0, base["height"] + body["height"] / 2)), "Block", "Rubin_Body")
        elif key == "Window":
            register(gat.create_panel(ctx.name("Glass"), window["width"], window["height"], 0.04,
                                      (0, -body["depth"] / 2 - 0.015, base["height"] + body["height"] / 2), bevel=0),
                     "Glass", "Rubin_Glass")
        elif key == "Supports":
            # One radial centreline repeated at quarter turns, with identical proportions.
            profile = ((0.0, 0.0), (0.60, 0.40), (0.90, 0.72), (1.0, 1.0))
            for side, dx, dy in support_directions:
                points = [(dx * (supports["spacing"] / 2 - supports["inward_offset"] * x),
                           dy * (supports["spacing"] / 2 - supports["inward_offset"] * x),
                           body_top + supports["height"] * z) for x, z in profile]
                for index, (start, end) in enumerate(zip(points, points[1:])):
                    # Small internal overlaps keep the three box segments visibly connected.
                    direction = tuple(b - a for a, b in zip(start, end))
                    length = sum(v * v for v in direction) ** 0.5
                    overlap = min(supports["thickness"] * 0.25, length * 0.1)
                    first = tuple(a - v / length * overlap for a, v in zip(start, direction)) if index else start
                    last = tuple(b + v / length * overlap for b, v in zip(end, direction)) if index < 2 else end
                    name = f"{side}_{index + 1:02d}"
                    register(gat.create_support(ctx.name(name), first, last, supports["thickness"],
                                                depth=supports["thickness"], bevel=0), name, "Rubin_Supports")
        elif key == "Gem":
            # A square bipyramid: six vertices, eight flat triangular facets, no hidden caps.
            w, d, h = (gem[k] / 2 for k in ("width", "depth", "height"))
            vertices = [(w, 0, 0), (0, d, 0), (-w, 0, 0), (0, -d, 0), (0, 0, h), (0, 0, -h)]
            faces = [(4, i, (i + 1) % 4) for i in range(4)]
            faces += [(5, (i + 1) % 4, i) for i in range(4)]
            # Clearance above the real tilted end caps, measured in asset-local Z.
            tip_z = max((obj.matrix_local @ v.co).z
                        for side, _, _ in support_directions
                        for obj in (ctx.get("Supports", f"{side}_03"),)
                        for v in obj.data.vertices)
            register(gat.create_mesh(ctx.name("Diamond"), vertices, faces,
                                     location=(0, 0, tip_z + gem["hover_gap"] + h)), "Diamond", "Rubin_Gem")
        else:
            raise ValueError(f"Unknown rubin_tower component {key!r}")


RECIPE = Recipe()
