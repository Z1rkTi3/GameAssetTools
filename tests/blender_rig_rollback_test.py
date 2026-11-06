"""Отказ сборки не оставляет риги/Actions и не удаляет пользовательские клипы."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.style import load_style


def identities():
    return {name: {item.as_pointer() for item in getattr(bpy.data, name)}
            for name in ("objects", "collections", "meshes", "armatures", "actions", "materials")}


def run(build_function):
    for existing in (False, True):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        user_action = bpy.data.actions.new("KeepUserClip")
        user_action.use_fake_user = True
        with tempfile.TemporaryDirectory(prefix="gat_rig_rollback_") as directory:
            project = Path(directory)
            shutil.copytree(PROJECT / "tests/fixtures/assembly_inspection", project / "game_assets/tests/assembly_fixture")
            shutil.copyfile(PROJECT / "game_style.json", project / "game_style.json")
            entry = Registry(project).get("assembly_fixture")
            recipe, config, style = entry.load(), load_config(entry), load_style(project)
            original = recipe.build_component
            def with_actions(ctx, key, values):
                original(ctx, key, values)
                if key == "Rig":
                    rig = ctx.get("Rig", "Skeleton")
                    rig.animation_data_create()
                    for name in ("GeneratedIdle", "GeneratedWalk"):
                        action = bpy.data.actions.new(name)
                        action.use_fake_user = True
                        rig.animation_data.action = action
                        rig.pose.bones["LeftFoot"].keyframe_insert("rotation_euler", frame=0)
                        track = rig.animation_data.nla_tracks.new()
                        track.strips.new(name, 0, action)
            if existing:
                with patch.object(recipe, "build_component", side_effect=with_actions):
                    build_function(entry, config, style)
                preserved = [(obj, obj.data) for obj in asset_objects(find_root(entry.id))]
            baseline = identities()
            def failure(ctx, key, values):
                with_actions(ctx, key, values)
                if key == "Foot":
                    raise RuntimeError("injected_recipe_failure")
            with patch.object(recipe, "build_component", side_effect=failure):
                try:
                    build_function(entry, config, style, rebuild=existing, components=["Rig"] if existing else None)
                except RuntimeError as error:
                    assert str(error) == "injected_recipe_failure"
                else:
                    raise AssertionError("Expected recipe failure")
            assert identities() == baseline, {key: len(value - baseline[key]) for key, value in identities().items()}
            assert bpy.data.actions.get("KeepUserClip") == user_action
            if existing:
                assert all(obj.data == data for obj, data in preserved)
            # Неудачная первая попытка не резервирует имена будущих клипов.
            if not existing:
                with patch.object(recipe, "build_component", side_effect=with_actions):
                    build_function(entry, config, style)
                assert {a.name for a in bpy.data.actions} == {"KeepUserClip", "GeneratedIdle", "GeneratedWalk"}
            print(f"Rig rollback: {'rebuild' if existing else 'initial build and retry'} OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-lifecycle", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    if args.legacy_lifecycle:
        spec = importlib.util.spec_from_file_location("game_asset_tools.asset.legacy_lifecycle", args.legacy_lifecycle)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build = module.build
    run(build)
