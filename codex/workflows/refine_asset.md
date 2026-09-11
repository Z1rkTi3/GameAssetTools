# Refine an asset

Resolve the asset and the requested semantic component. Inspect that component and
read its relevant config keys. Change values rather than rewriting geometry when
the recipe already exposes the design choice. Rebuild uses the saved blend config.

```powershell
python -m game_asset_tools inspect scout_mech --blend output/blend/scout_mech.blend --component Weapon_Right
python -m game_asset_tools rebuild scout_mech --blend output/blend/scout_mech.blend --set weapons.right_scale=1.5 --dry-run
python -m game_asset_tools rebuild scout_mech --blend output/blend/scout_mech.blend --set weapons.right_scale=1.5 --overwrite
python -m game_asset_tools preview scout_mech --blend output/blend/scout_mech.blend --component Weapon_Right --view perspective --overwrite
```

Review the plan's affected/preserved components. Respect exact scope constraints;
if a mathematical dependency conflicts with them, explain it before broadening the
edit. Approved components are preserved unless explicitly made editable; locked
components remain blocked during stage advancement. A manual-edit conflict needs
an intentional preserve-or-replace decision. Do not auto-unlock or auto-force.

Use stage approval before advancing, then validate the edited asset. Avoid full
scene analysis for simple numerical changes.
