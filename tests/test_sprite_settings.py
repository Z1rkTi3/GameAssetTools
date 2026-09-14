"""One persistent sprite settings contract for manual UI and programmatic clients."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from game_asset_tools.asset.parameters import changed_components, load_config, validate_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.sprites.settings import FIELDS, read_settings, validate_settings, write_settings


PROJECT = Path(__file__).resolve().parents[1]


class SpriteSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        source = Registry(PROJECT).get("industrial_crate")
        shutil.copytree(source.path, self.project / "game_assets" / "props" / source.id)
        self.entry = Registry(self.project).get(source.id)
        self.path = self.entry.config_path

    def test_schema_defaults_are_complete_and_do_not_write_on_read(self):
        before = self.path.read_bytes()
        result = read_settings(self.project, self.entry.id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["settings"], {field["key"]: field["default"] for field in FIELDS})
        self.assertEqual(result["revision"], hashlib.sha256(before).hexdigest())
        self.assertEqual(Path(result["path"]), self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn("sprites", load_config(self.entry))

    def test_schema_rejects_unknown_wrong_types_nonfinite_and_invalid_choices(self):
        bad = [None, [], {"unknown": 1}, {"look": "cel"}, {"directions": 3}, {"margin": 0.5},
               {"directions": "8"}, {"resolution": 512.0}, {"resolution": True},
               {"elevation": False}, {"azimuth": float("nan")},
               {"light_elevation": float("inf")}, {"light_azimuth": "45"}]
        for field in FIELDS:
            if field["type"] in ("int", "float"):
                bad.extend(({field["key"]: field["min"] - 1},
                            {field["key"]: field["max"] + 1}))
        for settings in bad:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_settings(settings)
        for count in (1, 4, 8, 16):
            self.assertEqual(validate_settings({"directions": count})["directions"], count)
        self.assertEqual(validate_settings({"azimuth": 45})["azimuth"], 45.0)

    def test_updates_persist_between_clients_and_preserve_other_config(self):
        before = json.loads(self.path.read_text(encoding="utf-8"))
        before["style"] = {"materials": {"Painted_Metal": {"roughness": 0.6}}}
        before["appearance"] = {"Body": {"Hull": {"0": {
            "role": "Painted_Metal", "values": {"roughness": 0.7}}}}}
        self.path.write_text(json.dumps(before), encoding="utf-8")
        initial = read_settings(self.project, self.entry.id)
        saved = write_settings(self.project, self.entry.id,
                               {"directions": 4, "look": "standard"}, initial["revision"])
        self.assertEqual(saved["status"], "saved")
        self.assertNotEqual(saved["revision"], initial["revision"])
        fresh = read_settings(str(self.project), self.entry.id)
        self.assertEqual(fresh["settings"], saved["settings"])
        self.assertEqual(fresh["revision"], saved["revision"])
        second = write_settings(self.project, self.entry.id, {"resolution": 256}, fresh["revision"])
        self.assertEqual(second["settings"]["directions"], 4)
        self.assertEqual(second["settings"]["look"], "standard")
        after = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(after.pop("sprites"), second["settings"])
        self.assertEqual(after, before)
        self.assertFalse(list(self.path.parent.glob(".sprites-*.tmp")))

    def test_dry_run_is_reviewable_and_does_not_change_file_or_revision(self):
        before = self.path.read_bytes()
        initial = read_settings(self.project, self.entry.id)
        result = write_settings(self.project, self.entry.id, {"resolution": 256},
                                expected_revision=initial["revision"], dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["settings"]["resolution"], 256)
        self.assertEqual(result["revision"], initial["revision"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_whole_config_revision_rejects_stale_clients_without_overwriting(self):
        initial = read_settings(self.project, self.entry.id)
        config = json.loads(self.path.read_text(encoding="utf-8"))
        config["style"] = {"materials": {"Metal": {"roughness": 0.6}}}
        self.path.write_text(json.dumps(config), encoding="utf-8")
        externally_changed = self.path.read_bytes()
        for dry_run in (False, True):
            with self.assertRaisesRegex(ValueError, "conflict"):
                write_settings(self.project, self.entry.id, {"resolution": 256},
                               initial["revision"], dry_run=dry_run)
        self.assertEqual(self.path.read_bytes(), externally_changed)

    def test_bad_settings_or_invalid_full_config_never_replace_original(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            write_settings(self.project, self.entry.id, {"resolution": -1})
        self.assertEqual(self.path.read_bytes(), before)
        config = json.loads(before)
        config["parameters"]["unknown"] = 1
        self.path.write_text(json.dumps(config), encoding="utf-8")
        invalid = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Unknown parameters"):
            write_settings(self.project, self.entry.id, {"resolution": 256})
        self.assertEqual(self.path.read_bytes(), invalid)

    def test_partial_recipe_defaults_are_validated_without_expanding_config(self):
        self.path.write_text(json.dumps({"parameters": {}}), encoding="utf-8")
        self.assertEqual(read_settings(self.project, self.entry.id)["settings"]["look"], "toon")
        write_settings(self.project, self.entry.id, {"resolution": 256})
        config = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(config["parameters"], {})
        self.assertEqual(set(config), {"parameters", "sprites"})
        self.assertEqual(load_config(self.entry)["sprites"]["resolution"], 256)

    def test_atomic_replace_failure_cleans_temporary_file_and_preserves_config(self):
        before = self.path.read_bytes()
        with patch("game_asset_tools.sprites.settings.os.replace", side_effect=OSError("test refusal")):
            with self.assertRaisesRegex(OSError, "test refusal"):
                write_settings(self.project, self.entry.id, {"resolution": 256})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob(".sprites-*.tmp")))

    def test_concurrent_change_before_replace_is_detected(self):
        externally_changed = self.path.read_bytes() + b"\n"
        with patch("game_asset_tools.sprites.settings.os.fsync",
                   side_effect=lambda descriptor: self.path.write_bytes(externally_changed)):
            with self.assertRaisesRegex(ValueError, "conflict"):
                write_settings(self.project, self.entry.id, {"resolution": 256})
        self.assertEqual(self.path.read_bytes(), externally_changed)
        self.assertFalse(list(self.path.parent.glob(".sprites-*.tmp")))

    def test_sprite_settings_are_validated_but_do_not_make_geometry_dirty(self):
        original = load_config(self.entry)
        changed = deepcopy(original)
        changed["sprites"] = {"resolution": 256, "directions": 4}
        validate_config(self.entry, changed)
        self.assertEqual(changed_components(self.entry.load(), original, changed), set())
        self.assertEqual(changed_components(self.entry.load(), changed, original), set())
        changed["sprites"]["resolution"] = 1024
        self.assertEqual(changed_components(self.entry.load(), original, changed), set())
        changed["style"] = {"materials": {"Metal": {"roughness": 0.6}}}
        self.assertEqual(changed_components(self.entry.load(), original, changed),
                         set(self.entry.load().components(original)))
        for bad in ({"resolution": 0}, None, {"directions": 3}, {"unknown": "x"}):
            changed["sprites"] = bad
            with self.subTest(settings=bad), self.assertRaises(ValueError):
                validate_config(self.entry, changed)


if __name__ == "__main__":
    unittest.main()
