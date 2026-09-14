# Save and export

For transparent toon/standard PNG frames, atlases and shared Blender/Codex render
settings, see [sprite export](sprites.md). The `sprites` operation is separate
from GLB export and does not modify source materials.

`save` writes the current Blender scene to `output/blend/<asset>.blend`. It preserves
other user scene content, including manual edits. The headless build/rebuild/status/
delete commands save automatically; the add-on saves only on request.

Use `save <asset> --view-copy --save-view front` (or `--save-view perspective`) for a separate
`output/blend/<asset>_view.blend` prepared for opening in Blender. The copy frames
the full evaluated asset, including modifiers and parent transforms, in every
saved 3D viewport and enables material preview. Other standard preview directions
are accepted too. The working file, viewport state, and selection are retained,
including if saving fails. This uses Blender's save-copy API, without UI control
or preference changes. The scene must contain a saved 3D viewport. `--overwrite`
can replace an existing viewing copy, but can never replace the currently open
source file through this mode; choose another output directory in that case.

Validation output has explicit modes: `validate <asset> --report-mode stdout`
returns JSON without writing a report; `unique` creates an exclusive UUID-named
report; `replace` updates only `reports/<asset>_validation.json`. These modes allow
repeat checks without `--overwrite` and grant no overwrite permission for blend,
preview, or GLB artifacts. The default `file` mode retains the existing fixed path
and explicit overwrite requirement. `validate --dry-run` still validates without
writing a file, regardless of report mode.

`export` validates then writes `output/glb/<asset>.glb`. It selects generated asset
objects and its root, omits construction helpers and unrelated/unmanaged objects,
applies modifiers through the glTF exporter, and includes custom properties. Named
socket empties can be registered as non-helper objects and retained. Static export
is the implemented scope; animation is disabled.

Recipe coordinates use +Z up and -Y front in meters by default. The glTF exporter
converts to glTF +Y up; Blender -Y front maps to glTF +Z. Godot imports the GLB basis;
gameplay code using Godot -Z forward may rotate the visual root 180 degrees or
choose its model-front convention accordingly. Do not rotate individual meshes
ad hoc. Root scale and hierarchy are retained. Blender's display unit scale is
temporarily normalized during export and restored afterward.

Existing output needs `--overwrite`, independent of permission to rebuild generated
geometry. The exporter restores selection, active object, and object visibility.
GLB verification checks magic/version/length, JSON structure, meshes, materials,
and nodes. The smoke suite additionally imports each GLB into a fresh Blender scene.
Actual Godot project import is not tested in this repository; no Godot project is
present. Collision, LOD, and animation are future modules, not implied by GLB success.
