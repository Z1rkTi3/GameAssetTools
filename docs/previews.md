# Preview and structured inspection

Use inspection first for dimensions, transforms, hierarchy, materials, counts, or
approval state. `inspect --component Weapon_Right` returns only relevant objects.
`inspection.scene_summary()` lists compact asset summaries, never full mesh arrays.
Counts and bounds use evaluated geometry, including modifiers.

Render visual questions with `preview`: front (-Y), back (+Y), left (-X), right
(+X), top (+Z), and perspective. The first five are orthographic. Default is
512×512; 256 and 1024 are supported. A single `--component` excludes all other
geometry. Repeat `--view` for a smaller set. `--view all` renders six directions.

Eevee renders frozen evaluated copies in a temporary scene with consistent
lighting, background, and camera settings. User cameras, lights, selection, and
visibility survive. `framing.json` stores the target center/radius. A smaller or
unchanged asset keeps framing; an outgrown frame expands with an explicit report
warning. `--reframe` intentionally resets it. This makes unchanged framing
comparable and avoids silently clipping larger revisions.

Images and `preview.json` live under `output/previews/<asset>/<component-or-asset>`.
Overwriting requires `--overwrite`. `--debug` produces a separate debug directory
with component colors, names, axes/origin, and bounding boxes. Normal previews omit
debug overlays. Previews are engineering views, not final art presentation renders.
