"""Install/enable the ZIP in isolated Blender user directories, never the user's profile."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from game_asset_tools.cli import find_blender
from scripts.package_addon import default_output

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--zip",type=Path,default=default_output(PROJECT))
parser.add_argument("--blender",help="Blender executable (otherwise use normal discovery)")
args=parser.parse_args()
archive=args.zip.expanduser().resolve()
if not archive.is_file():
    parser.error(f"ZIP does not exist: {archive}. Run scripts/package_addon.py first.")

script='''import bpy, addon_utils, sys
from pathlib import Path
archive = sys.argv[sys.argv.index("--") + 1]
assert bpy.ops.preferences.addon_install(filepath=archive, overwrite=True) == {"FINISHED"}
bpy.utils.refresh_script_paths()
addon_utils.modules_refresh()
assert bpy.ops.preferences.addon_enable(module="game_asset_tools_addon") == {"FINISHED"}
assert hasattr(bpy.context.scene, "game_asset_tools")
bpy.ops.game_asset_tools.refresh()
settings = bpy.context.scene.game_asset_tools
settings.category = "props"
settings.asset = "industrial_crate"
assert bpy.ops.game_asset_tools.action(action="build") == {"FINISHED"}
import game_asset_tools_addon
assert Path(sys.argv[sys.argv.index("--") + 2]) in Path(game_asset_tools_addon.__file__).parents
assert bpy.ops.preferences.addon_disable(module="game_asset_tools_addon") == {"FINISHED"}
print("GAT_INSTALL_ENABLE_DISABLE_OK")
'''
with tempfile.TemporaryDirectory(prefix="gat_install_") as directory:
    root=Path(directory)
    runner=root/"check.py"
    runner.write_text(script,encoding="utf-8")
    env={**os.environ,"BLENDER_USER_SCRIPTS":str(root/"scripts"),"BLENDER_USER_CONFIG":str(root/"config")}
    result=subprocess.run([str(find_blender(args.blender)),"--background","--factory-startup","--python-exit-code","1",
                           "--python",str(runner),"--",str(archive),str(root)],
                          env=env,cwd=directory,text=True,capture_output=True)
    print(result.stdout)
    if result.returncode:
        print(result.stderr,file=sys.stderr)
        raise SystemExit(result.returncode)
