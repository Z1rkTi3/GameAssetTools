"""Appearance envelopes reject ambiguous selectors and invalid material values."""

from copy import deepcopy
from pathlib import Path
import unittest

from game_asset_tools.asset.parameters import load_config, validate_config
from game_asset_tools.asset.registry import Registry

PROJECT = Path(__file__).resolve().parents[1]


class AppearanceConfigTests(unittest.TestCase):
    def test_valid_scoped_configuration_and_rejections(self):
        entry = Registry(PROJECT).get("rubin_tower")
        config = load_config(entry)
        config["appearance"] = {"Body": {"Block": {"0": {"role": "Rubin_Body", "values": {"base_color": [1,0,0,1]}}}}}
        self.assertIs(validate_config(entry, config), config)
        for invalid in ({"Missing": {}}, {"Body": {"Block": {"-1": {}}}},
                        {"Body": {"Block": {"0": {"role": "Rubin_Body", "values": {"roughness": float("nan")}}}}}):
            attempt = deepcopy(config)
            attempt["appearance"] = invalid
            with self.assertRaises(ValueError):
                validate_config(entry, attempt)


if __name__ == "__main__":
    unittest.main()
