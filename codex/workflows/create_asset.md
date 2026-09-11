# Create an asset

Read game style, supplied references, and one related recipe. Identify category,
dimensions, axes/pivot, semantic components, dependencies, and adjustable design
choices. Search the relevant Core helper rather than the whole repository.

`python -m game_asset_tools create <id> --category <category>` creates editable
source files. Implement `build_component`, expose meaningful parameters, and keep
reference-specific construction there. Start with BLOCKOUT primitives. Build,
preview useful orthographic/perspective views, inspect silhouette and proportion,
and correct them. Do not add arbitrary greebles or unsupported details.

Show the blockout for artistic approval before substantial refinement. Record that
approval with `status --state approved` on the existing blend. Refine the approved
design, validate, save, and export. For the contract see `docs/asset_recipes.md`.
