# Changelog

## 0.4.0 — 2026-09-14

- English/Russian sidebar with automatic Blender-language selection and an
  independent user preference; language changes preserve parameter drafts.
- Separate collapsible geometry, preview, materials, sprites, export and protection
  sections. Scene-dependent actions are disabled until the chosen asset is built.
- A sole registered scene asset is selected on opening; multiple assets require
  an explicit choice. Selection by object uses ownership metadata, never its name.
- Unapplied geometry, stage and sprite edits survive asset/project switches and
  Refresh within the open Blender session. Explicit reload confirms draft loss;
  stale sources/revisions remain protected. Draft values are not saved in .blend.
- Numeric sprite choices use dropdowns, bundled sprite profiles show read-only
  controls, and reports retain their actual datablock name after collisions/renames.
- Preview and sprite worlds resolve shader nodes by type, so Russian Blender
  datablock names cannot break rendering. Incompatible older recipe configs leave
  a clear error instead of a partially initialized parameter form.
- Both release ZIPs contain identical Core and Python translation catalogs.
  Packaging rejects version drift; isolated tests exercise the exact candidate ZIPs.
- Blender installer enables updated code in a fresh process, preserving preferences
  and avoiding stale submodules from a previously enabled version.
- Includes all material, batch, viewing-copy and sprite functionality developed
  locally as 0.2 and 0.3 below. Recipe/config schemas remain at version 1.

### Included 0.3 development — 2026-09-14

- One asset-local sprite profile and field schema used by both Blender UI and
  Codex/CLI, with validated atomic saves and stale-edit conflict detection.
- Local Blender controls for profile loading/saving, one-angle preview and sprite
  export; settings changes require neither Codex nor geometry rebuilds.
- Eevee toon/standard static sprite rendering, transparent PNG frames and atlas,
  shared orthographic framing, ground pivots and machine-readable frame metadata.
- Temporary evaluated render copies preserve the source document and materials.

### Included 0.2 development — 2026-09-13

- Geometry-preserving `recolor`, exact role/component/object/slot plans, isolated
  shaders, rollback and persistent scoped appearance config. Existing locks and
  manual-edit protections remain in force.
- Role usage inspection with linear RGBA, sRGB samples and SVG swatches.
- One-process variant batches, isolated baselines, common evaluated framing,
  per-variant failures, aggregate JSON and an embedded comparison sheet.
- Optional framed viewing copies that restore the working document and viewport.
- Independent validation report modes: stdout, unique, replace, protected file.
- Blender sidebar material controls and portable Codex/Blender packages updated
  from the same Core; CLI-first skill guidance avoids unnecessary desktop actions.

## 0.1.0 — 2026-09-11

- Shared Blender Core, recipe/config schema 1, dynamic filesystem registry.
- Targeted rebuild planning with dependency closure, approval locks, manual-edit
  fingerprints, and construction rollback before replacement.
- Six standard previews, isolated component previews, persisted framing, debug mode.
- Compact inspection, validation reports, explicit save and selected asset GLB export.
- Tower, articulated scout mech, and cargo crate recipe families.
- Generic Blender sidebar and standalone installation ZIP builder.
- Headless JSON CLI and repository Codex skill with focused workflows.
- Real Blender geometry, production workflow, add-on and packaged import tests.
- Versioned add-on release archive with MIT license and version consistency checks.
- Canonical package version and CLI `--version` command.
- Python-only CI on Windows/Linux, repository documentation, and GitHub release packaging.

### Future work (not implemented)

- Collision generation, LOD generation, and rigging/animation pipelines.
- Animated sprite sheets and an optional live Blender bridge.
- Godot project import verification and additional Blender/OS integration coverage.
