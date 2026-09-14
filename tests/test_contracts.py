"""Pure-Python contracts, malformed input, discovery and output boundaries."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.parameters import Parameter, changed_components, load_config, validate_config
from game_asset_tools.asset.recipe import ComponentSpec, validate_components
from game_asset_tools.cli import create_asset, parse_overrides
from game_asset_tools.style import load_style

PROJECT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_discover_load_all_recipes_without_blender(self):
        registry = Registry(PROJECT)
        self.assertEqual({e.id for e in registry.list()}, {"watchtower","scout_mech","industrial_crate","rubin_tower"})
        for entry in registry.list():
            self.assertEqual(load_config(entry)["asset"],entry.id)
            self.assertIs(entry.load(),entry.load())

    def test_targeted_and_dependency_changes(self):
        entry = Registry(PROJECT).get("scout_mech")
        original = load_config(entry)
        changed = load_config(entry,overrides={"weapons.right_scale":1.5})
        self.assertEqual(changed_components(entry.load(),original,changed),{"Weapon_Right"})
        wider = load_config(entry,overrides={"body.width":2.0})
        self.assertEqual(changed_components(entry.load(),original,wider),{"Body","Cockpit","Weapon_Left","Weapon_Right"})
        self.assertEqual(changed_components(entry.load(),original,original),set())

    def test_invalid_parameters_and_schema_fail(self):
        entry = Registry(PROJECT).get("scout_mech")
        for updates in ({"legs.length":-1},{"legs.length":True},{"unknown":1},{"legs.length":float("nan")}):
            with self.assertRaises(ValueError): load_config(entry,overrides=updates)
        for updates in ({"asset":"wrong"},{"schema_version":99},{"unexpected":1}):
            value = load_config(entry)
            value.update(updates)
            with self.assertRaises(ValueError): validate_config(entry,value)

    def test_dependencies_reject_cycles(self):
        with self.assertRaises(ValueError):
            validate_components({"A":ComponentSpec("Structure",("B",)),"B":ComponentSpec("Structure",("A",))})

    def test_dynamic_create_discovery_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            result=create_asset(root,"new_crate","props","New Crate")
            entry=Registry(root).get("new_crate")
            self.assertEqual(load_config(entry)["asset"],"new_crate")
            with self.assertRaises((FileExistsError,ValueError)): create_asset(root,"new_crate","props",None)
            import shutil
            shutil.copytree(entry.path,root/"game_assets"/"other"/"duplicate")
            with self.assertRaises(ValueError): Registry(root).list()
            with self.assertRaises(ValueError): create_asset(root,"../escape","props",None)

    def test_style_merge_isolated_and_validated(self):
        default=load_style(PROJECT)
        custom=load_style(PROJECT,{"materials":{"Stone":{"roughness":.3}}})
        self.assertEqual(custom["materials"]["Stone"]["roughness"],.3)
        self.assertEqual(load_style(PROJECT),default)
        with self.assertRaises(ValueError): load_style(PROJECT,{"preview":{"resolution":20}})

    def test_cli_values_are_json_not_code(self):
        self.assertEqual(parse_overrides(["body.width=2.5","details.handles=false"]),{"body.width":2.5,"details.handles":False})
        with self.assertRaises(ValueError): parse_overrides(["body.width=__import__('os')"])

    def test_export_paths_and_explicit_overwrite(self):
        from game_asset_tools.export.paths import artifact_path, write_json
        with tempfile.TemporaryDirectory() as folder:
            target=artifact_path(folder,"reports","test_asset",".json")
            write_json(target,{"status":"pass"})
            with self.assertRaises(FileExistsError): write_json(target,{"status":"changed"})
            self.assertEqual(json.loads(target.read_text()),{"status":"pass"})
            write_json(target,{"status":"changed"},overwrite=True)
            with self.assertRaises(ValueError): artifact_path(folder,"glb","../escape",".glb")


if __name__=="__main__": unittest.main()
