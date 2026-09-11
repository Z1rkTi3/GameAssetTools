# Extend a reusable operation

Use `docs/extending_core.md` and the relevant Core module. Confirm there is a second
asset use case and no existing helper solves it. Prefer a small semantic function
with explicit inputs and backwards-compatible options. Keep rare reference-specific
work in the recipe. Add meaningful Blender behavior coverage, run it, update docs,
and retain both interfaces as callers of the same Core.
