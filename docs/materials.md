# Material roles and geometry-preserving recolor

`inspect` includes `material_roles`: role → components → object slots, linear RGBA,
sRGB hex samples, shared users and protected/manual-edit warnings. Roles are metadata,
not Blender display names. Existing owned palette tags are recognized in old scenes.
`inspect --swatches` additionally writes a portable SVG color/role map. These are base
color samples; complex shaders are marked approximate and lighting is not represented.

Use different recipe roles for parts that must stay independently colored. For example,
`Rubin_Body` belongs to the tower body and `Rubin_RoofCorner` to corner decorations.
Initially give both roles equal material definitions to preserve the existing appearance.

For color-only edits, do not change `style` through `rebuild`. Write a JSON mapping of
allowed roles to only the properties to change, for example `blue.json`:

```json
{"Rubin_Body": {"base_color": [0.025, 0.10, 0.50, 1.0]}}
```

```powershell
python -m game_asset_tools inspect rubin_tower --blend source.blend --swatches --output review
python -m game_asset_tools recolor rubin_tower --blend source.blend --materials blue.json --component Body --output versions/blue --dry-run
python -m game_asset_tools recolor rubin_tower --blend source.blend --materials blue.json --component Body --output versions/blue
```

The plan lists exact objects, slots, roles, before/after values, and blockers. Optional
repeatable `--object` selectors use exact owned object names and intersect component
selectors. Unselected users of the same shader or mesh remain unchanged. Unknown roles,
missing selectors, linked geometry, approved/locked components and manual edits block
the edit. `--replace-edited` explicitly accepts current manual edits as the starting
point; it never bypasses approval/locks or replaces geometry during recolor.

The operation copies each affected shader, changes only allowed properties, and assigns
an object-linked slot. Original mesh datablocks and shared materials are retained.
Before accepting the operation it compares source and evaluated mesh data, attributes,
shape keys, modifiers, parent and object transforms. A mismatch rolls back assignments,
saved configuration and edit baselines. Unrelated shader inputs and render settings are
copied unchanged. Currently this operation supports local mesh objects with exactly one
Principled shader; linked, animated or node-driven target inputs are rejected.

Allowed properties are `base_color`, `metallic`, `roughness`, `alpha`, `transmission`,
`emission`, `emission_strength`. Colors use linear RGBA. Changing base-color alpha does
not implicitly change the separate shader Alpha input or render mode. Specify `alpha`
explicitly when that input is intended to change.

The saved config gains an optional `appearance` mapping:

```json
{"appearance": {"Body": {"Block": {"0": {"role": "Rubin_Body", "values": {"base_color": [0.025, 0.10, 0.50, 1.0]}}}}}}
```

Keys are component, stable local object name and material slot. Later geometry rebuilds
apply these overrides to new staged objects before accepting their fingerprints. The
global palette stays unchanged, so a partial recolor cannot silently repaint decorations
on a later rebuild. A changed slot/role contract requires updating the saved overrides.

The CLI always saves recolor into a separate output version, and rejects the source path
even with `--overwrite`. The Blender sidebar offers Material Role, Base Color, Plan
Material Change and Apply Material Change for the current target. It edits the open
document through the same Core and saves only when Save Blend is requested.
