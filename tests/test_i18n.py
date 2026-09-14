"""Presentation translations must never change persisted technical vocabulary."""

import json
from pathlib import Path
from string import Formatter
import unittest

from game_asset_tools.asset.registry import Registry
from game_asset_tools.i18n import CATALOGS, translate
from game_asset_tools.sprites.settings import FIELDS


PROJECT = Path(__file__).resolve().parents[1]


class TranslationTests(unittest.TestCase):
    def test_catalogs_have_identical_messages_and_named_placeholders(self):
        self.assertEqual(set(CATALOGS), {"en_US", "ru_RU"})
        self.assertEqual(set(CATALOGS["en_US"]), set(CATALOGS["ru_RU"]))
        formatter = Formatter()
        for message, translated in CATALOGS["ru_RU"].items():
            with self.subTest(message=message):
                self.assertEqual(CATALOGS["en_US"][message], message)
                self.assertTrue(translated.strip())
                original_fields = [(name, spec, conversion) for _, name, spec, conversion in formatter.parse(message) if name is not None]
                translated_fields = [(name, spec, conversion) for _, name, spec, conversion in formatter.parse(translated) if name is not None]
                self.assertCountEqual(original_fields, translated_fields)

    def test_explicit_languages_and_english_fallback(self):
        self.assertEqual(translate("Build"), "Build")
        self.assertEqual(translate("Build", "ru_RU"), "Создать")
        self.assertEqual(translate("Build", "de_DE"), "Build")
        self.assertEqual(translate("Third-party Recipe Label", "ru_RU"), "Third-party Recipe Label")
        self.assertEqual(translate("Unknown {name}", "ru_RU", name="my_asset"), "Unknown my_asset")
        self.assertEqual(translate("literal {braces}", "ru_RU"), "literal {braces}")

    def test_bundled_recipe_and_sprite_labels_have_translations(self):
        for entry in Registry(PROJECT).list():
            with self.subTest(asset=entry.id):
                self.assertIn(entry.display_name, CATALOGS["ru_RU"])
                for parameter in entry.load().parameters:
                    self.assertIn(parameter.label, CATALOGS["ru_RU"])
        for field in FIELDS:
            self.assertIn(field["label"], CATALOGS["ru_RU"])

    def test_interpolation_preserves_ids_paths_values_and_json(self):
        identifiers = ("rubin_tower", "sprites.resolution", "gat_config", "game_asset_tools.action",
                       "BLOCKOUT", "ru_RU", "C:/assets/config.json", "--sprite-preview")
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                self.assertEqual(translate(identifier, "ru_RU"), identifier)
                self.assertEqual(translate("Loaded {name}", "ru_RU", name=identifier), "Загружено: " + identifier)
        profile = {"asset": "rubin_tower", "sprites": {"look": "toon", "resolution": 512}, "state": "locked"}
        encoded = json.dumps(profile, sort_keys=True)
        self.assertEqual(translate(encoded, "ru_RU"), encoded)
        self.assertEqual(json.loads(encoded), profile)


if __name__ == "__main__":
    unittest.main()
