"""Изменение исходников при сборке сохраняет прежнюю геометрию и metadata.

Все recipe/helper файлы создаются во временном проекте. Намеренное изменение
helper моделирует сохранение исходника редактором во время работы Blender.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from game_asset_tools import core as gat
from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.style import load_style


ASSET = "source_transaction_fixture"
RECIPE = '''from pathlib import Path
from game_asset_tools.asset import ComponentSpec, Parameter

namespace = {}
source = Path(__file__).parents[1] / "shared.py"
exec(compile(source.read_bytes(), str(source), "exec"), namespace)
VALUE = namespace["VALUE"]

class Recipe:
    parameters = (Parameter("body.width", "Width", "float", 1.0, .5, 3.0,
                            components=("Body", "Cap")),)

    def components(self, config):
        return {"Body": ComponentSpec("Structure"), "Cap": ComponentSpec("Structure")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        width = config["parameters"]["body"]["width"] * VALUE
        size = (width, 1, .5) if key == "Body" else (.5 * width, .5, .2)
        obj = gat.add_box(ctx.name("Block"), size, location=(0, 0, .5 if key == "Body" else .9))
        ctx.add(obj, "Block")
        gat.assign_material(obj, gat.project_material("Painted_Metal", ctx.style))

RECIPE = Recipe()
'''


def identities():
    """Проверяет не только имена: прежние Blender ID должны остаться прежними."""
    return {name: {item.as_pointer() for item in getattr(bpy.data, name)}
            for name in ("objects", "collections", "meshes", "armatures", "actions", "materials")}


def asset_snapshot(root):
    return {"root": root.as_pointer(), "metadata": dict(root.items()),
            "pivot_matrix": [list(row) for row in root_object(root).matrix_world],
            "objects": {obj.name: (obj.as_pointer(), obj.data.as_pointer(), fingerprint(obj), dict(obj.items()))
                        for obj in asset_objects(root)}}


class SourceTransactionTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_source_transaction_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        folder = self.project / "game_assets/tests" / ASSET
        folder.mkdir(parents=True)
        self.helper = folder.parent / "shared.py"
        self.original_helper = b"VALUE = 1.0\n"
        self.helper.write_bytes(self.original_helper)
        (folder / "asset.py").write_text(RECIPE, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps({"schema_version": 1, "id": ASSET,
            "display_name": "Source transaction fixture", "category": "tests", "recipe_version": 1,
            "supported_stages": ["BLOCKOUT"], "source_files": ["game_assets/tests/shared.py"]}), encoding="utf-8")
        (folder / "config.json").write_text(json.dumps({"schema_version": 1, "asset": ASSET,
            "parameters": {"body": {"width": 1.0}}}), encoding="utf-8")
        shutil.copyfile(PROJECT / "game_style.json", self.project / "game_style.json")
        self.entry = Registry(self.project).get(ASSET)
        self.config, self.style = load_config(self.entry), load_style(self.project)
        build(self.entry, self.config, self.style)
        self.root = find_root(ASSET)
        self.root["user_note"] = "Сохранить пользовательскую пометку"
        pivot = root_object(self.root)
        pivot.location, pivot.rotation_euler = (4, -2, 3), (.1, .2, .3)
        self.user = gat.add_box("KeepUserContent", (1, 1, 1), location=(12, 0, 0))
        action = bpy.data.actions.new("KeepUserAction")
        action.use_fake_user = True
        bpy.context.view_layer.update()

    def check_failure(self, mode):
        changed = deepcopy(self.config)
        changed["parameters"]["body"]["width"] = 2.0
        before_ids, before = identities(), asset_snapshot(self.root)
        recipe, calls = self.entry.load(), []
        original = recipe.build_component

        def interrupted(ctx, key, config):
            original(ctx, key, config)
            calls.append(key)
            if key == "Body":
                if mode == "change":
                    self.helper.write_bytes(b"VALUE = 9.0\n")
                else:
                    self.helper.unlink()

        try:
            with patch.object(recipe, "build_component", side_effect=interrupted):
                with self.assertRaisesRegex(ValueError, "Recipe sources changed during build"):
                    build(self.entry, changed, self.style, rebuild=True)
        finally:
            self.helper.write_bytes(self.original_helper)

        # Даже второй компонент строится закреплённым recipe. Затем общий
        # precommit-check отклоняет staging, не затрагивая ни один старый ID.
        self.assertEqual(calls, ["Body", "Cap"])
        self.assertEqual(identities(), before_ids)
        self.assertEqual(asset_snapshot(find_root(ASSET)), before)
        self.assertEqual(root_object(self.root).location[:], (4, -2, 3))
        self.assertEqual(bpy.data.objects.get("KeepUserContent"), self.user)
        self.assertIn("KeepUserAction", bpy.data.actions)

        # После восстановления источника обычная повторная сборка работает,
        # а сохранённый digest относится к использованному snapshot исходников.
        result = build(self.entry, changed, self.style, rebuild=True)
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(result["components"], ["Body", "Cap"])
        self.assertEqual(self.root["gat_recipe_digest"], self.entry.source_digest())
        self.assertEqual(json.loads(self.root["gat_config"])["parameters"]["body"]["width"], 2.0)
        self.assertEqual(self.root["user_note"], "Сохранить пользовательскую пометку")

    def test_changed_helper_rejects_before_replacement(self):
        self.check_failure("change")

    def test_deleted_helper_rejects_before_replacement(self):
        self.check_failure("delete")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SourceTransactionTests))
    raise SystemExit(not result.wasSuccessful())
