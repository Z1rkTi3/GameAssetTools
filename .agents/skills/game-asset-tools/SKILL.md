---
name: game-asset-tools
description: Create and refine game assets from references or descriptions using this project's Blender Core, recipes, previews, validation, and GLB export. Use for GameAssetTools asset production and targeted edits.
---

Use the repository's `python -m game_asset_tools` command surface. Locate the project
from this skill's `.agents/skills/game-asset-tools` directory, then run commands
there (or pass `--project` before the action). Discover Blender through the CLI or
`BLENDER_EXECUTABLE`. Use the available host Python; do not install host `bpy`.

For a new asset, read `game_style.json`, inspect the supplied reference, and identify
semantic components. References control silhouette/proportions; keep uncertain details
simple. Reuse helpers and one relevant recipe before writing new geometry. Create
recipe/config/metadata, build BLOCKOUT, render useful views, inspect them, and correct
proportions. Show the blockout before asking for major artistic approval. Advance the
approved design through REFINE/DETAIL/FINALIZE, then validate, save, and export.

For a local edit, inspect only its component, identify the parameter, and change only
that parameter. Use `rebuild --dry-run` to see dependencies/blockers. Pass the current
`--blend` so saved configuration and manual work survive. Existing artifacts need
explicit `--overwrite`; `--replace-edited` authorizes replacing manual edits and must
match user intent. Approved/locked components require an intentional state change;
do not unlock them just to make a command pass. Numerical questions use structured
inspection; visual questions use a component preview and relevant reference crop.

Keep context small: registry metadata → chosen config/recipe → specific helper/docs.
For material-only changes use `recolor --materials <roles.json>` with a dry-run and
a separate output version (`docs/materials.md`). Inspect roles and swatches first.
For multiple variants use one `batch --batch-config <manifest.json>` call and its
common-frame comparison sheet (`docs/batch_variants.md`). Repeat validation with
`--report-mode stdout|unique|replace`; a viewing copy uses `save --view-copy`.
Avoid desktop automation solely for zooming or repeated screenshots; use saved
previews and numerical inspection. Reuse already-read instructions and test evidence.
Do not reload every module, render all six views for a local fix, or rebuild unchanged
assets. Use ordinary low reasoning for numerical edits, transforms, rebuilds, previews,
and export; medium for new construction/reference interpretation; higher effort for
difficult geometry or persistent failures. This is guidance, not a model-setting API.

Do not modify GameAssetTools Core merely to solve one asset-specific problem.
Raw bpy is allowed inside recipes, but register new objects through `ctx.add`; never
mutate preserved objects in a component builder. A generally reusable missing
operation belongs in Core only after checking existing helpers and adding coverage.

Read only the workflow relevant to the request:
- `codex/workflows/create_asset.md` and `docs/asset_recipes.md`: new construction.
- `codex/workflows/refine_asset.md`: targeted edits and approvals.
- `codex/workflows/inspect_asset.md`: numerical/visual inspection.
- `codex/workflows/validate_asset.md`: validation and repair.
- `codex/workflows/export_asset.md`: save/GLB delivery.
- `codex/workflows/extend_core.md`: reusable Core changes.
- `docs/sprites.md`: shared sprite profiles, toon/standard PNG frames and atlases.

For sprite export, read `sprite-settings ASSET --schema`, update only requested
fields with `sprite-settings --set KEY=JSON --expected-revision HASH`, then use
`sprites ASSET --blend PATH --preview` before the full `sprites` export. Blender UI
edits the same asset-local config profile; do not create a separate Codex preset
or replace geometry/materials to change sprite appearance. Settings need no Blender
process. Preserve source .blend work and use explicit artifact overwrite only as
authorized. Current sprite export is static; do not claim animation generation.

Report artifact paths and actual validation results. Preview renders are blockout
engineering evidence; do not claim final reference accuracy or Godot import testing
without actually inspecting/testing those results. Optional paid services, collision,
LOD, rigging and animated sprite generation remain outside the implemented workflow.
