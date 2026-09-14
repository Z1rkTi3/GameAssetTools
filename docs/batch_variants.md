# Variant batches

`batch` runs a whole manifest in one headless Blender process. Each variant begins from
the same input scene, uses the normal guarded rebuild or recolor operation, validates,
and saves its own config and blend. The second pass renders all successful variants
with one frame computed from their combined evaluated bounds. Different dimensions do
not change the camera between comparison images.

```powershell
python -m game_asset_tools batch rubin_tower --blend source.blend --batch-config game_assets/towers/rubin_tower/palettes.json --view front --view perspective --output variants
```

Manifest schema 1:

```json
{"schema_version": 1, "variants": [
  {"name": "ruby", "action": "recolor", "materials": {"Rubin_Gem": {"base_color": [0.65, 0.008, 0.035, 1]}}},
  {"name": "wide", "action": "rebuild", "config": {"parameters": {"base": {"width": 7.2}}}}
]}
```

Recolor variants may include `components` and exact `objects`; rebuild variants accept
a config overlay and optional `components`. Names must be unique safe lowercase names.
Without `--blend`, the baseline is built once from normal project defaults and optional
`--config`, `--set` and `--stage`, then saved only to a temporary file.

Outputs go beneath `OUTPUT/batches/ASSET/NAME/`: the resulting `config.json`, blend,
validation JSON and each preview. `batch.json` contains every result and shared framing.
`comparison.svg` embeds the actual PNGs in one portable sheet, with names and failure
cells. It needs no image library or external files. An error in any variant makes the
whole command fail with exit code 1 while retaining the successful results and explicit
per-variant errors. Failed previews never appear as successful comparison cells.

All target artifacts are checked before processing. Existing outputs require explicit
`--overwrite`; source blend, manifest and source config are never overwritten. One
variant cannot inherit geometry or material changes from the previous variant. Locks,
manual edits and stage approvals use the existing Core rules.

`--dry-run` returns plans without saving/rendering. With no source blend, scene ownership
and material selectors cannot be fully verified yet and are explicitly reported deferred.
Batch is a headless command because it loads independent documents. Use single operations
for a user's currently open Blender scene. Process-count reduction is not a token-usage
measurement; performance claims require measuring the actual workload.
