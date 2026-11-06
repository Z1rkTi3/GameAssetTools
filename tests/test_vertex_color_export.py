"""Явный цветовой слой проходит от CLI до общего Core только в GLB export."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_asset_tools.cli import create_asset, main, make_parser
from game_asset_tools.export import _vertex_color_options
from game_asset_tools.i18n import translate
from game_asset_tools.operations import execute


class VertexColorExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gat_vertex_color_cli_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        create_asset(self.project, "sample")

    def request(self, *arguments):
        output = StringIO()
        with redirect_stdout(output), \
                patch("game_asset_tools.cli.find_blender", return_value=Path("blender")), \
                patch("game_asset_tools.cli.run_blender", return_value={"status": "exported"}) as run:
            self.assertEqual(main(["--project", str(self.project), "export", "sample", *arguments]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "exported")
        run.assert_called_once()
        return run.call_args.args[0]

    def test_default_and_named_cli_requests_preserve_other_options(self):
        default = self.request()
        self.assertEqual(default["vertex_color_name"], "")
        named = self.request("--vertex-color-name", "Painted Detail", "--animations", "--dry-run")
        self.assertEqual(named["vertex_color_name"], "Painted Detail")
        self.assertIs(named["animations"], True)
        self.assertIs(named["dry_run"], True)
        self.assertIs(named["overwrite"], False)

    def test_cli_option_is_export_only(self):
        for action in ("build", "save", "sprites", "preview"):
            with self.subTest(action=action), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                make_parser().parse_args([action, "sample", "--vertex-color-name", "Colors"])
            self.assertEqual(error.exception.code, 2)

    def test_shared_dispatch_passes_name_to_core_and_reports_dry_run(self):
        base = {"project": str(self.project), "action": "export", "asset": "sample"}
        # Диспетчер импортирует Blender lifecycle для всех действий. Здесь
        # проверяется маршрутизация запроса; реальная сцена покрыта Blender-тестом.
        lifecycle = SimpleNamespace(build=None, set_status=None, delete_generated=None)
        with patch.dict("sys.modules", {"game_asset_tools.asset.lifecycle": lifecycle}), \
                patch("game_asset_tools.export.export_asset", return_value={"status": "exported"}) as export:
            self.assertEqual(execute({**base, "vertex_color_name": "Colors"})["status"], "exported")
        self.assertEqual(export.call_args.kwargs["vertex_color_name"], "Colors")
        self.assertIs(export.call_args.kwargs["animations"], False)
        self.assertIs(export.call_args.kwargs["overwrite"], False)
        with patch.dict("sys.modules", {"game_asset_tools.asset.lifecycle": lifecycle}), \
                patch("game_asset_tools.asset.scene.find_root"):
            planned = execute({**base, "vertex_color_name": "Colors", "dry_run": True})
        self.assertEqual(planned["vertex_color_name"], "Colors")
        self.assertEqual(planned["status"], "planned")

    def test_invalid_names_are_rejected_without_blender_or_registry_access(self):
        for name in (None, True, 4, [], {}):
            with self.subTest(name=name), patch("game_asset_tools.operations.Registry") as registry:
                with self.assertRaisesRegex(ValueError, "vertex_color_name must be a string"):
                    execute({"project": str(self.project), "action": "export", "asset": "sample",
                             "vertex_color_name": name})
                registry.assert_not_called()
                with self.assertRaisesRegex(ValueError, "vertex_color_name must be a string"):
                    _vertex_color_options([], name)

    def test_empty_name_keeps_exporter_defaults_and_named_requires_every_mesh(self):
        # Пустое имя не требует ни активного слоя, ни существования color data.
        bare_mesh = SimpleNamespace(type="MESH", name="Uncolored", data=SimpleNamespace(color_attributes={}))
        colored = SimpleNamespace(type="MESH", name="Colored", data=SimpleNamespace(color_attributes={"Colors": object()}))
        socket = SimpleNamespace(type="EMPTY", name="Socket")
        self.assertEqual(_vertex_color_options([bare_mesh, socket], ""), {})
        with self.assertRaisesRegex(ValueError, "'Colors'.*Uncolored"):
            _vertex_color_options([colored, socket, bare_mesh], "Colors")
        options = _vertex_color_options([colored, socket], "Colors")
        self.assertEqual(options["export_vertex_color"], "NAME")
        self.assertEqual(options["export_vertex_color_name"], "Colors")
        self.assertIs(options["export_all_vertex_colors"], False)

    def test_panel_labels_have_russian_translation(self):
        self.assertEqual(translate("Vertex Color Attribute", "ru_RU"), "Цветовой атрибут вершин")
        self.assertEqual(translate("Named color attribute is required on every mesh", "ru_RU"),
                         "Указанный цветовой атрибут обязателен на каждом меше")


if __name__ == "__main__":
    unittest.main()
