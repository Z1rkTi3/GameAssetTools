# Development and release checks

Use an editable checkout as described in the README. Runtime dependencies remain
Python standard library plus Blender. The Blender and Codex ZIPs bundle the same
Core; the CLI can use the complete checkout or the Codex package's runtime.

## Adding an asset

Follow **reference → recipe → config → BLOCKOUT → preview → approved refinement →
validation → export**. `python -m game_asset_tools create <id> --category <category>`
creates a working scaffold. Keep specific geometry in its recipe and expose useful
parameters. Read [the recipe contract](asset_recipes.md) before declaring component
dependencies and [Codex workflow](codex_workflow.md) for selective inspection.

Do not modify Core merely to solve one asset-specific problem. Promote functionality
only when it is genuinely reusable; see [extending Core](extending_core.md).
Examples in `game_assets/` exercise the framework and do not define its categories.

## Automated checks

GitHub Actions runs Python-only tests on Windows/Linux and Python 3.11/3.12. It also
checks CLI imports/registry, compiles sources, and builds both ZIPs. Blender integration
is currently local, so the CI workflow does not depend on Blender being installed.

From the project root, with actual Python and Blender executables on PATH:

```sh
python -m unittest discover -s tests -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_geometry.py
blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_addon_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_ui_polish_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_i18n_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_recolor_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_material_inspection_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_batch_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_view_copy_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_sprites_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_sprite_ui_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_sprite_roundtrip_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/check_packaged_addon.py
python tests/run_cli_smoke.py
python tests/run_install_smoke.py
python tests/run_installer_persistence_smoke.py
```

Run Blender scripts in disposable headless processes: they reset their test scenes.
The add-on test builds the versioned ZIP; the package/import and install tests consume
that exact archive. The install test uses isolated Blender profile directories and
does not change the user's enabled add-ons. Test outputs are ignored under `output/`.
The repository skill is instruction-only and its CLI is exercised by the smoke suite.
An optional external Skill Creator validator is not required for development or CI.

## Preparing a release

`game_asset_tools.__version__` is the canonical version for package metadata, CLI,
and ZIP naming. Blender needs a literal `bl_info` tuple and Codex a manifest version;
both builders and tests reject a mismatch. Update README/changelog/docs
together. Recipe/config schema versions are separate from the product version.

Run the checks above, update [verification results](verification.md), then build:

```sh
python scripts/package_addon.py --overwrite
python scripts/package_codex_plugin.py --overwrite
python tests/run_release_candidate_smoke.py --addon-zip output/game_asset_tools_blender_0.4.0.zip --codex-zip output/game_asset_tools_codex_0.4.0.zip --blender blender --output output/release_candidate_0_4
```

The candidate test checks archive/source equality, isolated imports, real CLI and
Blender builds/previews and shared profile round trips. It redirects both OS home
and Blender/Codex directories, asserts that they are temporary before preference
writes, and never uses the existing personal marketplace. Use a new output path
for each run. Do not run ZIP-building suites concurrently.

Inspect package members and test installation from the ZIPs. Commit source/docs/tests
only. Publish an annotated `v<version>` tag and attach both ZIPs to its GitHub Release; do not commit
release archives, sample renders, or generated assets. Include test results and
known limitations in release notes. Git operations require explicit user intent.

Before a public push, review staged files for secrets, private paths, generated
artifacts, unexpectedly large files, version drift, and broken documentation links.
After publishing, verify remote commit/tag, release asset, and CI results.
