# GameAssetTools 0.4.0

[![Python tests](https://github.com/Z1rkTi3/GameAssetTools/actions/workflows/tests.yml/badge.svg)](https://github.com/Z1rkTi3/GameAssetTools/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

GameAssetTools is a reusable Blender asset-production framework for **Codex/Astra
workflows** and **direct human use inside Blender**. Shared Python helpers and
configurable recipes support different game asset types: buildings, props, machines,
weapons, and other procedural low-poly or hard-surface assets. Each game's recipes
and style live alongside one shared Core.

```text
            GameAssetTools Core
                     ↑
              ┌──────┴──────┐
              │             │
           Codex         Blender
         Integration      Add-on
              │             │
              └──────┬──────┘
                     ↓
                Asset Recipes
```

**One Core, two interfaces.** Both call the same operation dispatcher and recipe
contract. A new asset needs a recipe/config, without a new UI class or asset-specific
Core implementation.

GameAssetTools is also available as a portable local **Codex plugin**. Build it with
`python scripts/package_codex_plugin.py`, extract the ZIP in `output/`, and run
`python game-asset-tools/install_codex_plugin.py`. The installer enables it in the
personal marketplace. Start a new Codex task to use it from any local project.
The ZIP includes Core and recipes, including Rubin Tower, and can be installed
under another account/profile without copying credentials. See
[plugin installation and usage](codex/plugins/game-asset-tools/README.md).

## Implemented

- A parameterized industrial walker recipe with mirrored legs, geometric checks,
  Blender geometry controls and JSON presets. See [Mech Generator](docs/mech_generator.md).
- Typed modular part/slot/rig contracts, scene inspection, portable part libraries
  and protected component replacement through Python and the Blender sidebar.
  Persistent recipe components preserve authored rigs; lifetime changes require
  explicit migration. See [modular assemblies](docs/assembly.md).
- Opt-in skeletal GLB export preserves existing skins and Actions; named RGBA
  attributes can be exported independently of material nodes. Validated payloads
  are published atomically. See [save and export](docs/export.md).
- English/Russian Blender sidebar: follow Blender's language or override it in
  GameAssetTools preferences. Scene-aware controls and per-asset session drafts
  keep the selected target clear while switching projects and recipes.
- Toon/standard static sprite atlases with one saved settings profile shared by
  manual Blender controls and Codex/CLI. See [sprite export](docs/sprites.md).
- Material-only recolor with exact role/object plans, geometry invariants, protected
  shared users and persistent object-scoped appearance overrides.
- Material role inspection with linear RGBA, sRGB samples and optional SVG swatches.
- Variant batches in one headless process with shared framing, JSON results and an
  embedded comparison sheet. See [materials](docs/materials.md) and [batches](docs/batch_variants.md).
- Optional framed viewing copies and independent validation report output modes.

- Semantic geometry, modifiers, transforms/pivots, collections, and reusable materials.
- Typed nested configurations, dynamic recipe discovery, component dependencies,
  and game-wide style defaults.
- Targeted rebuilds with plans, approval/lock states, manual-edit detection, and
  staged construction that preserves unrelated generated and user-authored content.
- BLOCKOUT, REFINE, DETAIL, and FINALIZE stages with approval-gated advancement.
- Six standard preview views, component isolation, persisted framing, and debug views.
- Structured inspection, evaluated polygon statistics, and JSON validation reports.
- Explicit `.blend` save and centralized GLB export, static by default.
- Generic Blender sidebar; headless JSON CLI; repository Codex skill and workflows.
- Example watchtower, scout mech, and cargo crate recipes plus automated tests.

## Planned / future

Collision and LOD generation, automatic rig/animation authoring and retargeting,
animated sprite sheets, and an optional live Blender bridge remain future work.
Skeletal export requires an authored rig and clips; assembly contracts do not
certify mechanical clearance or physical joint limits. Godot integration remains
project-owned. The examples demonstrate the framework and are not architectural
requirements or final reference-matched art.

## Requirements

| Use | Requirement |
|---|---|
| Blender work | **Blender 5.2.0 LTS is the only verified Blender version.** The add-on declares a 4.2 API minimum; other versions are unverified. |
| CLI / development | Python 3.11+; the local release checks used Python 3.13 on Windows. Keep the complete checkout for CLI use. |
| Blender add-on | Uses Blender's bundled Python; no separate Python installation is needed. |
| Codex integration | A Codex environment that can read repository skills and run local Python/Blender commands. Codex is optional for manual add-on use. |
| Operating systems | Blender integration was verified on Windows. Python-only CI covers Windows and Linux; this does not verify Blender on Linux. |

Runtime dependencies are Python's standard library and Blender's `bpy`. No API key,
paid generator, or external service is required. Do not install host `bpy`.

## Installation

### Blender Add-on installation

1. Run `python scripts/package_addon.py` to build **`game_asset_tools_blender_0.4.0.zip`**
   in `output/`. This release includes shared sprite export and the English/Russian sidebar;
   it has not been published as a GitHub release.
2. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**, select
   the ZIP, and enable **GameAssetTools**.
3. Open the 3D View sidebar (`N`) and select **GameAssetTools**. Choose a category,
   recipe, and stage, then build. The ZIP includes Core, example recipes, style, and license.

The **Project** field can point to an external folder containing `game_assets/`
and `game_style.json`. See [add-on controls](docs/blender_addon.md).

### Codex integration

Clone this repository and open it as the Codex project. The skill is discovered at
[`.agents/skills/game-asset-tools/SKILL.md`](.agents/skills/game-asset-tools/SKILL.md).
Invoke `$game-asset-tools` or describe an asset-production task. The root
[AGENTS.md](AGENTS.md) and focused [Codex workflows](docs/codex_workflow.md) provide
persistent instructions. No separate MCP server or plugin installation is needed.

The CLI uses host Python to invoke headless Blender. Configure Blender with
`--blender`, `BLENDER_EXECUTABLE`, PATH, or Windows installation discovery. Global
options such as `--project` and `--blender` go **before** the action:

```powershell
python -m game_asset_tools --blender "C:\Path\To\Blender\blender.exe" list
```

The path above is a placeholder. Use your installed executable.

### Development installation

```sh
git clone https://github.com/Z1rkTi3/GameAssetTools.git
cd GameAssetTools
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` on PowerShell or
`source .venv/bin/activate` on a POSIX shell, then:

```sh
python -m pip install -e .
python -m game_asset_tools --version
python -m game_asset_tools list
```

Editable installation is optional when running `python -m game_asset_tools` from
the repository. The CLI currently needs the complete checkout, including `scripts/`,
recipes, and style; a standalone Python wheel is not the distributed product.

## Basic usage

Run from the repository root with Blender discoverable:

```sh
python -m game_asset_tools create cargo_door --category props
python -m game_asset_tools build cargo_door
python -m game_asset_tools preview cargo_door --blend output/blend/cargo_door.blend --view front --view perspective
python -m game_asset_tools inspect cargo_door --blend output/blend/cargo_door.blend --component Body
python -m game_asset_tools validate cargo_door --blend output/blend/cargo_door.blend
python -m game_asset_tools export cargo_door --blend output/blend/cargo_door.blend
```

`create` makes a small working scaffold. Replace its geometry with the intended
asset recipe. The production flow is **reference → recipe/config → blockout →
preview → approved refinement → validation → export**.

For an existing example, change a useful parameter instead of rewriting the scene:

```sh
python -m game_asset_tools build scout_mech
python -m game_asset_tools rebuild scout_mech --blend output/blend/scout_mech.blend --set weapons.right_scale=1.5 --dry-run
python -m game_asset_tools rebuild scout_mech --blend output/blend/scout_mech.blend --set weapons.right_scale=1.5 --overwrite
```

Inspect previews before approving a stage. Use `status --state approved` on the
saved blend before advancing to REFINE/DETAIL/FINALIZE. Locked components require
an explicit state change; detected manual edits require an intentional preserve-or-
replace decision. See [recipe and ownership rules](docs/asset_recipes.md).

Commands print compact JSON and keep detailed logs under `output/reports/`.
Existing artifacts require `--overwrite`. Headless build/rebuild/status/delete save
the resulting scene; add-on operations save only when **Save Blend** is used.
Always pass `--blend` for an existing iteration: omitting it for inspection, preview,
validation, or export constructs a fresh asset from recipe defaults.

## Repository and documentation

| Area | Location |
|---|---|
| Shared Core and asset services | `game_asset_tools/` |
| Blender UI source | `blender_addon/` |
| Codex skill / focused workflows | `.agents/skills/`, `codex/` |
| Example recipes and configurations | `game_assets/` |
| Game defaults | `game_style.json` |
| Command adapter and ZIP builder | `scripts/` |
| Pure Python and Blender tests | `tests/` |

Generated previews, `.blend`/GLB files, reports, logs, caches, and release ZIPs stay
out of Git. Distributable ZIPs are attached to [GitHub Releases](https://github.com/Z1rkTi3/GameAssetTools/releases).

- [Architecture](docs/architecture.md) and [asset recipe contract](docs/asset_recipes.md)
- [Codex workflow](docs/codex_workflow.md) and [Blender add-on](docs/blender_addon.md)
- [Previews](docs/previews.md), [validation](docs/validation.md), and [export conventions](docs/export.md)
- [Extending Core](docs/extending_core.md), [style](docs/style_system.md), and [naming](docs/naming.md)
- [Verification results](docs/verification.md) and [development/release checks](docs/development.md)

## Tests and release package

```sh
python -m unittest discover -s tests -p "test_*.py"
python scripts/package_addon.py
```

The ZIP builder produces `output/game_asset_tools_blender_0.4.0.zip`, checks version
consistency, and includes the MIT license. `--overwrite` explicitly replaces an
existing build. [CI](.github/workflows/tests.yml) runs Python-only tests, imports,
compilation and packaging without Blender. The full Blender and installation
commands remain local; see [development checks](docs/development.md).

## License

[MIT](LICENSE), copyright 2026 Z1rkTi3. See [CHANGELOG.md](CHANGELOG.md) for version history.
