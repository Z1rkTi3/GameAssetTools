"""Verify real add-on languages and preference persistence using disposable data.

Run in a fresh Blender: --background --factory-startup --python-exit-code 1
--python tests/blender_i18n_test.py. Only child processes save user preferences,
and each asserts that its configuration folder is inside a temporary profile.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import addon_utils
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "blender_addon"))

import game_asset_tools_addon as addon
from game_asset_tools_addon import i18n, properties
from game_asset_tools.asset.scene import find_root
from game_asset_tools.operations import execute


class BlenderTranslationTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_i18n_")
        self.project = Path(self.directory.name)
        recipe = Path("game_assets/towers/rubin_tower")
        shutil.copytree(PROJECT / recipe, self.project / recipe)
        shutil.copyfile(PROJECT / "game_style.json", self.project / "game_style.json")
        addon_utils.enable(i18n.ADDON_ID, default_set=True, persistent=True)
        self.preferences = i18n.get_preferences()
        self.assertIsNotNone(self.preferences)
        self.view_language = bpy.context.preferences.view.language
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(self.project)
        bpy.ops.game_asset_tools.refresh()

    def tearDown(self):
        bpy.context.preferences.view.language = self.view_language
        addon_utils.disable(i18n.ADDON_ID, default_set=True)
        self.directory.cleanup()

    def test_explicit_auto_languages_and_live_data_preservation(self):
        execute({"action": "build", "project": str(self.project), "asset": "rubin_tower"})
        root = find_root("rubin_tower")
        root_config = root["gat_config"]
        config_path = self.project / "game_assets/towers/rubin_tower/config.json"
        disk_config = config_path.read_bytes()
        parameters = self.settings.parameters
        parameters[0].float_value += 0.2
        sprite_control = next(item for item in self.settings.sprite_parameters if item.path == "resolution")
        sprite_control.int_value = 128
        edited_parameters = [(item.path, item.kind, getattr(item, item.kind + "_value")) for item in parameters]
        sprite_changes = properties.sprite_updates(self.settings)
        original_revision = self.settings.sprite_revision

        self.assertEqual(self.preferences.language, "AUTO")
        for choice, blender_language, expected in (
            ("en_US", "ru_RU", "en_US"),
            ("ru_RU", "en_US", "ru_RU"),
            ("AUTO", "ru_RU", "ru_RU"),
            ("AUTO", "en_US", "en_US"),
        ):
            with self.subTest(choice=choice, blender_language=blender_language):
                bpy.context.preferences.view.language = blender_language
                self.preferences.language = choice
                self.assertEqual(i18n.language(), expected)
                self.assertEqual(i18n.tr("Build"), "Создать" if expected == "ru_RU" else "Build")
                self.assertEqual(i18n.tr("Loaded {name}", name="rubin_tower"),
                                 "Загружено: rubin_tower" if expected == "ru_RU" else "Loaded rubin_tower")
                self.assertEqual(bpy.context.preferences.view.language, blender_language)
                self.assertEqual(edited_parameters, [(item.path, item.kind, getattr(item, item.kind + "_value")) for item in self.settings.parameters])
                self.assertEqual(properties.sprite_updates(self.settings), sprite_changes)
                self.assertEqual(self.settings.sprite_revision, original_revision)
                self.assertEqual(root["gat_config"], root_config)
                self.assertEqual(config_path.read_bytes(), disk_config)
                self.assertFalse(hasattr(self.settings, "language"))
                self.assertNotIn("language", json.loads(root_config))

    def test_source_registration_has_safe_auto_fallback(self):
        addon_utils.disable(i18n.ADDON_ID, default_set=True)
        addon.register()
        try:
            self.assertIsNone(i18n.get_preferences())
            bpy.context.preferences.view.language = "ru_RU"
            self.assertEqual(i18n.language(), "ru_RU")
            self.assertEqual(i18n.tr("Build"), "Создать")
        finally:
            addon.unregister()
            addon_utils.enable(i18n.ADDON_ID, default_set=True, persistent=True)

    def test_russian_blender_build_preview_and_sprites(self):
        bpy.context.preferences.view.language = "ru_RU"
        bpy.context.preferences.view.use_translate_new_dataname = True
        self.preferences.language = "AUTO"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="build"), {"FINISHED"})
        self.settings.output = str(self.project / "output")
        self.settings.resolution = "256"
        self.assertEqual(bpy.ops.game_asset_tools.action(action="preview", view="front"), {"FINISHED"})
        preview = json.loads(bpy.data.texts[self.settings.report_text].as_string())
        self.assertTrue(Path(preview["paths"]["front"]).is_file())
        for item in self.settings.sprite_parameters:
            if item.path == "resolution":
                item.int_value = 64
            elif item.path == "directions":
                item.choice_value = "1"
        self.assertEqual(bpy.ops.game_asset_tools.sprites(action="export"), {"FINISHED"})
        self.assertTrue(Path(self.settings.sprite_atlas_path).is_file())

    def test_preference_survives_restart_in_isolated_profile(self):
        with tempfile.TemporaryDirectory(prefix="gat_i18n_preferences_") as directory:
            profile = Path(directory)
            scripts = profile / "scripts"
            config = profile / "config"
            config.mkdir()
            installed = scripts / "addons" / i18n.ADDON_ID
            ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "bundled")
            shutil.copytree(PROJECT / "blender_addon" / i18n.ADDON_ID, installed, ignore=ignore)
            shutil.copytree(PROJECT / "game_asset_tools", installed / "bundled" / "game_asset_tools", ignore=ignore)
            env = {**os.environ, "BLENDER_USER_SCRIPTS": str(scripts), "BLENDER_USER_CONFIG": str(config)}
            guard = ("import bpy, os; from pathlib import Path; "
                     "assert Path(bpy.utils.user_resource('CONFIG')).resolve() == Path(os.environ['BLENDER_USER_CONFIG']).resolve(); ")
            seed = guard + (
                "import addon_utils; addon_utils.enable('game_asset_tools_addon', default_set=True, persistent=True); "
                "prefs=bpy.context.preferences.addons['game_asset_tools_addon'].preferences; "
                "assert prefs.language == 'AUTO'; prefs.language='ru_RU'; "
                "bpy.context.preferences.filepaths.save_version=7; bpy.ops.wm.save_userpref(); "
                "print('GAT_I18N_PREFERENCES_SAVED')")
            check = guard + (
                "from game_asset_tools_addon.i18n import get_preferences, language, tr; "
                "assert get_preferences().language == 'ru_RU'; assert language() == 'ru_RU'; "
                "assert tr('Build') != 'Build'; assert bpy.context.preferences.filepaths.save_version == 7; "
                "print('GAT_I18N_PREFERENCES_RESTORED')")
            for factory, code, marker in ((True, seed, "GAT_I18N_PREFERENCES_SAVED"),
                                           (False, check, "GAT_I18N_PREFERENCES_RESTORED")):
                command = [bpy.app.binary_path, "--background"]
                if factory:
                    command.append("--factory-startup")
                command += ["--python-exit-code", "1", "--python-expr", code]
                result = subprocess.run(command, cwd=profile, env=env, text=True,
                                        encoding="utf-8", errors="replace", capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(marker, result.stdout)
            self.assertTrue((config / "userpref.blend").is_file())


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderTranslationTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
