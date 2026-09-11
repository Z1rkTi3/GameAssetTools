# Authoring and editing recipes

Create a working starting recipe with:

```powershell
python -m game_asset_tools create cargo_door --category props
```

It creates `game_assets/props/cargo_door/{asset.py,metadata.json,config.json}`.
Edit these source files; generated outputs belong elsewhere. Put reference images
and development notes beside the recipe when useful, not in Core. A supplied
reference controls silhouette, proportions, placement, and major features.

Metadata schema 1 requires `id` (lower_case), display name, category (free-form),
positive integer `recipe_version`, and supported uppercase stages. Config schema 1
contains `asset`, `parameters` (nested JSON), and optional `style` overrides.
Unknown parameter paths, wrong types, nonfinite values, and out-of-range numbers
are rejected before mutation. Defaults → optional config overlay → dotted CLI
overrides are merged. Rebuild begins with the saved successful config.

An `asset.py` exports `RECIPE = Recipe()`; importing it should not import Blender
until geometry is actually built:

```python
from game_asset_tools.asset import ComponentSpec, Parameter

class Recipe:
    parameters = (Parameter("body.width", "Width", "float", 2.0,
                            min=0.2, components=("Body",)),)

    def components(self, config):
        return {"Body": ComponentSpec("Structure")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        width = config["parameters"]["body"]["width"]
        obj = gat.add_box(ctx.name("Hull"), (width, 1.0, 1.0), location=(0, 0, .5))
        ctx.add(obj, "Hull")
        gat.assign_material(obj, gat.project_material("Painted_Metal", ctx.style))

RECIPE = Recipe()
```

`ctx.name(local_name)` creates a collision-resistant staging name. `ctx.add` registers
stable identity, links the appropriate collection, and parents to the asset root.
`ctx.get(component,local_name)` resolves built dependencies; declare them in
`ComponentSpec(depends_on=("Body",))` before referencing their objects. Pass explicit
`parent=` to `ctx.add` for articulation. Coordinates remain asset-local even if the
root is moved. A component may intentionally build zero objects, e.g. disabled
handles. Its expected object count is recorded for validation.

Parameter `components=()` conservatively means every component. Otherwise list
each direct effect. Dependency closure adds indirect effects. Do not expose every
vertex as a parameter. Useful controls are proportions, counts, materials, and
meaningful placements. Keep unusual local geometry inside the recipe.

Stages are BLOCKOUT, REFINE, DETAIL, FINALIZE. Use `ctx.stage` to control detail.
Set current whole-stage status approved after reviewing its blockout; advancing
requires this approval. Approved components reject ordinary rebuilds. An approved
stage permits advancement of approved components, while locked components still
block. Changing a protected design requires marking the affected component editable.

Existing names are never sufficient evidence of ownership. Rebuild/delete act on
owned generated objects only. Mesh/UV, transform, hierarchy, modifiers, visibility,
and material changes trigger the manual-edit guard. Arbitrary rigging/animation,
constraints, drivers, or custom shader systems are not fully fingerprinted; lock
those components before using manual workflows. Unmanaged objects and children are
preserved; external children or shared collection links block replacement.

`--dry-run` shows replacements, preserved components, and blockers. `--replace-edited`
explicitly permits overwriting detected manual edits, but does not bypass locks.
Recipes must create objects through `ctx.add` and must not edit pre-existing objects
or scene state. Staging cannot roll back arbitrary raw Python side effects.

Increment `recipe_version` when changing build semantics. Recipe source changes also
invalidate builds. Normal rebuild skips unchanged content; use `--component` to
explicitly rebuild a component with unchanged parameters. A `.blend` retains the
last successful config; CLI overrides do not rewrite source `config.json`.
