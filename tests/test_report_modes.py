"""Validation reports can repeat without granting artifact overwrite permission."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from game_asset_tools.export.paths import artifact_path, prepare_path, write_validation_report


class ReportModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.report = {"asset": "test_asset", "errors": [], "warnings": []}
        self.blend = self.output / "blend" / "test_asset.blend"
        self.blend.parent.mkdir()
        self.blend.write_bytes(b"existing user blend must remain untouched")
        self.original = self.blend.read_bytes()

    def tearDown(self):
        self.assertEqual(self.blend.read_bytes(), self.original)
        with self.assertRaises(FileExistsError):
            prepare_path(self.blend)
        self.assertNotIn("report", self.report)

    def test_stdout_repeats_without_creating_output(self):
        for _ in range(3):
            self.assertEqual(write_validation_report("test_asset", self.output, self.report,
                                                     mode="stdout"), self.report)
        self.assertFalse((self.output / "reports").exists())

    def test_unique_repeats_and_preserves_all_reports(self):
        paths = [Path(write_validation_report("test_asset", self.output, self.report,
                                               mode="unique", overwrite=True)["report"])
                 for _ in range(4)]
        self.assertEqual(len(set(paths)), 4)
        self.assertFalse(artifact_path(self.output, "reports", "test_asset", "_validation.json").exists())
        for path in paths:
            self.assertEqual(json.loads(path.read_text()), self.report)
            UUID(path.stem.rsplit("_", 1)[1])

    def test_unique_collision_is_exclusive_even_with_overwrite(self):
        first, second = UUID(int=1), UUID(int=2)
        with patch("game_asset_tools.export.paths.uuid4", return_value=first):
            original = write_validation_report("test_asset", self.output, self.report, mode="unique")
        changed = {**self.report, "warnings": ["new report"]}
        with patch("game_asset_tools.export.paths.uuid4", side_effect=[first, second]):
            result = write_validation_report("test_asset", self.output, changed, mode="unique", overwrite=True)
        self.assertNotEqual(original["report"], result["report"])
        self.assertEqual(json.loads(Path(original["report"]).read_text()), self.report)

    def test_replace_only_replaces_canonical_report(self):
        unrelated = self.output / "reports" / "other.json"
        unrelated.parent.mkdir()
        unrelated.write_text("do not replace")
        path = None
        for index in range(3):
            changed = {**self.report, "iteration": index}
            result = write_validation_report("test_asset", self.output, changed, mode="replace")
            path = Path(result["report"])
            self.assertEqual(json.loads(path.read_text()), changed)
        self.assertEqual(path.name, "test_asset_validation.json")
        self.assertEqual(unrelated.read_text(), "do not replace")

    def test_default_file_retains_legacy_protection(self):
        write_validation_report("test_asset", self.output, self.report)
        with self.assertRaises(FileExistsError):
            write_validation_report("test_asset", self.output, self.report)
        result = write_validation_report("test_asset", self.output, self.report, overwrite=True)
        self.assertEqual(Path(result["report"]).name, "test_asset_validation.json")

    def test_invalid_mode_has_no_output_side_effect(self):
        with self.assertRaises(ValueError):
            write_validation_report("test_asset", self.output, self.report, mode="unknown", overwrite=True)
        self.assertFalse((self.output / "reports").exists())


if __name__ == "__main__":
    unittest.main()
