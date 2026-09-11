# Blender add-on

Download `game_asset_tools_blender_0.1.0.zip` from the
[0.1.0 release](https://github.com/Z1rkTi3/GameAssetTools/releases/tag/v0.1.0),
or build the installable ZIP from the project root:

```powershell
python scripts/package_addon.py
```

In Blender, use **Edit > Preferences > Add-ons > Install from Disk**,
select the add-on ZIP (not GitHub's source archive), and enable **GameAssetTools**. Open the 3D View sidebar (`N`) and
choose **GameAssetTools**. The ZIP includes Core, the three example recipes, and
the game style and MIT license; it works without a repository checkout or a separate Python install.
Blender 5.2.0 LTS was tested. The declared API minimum is 4.2, but older versions
have not been verified.

The **Project** field selects an external project containing `game_assets/` and
`game_style.json`; leave it blank to use the bundled examples. Recipe files are
local Python code: select projects you trust. **Refresh Recipes** rediscovers
metadata, reloads recipe code, and loads the selected asset's last successful
configuration from the scene (or disk defaults when it is not built).

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

**Save Blend** and **Export GLB** use predictable paths beneath **Output Folder**
(default: the project's `output/`). Existing output requires **Overwrite Output**.
Build and rebuild affect the open scene; they do not save it implicitly. Save and
export are explicit actions. Export runs Core validation. Blender scene edits can
be undone; disk writes cannot be undone through Blender.

All operators dispatch to `game_asset_tools.operations.execute`. The UI contains
no modeling implementation and needs no changes when a new recipe is added.

Verification:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_addon_test.py
```
