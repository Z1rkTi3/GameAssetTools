# Save and export

Use the current saved blend, validate, save if needed, then `export <id> --blend
<file>`. Inspect returned GLB structure and warnings. Verify the artifact exists;
do not infer success from the intended path. Existing files need `--overwrite`.

Return `.blend`, `.glb`, relevant preview, and validation report paths. Read
`docs/export.md` for meter/axis conventions and static-export scope. Do not claim
collision, animation, or Godot import verification unless separately performed.
