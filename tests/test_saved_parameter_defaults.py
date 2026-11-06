"""Saved additive controls remain explicit, pure and component-scoped."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from game_asset_tools.asset.parameters import (
    Parameter, changed_components, effective_saved_config, validate_config,
)
from game_asset_tools.asset.recipe import ComponentSpec
from game_asset_tools.asset.registry import RecipeEntry


class RequiredRecipe:
    parameters = (
        Parameter("body.width", "Width", "float", 2.0, 1.0, 3.0,
                  components=("Chassis",)),
        Parameter("foot.length", "Foot length", "float", 1.0, 0.5, 2.0,
                  components=("Foot",)),
        Parameter("body.cradle_depth", "Cradle depth", "float", 1.0, 1.0, 1.3,
                  components=("Chassis",)),
        Parameter("frame.lower_inset", "Lower inset", "float", 0.0, 0.0, 0.1,
                  components=("Chassis",)),
    )

    def components(self, config):
        return {"Chassis": ComponentSpec("Structure"), "Foot": ComponentSpec("Feet")}


class AdditiveRecipe(RequiredRecipe):
    saved_parameter_defaults = ("body.cradle_depth", "frame.lower_inset")


def entry_for(recipe=None):
    # Deliberately nonexistent: reading disk config is outside this API.
    return RecipeEntry("saved_controls", "Saved controls", "fixtures", 1,
                       ("BLOCKOUT",), Path("__no_saved_defaults_disk_config__"),
                       _recipe=recipe if recipe is not None else AdditiveRecipe())


def legacy_config():
    return {"schema_version": 1, "asset": "saved_controls",
            "parameters": {"body": {"width": 2.0}, "foot": {"length": 1.0}},
            "style": {"materials": {"Painted_Metal": {"roughness": 0.7}}}}


def complete_config():
    result = legacy_config()
    result["parameters"]["body"]["cradle_depth"] = 1.0
    result["parameters"]["frame"] = {"lower_inset": 0.0}
    return result


class SavedParameterDefaultsTests(unittest.TestCase):
    def test_only_declared_opted_in_defaults_fill_missing_nested_paths(self):
        raw = legacy_config()
        before = deepcopy(raw)
        with patch("game_asset_tools.asset.parameters.read_json",
                   side_effect=AssertionError("Saved normalization must not read disk")):
            effective = effective_saved_config(entry_for(), raw)
        self.assertEqual(effective, complete_config())
        self.assertEqual(raw, before)
        self.assertIsNot(effective, raw)
        self.assertIsNot(effective["parameters"], raw["parameters"])
        self.assertIsNot(effective["parameters"]["body"], raw["parameters"]["body"])

    def test_output_changes_do_not_mutate_nested_input_or_other_sections(self):
        raw = legacy_config()
        raw["sprites"] = {"look": "standard", "resolution": 256}
        raw["appearance"] = {
            "Chassis": {"Housing": {"0": {"role": "Painted_Metal",
                                          "values": {"base_color": [0.2, 0.3, 0.4, 1.0]}}}}}
        before = deepcopy(raw)
        effective = effective_saved_config(entry_for(), raw)
        for section in ("style", "sprites", "appearance"):
            self.assertEqual(effective[section], raw[section])
            self.assertIsNot(effective[section], raw[section])
        effective["parameters"]["body"]["width"] = 2.5
        effective["style"]["materials"]["Painted_Metal"]["roughness"] = 0.4
        effective["sprites"]["resolution"] = 512
        effective["appearance"]["Chassis"]["Housing"]["0"]["values"]["base_color"][0] = 0.8
        self.assertEqual(raw, before)

    def test_existing_nondefault_values_and_absent_optional_sections_stay_exact(self):
        raw = complete_config()
        raw["parameters"]["body"]["cradle_depth"] = 1.2
        raw["parameters"]["frame"]["lower_inset"] = 0.06
        del raw["style"]
        effective = effective_saved_config(entry_for(), raw)
        self.assertEqual(effective, raw)
        self.assertNotIn("style", effective)
        self.assertNotIn("sprites", effective)
        self.assertNotIn("appearance", effective)

    def test_strict_validator_still_rejects_missing_additive_fields(self):
        raw = legacy_config()
        before = deepcopy(raw)
        with self.assertRaises(ValueError):
            validate_config(entry_for(), raw)
        self.assertEqual(raw, before)
        complete = complete_config()
        self.assertIs(validate_config(entry_for(), complete), complete)

    def test_recipe_without_hook_keeps_required_controls_strict(self):
        with self.assertRaises(ValueError):
            effective_saved_config(entry_for(RequiredRecipe()), legacy_config())
        raw = complete_config()
        self.assertEqual(effective_saved_config(entry_for(RequiredRecipe()), raw), raw)

    def test_empty_hook_does_not_fill_any_controls(self):
        recipe = AdditiveRecipe()
        recipe.saved_parameter_defaults = ()
        with self.assertRaises(ValueError):
            effective_saved_config(entry_for(recipe), legacy_config())

    def test_original_required_field_is_never_inferred_from_its_default(self):
        for original in ("width", "foot"):
            with self.subTest(original=original):
                raw = legacy_config()
                if original == "width":
                    del raw["parameters"]["body"]["width"]
                else:
                    del raw["parameters"]["foot"]
                before = deepcopy(raw)
                with self.assertRaises(ValueError):
                    effective_saved_config(entry_for(), raw)
                self.assertEqual(raw, before)

    def test_partial_whitelist_cannot_fill_other_new_controls(self):
        recipe = AdditiveRecipe()
        recipe.saved_parameter_defaults = ("body.cradle_depth",)
        raw = legacy_config()
        before = deepcopy(raw)
        with self.assertRaises(ValueError):
            effective_saved_config(entry_for(recipe), raw)
        self.assertEqual(raw, before)

    def test_malformed_whitelist_is_rejected_even_when_all_values_exist(self):
        invalid = (None, [], {}, "body.cradle_depth", {"body.cradle_depth"},
                   ("body.cradle_depth", "body.cradle_depth"),
                   ("missing",), ("",), ("body..cradle_depth",),
                   (1,), (None,), (["body.cradle_depth"],), ({"path": "body.cradle_depth"},))
        for whitelist in invalid:
            with self.subTest(whitelist=whitelist):
                recipe = AdditiveRecipe()
                recipe.saved_parameter_defaults = whitelist
                raw = complete_config()
                before = deepcopy(raw)
                with self.assertRaises(ValueError):
                    effective_saved_config(entry_for(recipe), raw)
                self.assertEqual(raw, before)

    def test_scalar_or_null_parent_is_not_replaced_by_nested_defaults(self):
        for parent in (None, 0, False, "legacy", []):
            for name in ("body", "frame"):
                with self.subTest(parent=parent, name=name):
                    raw = legacy_config()
                    raw["parameters"][name] = parent
                    before = deepcopy(raw)
                    with self.assertRaises(ValueError):
                        effective_saved_config(entry_for(), raw)
                    self.assertEqual(raw, before)

    def test_explicit_invalid_value_is_not_replaced_with_default(self):
        for path, values in (("body.cradle_depth", (None, False, "1.0", 0.9, 1.31,
                                                   float("nan"), float("inf"))),
                             ("frame.lower_inset", (None, True, "0", -0.01, 0.11))):
            for value in values:
                with self.subTest(path=path, value=value):
                    raw = complete_config()
                    section, name = path.split(".")
                    raw["parameters"][section][name] = value
                    # Compare a stable serialization-independent representation for NaN.
                    before = repr(raw)
                    with self.assertRaises(ValueError):
                        effective_saved_config(entry_for(), raw)
                    self.assertEqual(repr(raw), before)

    def test_unknown_fields_and_bad_envelopes_remain_invalid(self):
        invalid = [None, [], 1]
        for key, value in (("asset", "other"), ("schema_version", 2),
                           ("unexpected", True), ("parameters", None),
                           ("parameters", []), ("style", None)):
            raw = legacy_config()
            raw[key] = value
            invalid.append(raw)
        raw = legacy_config()
        raw["parameters"]["unknown"] = 1
        invalid.append(raw)
        raw = legacy_config()
        raw["parameters"]["body"]["unknown"] = 1
        invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw):
                before = deepcopy(raw)
                with self.assertRaises(ValueError):
                    effective_saved_config(entry_for(), raw)
                self.assertEqual(raw, before)

    def test_effective_default_equality_has_no_false_chassis_change(self):
        entry = entry_for()
        old = effective_saved_config(entry, legacy_config())
        new = effective_saved_config(entry, complete_config())
        self.assertEqual(changed_components(entry.load(), old, new), set())
        new["parameters"]["foot"]["length"] = 1.1
        self.assertEqual(changed_components(entry.load(), old, new), {"Foot"})

    def test_real_new_control_change_affects_its_declared_component(self):
        entry = entry_for()
        old = effective_saved_config(entry, legacy_config())
        for section, name, value in (("body", "cradle_depth", 1.2),
                                      ("frame", "lower_inset", 0.06)):
            with self.subTest(control=name):
                new = deepcopy(old)
                new["parameters"][section][name] = value
                self.assertEqual(changed_components(entry.load(), old, new), {"Chassis"})


if __name__ == "__main__":
    unittest.main()
