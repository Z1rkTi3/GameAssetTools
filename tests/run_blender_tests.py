"""End-to-end verification in a disposable headless Blender process.

Writes inspectable sample artifacts to output/smoke and a machine-readable report.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import bpy
from mathutils import Vector

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))

from game_asset_tools import core as gat
from game_asset_tools.asset.lifecycle import build, set_status, delete_generated
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root, root_object
from game_asset_tools.export import export_asset, inspect_glb, save_asset
from game_asset_tools.inspection import inspect_asset, bounds
from game_asset_tools.operations import execute
from game_asset_tools.preview import render_preview, VIEWS
from game_asset_tools.style import load_style
from game_asset_tools.validation import validate_asset

OUTPUT=PROJECT/"output"/"smoke"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.registry=Registry(PROJECT)
        self.entry=self.registry.get("scout_mech")
        self.config=load_config(self.entry)
        self.style=load_style(PROJECT)

    def build_mech(self):
        return build(self.entry,self.config,self.style)

    def test_three_assets_build_preview_validate_save_reopen_export(self):
        reports=[]
        for entry in self.registry.list():
            bpy.ops.wm.read_factory_settings(use_empty=True)
            config=load_config(entry)
            result=build(entry,config,self.style)
            self.assertGreater(result["objects"],5)
            root=find_root(entry.id)
            report=validate_asset(entry.id,entry)
            self.assertEqual(report["errors"],[],report)
            self.assertEqual(report["warnings"],[],report)
            images=render_preview(entry.id,OUTPUT,resolution=512,overwrite=True)
            self.assertEqual(set(images["paths"]),set(VIEWS))
            for file in images["paths"].values():
                self.assertGreater(Path(file).stat().st_size,2000)
            saved=save_asset(entry.id,OUTPUT,overwrite=True)
            before=inspect_asset(entry.id)
            bpy.ops.wm.open_mainfile(filepath=saved["blend"])
            self.assertEqual(inspect_asset(entry.id),before)
            self.assertEqual(validate_asset(entry.id,entry)["errors"],[])
            user=gat.add_box("User_Content",(1,1,1),location=(30,0,0))
            user.select_set(True)
            bpy.context.view_layer.objects.active=user
            exported=export_asset(entry.id,OUTPUT,entry=entry,overwrite=True)
            self.assertNotIn("User_Content",exported["structure"]["node_names"])
            self.assertTrue(user.select_get())
            self.assertEqual(bpy.context.view_layer.objects.active,user)
            self.assertGreater(inspect_glb(exported["glb"])["meshes"],0)
            # Real importer confirms the file is accepted by Blender, not only our parser.
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=exported["glb"])
            self.assertGreater(sum(o.type=="MESH" for o in bpy.context.scene.objects),0)
            reports.append({"asset":entry.id,"validation":report,"preview":images,"save":saved,"export":exported})
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/"artifacts.json").write_text(json.dumps(reports,indent=2),encoding="utf-8")

    def test_targeted_rebuild_preserves_approved_geometry_and_materials(self):
        self.build_mech()
        root=find_root(self.entry.id)
        before={o.name:(o.as_pointer(),fingerprint(o)) for o in asset_objects(root) if o["gat_component"]!="Weapon_Right"}
        mats={m.as_pointer() for m in bpy.data.materials}
        set_status(self.entry.id,"approved",["Body"])
        changed=load_config(self.entry,overrides={"weapons.right_scale":1.5})
        plan=build(self.entry,changed,self.style,rebuild=True,dry_run=True)
        self.assertEqual(plan["components"],["Weapon_Right"])
        build(self.entry,changed,self.style,rebuild=True)
        self.assertEqual(before,{o.name:(o.as_pointer(),fingerprint(o)) for o in asset_objects(root) if o["gat_component"]!="Weapon_Right"})
        self.assertEqual(mats,{m.as_pointer() for m in bpy.data.materials})
        self.assertEqual(build(self.entry,changed,self.style,rebuild=True)["status"],"unchanged")

    def test_manual_geometry_lock_and_external_children_guard(self):
        self.build_mech()
        root=find_root(self.entry.id)
        obj=asset_objects(root,"Weapon_Right")[0]
        obj.data.vertices[0].co.x+=.1
        with self.assertRaisesRegex(ValueError,"Manual edits"):
            build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"])
        build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"],replace_edited=True)
        set_status(self.entry.id,"locked",["Weapon_Right"])
        with self.assertRaisesRegex(ValueError,"locked"):
            build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"],replace_edited=True)
        set_status(self.entry.id,"editable",["Weapon_Right"])
        obj=asset_objects(root,"Weapon_Right")[0]
        user=gat.add_box("User_Attachment",(1,1,1))
        gat.parent_object(user,obj)
        with self.assertRaisesRegex(ValueError,"preserved child"):
            build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"])
        self.assertIn(user.name,bpy.data.objects)

    def test_failed_recipe_rolls_back_new_data(self):
        self.build_mech()
        root=find_root(self.entry.id)
        before={o.name:fingerprint(o) for o in asset_objects(root)}
        objects=set(bpy.data.objects)
        collections=set(bpy.data.collections)
        recipe=self.entry.load()
        original=recipe.build_component
        def fail(ctx,key,config):
            original(ctx,key,config)
            raise RuntimeError("Deliberate failure")
        recipe.build_component=fail
        try:
            with self.assertRaisesRegex(RuntimeError,"Deliberate"):
                build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"])
        finally: recipe.build_component=original
        self.assertEqual(objects,set(bpy.data.objects))
        self.assertEqual(collections,set(bpy.data.collections))
        self.assertEqual(before,{o.name:fingerprint(o) for o in asset_objects(root)})

    def test_stage_approval_and_all_stages(self):
        for entry in self.registry.list():
            config=load_config(entry)
            build(entry,config,self.style)
            with self.assertRaisesRegex(ValueError,"Approve"):
                build(entry,config,self.style,rebuild=True,stage="REFINE")
            for stage in ("REFINE","DETAIL","FINALIZE"):
                set_status(entry.id,"approved")
                result=build(entry,config,self.style,rebuild=True,stage=stage)
                self.assertEqual(result["stage"],stage)
                self.assertEqual(validate_asset(entry.id,entry)["errors"],[])

    def test_root_transform_survives_targeted_rebuild(self):
        self.build_mech()
        root=find_root(self.entry.id)
        pivot=root_object(root)
        pivot.location=(8,3,2)
        pivot.rotation_euler.z=.4
        bpy.context.view_layer.update()
        before=bounds(asset_objects(root,"Weapon_Right"))
        build(self.entry,self.config,self.style,rebuild=True,components=["Weapon_Right"])
        after=bounds(asset_objects(root,"Weapon_Right"))
        for a,b in zip(before["center"],after["center"]): self.assertAlmostEqual(a,b,places=4)

    def test_preview_isolation_framing_and_debug(self):
        self.build_mech()
        root=find_root(self.entry.id)
        user=gat.add_box("Huge_User_Object",(100,100,100))
        user.hide_render=True
        user.select_set(True)
        bpy.context.view_layer.objects.active=user
        before=(set(bpy.data.objects),set(bpy.data.scenes),set(bpy.data.materials),bpy.context.scene.render.engine)
        preview=render_preview(self.entry.id,OUTPUT,component="Weapon_Right",views=["front"],resolution=256,overwrite=True)
        smaller=deepcopy(self.config)
        smaller["parameters"]["weapons"]["right_scale"]=.8
        build(self.entry,smaller,self.style,rebuild=True)
        again=render_preview(self.entry.id,OUTPUT,component="Weapon_Right",views=["front"],resolution=256,overwrite=True)
        self.assertEqual(preview["framing"],again["framing"])
        debug=render_preview(self.entry.id,OUTPUT,component="Weapon_Right",views=["perspective"],resolution=1024,overwrite=True,debug=True)
        self.assertTrue(Path(debug["paths"]["perspective"]).is_file())
        self.assertTrue(user.hide_render)
        self.assertTrue(user.select_get())
        self.assertEqual(bpy.context.view_layer.objects.active,user)
        self.assertEqual(before[1:],(set(bpy.data.scenes),set(bpy.data.materials),bpy.context.scene.render.engine))
        self.assertFalse(any(o.name.startswith("GAT_Preview") or o.name.startswith("Preview_") for o in bpy.data.objects))

    def test_empty_optional_component_and_delete_rebuild(self):
        entry=self.registry.get("industrial_crate")
        config=load_config(entry,overrides={"details.handles":False})
        build(entry,config,self.style)
        self.assertEqual(validate_asset(entry.id,entry)["errors"],[])
        delete_generated(entry.id,components=["Lid"])
        self.assertTrue(validate_asset(entry.id,entry)["errors"])
        build(entry,config,self.style,rebuild=True)
        self.assertEqual(validate_asset(entry.id,entry)["errors"],[])

    def test_operation_uses_saved_config_for_incremental_changes(self):
        self.build_mech()
        base={"project":str(PROJECT),"asset":self.entry.id,"action":"rebuild"}
        execute({**base,"overrides":{"weapons.right_scale":1.4}})
        result=execute({**base,"overrides":{"weapons.left_scale":1.1}})
        self.assertEqual(result["components"],["Weapon_Left"])
        stored=json.loads(find_root(self.entry.id)["gat_config"])
        self.assertEqual(stored["parameters"]["weapons"]["right_scale"],1.4)

    def test_validation_catches_corrupt_state_without_repairing_it(self):
        self.build_mech()
        root=find_root(self.entry.id)
        obj=asset_objects(root,"Weapon_Right")[0]
        obj.scale.x=-1
        obj.hide_render=True
        obj.parent=None
        root["gat_stage"]="UNSUPPORTED"
        root_object(root).scale.z=0
        report=validate_asset(self.entry.id,self.entry)
        self.assertEqual(report["status"],"error")
        self.assertTrue(any("scale" in error for error in report["errors"]))
        self.assertTrue(any("parent" in error for error in report["errors"]))
        self.assertTrue(any("stage" in error for error in report["errors"]))
        self.assertTrue(any("root" in error for error in report["errors"]))
        self.assertTrue(any("Hidden" in warning for warning in report["warnings"]))
        self.assertEqual(obj.scale.x,-1)

    def test_export_normalizes_display_units_and_preserves_metric_root(self):
        scaled=deepcopy(self.style)
        scaled["unit_scale"]=.5
        build(self.entry,self.config,scaled)
        original=bounds(asset_objects(find_root(self.entry.id)))["dimensions"]
        bpy.context.scene.unit_settings.scale_length=.01
        result=export_asset(self.entry.id,OUTPUT/"units",entry=self.entry,overwrite=True)
        self.assertAlmostEqual(bpy.context.scene.unit_settings.scale_length,.01)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=result["glb"])
        imported=bounds([o for o in bpy.context.scene.objects if o.type=="MESH"])["dimensions"]
        for a,b in zip(original,imported): self.assertAlmostEqual(a,b,places=4)

    def test_artifact_dry_run_does_not_write(self):
        import tempfile
        self.build_mech()
        with tempfile.TemporaryDirectory() as folder:
            for action in ("save","preview","export","validate"):
                execute({"action":action,"project":str(PROJECT),"asset":self.entry.id,"output":folder,"dry_run":True})
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_reproduction_has_identical_geometry_and_metadata(self):
        def snapshot():
            root=find_root(self.entry.id)
            return {"root":dict(root.items()),"objects":{o.name:fingerprint(o) for o in asset_objects(root)}}
        self.build_mech()
        first=snapshot()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.build_mech()
        self.assertEqual(first,snapshot())


if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(WorkflowTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"test_result.json").write_text(json.dumps({"tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"success":result.wasSuccessful(),"blender":bpy.app.version_string},indent=2))
    if not result.wasSuccessful(): raise SystemExit(1)
