# Optional recipe authoring tools

Recipes can expose a small set of named Blender authoring operations in the existing
GameAssetTools sidebar. Recipes without these hooks keep their existing behavior.
Geometry, rig controls and baking remain in the project recipe; Core does not know
about a particular mech or rig family.

Implement `authoring_tools()` to return a list of dictionaries containing exactly
`id` and `label`, both nonempty strings. IDs must be unique. Implement
`run_authoring_tool(asset_id, tool_id)` to run these operations and return a report
dictionary. The registered `game_asset_tools.recipe_tool` operator accepts only IDs
advertised by the currently selected recipe and writes the result through the usual
report mechanism. Use `draw_authoring_tools(layout, asset_id)` optionally to show
recipe-specific fields above the buttons. Validate before mutation and restore
state on failure inside the recipe; the hook does not provide automatic transaction
rollback.

An optional `export_context(asset_id, *, animations=False)` context manager wraps
the existing Core `export_asset` call when a recipe entry is supplied. It can check
that preparation is complete and temporarily change authoring state. Always restore
that state in `finally`, including when validation, path publication or the Blender
exporter raises. A recipe can reject unsupported export options before creating
files. This hook does not implement animation export, bake constraints or change
static export defaults; those capabilities must already exist in the chosen Core
and recipe. Direct exports without an entry cannot discover recipe-specific hooks.

No new recipe base class, configuration schema or dependency is required. These
methods are executable recipe code; imported JSON cannot select arbitrary Python
functions. Existing recipe trust and project selection rules apply.

Verification in Blender:

```text
blender --background --factory-startup --python-exit-code 1 --python tests/blender_recipe_tools_test.py
```

The test uses an existing mech recipe with temporary hooks, calls the real registered
operator, checks panel fields, validates the tool whitelist, exercises ordinary GLB
export, and checks context restoration on success and failure.
