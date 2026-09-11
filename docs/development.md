# Development and release checks

Use an editable checkout as described in the README. Runtime dependencies remain
Python standard library plus Blender. The standalone product is the Blender add-on
ZIP; the CLI uses resources from the complete checkout.

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
checks CLI imports/registry, compiles sources, and builds the ZIP. Blender integration
is currently local, so the CI workflow does not depend on Blender being installed.

From the project root, with actual Python and Blender executables on PATH:

```sh
python -m unittest discover -s tests -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_geometry.py
blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_addon_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/check_packaged_addon.py
python tests/run_cli_smoke.py
python tests/run_install_smoke.py
```

Run Blender scripts in disposable headless processes: they reset their test scenes.
The add-on test builds the versioned ZIP; the package/import and install tests consume
that exact archive. The install test uses isolated Blender profile directories and
does not change the user's enabled add-ons. Test outputs are ignored under `output/`.
The repository skill is instruction-only and its CLI is exercised by the smoke suite.
An optional external Skill Creator validator is not required for development or CI.

## Preparing a release

`game_asset_tools.__version__` is the canonical version for package metadata, CLI,
and ZIP naming. Blender needs a literal `bl_info` tuple for discovery; the builder
and tests reject a mismatch. Update version references in README/changelog/docs
together. Recipe/config schema versions are separate from the product version.

Run the checks above, update [verification results](verification.md), then build:

```sh
python scripts/package_addon.py --overwrite
```

The current filename is `output/game_asset_tools_blender_0.1.0.zip`. Inspect its
members and test installation from the ZIP. Commit source/docs/tests only. Publish
an annotated `v<version>` tag and attach the ZIP to its GitHub Release; do not commit
release archives, sample renders, or generated assets. Include test results and
known limitations in release notes. Git operations require explicit user intent.

Before a public push, review staged files for secrets, private paths, generated
artifacts, unexpectedly large files, version drift, and broken documentation links.
After publishing, verify remote commit/tag, release asset, and CI results.
