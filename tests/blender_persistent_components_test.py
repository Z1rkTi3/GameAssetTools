"""Постоянный Rig переживает rebuild; recipe не снимает его lifetime-защиту.

Независимая fixture использует два звена и два настоящих Actions. Все изменения
конфигурации/recipe выполняются во временном проекте, без игровых исходников.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset import ComponentSpec, Parameter
from game_asset_tools.asset.lifecycle import build, plan_build, set_status
from game_asset_tools.asset.metadata import encode, fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from game_asset_tools.style import load_style


class PersistentFixture:
    """Меняет только тестовый состав/параметры поверх включённого rigid-рецепта."""
    parameters = (
        Parameter("geometry.width", "Width", "float", .3, .1, 1.0, components=("Links",)),
        Parameter("rig.length", "Rig length", "float", 1.0, .5, 2.0, components=("Rig",)),
    )

    def __init__(self, original):
        self.original = original
        self.persistent = True
        self.remove_rig = False
        self.reverse_dependency = False
        self.extra_persistent = False

    def components(self, config):
        if self.remove_rig:
            return {"Links": ComponentSpec("Structure")}
        specs = {
            "Rig": ComponentSpec("Structure", depends_on=("Links",) if self.reverse_dependency else (),
                                 persistent=self.persistent),
            "Links": ComponentSpec("Structure", depends_on=() if self.reverse_dependency else ("Rig",)),
        }
        if self.extra_persistent:
            specs["Calibration"] = ComponentSpec("Structure", helper=True, persistent=True)
        return specs

    def build_component(self, ctx, key, config):
        if key == "Calibration":
            # Новый авторский helper проверяет добавление persistent-компонента
            # в уже существующий asset, без изменения старого Rig или fixture.
            ctx.add(bpy.data.objects.new(ctx.name("Marker"), None), "Marker")
            return
        self.original.build_component(ctx, key, config)
        if key == "Links":
            scale = config["parameters"]["geometry"]["width"] / .3
            for local in ("BaseLink", "HingeLink"):
                for vertex in ctx.get("Links", local).data.vertices:
                    vertex.co.x *= scale


def action_values(action):
    """Сравниваем все ключи, handles и структуру bags, а не только число клипов."""
    return {
        "id": action.as_pointer(), "name": action.name, "properties": encode(dict(action.items())),
        "fake_user": action.use_fake_user,
        "layers": [
            [[[(curve.data_path, curve.array_index, curve.extrapolation, curve.mute, curve.lock,
                [(tuple(key.co), tuple(key.handle_left), tuple(key.handle_right), key.interpolation,
                  key.handle_left_type, key.handle_right_type, key.easing, key.type,
                  key.amplitude, key.back, key.period) for key in curve.keyframe_points])
               for curve in bag.fcurves] for bag in strip.channelbags] for strip in layer.strips]
            for layer in action.layers
        ],
    }


class PersistentComponentsTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_persistent_components_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        folder = self.project / "game_assets/tests/rig_fixture"
        shutil.copytree(PROJECT / "tests/fixtures/animated_rig", folder)
        shutil.copyfile(PROJECT / "game_style.json", self.project / "game_style.json")
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        metadata["supported_stages"] = ["BLOCKOUT", "REFINE"]
        (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.entry = Registry(self.project).get("rig_fixture")
        self.recipe = PersistentFixture(self.entry.load())
        self.entry._recipe = self.recipe
        self.config = load_config(self.entry)
        self.style = load_style(self.project)
        build(self.entry, self.config, self.style)
        self.root = find_root(self.entry.id)
        self.rig = next(obj for obj in asset_objects(self.root, "Rig") if obj.type == "ARMATURE")
        # Реальные ручные правки не входят в обычный mesh fingerprint. Lifetime
        # защищает их независимо от editable/replace_edited и состояния recipe.
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        self.rig.data.edit_bones["Hinge"].tail.z += .125
        bpy.ops.object.mode_set(mode="OBJECT")
        action = self.rig.animation_data.nla_tracks[0].strips[0].action
        curve = action.layers[0].strips[0].channelbags[0].fcurves[0]
        curve.keyframe_points[1].co.y += .123
        curve.update()
        action["manual_note"] = "preserve authored keys"
        bpy.context.scene.frame_set(7, subframe=.25)
        bpy.context.view_layer.update()

    def rig_state(self):
        return {
            "object": self.rig.as_pointer(), "data": self.rig.data.as_pointer(),
            "rest": [(bone.name, bone.parent.name if bone.parent else None,
                      tuple(tuple(row) for row in bone.matrix_local), tuple(bone.head_local),
                      tuple(bone.tail_local), bone.use_deform, bone.bbone_segments)
                     for bone in self.rig.data.bones],
            "actions": [action_values(action) for action in bpy.data.actions],
            "active_action": self.rig.animation_data.action.as_pointer() if self.rig.animation_data.action else None,
            "nla": [(track.name, track.mute,
                     [(strip.name, strip.action.as_pointer(), strip.frame_start, strip.frame_end,
                       strip.action_frame_start, strip.action_frame_end, strip.scale, strip.repeat,
                       strip.blend_type, strip.influence) for strip in track.strips])
                    for track in self.rig.animation_data.nla_tracks],
            "frame": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
        }

    def snapshot(self):
        # При отказе сравниваем также metadata и все существовавшие datablocks.
        ids = {(item.bl_rna.identifier, item.as_pointer(), item.name)
               for prop in bpy.data.bl_rna.properties if prop.type == "COLLECTION"
               for item in getattr(bpy.data, prop.identifier) if isinstance(item, bpy.types.ID)}
        return {
            "ids": ids, "metadata": encode(dict(self.root.items())), "rig": self.rig_state(),
            "objects": [(obj.as_pointer(), encode(dict(obj.items())), fingerprint(obj))
                        for obj in asset_objects(self.root)],
            "selected": sorted(obj.as_pointer() for obj in bpy.context.selected_objects),
            "active": bpy.context.view_layer.objects.active.as_pointer() if bpy.context.view_layer.objects.active else None,
        }

    def assert_preserved_rebuild(self, *, config=None, style=None, **options):
        before = self.rig_state()
        old_links = {obj.as_pointer() for obj in asset_objects(self.root, "Links")}
        result = build(self.entry, config or self.config, style or self.style, rebuild=True, **options)
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(result["components"], ["Links"])
        self.assertIn("Rig", result["preserved"])
        self.assertEqual(self.rig_state(), before)
        self.assertTrue(old_links.isdisjoint({obj.as_pointer() for obj in asset_objects(self.root, "Links")}))
        self.assertTrue(component_records(self.root)["Rig"]["persistent"])

    def assert_refused(self, expression, *, config=None, **options):
        before = self.snapshot()
        # План и сама операция обязаны отказаться до мутации, даже при явном
        # разрешении менять обычную вручную отредактированную геометрию.
        for operation in (plan_build, build):
            arguments = (self.entry, config or self.config)
            extra = {"style": self.style}
            if operation is build:
                arguments += (self.style,)
                extra = {}
            with self.assertRaisesRegex(ValueError, expression):
                operation(*arguments, rebuild=True, **extra, **options)
            self.assertEqual(self.snapshot(), before)

    def test_initial_rig_and_authored_actions_are_persistent_while_editable(self):
        self.assertEqual(len(asset_objects(self.root, "Rig")), 1)
        self.assertEqual(len(bpy.data.actions), 2)
        self.assertEqual(component_records(self.root)["Rig"]["status"], "editable")
        self.assertTrue(component_records(self.root)["Rig"]["persistent"])
        self.assertTrue(any(action.get("manual_note") for action in bpy.data.actions))

    def test_geometry_parameter_rebuild_preserves_manual_rest_and_all_action_keys(self):
        changed = load_config(self.entry, overrides={"geometry.width": .6})
        self.assert_preserved_rebuild(config=changed)
        mesh = next(obj for obj in asset_objects(self.root, "Links") if obj.type == "MESH")
        self.assertAlmostEqual(max(v.co.x for v in mesh.data.vertices) - min(v.co.x for v in mesh.data.vertices), .6, places=5)

    def test_stage_change_preserves_approved_rig_without_unlocking(self):
        set_status(self.entry.id, "approved")
        self.assert_preserved_rebuild(stage="REFINE")
        self.assertEqual(component_records(self.root)["Rig"]["status"], "approved")

    def test_recipe_version_change_preserves_authored_rig(self):
        self.entry.recipe_version += 1
        self.assert_preserved_rebuild()

    def test_recipe_digest_change_preserves_authored_rig(self):
        path = self.entry.path / "asset.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# Test-only recipe revision.\n", encoding="utf-8")
        self.assert_preserved_rebuild()

    def test_style_change_preserves_authored_rig(self):
        changed = deepcopy(self.style)
        changed["materials"]["Painted_Metal"]["roughness"] = .17
        self.assert_preserved_rebuild(style=changed)

    def test_explicit_rig_rebuild_is_refused_even_with_replace_edited(self):
        for allowed in (False, True):
            self.assert_refused("Cannot rebuild persistent components: Rig", components=["Rig"], replace_edited=allowed)

    def test_config_affecting_rig_requires_explicit_migration(self):
        changed = load_config(self.entry, overrides={"rig.length": 1.2})
        self.assert_refused("Config affects persistent components", config=changed, replace_edited=True)

    def test_removing_persistent_component_requires_explicit_migration(self):
        self.recipe.remove_rig = True
        self.recipe.parameters = (self.recipe.parameters[0], replace(self.recipe.parameters[1], components=("Links",)))
        self.assert_refused("Persistent components require an explicit migration: Rig", replace_edited=True)

    def test_downgrading_persistent_flag_requires_migration_even_with_replace_edited(self):
        self.recipe.persistent = False
        self.entry.recipe_version += 1
        for allowed in (False, True):
            self.assert_refused("Persistent components require an explicit migration: Rig", replace_edited=allowed)

    def test_adopting_mutable_component_requires_migration_with_missing_or_false_record(self):
        self.entry.recipe_version += 1
        for flag in (None, False):
            # Такие records создавал обычный mutable recipe. Новый spec не имеет
            # права молча назвать их постоянными и оставить старую запись без флага.
            records = component_records(self.root)
            if flag is None:
                records["Rig"].pop("persistent", None)
            else:
                records["Rig"]["persistent"] = flag
            self.root["gat_components"] = encode(records)
            for allowed in (False, True):
                with self.subTest(saved_flag=flag, replace_edited=allowed):
                    self.assert_refused("Existing components require an explicit migration before becoming persistent: Rig",
                                        replace_edited=allowed)

    def test_new_persistent_component_can_be_added_to_existing_asset(self):
        self.recipe.extra_persistent = True
        self.entry.recipe_version += 1
        before = self.rig_state()
        result = build(self.entry, self.config, self.style, rebuild=True)
        self.assertEqual(result["components"], ["Calibration", "Links"])
        self.assertEqual(self.rig_state(), before)
        helpers = asset_objects(self.root, "Calibration")
        self.assertEqual(len(helpers), 1)
        self.assertTrue(helpers[0].get("gat_helper"))
        self.assertTrue(component_records(self.root)["Calibration"]["persistent"])
        helper_id = helpers[0].as_pointer()
        changed = load_config(self.entry, overrides={"geometry.width": .6})
        self.assert_preserved_rebuild(config=changed)
        self.assertEqual(asset_objects(self.root, "Calibration")[0].as_pointer(), helper_id)

    def test_reverse_dependency_refuses_replacement_of_preserved_rig_support(self):
        self.recipe.reverse_dependency = True
        self.entry.recipe_version += 1
        self.assert_refused("A preserved persistent component depends on replaced geometry")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PersistentComponentsTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_PERSISTENT_COMPONENTS_TESTS_OK", result.testsRun)
