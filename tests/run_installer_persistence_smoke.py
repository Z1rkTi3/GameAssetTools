"""Test the real installer with existing preferences in an isolated Blender profile."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.cli import find_blender


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender")
    args = parser.parse_args()
    blender = str(find_blender(args.blender))
    with tempfile.TemporaryDirectory(prefix="gat_persistence_") as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / "config").mkdir()
        legacy = root / "scripts/addons/game_asset_tools_addon"
        legacy.mkdir(parents=True)
        (legacy / "__init__.py").write_text(
            "bl_info={'name':'GameAssetTools','version':(0,3,0),'blender':(4,2,0)}\n"
            "from . import properties\ndef register(): pass\ndef unregister(): pass\n")
        # The old module deliberately has none of the new add-on API.
        (legacy / "properties.py").write_text("legacy_only = True\n")
        env = {**os.environ, "BLENDER_USER_SCRIPTS": str(root / "scripts"),
               "BLENDER_USER_CONFIG": str(root / "config")}
        # Factory settings are used only to seed this disposable test profile.
        subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1",
                        "--python-expr", "import bpy,os,addon_utils; from pathlib import Path; "
                        "assert Path(bpy.utils.user_resource('CONFIG')).resolve()==Path(os.environ['BLENDER_USER_CONFIG']).resolve(); "
                        "bpy.context.preferences.filepaths.save_version=7; "
                        "addon_utils.enable('game_asset_tools_addon', default_set=True, persistent=True); "
                        "bpy.ops.wm.save_userpref()"], env=env, cwd=root, check=True)
        original = (root / "config" / "userpref.blend").read_bytes()
        subprocess.run([sys.executable, str(PROJECT / "scripts" / "install_blender_addon.py"),
                        "--blender", blender], env=env, cwd=root, check=True)
        backups = list((root / "config").glob("userpref.blend.gat-*.bak"))
        assert len(backups) == 1 and backups[0].read_bytes() == original
        subprocess.run([blender, "--background", "--python-exit-code", "1", "--python-expr",
                        "import bpy; assert bpy.context.preferences.filepaths.save_version==7; "
                        "assert 'game_asset_tools_addon' in bpy.context.preferences.addons; "
                        "print('GAT_EXISTING_PREFERENCES_PRESERVED')"], env=env, cwd=root, check=True)
        print("GAT_INSTALLER_PERSISTENCE_SMOKE_OK")


if __name__ == "__main__":
    main()
