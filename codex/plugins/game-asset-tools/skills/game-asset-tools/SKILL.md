---
name: game-asset-tools
description: Create and edit procedural Blender game assets with GameAssetTools, including shared sprite-export settings and toon PNG atlases. Use for recipes, symmetric blockouts, rebuilds, previews, validation, GLB export and static sprite sheets. Works with existing projects or initializes editable bundled recipes.
---

Use the bundled GameAssetTools Core through this plugin's `scripts/gat.py`.
Resolve the plugin root from this skill file: `../../` from this skill directory.
Read `bundled/AGENTS.md` and the relevant bundled workflow before construction.
The plugin includes runtime code, docs, and recipes. Do not assume a particular
Windows username, repository checkout, ChatGPT account, or current directory.

## Locate the runtime and editable project

Find an available Python 3.11+ and Blender executable. On Windows, if `python`
is a Store alias, use Blender's bundled Python under its versioned
`python/bin/python.exe`. The CLI discovers installed Blender; otherwise pass
`--blender PATH` or use `BLENDER_EXECUTABLE`. Do not install host `bpy`.

Use an existing user project containing `game_assets/` and `game_style.json` when
one is supplied or present in the current workspace. If there is none, initialize
an editable project in the current task workspace (or a named user destination):

```text
python <plugin-root>/scripts/gat.py init-project <workspace>
python <plugin-root>/scripts/gat.py --project <workspace> list
```

Initialization copies editable recipes and style without overwriting an existing
project. Keep source recipes and generated output in that workspace. Never edit
or generate assets inside the installed plugin/cache. Existing repository
projects continue to work with their own recipes and the same CLI contract.

## Build and edit

Read `game_style.json`, inspect the supplied reference, then locate the relevant
helper in `bundled/game_asset_tools/core/` and one example before implementing.
Create asset-specific recipes under `game_assets/<category>/<asset>/`; keep
parameters in their `config.json`. Do not modify Core for an asset-specific shape.
Use `ComponentSpec`, `Parameter`, `ctx.name`, `ctx.add`, and existing helpers.

```text
python <plugin-root>/scripts/gat.py --project <workspace> create new_asset --category props
python <plugin-root>/scripts/gat.py --project <workspace> build new_asset --stage BLOCKOUT
python <plugin-root>/scripts/gat.py --project <workspace> preview new_asset --blend <saved.blend> --view front --view perspective
python <plugin-root>/scripts/gat.py --project <workspace> rebuild new_asset --blend <saved.blend> --config <recipe/config.json> --dry-run
```

Global `--project` and `--blender` precede the action. Use the saved `--blend`
for inspection, rebuilds, previews, validation and export of an existing iteration.
Rebuild starts with its saved config; pass `--config` to apply edited source JSON.
Respect manual edits, locks and approval state. Never automatically add
`--replace-edited` or unlock protected components. Use `--overwrite` only when
the requested operation authorizes replacement of the generated artifact.

Start substantial assets at BLOCKOUT and inspect previews before refinement.
Reference silhouette and explicit user corrections govern the design. Keep paired
or radial parts mathematically symmetric from shared parameters. Rubin Tower is
currently BLOCKOUT-only, with one huge red ruby and four supports.

Read only the relevant bundled documents: `docs/asset_recipes.md`,
`docs/previews.md`, `docs/validation.md`, `docs/export.md`, or
`codex/workflows/`. Use structured inspection for numerical questions and previews
for appearance. Use `validate` before delivery and report actual output paths and
results. Do not claim Godot import, collision, rigging or final artistic approval
without evidence.

For material-only requests, use `inspect --swatches` and `recolor --materials
<roles.json> --dry-run`, then recolor to a separate `--output` version. Read
`docs/materials.md`; scope components/objects so shared roles do not include decor.
The plan names every changed object/slot and protected user. Never unlock or accept
manual edits just to make recolor succeed. Do not use geometry rebuild for a palette.

For several alternatives use `batch --batch-config <variants.json> --blend <source>
--view front --view perspective`. It runs one headless Blender process, isolates
each variant, validates, uses common framing and writes a comparison sheet plus JSON.
Read `docs/batch_variants.md`; a failed member makes the batch fail, even when other
members succeeded. Inspect the comparison once; do not repeat unrelated renders.

Use `validate --report-mode stdout` for repeatable numerical checks, `unique` for
new report files or `replace` to replace only the validation report. Use `save
--view-copy --save-view perspective` when a separately framed viewing copy is needed.
Use CLI/data/preview for scale and appearance checks; do not automate the desktop
just to zoom or take repeated window screenshots. Reuse instruction context and
test evidence until a relevant change or failure justifies another read/run.

The Blender add-on is a separate local UI for the same Core. It is optional for
this headless plugin workflow. Do not imply a live connection to an open Blender
window: this plugin starts a headless Blender process for each CLI operation.

For cel/toon or standard sprite export, read `bundled/docs/sprites.md`. Use
`sprite-settings ASSET --schema` to read the canonical asset-local profile and
field definitions. Change requested settings using `sprite-settings ASSET --set
KEY=JSON --expected-revision HASH`; this uses ordinary Python without starting
Blender. Blender's manual Sprites controls edit this same `config.json: sprites`
profile. Do not create separate Codex presets, infer saved settings from an older
.blend snapshot, or rebuild geometry to change the render look. If a revision
conflict occurs, reload and reconcile the requested fields with current values.

Use `sprites ASSET --blend PATH --preview` to inspect one saved-profile angle,
then `sprites ASSET --blend PATH` for frames, a transparent PNG atlas and JSON
rectangles/pivots. An omitted --blend builds a fresh BLOCKOUT; supply existing
.blend files to preserve manual work. Export is static at the evaluated current
frame; animation, outline effects and engine-specific resources are future work.
The toon look is applied to temporary render materials and baked into PNG, not
written into the original asset or exported as a GLB shader.
