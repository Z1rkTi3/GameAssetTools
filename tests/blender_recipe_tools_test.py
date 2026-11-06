"""Проверяет необязательные инструменты рецепта и обратимый export hook в Blender."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'blender_addon')]
import game_asset_tools_addon as addon
from game_asset_tools_addon import geometry_presets, properties
from game_asset_tools.asset.scene import find_root
from game_asset_tools.export import export_asset

OUTPUT = Path(os.environ.get('RECIPE_TOOLS_OUTPUT', PROJECT / 'output/recipe_tools'))


class RecipeToolsTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon.register()
        self.settings = bpy.context.scene.game_asset_tools
        self.settings.project = str(PROJECT)
        self.settings.output = str(OUTPUT / self._testMethodName)
        self.settings.overwrite = True
        bpy.ops.game_asset_tools.refresh()
        self.settings.category, self.settings.asset = 'mechs', 'industrial_walker'
        self.entry = properties.registry(self.settings).get(self.settings.asset)
        self.recipe = self.entry.load()
        self.assertEqual(bpy.ops.game_asset_tools.action(action='build'), {'FINISHED'})
        self.root = find_root(self.entry.id)

    def tearDown(self):
        addon.unregister()

    def report(self):
        return json.loads(bpy.data.texts[self.settings.report_text].as_string())

    def test_existing_recipe_has_no_extra_panel_or_export_behavior(self):
        self.assertEqual(geometry_presets.authoring_tools(self.recipe), [])
        self.assertFalse(geometry_presets.GAT_PT_recipe_tools.poll(bpy.context))
        result = export_asset(self.entry.id, self.settings.output, entry=self.entry, overwrite=True)
        self.assertGreater(result['structure']['meshes'], 0)

    def test_invalid_descriptors_and_missing_handler_are_rejected(self):
        for value in (None, {}, [{'id': 'x', 'label': ''}], [{'id': 'x', 'label': 'X', 'code': 'run'}],
                      [{'id': 'x', 'label': 'X'}, {'id': 'x', 'label': 'Y'}]):
            with patch.object(self.recipe, 'authoring_tools', return_value=value, create=True):
                with self.assertRaises(ValueError): geometry_presets.authoring_tools(self.recipe)
        with patch.object(self.recipe, 'authoring_tools', return_value=[{'id': 'x', 'label': 'X'}], create=True):
            with self.assertRaises(ValueError): geometry_presets.authoring_tools(self.recipe)

    def test_registered_ui_operator_whitelists_tools_and_stores_report(self):
        def run(asset, tool):
            self.root['authoring_counter'] = self.root.get('authoring_counter', 0) + 1
            return {'asset': asset, 'tool': tool, 'status': 'authored'}
        with patch.object(self.recipe, 'authoring_tools', return_value=[{'id': 'raise_flag', 'label': 'Флаг'}], create=True), \
             patch.object(self.recipe, 'run_authoring_tool', side_effect=run, create=True):
            self.assertTrue(geometry_presets.GAT_PT_recipe_tools.poll(bpy.context))
            self.assertEqual(bpy.ops.game_asset_tools.recipe_tool(tool='raise_flag'), {'FINISHED'})
            self.assertEqual(self.report(), {'asset': self.entry.id, 'tool': 'raise_flag', 'status': 'authored'})
            with self.assertRaises(RuntimeError): bpy.ops.game_asset_tools.recipe_tool(tool='unknown_or_python')
            self.assertEqual(self.root['authoring_counter'], 1)

    def test_panel_draws_recipe_fields_and_explicit_button(self):
        calls = []
        class Layout:
            enabled = True
            def operator(self, identifier, text):
                button = SimpleNamespace(tool=None)
                calls.append((identifier, text, button))
                return button
        with patch.object(self.recipe, 'authoring_tools', return_value=[{'id': 'x', 'label': 'Настроить'}], create=True), \
             patch.object(self.recipe, 'run_authoring_tool', create=True), \
             patch.object(self.recipe, 'draw_authoring_tools', create=True) as draw:
            layout = Layout()
            geometry_presets.GAT_PT_recipe_tools.draw(SimpleNamespace(layout=layout), bpy.context)
            draw.assert_called_once_with(layout, self.entry.id)
            self.assertEqual([(c[0], c[1], c[2].tool) for c in calls], [('game_asset_tools.recipe_tool', 'Настроить', 'x')])

    def test_non_dictionary_tool_report_is_rejected(self):
        with patch.object(self.recipe, 'authoring_tools', return_value=[{'id': 'x', 'label': 'X'}], create=True), \
             patch.object(self.recipe, 'run_authoring_tool', return_value=None, create=True):
            with self.assertRaises(RuntimeError): bpy.ops.game_asset_tools.recipe_tool(tool='x')

    def test_export_context_restores_scene_on_success_and_existing_file(self):
        events = []
        @contextmanager
        def context(asset, *, animations):
            events.append(('enter', asset, animations))
            self.root['temporary_export_flag'] = True
            try: yield
            finally:
                del self.root['temporary_export_flag']
                events.append(('exit', asset, animations))
        # Временный hook остаётся только в памяти; операции читают этот же fixture Registry.
        with patch.object(self.recipe, 'export_context', side_effect=context, create=True), \
             patch('game_asset_tools.operations.Registry', return_value=properties.registry(self.settings)):
            # Штатный оператор и прямой API используют один Core hook.
            self.assertEqual(bpy.ops.game_asset_tools.action(action='export'), {'FINISHED'})
            self.assertNotIn('temporary_export_flag', self.root)
            with self.assertRaises(FileExistsError): export_asset(self.entry.id, self.settings.output, entry=self.entry)
            self.assertNotIn('temporary_export_flag', self.root)
        self.assertEqual([event[0] for event in events], ['enter', 'exit', 'enter', 'exit'])
        self.assertTrue(all(event[1:] == (self.entry.id, False) for event in events))

    def test_export_context_decline_does_not_create_delivery(self):
        @contextmanager
        def context(asset, *, animations):
            raise ValueError('Сначала завершите подготовку рецепта')
            yield
        output = Path(self.settings.output) / 'declined'
        with patch.object(self.recipe, 'export_context', side_effect=context, create=True):
            with self.assertRaisesRegex(ValueError, 'подготовку'): export_asset(self.entry.id, output, entry=self.entry)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RecipeToolsTests))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), PROJECT / 'blender_addon/game_asset_tools_addon/geometry_presets.py',
               PROJECT / 'game_asset_tools/export/__init__.py']
    (OUTPUT / 'test_report.json').write_text(json.dumps({'project_root': str(PROJECT), 'blender': bpy.app.version_string,
        'sources_sha256': {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful()},
        ensure_ascii=False, indent=2), encoding='utf-8')
    if not result.wasSuccessful(): raise SystemExit(1)
