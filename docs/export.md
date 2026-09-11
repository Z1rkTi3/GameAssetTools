# Save and export

`save` writes the current Blender scene to `output/blend/<asset>.blend`. It preserves
other user scene content, including manual edits. The headless build/rebuild/status/
delete commands save automatically; the add-on saves only on request.

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
