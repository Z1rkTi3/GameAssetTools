"""Install and persistently enable GameAssetTools in the chosen Blender user profile.

Run with regular Python. The Blender processes load existing user preferences;
they never save a scene or startup file. Close Blender first so another instance
cannot overwrite the saved preferences when it exits.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from game_asset_tools.cli import find_blender
from scripts.package_addon import default_output


INSTALL = '''import addon_utils, bpy, json, os, shutil, sys, time
from pathlib import Path
archive, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
before = sorted(bpy.context.preferences.addons.keys())
prefs = Path(bpy.utils.user_resource("CONFIG", create=True)) / "userpref.blend"
if os.environ.get("BLENDER_USER_CONFIG"):
    assert prefs.parent.resolve() == Path(os.environ["BLENDER_USER_CONFIG"]).resolve(), "Blender ignored BLENDER_USER_CONFIG"
backup = None
if prefs.is_file():
    backup = prefs.with_name(prefs.name + ".gat-" + str(time.time_ns()) + ".bak")
    shutil.copy2(prefs, backup)
assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True) == {"FINISHED"}
report_path.write_text(json.dumps({
    "blender_version": bpy.app.version_string,
    "previously_enabled": before,
    "preferences": str(prefs),
    "preferences_backup": str(backup) if backup else None,
}), encoding="utf-8")
'''

ENABLE = '''import bpy, json, sys
from pathlib import Path
report_path = Path(sys.argv[sys.argv.index("--") + 1])
report = json.loads(report_path.read_text(encoding="utf-8"))
# A fresh process avoids reusing submodules from the previously enabled version.
assert Path(bpy.utils.user_resource("CONFIG")).resolve() == Path(report["preferences"]).parent.resolve(), "Preferences profile changed during installation"
assert bpy.ops.preferences.addon_enable(module="game_asset_tools_addon") == {"FINISHED"}
assert hasattr(bpy.types.Scene, "game_asset_tools")
assert set(report["previously_enabled"]) <= set(bpy.context.preferences.addons.keys()), "Existing add-ons changed"
assert bpy.ops.wm.save_userpref() == {"FINISHED"}
'''

VERIFY = '''import bpy, json, sys
from pathlib import Path
report_path = Path(sys.argv[sys.argv.index("--") + 1])
report = json.loads(report_path.read_text(encoding="utf-8"))
enabled = sorted(bpy.context.preferences.addons.keys())
assert "game_asset_tools_addon" in enabled, "Add-on enablement was not saved"
assert set(report["previously_enabled"]) <= set(enabled), "Existing add-ons changed"
assert hasattr(bpy.types.Scene, "game_asset_tools"), "Add-on failed to register"
import game_asset_tools_addon
installed = Path(game_asset_tools_addon.__file__).resolve()
assert Path(bpy.utils.user_resource("SCRIPTS")).resolve() in installed.parents
report.update({"enabled": enabled, "installed_addon": str(installed), "verified": True})
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("GAT_INSTALL_PERSISTENCE_OK")
'''


def install_addon(archive: Path, blender: str | None = None) -> dict:
    """Install the trusted ZIP and verify enablement in a fresh Blender process."""
    archive = archive.expanduser().resolve()
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if "game_asset_tools_addon/__init__.py" not in names or any(
            not name.startswith("game_asset_tools_addon/") or ".." in Path(name).parts
            for name in names
        ):
            raise ValueError("Expected a GameAssetTools add-on ZIP from package_addon.py")
        if package.testzip() is not None:
            raise ValueError("Add-on ZIP is corrupt")
    executable = str(find_blender(blender))
    with tempfile.TemporaryDirectory(prefix="gat_enable_") as directory:
        temporary = Path(directory)
        report = temporary / "report.json"
        for name, source, arguments in (
            ("install.py", INSTALL, [str(archive), str(report)]),
            ("enable.py", ENABLE, [str(report)]),
            ("verify.py", VERIFY, [str(report)]),
        ):
            runner = temporary / name
            runner.write_text(source, encoding="utf-8")
            # No --factory-startup: preserve the user's existing preferences.
            subprocess.run(
                [executable, "--background", "--python-exit-code", "1",
                 "--python", str(runner), "--", *arguments],
                cwd=temporary, check=True,
            )
        return json.loads(report.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=default_output(PROJECT))
    parser.add_argument("--blender", help="Blender executable; otherwise use normal discovery")
    args = parser.parse_args()
    print(json.dumps(install_addon(args.zip, args.blender), indent=2))


if __name__ == "__main__":
    main()
