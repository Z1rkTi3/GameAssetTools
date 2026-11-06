"""Opt-in GLB animation stays an export-only request to the shared Blender Core."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_asset_tools.cli import create_asset, main, make_parser
from game_asset_tools.i18n import translate


class AnimatedExportCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gat_animated_export_cli_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        create_asset(self.project, "sample")

    def export_request(self, *arguments):
        output = StringIO()
        with redirect_stdout(output), \
                patch("game_asset_tools.cli.find_blender", return_value=Path("blender")), \
                patch("game_asset_tools.cli.run_blender", return_value={"status": "exported"}) as run:
            code = main(["--project", str(self.project), "export", "sample", *arguments])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "exported")
        run.assert_called_once()
        return run.call_args.args[0]

    def test_default_export_is_explicitly_static(self):
        request = self.export_request()
        self.assertIs(request["animations"], False)
        self.assertIs(request["overwrite"], False)

    def test_opt_in_reaches_shared_request_without_changing_other_flags(self):
        request = self.export_request("--animations", "--dry-run")
        self.assertIs(request["animations"], True)
        self.assertIs(request["dry_run"], True)
        self.assertIs(request["overwrite"], False)
        self.assertEqual(request["action"], "export")

    def test_flag_is_not_accepted_by_build_or_sprite_export(self):
        for action in ("build", "sprites", "save"):
            with self.subTest(action=action), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                make_parser().parse_args([action, "sample", "--animations"])
            self.assertEqual(error.exception.code, 2)

    def test_checkbox_and_explanation_have_russian_translation(self):
        self.assertEqual(translate("Export Animations", "ru_RU"), "Экспортировать анимации")
        self.assertEqual(translate("Preserve owned rig, skin and actions", "ru_RU"),
                         "Сохранить риг, привязку и клипы ассета")


if __name__ == "__main__":
    unittest.main()
