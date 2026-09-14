# Validation

`validate` reports `status`, `errors`, `warnings`, and evaluated geometry statistics
as JSON, and writes `output/reports/<asset>_validation.json`. Export runs the same
validator; errors stop export. Warnings remain visible and do not stop it.

The default `--report-mode file` protects that fixed path. Use `stdout` to return
JSON without a report file, `unique` for a new UUID-named report, or `replace` to
replace only the validation JSON. These options never permit overwriting blend,
preview or export artifacts. `--dry-run` validates without writing a report.

Checks include root/collection ownership, required component counts, schema and
recipe/config consistency, stage, semantic duplicate/default names, parent ownership,
zero/negative/nonfinite scales, unapplied scale, visibility, missing materials,
empty/nonfinite geometry, exact duplicate mesh candidates, broken boolean operands,
and changes since generation. Unmanaged asset content is preserved and reported as
excluded from export. Output path and GLB failures are caught by artifact operations.

These are production checks, not automatic repair. They do not prove artistic
quality, manifold topology for every custom operation, UV quality, rig correctness,
collision quality, or Godot import settings. Blender itself enforces unique object
names; validation checks duplicate semantic identities too. Fingerprints are an
edit guard with the scope described in [recipe rules](asset_recipes.md).
