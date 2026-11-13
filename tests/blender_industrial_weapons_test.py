"""Настоящие payload A/B: UI, Library, skin, rest GLB и Save/Open.

Все blend/library/source edits изолированы во временном проекте; отчёт содержит
абсолютный authoritative root и SHA исходников. Не проверяет художественное качество.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT/"blender_addon")]
from game_asset_tools.asset.lifecycle import build, plan_build, set_status
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from game_asset_tools.assembly.authoring import get_interface, install_component, publish_component, validate_component
from game_asset_tools.assembly.library import LibraryError
from game_asset_tools.export import export_asset
from game_asset_tools.style import load_style

OUTPUT = Path(os.environ.get("INDUSTRIAL_WEAPONS_OUTPUT",PROJECT/"output/industrial_weapons"))
IDS = ("industrial_cannon", "industrial_emitter")
COMPONENT = "WeaponPayload"
RETAINED_DELIVERIES = []


def action_state(action):
    """Содержимое ключей и handles проверяется отдельно от одного Action ID."""
    return (action.as_pointer(), action.name,
            [[[(curve.data_path, curve.array_index,
                [(tuple(key.co),tuple(key.handle_left),tuple(key.handle_right),key.interpolation)
                 for key in curve.keyframe_points]) for curve in bag.fcurves]
              for bag in strip.channelbags] for layer in action.layers for strip in layer.strips])


class IndustrialWeaponBlenderTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gat_industrial_weapons_")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        shutil.copytree(PROJECT/"game_assets/weapons",self.project/"game_assets/weapons")
        shutil.copyfile(PROJECT/"game_style.json",self.project/"game_style.json")
        self.registry, self.style = Registry(self.project), load_style(self.project)
        self.library = self.project/"library"
        self.entry = self.registry.get(IDS[0])
        self.config, self.recipe = load_config(self.entry), self.entry.load()
        build(self.entry,self.config,self.style)
        self.root = find_root(self.entry.id)
        self.rig = next(o for o in asset_objects(self.root,"Rig") if o.type == "ARMATURE")

    def register(self, entry=None):
        entry = entry or self.entry
        return entry.load().run_authoring_tool(entry.id,"register_interface")

    def publish_pair(self):
        self.register()
        publish_component(self.library,IDS[0],COMPONENT,"cannon_payload",1)
        entry = self.registry.get(IDS[1])
        build(entry,load_config(entry),self.style)
        self.register(entry)
        publish_component(self.library,IDS[1],COMPONENT,"emitter_payload",1)
        return entry

    def rig_state(self):
        return (self.rig.as_pointer(),self.rig.data.as_pointer(),
                [(b.name,b.parent.name if b.parent else None,tuple(tuple(row) for row in b.matrix_local),b.length)
                 for b in self.rig.data.bones],
                [action_state(a) for a in bpy.data.actions],
                tuple(tuple(b.matrix_basis) for b in self.rig.pose.bones),
                self.rig.data.pose_position,bpy.context.scene.frame_current,bpy.context.scene.frame_subframe)

    def snapshot(self):
        return (self.root["gat_components"],self.rig_state(),
                [(o.as_pointer(),o.name,fingerprint(o)) for o in sorted(asset_objects(self.root),key=lambda o:o.name)])

    def author_action(self):
        bone = self.rig.pose.bones["WeaponMountLeft"]
        bone.rotation_mode = "XYZ"
        bone.rotation_euler.x = 0
        bone.keyframe_insert("rotation_euler",frame=1)
        bone.rotation_euler.x = .25
        bone.keyframe_insert("rotation_euler",frame=11)
        self.rig.animation_data.action.name = "UserPayloadPose"
        self.rig.animation_data.action.use_fake_user = True
        bpy.context.scene.frame_set(6,subframe=.25)
        bpy.context.view_layer.update()

    def test_sidebar_registers_real_interface_and_library_publishes(self):
        import game_asset_tools_addon as addon
        from game_asset_tools_addon import properties
        addon.register()
        self.addCleanup(addon.unregister)
        settings = bpy.context.scene.game_asset_tools
        settings.project = str(self.project)
        bpy.ops.game_asset_tools.refresh()
        settings.category,settings.asset,settings.component = "weapons",self.entry.id,COMPONENT
        self.assertTrue(properties.scene_state(settings)["recipe_available"])
        self.assertEqual(bpy.ops.game_asset_tools.recipe_tool(tool="register_interface"),{"FINISHED"})
        interface = get_interface(self.entry.id,COMPONENT)
        self.assertEqual(interface[0].input.interface,"walker_weapon_payload_v1")
        self.assertEqual(interface[1].outputs,())
        self.assertEqual(len(interface[0].bindings),4)
        self.assertEqual(validate_component(self.entry.id,COMPONENT)["status"],"pass")
        settings.library_root,settings.library_part_id,settings.library_revision = str(self.library),"ui_cannon",1
        self.assertEqual(bpy.ops.game_asset_tools.library_action(action="publish"),{"FINISHED"})
        with self.assertRaisesRegex(RuntimeError,"Unknown authoring tool for the selected recipe"):
            bpy.ops.game_asset_tools.recipe_tool(tool="execute_arbitrary_python")

    def test_geometry_rebuild_preserves_rig_actions_user_content_and_muzzle(self):
        self.register()
        self.author_action()
        user = bpy.data.objects.new("User_Content",None)
        bpy.context.scene.collection.objects.link(user)
        before, user_id = self.rig_state(),user.as_pointer()
        old_muzzle = self.recipe.describe(self.entry.id)[0].outputs[0].frame.origin
        changed = load_config(self.entry,overrides={"payload.length":1.25})
        result = build(self.entry,changed,self.style,rebuild=True)
        self.assertEqual(result["components"],[COMPONENT])
        self.assertEqual(self.rig_state(),before)
        self.assertEqual(bpy.data.objects["User_Content"].as_pointer(),user_id)
        self.assertLess(self.recipe.describe(self.entry.id)[0].outputs[0].frame.origin[1],old_muzzle[1])
        self.assertTrue(component_records(self.root)["Rig"]["persistent"])
        with self.assertRaisesRegex(ValueError,"persistent"):
            build(self.entry,changed,self.style,rebuild=True,components=["Rig"])

    def test_real_bidirectional_library_replacement_and_save_reopen(self):
        self.publish_pair()
        self.author_action()
        before = self.rig_state()
        donor = [(o.as_pointer(),fingerprint(o)) for o in asset_objects(find_root(IDS[1]))]
        for identity in ("emitter_payload","cannon_payload","emitter_payload"):
            result = install_component(self.library,self.entry.id,COMPONENT,identity,1)
            self.assertEqual(result["status"],"replaced")
            self.assertEqual(self.rig_state(),before)
            self.assertEqual(get_interface(self.entry.id,COMPONENT)[0].id,identity)
            self.recipe.describe(self.entry.id)  # Проверяет действительные connector/muzzle нового payload.
            self.assertEqual([(o.as_pointer(),fingerprint(o)) for o in asset_objects(find_root(IDS[1]))],donor)
        blend = self.project/"installed.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend),check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        self.root = find_root(self.entry.id)
        self.rig = next(o for o in asset_objects(self.root,"Rig") if o.type == "ARMATURE")
        self.assertEqual(self.rig.animation_data.action.name,"UserPayloadPose")
        self.assertEqual(get_interface(self.entry.id,COMPONENT)[0].id,"emitter_payload")
        self.assertEqual(validate_component(self.entry.id,COMPONENT)["status"],"pass")
        self.assertTrue(component_records(self.root)["Rig"]["persistent"])
        self.assertEqual(install_component(self.library,self.entry.id,COMPONENT,"cannon_payload",1)["status"],"replaced")

    def test_library_and_rebuild_guards_are_atomic(self):
        emitter = self.publish_pair()
        for status in ("locked","approved"):
            set_status(self.entry.id,status,[COMPONENT])
            before = self.snapshot()
            with self.assertRaises(LibraryError):
                install_component(self.library,self.entry.id,COMPONENT,"emitter_payload",1)
            self.assertEqual(self.snapshot(),before)
            set_status(self.entry.id,"editable",[COMPONENT])
        mesh = next(o for o in asset_objects(self.root,COMPONENT) if o.type == "MESH")
        original = mesh.data.vertices[0].co.copy()
        mesh.data.vertices[0].co.y += .013
        before = self.snapshot()
        with self.assertRaises(LibraryError):
            install_component(self.library,self.entry.id,COMPONENT,"emitter_payload",1)
        self.assertEqual(self.snapshot(),before)
        mesh.data.vertices[0].co = original
        # Несовпадение борта остаётся отказом, а не скрытым mirror/scale.
        right = load_config(emitter,overrides={"payload.side":"right"})
        build(emitter,right,self.style,rebuild=True)
        self.register(emitter)
        publish_component(self.library,emitter.id,COMPONENT,"right_emitter",1)
        before = self.snapshot()
        with self.assertRaises(LibraryError) as rejected:
            install_component(self.library,self.entry.id,COMPONENT,"right_emitter",1)
        self.assertTrue(any(issue.code in {"binding_mismatch","port_mismatch","port_frame_mismatch"}
                            for issue in rejected.exception.issues),rejected.exception)
        self.assertEqual(self.snapshot(),before)

    def test_export_rest_manifest_and_installed_ports_restore_source(self):
        self.publish_pair()
        install_component(self.library,self.entry.id,COMPONENT,"emitter_payload",1)
        self.author_action()
        before = self.snapshot()
        result = export_asset(self.entry.id,self.project/"delivery",entry=self.entry,overwrite=True)
        manifest = self.recipe.delivery_manifest(self.entry.id,result["glb"])
        self.assertEqual(self.snapshot(),before)
        # Реальный post-library export сохраняется для следующего Godot gate;
        # исходный временный .blend/проект всё равно удаляется после теста.
        OUTPUT.mkdir(parents=True,exist_ok=True)
        retained = Path(tempfile.mkdtemp(prefix="library_installed_",dir=OUTPUT))
        glb = retained / "industrial_cannon.glb"
        shutil.copyfile(result["glb"],glb)
        manifest_path = glb.with_suffix(".weapon.json")
        manifest_path.write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding="utf-8")
        RETAINED_DELIVERIES.append({"glb":str(glb),"manifest":str(manifest_path),
            "glb_sha256":hashlib.sha256(glb.read_bytes()).hexdigest(),
            "manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
        self.assertEqual(manifest["part"]["id"],"emitter_payload")
        self.assertEqual(manifest["glb_sha256"],hashlib.sha256(Path(result["glb"]).read_bytes()).hexdigest())
        self.assertEqual(set(manifest["nodes"]["meshes"]),set(manifest["material_roles"]))
        self.assertNotIn("Connector",manifest["heat_nodes"])
        for name in (manifest["nodes"]["input"],manifest["nodes"]["muzzle"]):
            self.assertIn(name,result["structure"]["node_names"])
        # finally восстанавливает pose/flags и при отказе exporter.
        with patch("game_asset_tools.validation.validate_asset",side_effect=RuntimeError("export failure")):
            with self.assertRaisesRegex(RuntimeError,"export failure"):
                export_asset(self.entry.id,self.project/"failed",entry=self.entry,overwrite=True)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaisesRegex(ValueError,"статический"):
            export_asset(self.entry.id,self.project/"animated",entry=self.entry,overwrite=True,animations=True)
        self.assertEqual(self.snapshot(),before)

    def test_right_side_marker_and_variable_length_are_measured(self):
        for length in (.25,1.5):
            changed = load_config(self.entry,overrides={"payload.side":"right","payload.length":length})
            build(self.entry,changed,self.style,rebuild=True)
            self.register()
            part,slot,_,_ = self.recipe.describe(self.entry.id)
            self.assertEqual(part.input.bone,"WeaponMountRight")
            self.assertEqual(slot.outputs,())
            self.assertEqual(part.outputs[0].frame.basis,part.input.frame.basis)
            self.assertGreater(part.outputs[0].frame.origin[0],part.input.frame.origin[0])
            self.assertTrue(all(tuple(o.scale) == (1,1,1) for o in asset_objects(self.root)))

    def test_invalid_connector_and_muzzle_are_rejected_without_accepting_edits(self):
        connector = next(o for o in asset_objects(self.root,COMPONENT) if o.get("gat_local_name") == "Connector")
        original = connector.data.vertices[0].co.copy()
        connector.data.vertices[0].co.y *= .9
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,"Female connector"):
            self.recipe.describe(self.entry.id)
        self.assertEqual(self.snapshot(),before)
        connector.data.vertices[0].co = original
        marker = next(o for o in asset_objects(self.root,COMPONENT) if o.get("gat_local_name") == "Muzzle")
        matrix = marker.matrix_basis.copy()
        matrix.translation.y += .03
        marker.matrix_basis = matrix
        bpy.context.view_layer.update()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.recipe.run_authoring_tool(self.entry.id,"register_interface")
        self.assertEqual(self.snapshot(),before)
        self.assertNotIn("assembly_interface",component_records(self.root)[COMPONENT])

    def test_connector_on_opposite_side_is_rejected_before_registration(self):
        for side in ("left", "right"):
            with self.subTest(side=side):
                if side == "right":
                    config = load_config(self.entry,overrides={"payload.side":side})
                    build(self.entry,config,self.style,rebuild=True)
                part,_,_,_ = self.recipe.describe(self.entry.id)
                connector = next(o for o in asset_objects(self.root,COMPONENT)
                                 if o.get("gat_local_name") == "Connector")
                original = connector.location.copy()
                # Сохраняем размеры втулки, IN/OUT и skin, но переносим реальную
                # посадку на противоположную сторону той же кости. Проверка
                # модуля расстояния от IN такой несовместимый стык не замечает.
                connector.location.x = 2*part.input.frame.origin[0]-original.x
                bpy.context.view_layer.update()
                before = self.snapshot()
                try:
                    with self.assertRaisesRegex(ValueError,"Female connector"):
                        self.recipe.run_authoring_tool(self.entry.id,"register_interface")
                    self.assertEqual(self.snapshot(),before)
                    self.assertNotIn("assembly_interface",component_records(self.root)[COMPONENT])
                finally:
                    connector.location = original
                    bpy.context.view_layer.update()

    def test_helper_only_change_invalidates_ui_draft_and_lifecycle(self):
        import game_asset_tools_addon as addon
        from game_asset_tools_addon import properties
        addon.register()
        self.addCleanup(addon.unregister)
        settings = bpy.context.scene.game_asset_tools
        settings.project = str(self.project)
        bpy.ops.game_asset_tools.refresh()
        settings.category,settings.asset = "weapons",self.entry.id
        properties.load_parameters(settings)
        next(p for p in settings.parameters if p.path == "payload.length").float_value = 1.1
        before = self.rig_state()
        helper = self.project/"game_assets/weapons/industrial_weapon.py"
        helper.write_text(helper.read_text(encoding="utf-8")+"\n# helper dependency changed\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"source changed"):
            properties.geometry_updates(settings,check_revision=True)
        plan = plan_build(self.entry,self.config,rebuild=True,style=self.style)
        self.assertEqual(plan["components"],[COMPONENT])
        self.assertEqual(build(self.entry,self.config,self.style,rebuild=True)["components"],[COMPONENT])
        self.assertEqual(self.rig_state(),before)
        properties.load_parameters(settings)
        self.assertEqual(properties.geometry_updates(settings,check_revision=True),{})

    def test_project_switch_remaps_category_four_to_zero_and_preserves_drafts(self):
        import game_asset_tools_addon as addon
        from game_asset_tools_addon import properties
        addon.register()
        self.addCleanup(addon.unregister)
        settings = bpy.context.scene.game_asset_tools
        # Bundled project содержит пять категорий, temporary — только weapons.
        # Читаем настоящие RNA getters до и после обычного Project update callback.
        self.assertEqual(properties.project_root(settings),PROJECT)
        self.assertEqual(settings.category,"weapons")
        self.assertEqual(settings.get("category"),4)
        self.assertEqual(settings.asset,self.entry.id)
        def length():
            return next(p for p in settings.parameters if p.path == "payload.length")
        invalid_stage_reads = []
        original_items = properties._items
        def observed_items(key, items, context=None):
            # Callback остаётся настоящим. Считаем запрещённый read path:
            # stage items → asset getter → category до remap нового проекта.
            if key == "stages":
                valid = {item[3] for item in properties.category_items(settings,context)}
                raw = settings.get("category")
                if raw not in valid:
                    invalid_stage_reads.append((raw,sorted(valid)))
            return original_items(key,items,context)
        with patch.object(properties,"_items",side_effect=observed_items):
            length().float_value = 1.125
            settings.project = str(self.project)
            self.assertEqual(settings.category,"weapons")
            self.assertEqual(settings.get("category"),0)
            self.assertEqual(settings.asset,self.entry.id)
            self.assertAlmostEqual(length().float_value,.85)
            length().float_value = 1.25
            settings.project = str(PROJECT)
            self.assertEqual(settings.category,"weapons")
            self.assertEqual(settings.get("category"),4)
            self.assertEqual(settings.asset,self.entry.id)
            self.assertAlmostEqual(length().float_value,1.125)
            settings.project = str(self.project)
            self.assertEqual(settings.category,"weapons")
            self.assertEqual(settings.get("category"),0)
            self.assertEqual(settings.asset,self.entry.id)
            self.assertAlmostEqual(length().float_value,1.25)
        self.assertEqual(invalid_stage_reads,[],"Stage RNA прочитан до remap category")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IndustrialWeaponBlenderTests))
    OUTPUT.mkdir(parents=True,exist_ok=True)
    sources = [Path(__file__),*sorted((PROJECT/"game_assets/weapons").rglob("*.py")),
               *sorted((PROJECT/"game_assets/weapons").rglob("*.json")),
               PROJECT/"game_asset_tools/asset/registry.py",PROJECT/"game_asset_tools/asset/lifecycle.py",
               PROJECT/"game_asset_tools/i18n.py",PROJECT/"blender_addon/game_asset_tools_addon/properties.py",
               PROJECT/"blender_addon/game_asset_tools_addon/geometry_presets.py"]
    (OUTPUT/"report.json").write_text(json.dumps({"project_root":str(PROJECT),"blender":bpy.app.version_string,
        "source_sha256":{str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "retained_deliveries":RETAINED_DELIVERIES,
        "suite":{"tests":result.testsRun,"passed":result.wasSuccessful(),"errors":len(result.errors),"failures":len(result.failures)}},indent=2),encoding="utf-8")
    if not result.wasSuccessful(): raise SystemExit(1)
