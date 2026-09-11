# Version 0.1.0 verification and scope

Release checks rerun on **2026-09-11**: Windows, Blender **5.2.0 LTS**
(`fbe6228777e7`), host Python **3.12.14**. **42 automated tests passed**, plus
13 CLI smoke commands and standalone ZIP import/installation checks. A fresh
virtual environment installed the checkout with `python -m pip install -e .`;
the installed `gat --version` and `gat list` entry points also passed.
Generated artifacts, logs, and validation-only dependencies are ignored under
`output/`. No user-authored scene content or application preferences were replaced.

## Executed checks

| Command (from repository root) | Result |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` | 14 tests passed: naming, configs, parameter effects, registry/scaffolding, style, CLI parsing, output guards, version consistency, ZIP contents/reproducibility and overwrite protection |
| `blender --background --factory-startup --python-exit-code 1 --python tests/blender_geometry.py` | 11 tests passed: geometry volumes/topology, modifiers/booleans, materials, hierarchy/pivots, selection/edit-mode preservation |
| `blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py` | 13 tests passed: three complete asset pipelines, all build stages, approvals/manual edits, rollback, targeted rebuilds, reproduction, units, validation and dry-runs |
| `blender --background --factory-startup --python-exit-code 1 --python tests/blender_addon_test.py` | 4 tests passed: registration cycles, operators/properties/panel registration, dynamic discovery/controls, edits, inspection, status, save/export |
| `blender --background --factory-startup --python-exit-code 1 --python tests/check_packaged_addon.py` | Standalone ZIP imported and built an asset with checkout imports excluded |
| `python tests/run_cli_smoke.py` | 13 real host/Blender commands passed, including compact JSON, unchanged rebuild, error exit and saved-file preservation |
| `python tests/run_install_smoke.py` | ZIP installed/enabled, built an asset, and disabled through Blender preferences operators using isolated temporary user directories |
| `python -m compileall -q game_asset_tools game_assets blender_addon scripts tests` | Passed |
| Bundled Skill Creator `quick_validate.py .agents/skills/game-asset-tools` | Passed. Its optional PyYAML dependency was installed only in ignored `output/validation_tools`; it is not a GameAssetTools dependency |

Use your actual Python/Blender paths if not on PATH. The CLI smoke test exercises
Windows Blender discovery. Release-check logs are in
`output/publishing/{geometry,workflow,addon,packaged,install,cli}.log`.
The tested archive is `output/game_asset_tools_blender_0.1.0.zip`; both package
checks also accept `--zip` to test an explicitly selected release archive.
Machine-readable evidence is in
`output/smoke/test_result.json`, `output/smoke/artifacts.json`, and
`output/cli_smoke/responses.json`.

[GitHub Actions](../.github/workflows/tests.yml) runs the 14 Python-only tests,
CLI/registry checks, compilation, and ZIP packaging on Windows/Linux with Python
3.11/3.12. Blender integration remains a local check. Live CI results are available
on the repository's Actions page; the local test totals above do not include CI
matrix repetitions. Three packaging regression tests were added to the original
39-test implementation suite for this release.

The artifact test builds each asset in a clean scene, renders all six standard
views at 512px, validates without errors/warnings, saves and reopens its `.blend`,
compares inspection data, exports GLB while excluding a foreign object, checks the
GLB structure, and imports it into another clean scene. Separate tests cover 256px
component previews, 1024px debug previews, framing reuse, and selection/scene
preservation. Perspective previews were visually inspected; this caught and fixed
crate coplanar surfaces and led to clearer opaque example window/cockpit materials.

## Specification audit

This maps the numbered source specification to implementation and concrete evidence.
Suggested names/layouts are implemented with equivalent cohesive modules; optional
and explicitly future systems are distinguished from the first-version deliverables.

| Spec sections | Evidence / implemented result |
|---|---|
| 1–4: reusable framework, agent efficiency, no paid dependencies, four layers | `core/`, `asset/`, `operations.py`, CLI, add-on, `.agents/skills`; three unrelated recipe families; zero runtime dependencies in `pyproject.toml` |
| 5–7: reusable semantic Core, raw bpy escape hatch | `core/{geometry,modifiers,materials,transforms,collections,naming}.py`; geometry tests; recipe-specific construction remains outside Core and uses `ctx.add` |
| 8–12: recipes, contract, useful typed parameters, components | `asset/{recipe,parameters,registry,context}.py`; pure contract tests and three loaded recipes; dependency closure tested on body and right-weapon changes |
| 13–15: semantic names, collections, approval/locking | `asset/{metadata,scene,lifecycle}.py`; naming tests; targeted preservation and locked/manual-edit tests |
| 16–19: simple construction, blockout-first stages and approval | Three primitive recipes, `ctx.stage`, approval-gated advancement; `test_stage_approval_and_all_stages` exercises all three assets through REFINE/DETAIL/FINALIZE |
| 20–24: six standard views, stable framing, component preview, compact inspection | `preview/`, `inspection/`; 18 standard PNGs; targeted/debug preview tests; world bounds and evaluated polygon statistics |
| 25–28: Codex access, persistent instructions, compact commands | Repository skill, root/Codex AGENTS, six workflows, CLI JSON protocol, 13-command smoke test. Optional interactive bridge is not needed for either working interface |
| 29–31: generic add-on/browser/typed controls | `blender_addon/game_asset_tools_addon/`; dynamic category/asset/stage/component enums; float/int/bool/string/choice controls; new recipe discovered without UI edits |
| 32–35: inherited style and simple reusable materials | `game_style.json`, `style/`, `core/materials.py`; style merge/isolation and material reuse/manual-preservation/transmission/emission tests |
| 36–39: units, Godot/GLB, validation/statistics | Root metric scale and glTF axis conversion documented; save/export, actual GLB import, display-unit preservation, validation corruption test; no arbitrary polycount limit |
| 40–43: future collision, LOD, rigging, sprite rendering | Independent export/preview modules, semantic hierarchy/helpers/sockets provide extension points. These features are explicitly future work, not implemented or claimed |
| 44–48: metadata, deterministic rebuild, manual edits, versions | Schema 1, Core 0.1.0, recipe versions/source digests, saved config/style, fingerprints, exact reproduction test, manual-edit guard, documented compatible-extension policy |
| 49–50: Git-friendly source and tests | `.gitignore`, README/changelog/docs/tests, MIT license and CI; outputs excluded; pure and real Blender runners executed; source and release packaging checked for publication |
| 51: three structurally different examples | Watchtower repetition/windows, scout mech joints/hierarchy/weapons, cargo crate frame/lid/optional handles; all build/preview/save/export/import successfully |
| 52–54: required docs, concise AGENTS, create workflow | All ten requested topic documents plus focused workflows; root AGENTS contains the required Core-modification rule; `create` scaffold tested |
| 55–61: targeted edits, visual reasoning, references, restrained Core growth | Skill and refine/inspect workflows; component rebuild preserves unrelated object pointers/fingerprints/materials; stored config reused between numerical edits |
| 62–63: cohesive modules, no everything-manager | Modeling split by responsibility; lifecycle owns build replacement; operations dispatches without modeling; no per-asset UI classes |
| 64–67: clear failures, logging, dry-run, practical efficiency | Structured CLI errors/nonzero exit, INFO/WARNING/ERROR/DEBUG stdlib logging into Blender logs, pre-mutation plans, no-op rebuilds, lazy recipe loading |
| 68–71: interface dependency direction, headless and interactive | Core imports no UI/Codex modules; add-on invokes `operations.execute`; CLI runner invokes the same function; both paths tested |
| 72–75: ownership metadata, registry, flexible categories | Asset root properties/object identity, registry discovery by metadata, duplicate-ID errors, fresh arbitrary category/asset created in tests |
| 76–80: predictable paths, JSON reports, auto framing, optional debug | `export/paths.py`, preview/validation reports, stored center/radius, named/color debug components with bounds and origin axes; overwrite guards tested |
| 81–87: symmetry, repetition, bevel/boolean, pivots, sockets, engine readiness | Core mirror/array/boolean/bevel/pivot/socket helpers tested; tower loop repetition and bilateral mech; static GLB hierarchy/material/scale pipeline |
| 88–89: human and Codex workflows independently useful | Standalone add-on ZIP build without checkout, actual isolated installation/enable/disable; CLI commands without add-on registration; both use identical Core |
| 90–100: incremental implementation, execution, install, Windows, stdlib, quality | Core exercised before add-on integration; actual Blender fixes and execution; saved-file reopen/import tests; ZIP registration/build; installation and extension docs |
| 101–107: art defaults, references authoritative, constrained edits, approvals, reproducibility, explicit destruction | Low-detail examples; instructions preserve reference authority; targeted/manual/locked/reproduction tests; rebuild/delete plans and explicit artifact/manual overwrite flags |
| 108–112: scalable recipe discovery and low context | No hardcoded asset list in UI/Core; small registry metadata response, component inspection, concise skill routing and workflows, detailed logs kept out of stdout |
| 113–120: complete first-version workflow and architecture | Executable shared Core + recipes + two interfaces; sample artifacts, passing suites, source/docs/ZIP delivered; no architecture-only or one-asset prototype |

## Practical boundaries

- Windows/Blender 5.2.0 LTS is the verified Blender environment. Blender integration
  on other operating systems/Blender versions and a real Godot project import have
  not been tested. Python-only CI does not establish Blender compatibility.
- Add-on registration, panel class/properties and operators are exercised in Blender;
  a human visual audit of the sidebar at every screen size is not performed.
- Example outputs are blockouts; they are not claims of reference reconstruction or
  final artistic approval. Future asset-specific art decisions still need review.
- Recipe execution is trusted Python. Staging protects normal registered construction
  failures, not arbitrary external side effects or edits to pre-existing data.
- Fingerprints cover ordinary static geometry/material/transform edits, not every
  animation/driver/constraint system. Lock manually rigged or unusual components.
- Save preserves the whole scene. GLB export includes owned non-helper asset objects;
  unmanaged objects remain in the blend and are reported as excluded from GLB.
- Collision, LOD, rigging/animation pipelines, turntables/sprite sheets, and the
  optional local live bridge remain the explicitly future/optional work from the spec.
