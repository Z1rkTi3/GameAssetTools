# Version 0.4.0 verification and scope

Release checks: **2026-09-14**, Windows, Blender **5.2.0 LTS**
(`fbe6228777e7`), host Python **3.13**. Runtime dependencies remain the Python
standard library and Blender. Optional skill validation uses PyYAML outside the
project/runtime package.

## Automated suites

Run Python tests with `python -m unittest discover -s tests -p "test_*.py"`.
Run each Blender script using
`blender --background --factory-startup --python-exit-code 1 --python tests/<script>.py`.

| Suite | Passed tests |
|---|---:|
| Python contracts, settings, CLI, translation catalogs and both ZIP builders | 56 |
| `blender_geometry.py` | 11 |
| `run_blender_tests.py` | 13 |
| `blender_recolor_test.py` | 6 |
| `blender_material_inspection_test.py` | 7 |
| `blender_batch_test.py` | 4 |
| `blender_view_copy_test.py` | 5 |
| `blender_addon_test.py` | 5 |
| `blender_sprites_test.py` | 6 |
| `blender_sprite_ui_test.py` | 9 |
| `blender_ui_polish_test.py` | 12 |
| `blender_i18n_test.py` | 4 |
| `game_assets/towers/rubin_tower/verify_blender.py` (saved blockout) | 3 |
| **Total** | **141** |

These cover the bundled watchtower, scout mech, cargo crate and ruby tower;
component locks/manual-edit guards, geometry-preserving recolor, batch isolation,
static GLB save/export, sprite framing/transparency and source preservation.
New UI checks cover separate project/asset drafts, stale revisions, integer choices,
explicit reload, report name collisions, saved-file reopening, sole/multiple asset
selection, panel action availability, language overrides and preference persistence.

Russian Blender is tested with new-datablock translation enabled and actual build,
preview and sprite export. World shader lookup uses node types, not localized names.

## Integration and packaging

Additional real-process checks:

- `tests/blender_sprite_roundtrip_test.py`: host CLI → manual Blender settings →
  host CLI → rendered atlas, using a temporary Unicode project path.
- `tests/run_cli_smoke.py`: 13 actual CLI requests, including saved-file edits,
  guards, unchanged rebuild and compact JSON.
- `tests/check_packaged_addon.py`: standalone ZIP import/build without checkout.
- `tests/run_install_smoke.py`: isolated add-on install/enable/build/disable.
- `tests/run_installer_persistence_smoke.py`: installer preserves an existing
  preference and makes an exact backup in a disposable profile.
- `tests/run_release_candidate_smoke.py`: exact Blender/Codex ZIPs; byte-identical
  packaged Core and wrappers; isolated home, Codex and Blender folders; pure locale
  import; CLI init/settings/build/preview; manual build/preview and settings round trip.
- `compileall`, `git diff --check`, plugin manifest and both skill validators.

The candidate archives are `output/game_asset_tools_blender_0.4.0.zip` and
`output/game_asset_tools_codex_0.4.0.zip`. Logs and generated evidence live under
`output/reports/v04/` and `output/release_candidate_0_4_final/`; they are excluded from Git.
See [development](development.md) for reproducible commands and isolation rules.

GitHub Actions runs Python tests, CLI checks, compilation and both package builds
on Windows/Linux with Python 3.11/3.12. Blender integration is verified locally.

## Existing saved assets

Four external ruby-tower snapshots were opened and rendered from front/perspective.
Source file hashes, object fingerprints and saved root metadata were unchanged.
Validation results were compared with the previously installed 0.3 Core:

- The REFINE snapshot retains its existing recipe-version warning and no errors.
- Three earlier snapshots retain pre-existing missing-parameter errors against the
  newer external recipe: `supports.foot_flare` or `architecture.wall_inset`.

The 0.4 UI handles unavailable stages/missing parameters without crashing or
leaving a partial invalid form. It does not silently migrate historical recipes or
regenerate approved geometry. Use the matching original recipe/project to rebuild
an older snapshot. Preview remains available without changing its geometry.

## Practical boundaries

- Windows/Blender 5.2 is the verified integration environment. The declared Blender
  4.2 minimum, Blender on other OS versions and real Godot import remain unverified.
- UI registration, draw methods and operators are tested in Blender; a human visual
  audit of every sidebar width/display scaling is not claimed.
- UI labels, choices, status messages and operator descriptions support EN/RU.
  Standard Blender property tooltips and technical reports retain source text;
  unknown third-party recipe labels use their original text.
- Session drafts clear when opening a file, disabling the add-on or closing Blender.
  Applied geometry and explicitly saved shared sprite profiles persist normally.
- Recipes are trusted local Python. Staging does not undo arbitrary external effects.
  Lock manually rigged/animated components outside the static fingerprint contract.
- Sprites are static direction atlases. Animation, collision/LOD generation and
  rigging pipelines remain future work.
