# Rubin Tower blockout

Reference: `ChatGPT Image 11 сент. 2026 г., 20_48_30.png`, supplied for this asset.
Revision 2 follows the user's update: an oversized red ruby and four supports
around it (left, right, front, back).
Only BLOCKOUT is supported. The scene remains editable and awaits visual approval.

The recipe uses meters, +Z up, -Y front, and a root at the ground-plane origin.
The footprint is centered on X/Y; the single door and window sit on the front
faces. Body depth is assumed equal to its width because the front reference does
not determine depth. The base is slightly wider than deep.

Base and Body use `add_box`; Door and Window use unbeveled `create_panel`.
The window is opaque dark gray glass without emission. Each support uses three
unbeveled `create_support` beams, repeated from one radial centerline at 90-degree
intervals with small overlaps at the two joints. Gem uses `create_mesh` for a closed
red square bipyramid with six vertices and eight triangular faces.
All 17 objects use `ctx.name` and `ctx.add`.
There is no roof, central connector, trim, lighting, or additional decoration.

All 18 controls live in `config.json`:

| Group | Defaults (meters) |
| --- | --- |
| base | width 6.8, depth 5.8, height 1.9 |
| body | width 5.1, depth 5.1, height 2.9 |
| door | width 1.15, height 1.45 |
| window | width 0.45, height 1.3 |
| supports | spacing 3.6, height 1.85, thickness 0.44, inward_offset 0.9 |
| gem | width 3.6, depth 3.6, height 3.8, hover_gap 0.1 |

`supports.spacing` measures opposite foot-center to foot-center along both X and Y.
The four feet must fit within both dimensions of Body. `inward_offset` applies
to each side. `height` is the vertical rise of the centerline; tilted cap corners
can extend above it. `gem.hover_gap` measures vertical clearance from those actual
cap vertices to the gem's lower tip. The palette is asset-local in
`config.json` under `style.materials`.

Parameter changes rebuild dependent components through the standard lifecycle:
Base -> Body/Door, Body -> Window/Supports, Supports -> Gem. Incompatible
proportions fail config validation before mutation instead of silently clamping.

From the repository root, with Python and Blender on PATH (or set
`BLENDER_EXECUTABLE` for the CLI):

```powershell
python -m game_asset_tools build rubin_tower --stage BLOCKOUT
python -m game_asset_tools preview rubin_tower --blend output/blend/rubin_tower.blend --view front --view perspective --resolution 1024
python -m game_asset_tools validate rubin_tower --blend output/blend/rubin_tower.blend
python -m unittest discover -s tests -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_geometry.py
blender --background --factory-startup --python-exit-code 1 --python game_assets/towers/rubin_tower/verify_blender.py
```

Existing generated output requires an explicit `--overwrite` for replacement.
To update an existing unedited blockout with the current source configuration:

```powershell
python -m game_asset_tools rebuild rubin_tower --blend output/blend/rubin_tower.blend --config game_assets/towers/rubin_tower/config.json --dry-run
python -m game_asset_tools rebuild rubin_tower --blend output/blend/rubin_tower.blend --config game_assets/towers/rubin_tower/config.json --overwrite
```

The asset-local verifier reads the saved blockout, checks closed meshes, dimensions,
ground contact, centering, mirror and quarter-turn symmetry, ruby color, and gem clearance, then tests changed
proportions with a moved/rotated root and selective rebuild dependencies. It never
saves its test mutations. Its JSON report is
`output/reports/rubin_tower_geometry.json`.

Deliverables stay in ignored output directories:

- `output/blend/rubin_tower.blend`
- `output/previews/rubin_tower/asset/front.png`
- `output/previews/rubin_tower/asset/perspective.png`
- `output/reports/rubin_tower_validation.json`
