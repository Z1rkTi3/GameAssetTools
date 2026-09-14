# Codex access

## Installed plugin (any local project)

Build `output/game_asset_tools_codex_0.4.0.zip` with
`python scripts/package_codex_plugin.py`. Extract it and run
`python game-asset-tools/install_codex_plugin.py`. This installs and enables
`game-asset-tools` in the personal Codex marketplace. Start a new task to load the
plugin's skill. No service login or API key is required by GameAssetTools.

The package includes the unchanged shared Core and all current recipes. Its
`scripts/gat.py` adapter accepts the normal CLI arguments and an additional
`init-project PATH` command that copies editable recipes/style to a user workspace
without overwriting existing project content. Always keep output outside the
installed plugin/cache. See `codex/plugins/game-asset-tools/README.md` for portable
installation and usage.

The same ZIP can be installed on another local OS profile/computer or with another
Codex account. Installation is local configuration, not automatic account-wide
synchronization. Managed workspace restrictions still apply; local Blender is
required. Official installation/new-session guidance:
[Codex plugins](https://learn.chatgpt.com/docs/plugins).

## Repository skill (development checkout)

Open this checkout as the Codex project. The repository skill lives at
`.agents/skills/game-asset-tools/SKILL.md`; the root `AGENTS.md` provides essential
rules without loading the full manual. Invoke `$game-asset-tools`, or describe the
asset/reference task. This uses the currently documented repository skill mechanism
([official skill discovery](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)).

The skill and workflows are instruction files; executable access is the local CLI.
No API key, plugin server, or background bridge is necessary. Python starts one
headless Blender process per command, passes a JSON request file, and prints one
compact JSON response. Detailed logs stay on disk. Interactive Blender uses the
add-on and the exact same operation dispatcher. A future bridge can call that
dispatcher without duplicating Core.

The CLI supports list/create/build/rebuild/recolor/batch/inspect/preview/validate/save/export/status/
delete. `--project` and `--blender` precede the action. `--component`, `--set`, and
`--view` can repeat. CLI parameter values are JSON; for strings prefer a config
overlay if shell quoting is inconvenient. Numerical overrides such as
`--set weapons.right_scale=1.5` need no special quoting on PowerShell.

Select assets from registry metadata, inspect relevant parameters/components, and
render only when appearance is the question. Existing production iterations always
use `--blend`; omitting it constructs a fresh default scene for read/export commands.
Rebuild starts from saved config and preserves unrelated approved geometry. Save
successful config changes into source JSON when you intend to make them recipe
defaults; runtime overrides are stored in the Blender asset metadata.

For color-only edits use `recolor` with an exact material-role plan and a separate
output version (`docs/materials.md`). For multiple alternatives use one `batch`
request with common framing and its comparison sheet (`docs/batch_variants.md`).
Use `validate --report-mode stdout` for repeat checks; `unique` and `replace` affect
only report files. `save --view-copy --save-view perspective` prepares a separate
viewing file without changing the working viewport. Numerical inspection and saved
previews normally remove any need to automate the desktop for zoom or screenshots.

Asset stages require artistic review. Do not turn a routine deterministic command
into a repeated approval conversation when the user has already authorized it.
For new substantial references, supply a concrete blockout preview before asking
for the artistic decision that gates refinement.

Sprite export uses a shared asset-local disk profile, also edited by Blender UI.
Read `sprite-settings ASSET --schema`, change requested fields with `--set KEY=JSON`
and `--expected-revision HASH`, then run `sprites ASSET --blend PATH --preview`
before full export. Profile edits need no Blender process and do not regenerate
geometry. See [sprites](sprites.md); do not maintain separate Codex settings.
