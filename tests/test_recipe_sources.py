"""Opt-in shared-source digests, safe paths and fresh recipe execution."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from game_asset_tools.asset.registry import Registry


RECIPE = '''from pathlib import Path
import hashlib
import sys
import types

# Как у bundled weapon recipes: helper импортируется по содержимому, не mtime.
source = Path(__file__).parents[1] / "shared.py"
content = source.read_bytes()
name = "_gat_test_helper_" + hashlib.sha256(str(source.resolve()).encode() + content).hexdigest()
module = sys.modules.get(name)
if module is None:
    module = types.ModuleType(name)
    module.__file__ = str(source)
    exec(compile(content, str(source), "exec"), module.__dict__)
    sys.modules[name] = module

class Recipe:
    parameters = ()
    value = module.VALUE

    def components(self, config):
        return {}

    def build_component(self, ctx, key, config):
        pass

RECIPE = Recipe()
'''


class RecipeSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.recipe_path = self.project / "game_assets" / "fixtures" / "source_fixture"
        self.recipe_path.mkdir(parents=True)
        self.source_path = self.recipe_path / "asset.py"
        self.helper_path = self.recipe_path.parent / "shared.py"
        self.profile_path = self.recipe_path.parent / "profile.json"
        self.source_path.write_text(RECIPE, encoding="utf-8")
        self.helper_path.write_text("VALUE = 'one'\n", encoding="utf-8")
        self.profile_path.write_text('{"revision": 1}\n', encoding="utf-8")
        (self.recipe_path / "config.json").write_text(
            '{"schema_version": 1, "asset": "source_fixture", "parameters": {}}', encoding="utf-8")
        self.dependencies = ["game_assets/fixtures/shared.py", "game_assets/fixtures/profile.json"]
        self.metadata = {"schema_version": 1, "id": "source_fixture", "display_name": "Source Fixture",
                         "category": "fixtures", "recipe_version": 1, "supported_stages": ["BLOCKOUT"]}
        self.write_metadata()

    def write_metadata(self, dependencies=None):
        metadata = dict(self.metadata)
        if dependencies is not None:
            metadata["source_files"] = dependencies
        (self.recipe_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    def entry(self, dependencies=None):
        self.write_metadata(self.dependencies if dependencies is None else dependencies)
        return Registry(self.project).get("source_fixture")

    def test_legacy_digest_and_cache_remain_exact(self):
        entry = Registry(self.project).get("source_fixture")
        self.assertEqual(entry.source_digest(), hashlib.sha256(self.source_path.read_bytes()).hexdigest())
        recipe = entry.load()
        self.source_path.write_text(RECIPE.replace("class Recipe:", "class ChangedRecipe:")
                                    .replace("RECIPE = Recipe()", "RECIPE = ChangedRecipe()"), encoding="utf-8")
        self.assertIs(entry.load(), recipe)
        self.assertEqual(entry.source_digest(), hashlib.sha256(self.source_path.read_bytes()).hexdigest())
        self.assertNotIn("source_files", entry.as_dict())

    def test_digest_covers_asset_helper_and_profile_only(self):
        entry = self.entry()
        original = entry.source_digest()
        self.profile_path.write_text('{"revision": 2}\n', encoding="utf-8")
        self.assertNotEqual(entry.source_digest(), original)
        self.profile_path.write_text('{"revision": 1}\n', encoding="utf-8")
        self.assertEqual(entry.source_digest(), original)
        self.helper_path.write_text("VALUE = 'two'\n", encoding="utf-8")
        self.assertNotEqual(entry.source_digest(), original)
        self.helper_path.write_text("VALUE = 'one'\n", encoding="utf-8")
        self.source_path.write_text(RECIPE + "\n# change\n", encoding="utf-8")
        self.assertNotEqual(entry.source_digest(), original)
        self.source_path.write_text(RECIPE, encoding="utf-8")
        (self.recipe_path / "unrelated.txt").write_text("untracked source", encoding="utf-8")
        self.assertEqual(entry.source_digest(), original)
        self.assertEqual(entry.as_dict()["source_files"], self.dependencies)

    def test_digest_is_portable_and_order_independent(self):
        entry = self.entry()
        digest = entry.source_digest()
        self.assertEqual(self.entry(list(reversed(self.dependencies))).source_digest(), digest)
        with tempfile.TemporaryDirectory() as destination:
            copied = Path(destination) / "copied"
            shutil.copytree(self.project, copied)
            self.assertEqual(Registry(copied).get("source_fixture").source_digest(), digest)

    def test_cached_and_new_entry_execute_changed_helper_without_bytecode_staleness(self):
        entry = self.entry()
        original = entry.load()
        self.assertEqual(original.value, "one")
        self.assertIs(entry.load(), original)
        stat = self.helper_path.stat()
        self.helper_path.write_text("VALUE = 'two'\n", encoding="utf-8")
        os.utime(self.helper_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        current = entry.load()
        self.assertEqual(current.value, "two")
        self.assertIsNot(current, original)
        self.assertIs(entry.load(), current)
        self.assertEqual(Registry(self.project).get("source_fixture").load().value, "two")

    def test_same_size_and_mtime_asset_edit_executes_fresh_source_bytes(self):
        entry = self.entry()
        original = entry.load()
        stat = self.source_path.stat()
        updated = RECIPE.replace("value = module.VALUE", "value = 'new-value' ")
        self.assertEqual(len(updated), len(RECIPE))
        self.source_path.write_text(updated, encoding="utf-8")
        os.utime(self.source_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(entry.load().value, "new-value")
        self.assertIsNot(entry.load(), original)

    def test_failed_reload_never_returns_old_recipe(self):
        entry = self.entry()
        original = entry.load()
        self.helper_path.write_text("raise RuntimeError('broken helper')\n", encoding="utf-8")
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "broken helper"):
                entry.load()
        self.helper_path.write_text("VALUE = 'two'\n", encoding="utf-8")
        self.assertEqual(entry.load().value, "two")
        self.assertIsNot(entry.load(), original)

    def test_invalid_source_lists_and_paths_reject_during_discovery(self):
        bad_lists = ([], "game_assets/fixtures/shared.py", {}, [None], [1],
                     [self.dependencies[0], self.dependencies[0]],
                     ["game_assets/fixtures/source_fixture/asset.py"],
                     ["../outside.py"], ["/outside.py"], ["C:/outside.py"],
                     ["C:outside.py"], ["\\\\server\\share\\outside.py"],
                     ["game_assets\\fixtures\\shared.py"], ["game_assets//fixtures/shared.py"],
                     ["./game_assets/fixtures/shared.py"], ["game_assets/fixtures/../fixtures/shared.py"],
                     ["game_assets/fixtures/shared.py/"], ["game_assets/fixtures/missing.py"],
                     ["game_assets/fixtures"], ["game_assets/fixtures/shared.py\x00"])
        for paths in bad_lists:
            with self.subTest(paths=paths):
                self.write_metadata(paths)
                with self.assertRaises(ValueError):
                    Registry(self.project).list()

    def test_symlink_escape_and_duplicate_target_reject_and_revalidate(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "shared.py"
            external.write_text("VALUE = 'external'\n", encoding="utf-8")
            link = self.recipe_path.parent / "linked.py"
            junction = False
            try:
                link.symlink_to(self.helper_path)
            except (OSError, NotImplementedError) as exc:
                if os.name != "nt":
                    self.skipTest(f"Symlinks unavailable: {exc}")
                # NTFS junction проверяет тот же реальный resolve/escape путь без
                # привилегии файлового symlink. Ссылка вне game_assets исключает
                # цикл при discovery; перед cleanup удаляется только сама ссылка.
                from _winapi import CreateJunction
                link = self.project / "shared_link"
                CreateJunction(str(self.helper_path.parent), str(link))
                junction = True
            alias = "shared_link/shared.py" if junction else "game_assets/fixtures/linked.py"
            try:
                with self.assertRaisesRegex(ValueError, "duplicate source file target"):
                    self.entry([*self.dependencies, alias])
                entry = self.entry([alias])
                entry.load()
                if junction:
                    link.rmdir()
                    CreateJunction(str(external.parent), str(link))
                else:
                    link.unlink()
                    link.symlink_to(external)
                with self.assertRaisesRegex(ValueError, "outside its project"):
                    entry.source_digest()
                with self.assertRaisesRegex(ValueError, "outside its project"):
                    entry.load()
                with self.assertRaises(ValueError):
                    Registry(self.project).list()
            finally:
                if junction and link.exists():
                    link.rmdir()


if __name__ == "__main__":
    unittest.main()
