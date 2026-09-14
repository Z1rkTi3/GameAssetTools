# Architecture and decisions

The dependency direction is interfaces → operations → asset services/Core → bpy.
The Core has no Codex or add-on dependency. The CLI uses ordinary Python for
discovery/config work and starts Blender for scene work. The add-on calls the same
`operations.execute(request)` inside the current process. There is no network
listener, MCP server, or second modeling implementation.

`AssetRecipe` is a small structural protocol. A recipe declares useful typed
parameters and a dependency graph of semantic components. Builders receive an
explicit `BuildContext`. A new asset therefore requires files under `game_assets/`,
not new UI classes or a Core registry edit. Discovery reads metadata; only the
chosen recipe's Python module is loaded. Recipe code is trusted local Python.

Asset collection properties store the full successful config, style, versions,
stage, and component records. Object properties store identity, generated/helper
flags, stage/status, and an edit fingerprint. Names aid humans; metadata identifies
ownership. Root transforms are user-controlled; recipes construct in asset-local
coordinates. Raw bpy is allowed for specific geometry, registered through `ctx.add`.

Rebuild planning maps changed parameters to components and their dependents.
Explicit component requests must include all affected work. New geometry is built
in a temporary collection. Validation of names/registration and construction
finish before old generated objects are removed. Build failures discard new data.
This is a focused staging mechanism, not a sandbox or undo engine for arbitrary
Python side effects. Recipes must never mutate previously existing objects.

Materials are reusable definitions. Definition changes create new owned materials
instead of modifying shared shaders behind approved geometry. Geometry helpers use
direct mesh/bmesh data; operator-only tasks restore Blender selection/mode.
Preview copies evaluated geometry into a temporary scene. Export filters ownership
and uses one centralized glTF path.

Sprite export uses one pure settings schema and the recipe's `config.json: sprites`
as its authoritative profile. The Blender form is a working copy with an optimistic
revision check; the CLI reads/writes the same service without launching Blender.
Both render entry points read that saved profile and call the same isolated sprite
renderer. The `.blend` build-config snapshot is not a competing sprite profile.

Version 0.3 targets static hard-surface/low-poly assets and static sprite atlases.
Helpers, sockets, hierarchy and stages provide extension points for collision,
LOD, rigging and animation. Those future systems and an optional interactive bridge
are deliberately not implemented. Current GLB export disables animation. No game engine
project or Godot executable is required for the Blender workflow.
