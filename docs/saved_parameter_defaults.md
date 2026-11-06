# Compatible additive parameters in saved assets

An existing `.blend` keeps its last successful `gat_config`. A recipe can add a
geometry-neutral control without rewriting every saved asset by explicitly
declaring which missing parameters may use their current declared defaults:

```python
class Recipe:
    parameters = (
        Parameter("body.width", "Width", "float", 2.0, min=0.2,
                  components=("Body",)),
        Parameter("body.lower_inset", "Lower inset", "float", 0.0, 0.0, 0.1,
                  components=("Body",)),
    )
    saved_parameter_defaults = ("body.lower_inset",)
```

Opt in only when omission in an old saved asset has the same meaning and geometry
as the declared `Parameter.default`. Do not use this hook for renamed parameters,
changed defaults with different historical meaning, topology/rig migrations, or
recipe-version/source-digest changes. Those still require explicit migration and
the existing rebuild guards. A whitelist does not waive recipe invalidation.

`effective_saved_config(entry, raw)` in `game_asset_tools.asset.parameters` returns
a validated deep copy. It fills only absent whitelisted paths from declared
defaults, reads no `config.json`, and writes no scene data. The optional declaration
must be a tuple of unique declared parameter paths. Unknown paths, missing original
required controls, explicit `None`, scalar parents, invalid values and bounds are
rejected. `validate_config` remains strict; initial builds still require a complete
validated configuration. Ordinary disk/JSON loading continues to use `load_config`.

The Core rebuild path normalizes both candidate and saved configs before comparing
effects. The add-on uses the same effective values for controls, source revisions
and Geometry JSON drafts; validation and export also accept the compatible saved
form. Loading controls, JSON import/export, validation, export, dry-run and failed
rebuild do not persist defaults. An unchanged rebuild leaves saved metadata alone.
Only a successful explicit geometry rebuild stores the complete effective config.
Component locks, manual-edit checks, dependency closure and persistent components
retain their usual rules. Recipes without the declaration keep strict behavior.

Verification:

```powershell
python -B -m unittest discover -s tests -p test_saved_parameter_defaults.py
python -B -m unittest discover -s tests -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_saved_parameter_defaults_test.py
```

The Blender suite creates its own temporary fixture project and never loads game
assets. Its report and source hashes go to `output/saved_parameter_defaults/blender`;
set `GAT_SAVED_DEFAULTS_OUTPUT` to select a separate QA output directory.
