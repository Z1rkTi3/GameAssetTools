# GameAssetTools

One shared Python Core powers the headless CLI and Blender add-on. Asset-specific
recipes live in `game_assets/<category>/<asset>/`; adjustable values belong in
their `config.json`. Project defaults live in `game_style.json`.

Do not modify GameAssetTools Core merely to solve one asset-specific problem.
Search the relevant helper or example before extending reusable functionality.

Build substantial assets at BLOCKOUT first; inspect previews before refinement.
Preserve approved, locked, and manually edited components. Use targeted config
changes and component rebuilds. Never remove user-authored scene content.

Use `python -m game_asset_tools --help` for the compact command interface.
Set `BLENDER_EXECUTABLE` or pass `--blender` when discovery is insufficient.
Read `docs/asset_recipes.md` for authoring, `docs/previews.md` for visual work,
and `docs/export.md` for delivery. Avoid loading all documentation for local edits.

Verification: `python -m unittest discover -s tests -p "test_*.py"` and
`blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py`.
Keep generated output, caches, and Blender backups out of Git. Do not commit or
create branches without a user request.
