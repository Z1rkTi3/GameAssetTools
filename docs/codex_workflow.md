# Codex access

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

The CLI supports list/create/build/rebuild/inspect/preview/validate/save/export/status/
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

Asset stages require artistic review. Do not turn a routine deterministic command
into a repeated approval conversation when the user has already authorized it.
For new substantial references, supply a concrete blockout preview before asking
for the artistic decision that gates refinement.
