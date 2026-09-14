"""The CLI and Blender dispatcher share a disk profile, without starting Blender."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_asset_tools.cli import create_asset, main
from game_asset_tools.operations import execute


class SpriteCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        create_asset(self.project, "sample")

    def cli(self, *arguments):
        output = StringIO()
        with redirect_stdout(output), patch("game_asset_tools.cli.run_blender", side_effect=AssertionError("Settings must not start Blender")):
            code = main(["--project", str(self.project), *arguments])
        return code, json.loads(output.getvalue())

    def test_cli_write_dispatcher_read_and_schema(self):
        code, before = self.cli("sprite-settings", "sample", "--schema")
        self.assertEqual(code, 0)
        self.assertEqual({field["key"] for field in before["fields"]}, set(before["settings"]))
        code, saved = self.cli("sprite-settings", "sample", "--set", "resolution=256",
                               "--set", 'look="standard"', "--expected-revision", before["revision"])
        self.assertEqual(code, 0)
        current = execute({"action": "sprite-settings", "asset": "sample", "project": str(self.project)})
        self.assertEqual(current["settings"], saved["settings"])
        self.assertEqual(current["settings"]["resolution"], 256)
        self.assertEqual(current["settings"]["look"], "standard")

    def test_dispatcher_write_cli_read_and_conflict(self):
        code, original = self.cli("sprite-settings", "sample")
        execute({"action": "sprite-settings", "asset": "sample", "project": str(self.project),
                 "sprite_updates": {"cel_steps": 4}})
        code, current = self.cli("sprite-settings", "sample")
        self.assertEqual(current["settings"]["cel_steps"], 4)
        code, error = self.cli("sprite-settings", "sample", "--set", "cel_steps=2",
                               "--expected-revision", original["revision"])
        self.assertEqual(code, 1)
        self.assertEqual(error["status"], "error")
        self.assertEqual(self.cli("sprite-settings", "sample")[1]["settings"]["cel_steps"], 4)

    def test_invalid_or_dry_run_cannot_write_profile(self):
        path = self.project / "game_assets/other/sample/config.json"
        before = path.read_bytes()
        for setting in ("directions=3", "resolution=true", "typo=1", "cel_steps=NaN"):
            self.assertEqual(self.cli("sprite-settings", "sample", "--set", setting)[0], 1)
            self.assertEqual(path.read_bytes(), before)
        code, result = self.cli("sprite-settings", "sample", "--set", "cel_steps=4", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(path.read_bytes(), before)

    def test_sprite_export_rejects_hidden_geometry_or_profile_overrides(self):
        for flag in (("--set", "resolution=128"), ("--resolution", "256"), ("--component", "Body")):
            code, result = self.cli("sprites", "sample", *flag)
            self.assertEqual(code, 1)
            self.assertIn("saved profile", result["error"])

    def test_programmatic_requests_share_validation(self):
        request = {"project": str(self.project), "asset": "sample"}
        for invalid in (None, [], 0, ""):
            with self.assertRaises(ValueError):
                execute({**request, "action": "sprite-settings", "sprite_updates": invalid})
        for option in ({"resolution": 128}, {"views": ["front"]}, {"sprite_updates": {}},
                       {"replace_edited": True}, {"sprite_preview": "false"}):
            with self.assertRaises(ValueError):
                execute({**request, "action": "sprites", **option})


if __name__ == "__main__":
    unittest.main()
