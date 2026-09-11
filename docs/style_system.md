# Game-wide style

`style.load_style(project, asset_overrides)` merges built-in defaults,
`game_style.json`, then the asset config's `style` mapping. Recipes receive the
result as `ctx.style`. Operational settings are validated; descriptive art-direction
extensions are allowed. Source style and config schema versions are both 1.

Defaults favor low-poly, large readable forms, restrained bevels, simple shading,
meters, Godot, and GLB. Asset/reference decisions override artistic defaults.
`materials` maps named roles to Principled base color, metallic, roughness,
alpha, transmission, and emission settings. The shared helper reuses unchanged
definitions and creates variations without editing existing users.

`bevel.width` and `bevel.segments` are defaults a recipe can read; an exposed
asset-specific bevel parameter takes precedence. `preview` controls resolution,
RGB background, and framing margin. `unit_scale` sets meters per recipe unit on
the generated root. Asset roots can subsequently be transformed intentionally.
Changing unit scale after building should be handled by explicitly setting the
root scale; changing it in style alone does not replace a manually positioned root.

Texture resolution and target engine are production guidance. Version 0.1 does
not generate textures, collision, or engine import scripts. No arbitrary polygon
budget is imposed.
