# Naming and identity

Public objects use `<asset>_<component>_<local_name>` names, produced by
`core.semantic_name`. Whitespace/punctuation normalize to underscores; long names
retain a stable digest within Blender's name limit. Local names must be unique
inside a component. Object name collisions with preserved user data are errors.

The root collection is `ASSET_<asset>`. Child collections are grouped by semantic
purpose (Structure, Legs, Weapons, Details, and any recipe-specific group). An
owned empty is the asset transform/pivot. Mesh datablocks receive semantic names.

Identity uses `gat_asset_id`, `gat_component`, and `gat_local_name`. Generated
ownership, helpers, stage, approval, and recipe version are explicit metadata.
Renaming in Blender does not make another object owned by the system. Use
`ctx.get` instead of inferring an identity from a generated name or numeric suffix.
