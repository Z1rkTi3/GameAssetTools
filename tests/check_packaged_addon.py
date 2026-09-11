"""Verify standalone ZIP contents with the checkout excluded from sys.path."""
import argparse
from pathlib import Path
import sys
import tempfile
import zipfile

import bpy

project=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(project))
from scripts.package_addon import default_output

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--zip",type=Path,default=default_output(project))
args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
with tempfile.TemporaryDirectory() as directory:
    with zipfile.ZipFile(args.zip) as archive:
        archive.extractall(directory)
    sys.path[:]=[p for p in sys.path if p and Path(p).resolve() not in {project,project/"blender_addon"}]
    sys.path.insert(0,directory)
    import game_asset_tools_addon as addon
    addon.register()
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        settings=bpy.context.scene.game_asset_tools
        bpy.ops.game_asset_tools.refresh()
        settings.category="props"
        settings.asset="industrial_crate"
        assert bpy.ops.game_asset_tools.action(action="build")=={"FINISHED"}
        import game_asset_tools
        assert Path(directory) in Path(game_asset_tools.__file__).parents
        print("GAT_PACKAGED_ADDON_OK",game_asset_tools.__file__)
    finally:
        addon.unregister()
