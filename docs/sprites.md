# Shared sprite export

GameAssetTools 0.3 exports static assets as transparent PNG frames and a sprite
atlas. Blender UI and Codex use one profile, schema, validator and renderer.
Manual Blender controls run locally and make no Codex/model/network requests.

## One source of settings

The optional `sprites` section in `game_assets/<category>/<asset>/config.json` is
authoritative. Omitted fields use the defaults in `sprites/settings.py::FIELDS`.
The Blender controls are generated from these field definitions; there is no
second collection of UI defaults or render logic. Geometry parameters and sprite
settings have separate validation and changing only `sprites` does not rebuild
geometry. Render reads the current disk profile even when a `.blend` contains an
older configuration snapshot.

Blender keeps an editable form plus the loaded file revision. Save writes through
the shared service and preserves the rest of the config. A changed disk revision
rejects a stale save; reload to see the newer values. This also catches changes to
geometry settings in the same file. Disk writes are not Blender undo operations.
Use an editable project outside the installed plugin's bundled examples/cache.

## Blender

In **3D Viewport → N sidebar → GameAssetTools**, choose the same **Project** and
**Asset** used by Codex. The **Sprites** panel loads that asset's shared profile.
Edit the controls and save, preview one angle, or export all directions. Preview
and export use the shared operation dispatcher. Existing artifacts require the
normal **Overwrite Output** option. The asset must be built in the current scene;
sprite export itself never rebuilds it or advances its stage.

## Codex, shell and Python

The repository commands below also work through the installed plugin's
`scripts/gat.py`; put `--project PATH` before the command in either interface.

```text
python -m game_asset_tools sprite-settings rubin_tower --schema
python -m game_asset_tools sprite-settings rubin_tower --set resolution=512 --set directions=8 --set cel_steps=3
python -m game_asset_tools sprites rubin_tower --blend output/blend/rubin_tower.blend --preview
python -m game_asset_tools sprites rubin_tower --blend output/blend/rubin_tower.blend
```

Settings reads/writes use ordinary Python and do not start Blender. To avoid
overwriting a simultaneous UI edit, pass the revision from a read using
`--expected-revision HASH`. `--dry-run` validates a settings edit without writing.
`sprites --dry-run` describes rendering without writing images. Without `--blend`,
the normal headless runner builds the recipe's BLOCKOUT in a disposable process.
Use `--blend` to render existing/manual work.

Inside Blender, both interfaces ultimately use:

```python
from game_asset_tools.operations import execute
request = {"project": project_path, "asset": "rubin_tower"}
profile = execute({**request, "action": "sprite-settings"})
execute({**request, "action": "sprite-settings",
         "sprite_updates": {"directions": 8},
         "expected_revision": profile["revision"]})
execute({**request, "action": "sprites", "output": output_path})
```

## Controls and output contract

The shared fields are `look` (toon/standard), `resolution`, `directions` (1/4/8/16),
`azimuth`, `elevation`, `margin`, `cel_steps` (2–4), `light_azimuth`,
`light_elevation`, `padding` and `atlas_columns`. Angles are degrees. Azimuth zero
looks from the front (-Y). All frames have the same orthographic scale and ground
anchor; framing accounts for all requested angles before rendering. A transparent
RGBA background and a consistent atlas grid are part of this export contract.

Full output is under `output/sprites/<asset>/`: separate frames, `atlas.png` and
`sprites.json` recording exact settings, frame rectangles, angles and pivots.
One-angle previews are separate from the full atlas. The metadata is the authority
for tile positions and atlas size, including padding. Use the declared pivot when
placing sprites; do not independently trim every frame.

The renderer copies evaluated meshes and their effective material assignments
into a temporary scene. Toon shading uses Eevee, Shader to RGB and a stepped ramp;
standard mode retains the source material graphs. Original meshes, shaders,
cameras, lights, selection and scene settings survive rendering. Source content
outside the selected asset is excluded. Failures do not publish a successful
manifest. This is a static render of the current evaluated frame: animation loops,
outline styles, normal-map atlases and engine-specific importers are future work.
The toon look is baked into PNG; it is not a portable GLB shader.

## Verification

Run pure profile/CLI tests with `python -m unittest discover -s tests -p 'test_*.py'`.
Use Blender background tests `tests/blender_sprites_test.py` and
`tests/blender_sprite_ui_test.py` for atlas pixels/alpha/framing, source preservation,
and UI ↔ programmatic profile round trips. These tests use disposable projects.
