"""Численные контракты двух payload без bpy и без генерации файлов доставки."""
from collections import Counter
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from game_asset_tools.asset.parameters import changed_components, load_config
from game_asset_tools.asset.registry import Registry

PROJECT = Path(__file__).resolve().parents[1]
WEAPONS = ("industrial_cannon", "industrial_emitter")


class IndustrialWeaponTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(PROJECT)

    def layout(self, identity, **overrides):
        entry = self.registry.get(identity)
        recipe = entry.load()
        module = sys.modules[type(recipe).__module__]
        return module, module.geometry(identity, load_config(entry, overrides=overrides))

    def test_distinct_recipes_share_fixed_persistent_profile(self):
        expected = [("Root", None, (0, 0, 0)), ("Chassis", "Root", (0, 0, 1.95))]
        for side, prefix in ((-1, "Left"), (1, "Right")):
            parent, x = "Chassis", side*.67
            for suffix, position in (("Hip",(x,0,1.90)),("UpperLeg",(x,0,1.90)),
                                     ("Knee",(x,.38,1.10)),("LowerLeg",(x,.38,1.10)),
                                     ("Ankle",(x,-.12,.32)),("Foot",(x,-.12,.32))):
                expected.append((prefix+suffix, parent, position))
                parent = prefix+suffix
        expected += [("WeaponMountLeft","Chassis",(-1.13,-.1,2.5)),
                     ("WeaponMountRight","Chassis",(1.13,-.1,2.5))]
        sets = []
        for identity in WEAPONS:
            entry, recipe = self.registry.get(identity), self.registry.get(identity).load()
            self.assertEqual(entry.category, "weapons")
            self.assertEqual(entry.supported_stages, ("BLOCKOUT",))
            specs = recipe.components(load_config(entry))
            self.assertTrue(specs["Rig"].persistent)
            self.assertEqual(specs["WeaponPayload"].depends_on, ("Rig",))
            from game_asset_tools.i18n import CATALOGS
            for tool in recipe.authoring_tools():
                self.assertIn(tool["label"], CATALOGS["ru_RU"])
                self.assertNotEqual(CATALOGS["en_US"][tool["label"]], CATALOGS["ru_RU"][tool["label"]])
            module, layout = self.layout(identity)
            rig = module.rig_contract()
            self.assertEqual((rig.id, rig.revision, len(rig.bones), rig.joints), ("industrial_biped",1,16,()))
            self.assertEqual([(b.id,b.parent,b.rest.origin) for b in rig.bones], expected)
            self.assertEqual((rig.coordinates.units,rig.coordinates.up,rig.coordinates.forward), ("m","+Z","-Y"))
            sets.append({p["id"] for p in layout["parts"]})
        self.assertNotEqual(*sets)
        self.assertEqual(sets[0] & sets[1], {"Connector", "Receiver"})

    def test_closed_outward_meshes_at_parameter_limits(self):
        for identity in WEAPONS:
            for side in ("left", "right"):
                for length in (.25, 1.5):
                    module, layout = self.layout(identity, **{"payload.side":side,"payload.length":length,
                                                           "receiver.width":.60,"receiver.height":.55})
                    for part in layout["parts"]:
                        with self.subTest(asset=identity, side=side, length=length, mesh=part["id"]):
                            vertices, faces = part["vertices"], part["faces"]
                            self.assertGreater(module._volume(vertices, faces), 0)
                            edges = Counter(tuple(sorted((a,b))) for face in faces for a,b in zip(face,(*face[1:],face[0])))
                            self.assertEqual(set(edges.values()), {2})
                            directed = Counter((a,b) for face in faces for a,b in zip(face,(*face[1:],face[0])))
                            self.assertTrue(all(directed[(a,b)] == directed[(b,a)] for a,b in directed))

    def test_connector_clearance_and_muzzle_are_geometric(self):
        import math
        for identity in WEAPONS:
            module, first = self.layout(identity)
            _, longer = self.layout(identity, **{"payload.length":1.25})
            self.assertLess(longer["muzzle"]["origin"][1], first["muzzle"]["origin"][1])
            self.assertEqual(first["input"], longer["input"])
            self.assertEqual(first["muzzle"]["basis"], module.IDENTITY)
            front = min(p["origin"][1]+v[1] for p in first["parts"] for v in p["vertices"])
            self.assertAlmostEqual(first["muzzle"]["origin"][1], front)
            connector = next(p for p in first["parts"] if p["id"] == "Connector")
            radii = sorted({round(math.hypot(v[1],v[2]),9) for v in connector["vertices"]})
            self.assertEqual(len(radii),2)
            self.assertAlmostEqual(radii[0]*math.cos(math.pi/module.CONNECTOR["sides"])-.09, .002, places=8)
            extent = max(v[0] for v in connector["vertices"])-min(v[0] for v in connector["vertices"])
            self.assertAlmostEqual((extent-.035)/2,.003)

    def test_both_sides_mirror_vertices_without_transform_scale(self):
        for identity in WEAPONS:
            _, left = self.layout(identity)
            _, right = self.layout(identity, **{"payload.side":"right"})
            self.assertEqual(left["bone"],"WeaponMountLeft")
            self.assertEqual(right["bone"],"WeaponMountRight")
            for first, second in zip(left["parts"], right["parts"]):
                self.assertAlmostEqual(first["origin"][0],-second["origin"][0])
                # Локальные сечения симметричны; локальные origins с обеих сторон осмысленны.
                self.assertEqual(sorted((round(-x,9),round(y,9),round(z,9)) for x,y,z in first["vertices"]),
                                 sorted((round(x,9),round(y,9),round(z,9)) for x,y,z in second["vertices"]))
            self.assertAlmostEqual(left["muzzle"]["origin"][0],-right["muzzle"]["origin"][0])

    def test_every_geometry_control_only_affects_payload(self):
        for identity in WEAPONS:
            entry = self.registry.get(identity)
            original = load_config(entry)
            for overrides in ({"payload.side":"right"},{"payload.length":1.3},
                              {"receiver.width":.5},{"receiver.height":.4}):
                self.assertEqual(changed_components(entry.load(),original,load_config(entry,overrides=overrides)),
                                 {"WeaponPayload"})
            for overrides in ({"payload.side":"front"},{"payload.length":float("nan")},
                              {"receiver.width":-.2},{"payload.length":True}):
                with self.assertRaises(ValueError): load_config(entry,overrides=overrides)

    def test_real_wrappers_reload_helper_and_profile_without_mutating_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            shutil.copytree(PROJECT/"game_assets/weapons",project/"game_assets/weapons")
            entry = Registry(project).get(WEAPONS[0])
            first, digest = entry.load(), entry.source_digest()
            helper = project/"game_assets/weapons/industrial_weapon.py"
            helper.write_text(helper.read_text(encoding="utf-8").replace('"outer_radius": .13','"outer_radius": .131'),encoding="utf-8")
            second = entry.load()
            self.assertIsNot(first,second)
            self.assertNotEqual(entry.source_digest(),digest)
            self.assertEqual(sys.modules[type(second).__module__].CONNECTOR["outer_radius"],.131)
            profile = project/"game_assets/weapons/industrial_biped.rig.json"
            profile.write_text(profile.read_text(encoding="utf-8")+"\n",encoding="utf-8")
            self.assertIsNot(entry.load(),second)


if __name__ == "__main__":
    unittest.main()
