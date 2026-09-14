"""Actual host CLI -> Blender UI -> host CLI -> rendered atlas round trip."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "blender_addon"))
import game_asset_tools_addon as addon
from game_asset_tools.asset.metadata import fingerprint
from game_asset_tools.asset.scene import asset_objects, find_root


def main():
    version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    python = Path(bpy.app.binary_path).parent / version / "python/bin/python.exe"
    if not python.is_file():
        python = Path(shutil.which("python3") or sys.executable)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with tempfile.TemporaryDirectory(prefix="gat sprites ") as temporary:
        project = Path(temporary) / "Башня project"
        recipe = Path("game_assets/towers/rubin_tower")
        shutil.copytree(PROJECT / recipe, project / recipe)
        shutil.copyfile(PROJECT / "game_style.json", project / "game_style.json")

        def cli(*args):
            result = subprocess.run([str(python), "-m", "game_asset_tools", "--project", str(project),
                                     "sprite-settings", "rubin_tower", *args], cwd=PROJECT,
                                    capture_output=True, text=True, encoding="utf-8", check=True)
            return json.loads(result.stdout)

        initial = cli("--set", "resolution=128", "--set", "directions=4", "--set", 'look="toon"')
        addon.register()
        try:
            settings = bpy.context.scene.game_asset_tools
            settings.project = str(project)
            settings.output = str(project / "output")
            settings.overwrite = True
            bpy.ops.game_asset_tools.refresh()

            def control(key):
                return next(item for item in settings.sprite_parameters if item.path == key)

            assert settings.sprite_revision == initial["revision"]
            for key, value in initial["settings"].items():
                item = control(key)
                current = getattr(item, item.kind + "_value")
                assert abs(current - value) < 1e-6 if isinstance(value, float) else current == value
            control("cel_steps").int_value = 4
            control("elevation").float_value = 35
            assert bpy.ops.game_asset_tools.sprites(action="save") == {"FINISHED"}
            saved = cli()
            assert saved["settings"]["cel_steps"] == 4
            assert saved["settings"]["elevation"] == 35
            assert saved["revision"] == settings.sprite_revision
            assert bpy.ops.game_asset_tools.action(action="build") == {"FINISHED"}
            root = find_root("rubin_tower")
            before = {obj.name: (obj.as_pointer(), fingerprint(obj)) for obj in asset_objects(root)}
            results = []
            for action in ("preview", "export"):
                assert bpy.ops.game_asset_tools.sprites(action=action) == {"FINISHED"}
                result = json.loads(bpy.data.texts[settings.report_text].as_string())
                assert result["settings"] == cli()["settings"]
                assert result["profile"]["revision"] == cli()["revision"]
                assert len(result["frames"]) == (1 if action == "preview" else 4)
                results.append({"action": action, "settings_match": True, "frames": len(result["frames"])})
            # A clean UI must adopt an external CLI change without saving stale values.
            changed = cli("--set", "resolution=64")
            assert bpy.ops.game_asset_tools.sprites(action="preview") == {"FINISHED"}
            result = json.loads(bpy.data.texts[settings.report_text].as_string())
            assert result["settings"] == changed["settings"]
            assert settings.sprite_revision == changed["revision"]
            assert control("resolution").int_value == 64
            image = bpy.data.images.load(result["frames"][0]["path"], check_existing=False)
            try:
                assert tuple(image.size) == (64, 64)
                assert image.pixels[3] == 0
            finally:
                bpy.data.images.remove(image)
            assert before == {obj.name: (obj.as_pointer(), fingerprint(obj)) for obj in asset_objects(root)}
            report = {"status": "passed", "blender": bpy.app.version_string,
                      "actual_host_subprocess": True, "unicode_project": True,
                      "cli_to_ui": True, "ui_to_cli": True, "clean_ui_adopts_cli_change": True,
                      "source_preserved": True, "render_results": results}
        finally:
            addon.unregister()
    path = PROJECT / "output/reports/sprite_roundtrip.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("GAT_SPRITE_ROUNDTRIP_OK", path)


if __name__ == "__main__":
    main()
