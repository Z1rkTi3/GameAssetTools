# Blender add-on

Build the installable `game_asset_tools_blender_0.4.0.zip` from the project root:

```powershell
python scripts/package_addon.py
```

In Blender, use **Edit > Preferences > Add-ons > Install from Disk**,
select the add-on ZIP (not GitHub's source archive), and enable **GameAssetTools**. Open the 3D View sidebar (`N`) and
choose **GameAssetTools**. The ZIP includes Core, all current recipes (including Rubin Tower), and
the game style and MIT license; it works without a repository checkout or a separate Python install.
Blender 5.2.0 LTS was tested. The declared API minimum is 4.2, but older versions
have not been verified.

To install and enable the built ZIP automatically, close Blender and run from the
checkout:

```powershell
python scripts/install_blender_addon.py --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

Use your Blender executable path, or omit `--blender` for automatic discovery.
`--zip PATH` selects a different locally built add-on ZIP. The installer backs up
existing `userpref.blend` beside it as `userpref.blend.gat-<timestamp>.bak`, preserves
enabled add-ons and other preferences, saves enablement, and verifies it in a fresh
Blender process. It does not save scenes or startup files. Do not run the installer
inside a factory-startup Blender session. A Blender instance already open during
installation must be restarted; closing it first avoids competing preference saves.

The installation belongs to the operating-system user and Blender version, not a
ChatGPT/Codex account. Switching Codex accounts on this same OS profile does not
require reinstalling the Blender add-on. For another computer, OS user, or Blender
version, copy the ZIP and install/enable it there through Preferences. Rebuild the
ZIP with `python scripts/package_addon.py --overwrite` to bundle current recipes,
including `towers/rubin_tower`.

## Optional live BlenderMCP connection

GameAssetTools works through its own CLI/add-on without an MCP server. For a live
Codex connection to an open Blender window, the separate
[official BlenderMCP project](https://github.com/ahujasid/blender-mcp) supplies
the bridge. The setup verified on 2026-09-12 uses server `blender-mcp==1.9.1`
and its bundled add-on 1.6 (protocol 5).

With `uvx` and `codex` installed, use the actual Blender add-ons directory:

```powershell
uvx --from blender-mcp==1.9.1 blender-mcp install-addon --addons-dir <Blender-addons-directory>
codex mcp add blender --env BLENDER_MCP_DISABLE_TELEMETRY=1 --env PYTHONIOENCODING=utf-8 --env BLENDERMCP_ADDONS_DIR=<Blender-addons-directory> -- uvx --from blender-mcp==1.9.1 blender-mcp
```

Use full executable paths if these commands are not on PATH. Enable Blender MCP
in Blender Preferences and turn off **Allow Telemetry**. Its bridge starts at
`localhost:9876` when a normal Blender GUI process runs; headless Blender does not
serve this live bridge. Start a new Codex task after adding the MCP configuration.
This MCP configuration is separate from the portable GameAssetTools plugin; repeat
it on another computer/profile if a live bridge is needed there.

## Language and scene selection

The **Language** control follows Blender by default (**Automatic**) and also offers
**English** and **Русский** independently of Blender's language. The same setting is
available in the add-on's Preferences. Save Blender Preferences to retain it after
restart. It is user-wide, never written into asset configs. Labels, choices and
operation descriptions are localized; Blender's standard property tooltips and
technical JSON reports retain their original technical text. Third-party recipe
labels fall back to English/source text when absent from the translation catalog.

On file open, the panel chooses the sole registered asset if its recipe exists in
the current project. If several assets exist, choose one explicitly in **Asset** or
use **Use Selected Asset**. That button reads GameAssetTools ownership metadata, not
object names. The panel states whether the chosen asset is built and disables
scene actions when unavailable. Geometry, preview, materials, sprites, output and
protection have separate collapsible sections.

The **Project** field selects an external project containing `game_assets/` and
`game_style.json`; leave it blank to use the bundled examples. Recipe files are
local Python code: select projects you trust. **Refresh Recipes** rediscovers
metadata and reloads recipe code while retaining unsaved per-asset drafts. Without
a draft it uses the selected asset's last successful scene configuration, or disk
defaults when unbuilt. Existing scene metadata does not record a project path:
select the original project before operating on older scenes. Within a session,
switching to another project with the same asset ID blocks scene actions until
the original project is restored.

Geometry parameters, stage and sprite settings retain separate drafts per project,
asset and scene while switching selectors or refreshing. Building/rebuilding clears
the applied geometry draft; saving a sprite profile clears its sprite draft.
**Reload Saved Parameters/Settings** asks before discarding edits in the UI. Source
changes still require reload, so restoring an old draft cannot bypass conflict
checks. Draft values are memory-only: opening a file, disabling the add-on or closing
Blender clears them. Save the asset/profile explicitly to keep applied work.

Select a category and asset. Controls are generated from the recipe's typed
parameters, including numbers, checkboxes, strings, and choices. Core validates
parameter bounds before geometry changes. **Build** begins at BLOCKOUT. Edit
parameters and choose **Rebuild** to change only affected components. The
confirmation lists exact replacements. **Target** restricts previews, inspection,
status, and deletion; on rebuild Core checks that this target includes every
component affected by the new parameters.

Inspect BLOCKOUT previews before changing the stage. With **Whole Asset** selected,
set the state to **Approved** before advancing the stage. Approving individual
components protects local edits; **Locked** components always require an explicit
state change back to **Editable** before replacement. Manual edits are detected.
The **Replace Manually Edited Geometry** checkbox is a deliberate override for
edited generated data, and does not bypass component locks or delete user objects.

Preview buttons operate on the target. **Inspect Selected** resolves the active
object's semantic component. Full structured reports are stored in the Blender
Text datablock `GameAssetTools_Report`; **Open Detailed Report** opens it in the
current area. Validation summaries show error and warning counts.

**Materials** uses the current component target. Select a recorded **Material Role**
and **Base Color**, use **Plan Material Change** for the exact slot list, then
**Apply Material Change**. Protected or manually edited content remains guarded.
Recolor uses the shared Core without regenerating geometry; see `docs/materials.md`.
Inspect reports include role usage, linear RGBA and sRGB samples. The **Validation
Report** selector controls in-app output, unique report files or report-only replacement.
**Save Viewing Copy** produces a separate framed file for the selected **Opening View**,
while restoring the working viewport. Batch processing uses the headless CLI because
it opens separate documents; see `docs/batch_variants.md`.

**Save Blend** and **Export GLB** use predictable paths beneath **Output Folder**
(default: the project's `output/`). Existing output requires **Overwrite Output**.
Build and rebuild affect the open scene; they do not save it implicitly. Save and
export are explicit actions. Export runs Core validation. Blender scene edits can
be undone; disk writes cannot be undone through Blender.

All operators dispatch to `game_asset_tools.operations.execute`. The UI contains
no modeling implementation and needs no changes when a new recipe is added.

**Sprites** uses the same saved profile as Codex's `sprite-settings` command.
Choose an editable **Project**, load the selected asset's profile, adjust its
schema-generated controls, then save, preview or export. Profile saves detect
external edits before overwriting them. Unchanged render controls pick up the
latest saved profile. No Codex/model/network request is involved in manual use.
See [shared sprite export](sprites.md) for controls and output metadata.

Bundled profile controls are read-only; you can render their saved settings or use
an editable project to change them. Direction counts use the supported numeric
choices. Output folder and overwrite controls are shared in **Save and Export**.

Verification:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_addon_test.py
python tests/run_install_smoke.py
python tests/run_installer_persistence_smoke.py
```

Both install smoke tests use disposable Blender user directories. The persistence
test also checks preservation of a saved preference and the exact backup contents.
