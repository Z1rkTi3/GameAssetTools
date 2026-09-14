# GameAssetTools for Codex

Installable local Codex plugin with the shared GameAssetTools Core, recipes,
previews, validation, GLB export and toon sprite atlases. Includes Rubin Tower:
a large red ruby and four symmetric supports. No external service login or API key.

Requires Codex desktop/CLI, Python 3.11+ and local Blender. Blender 5.2 LTS is the
verified version. Blender's bundled Python can serve as the host Python.

## Install on another account or computer

Extract `game_asset_tools_codex_0.4.0.zip` and run inside its `game-asset-tools` folder:

```powershell
python install_codex_plugin.py
```

If `python` or `codex` is not on PATH, use its full executable path and pass
`--codex <path-to-codex>`. The installer copies this package into
`~/plugins/game-asset-tools`, adds it to the personal marketplace, and asks the
Codex CLI to install and enable it. It preserves unrelated plugins. Reinstalling
into an existing source folder requires `--overwrite`.

Start a new Codex task and invoke `@game-asset-tools` (or its listed skill).
Example: "Use GameAssetTools to make a blockout tower from my reference."
The plugin works outside the original repository. For a new editable project:

```powershell
python scripts/gat.py init-project <workspace>
python scripts/gat.py --project <workspace> list
python scripts/gat.py --project <workspace> build rubin_tower --stage BLOCKOUT
```

Assets and outputs stay in the editable project, outside the plugin cache.
Reuse an existing GameAssetTools project with `--project`; do not initialize over it.
The plugin starts headless Blender for commands. The separately installable Blender
add-on supplies the interactive sidebar and is not needed for this CLI workflow.

Version 0.2 adds `recolor` (no geometry rebuild), role/color inspection, `batch`
variants with common framing and a comparison sheet, `save --view-copy`, and
`validate --report-mode stdout|unique|replace`. Read bundled `docs/materials.md`,
`docs/batch_variants.md`, and `docs/export.md` for the exact command contracts.

Installation belongs to the local OS profile/Codex configuration. The package
does not carry authentication, account identifiers or fixed machine paths. Copy
the same ZIP to another machine/profile and install it there. This does not
automatically install it into every account or publish it to the public directory.
Managed Codex workspaces may restrict plugins. A fresh task picks up installed
skills: https://learn.chatgpt.com/docs/plugins

## Build from source

From the GameAssetTools repository, run `python scripts/package_codex_plugin.py`.
Bundled Core is generated directly from the shared source at packaging time; it
is not a separately maintained implementation. Generated artifacts and personal
installation directories stay out of Git. Changes to the local plugin must be
repackaged and reinstalled; use the plugin-creator cachebuster workflow for local
iterations with an already installed version.
