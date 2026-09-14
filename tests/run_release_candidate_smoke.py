"""Exercise explicitly supplied fresh ZIPs with disposable OS, Blender and Codex profiles.

No marketplace lookup or installation into the caller's profile is performed.
The archives must match the checkout; the child runtimes import their packaged
Core outside the checkout. Persistent evidence goes only to --output.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


PROJECT = Path(__file__).resolve().parents[1]


def isolated_environment(root: Path) -> dict[str, str]:
    """Redirect Windows and POSIX profile discovery before any child can write."""
    locations = {
        "HOME": "home", "USERPROFILE": "home", "CODEX_HOME": "home/.codex",
        "APPDATA": "home/AppData/Roaming", "LOCALAPPDATA": "home/AppData/Local",
        "XDG_CONFIG_HOME": "home/.config", "XDG_CACHE_HOME": "home/.cache",
        "XDG_DATA_HOME": "home/.local/share", "PYTHONUSERBASE": "home/python",
        "BLENDER_USER_CONFIG": "blender/config", "BLENDER_USER_SCRIPTS": "blender/scripts",
        "BLENDER_USER_DATAFILES": "blender/datafiles", "BLENDER_USER_EXTENSIONS": "blender/extensions",
        "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp",
    }
    env = dict(os.environ)
    for variable, relative in locations.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"Profile path escaped the temporary directory: {path}")
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path)
    home = Path(env["HOME"])
    env.update(HOMEDRIVE=home.drive, HOMEPATH=str(home)[len(home.drive):],
               PYTHONPATH="", PYTHONNOUSERSITE="1", PYTHONUTF8="1",
               GAT_SMOKE_ROOT=str(root.resolve()))
    # An existing user-resource override would outrank the per-directory paths.
    env.pop("BLENDER_USER_RESOURCES", None)
    return env


PROFILE_GUARD = """import os, sys
from pathlib import Path
root = Path(os.environ['GAT_SMOKE_ROOT']).resolve()
assert Path.home().resolve() == root / 'home', 'Path.home() escaped the disposable profile'
assert Path(os.environ['CODEX_HOME']).resolve() == root / 'home/.codex'
assert not (Path(os.environ['CODEX_HOME']) / 'auth.json').exists()
"""


def literal_assignment(data: bytes, name: str):
    for node in ast.parse(data).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing {name} in packaged metadata")


def inspect_archives(addon_zip: Path, codex_zip: Path) -> dict:
    cores = []
    archives = {}
    for kind, path, prefix in (("addon", addon_zip, "game_asset_tools_addon/"),
                               ("codex", codex_zip, "game-asset-tools/")):
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None, f"Corrupt archive: {path}"
            names = archive.namelist()
            assert len(names) == len(set(names)), "Duplicate archive members"
            assert all(name.startswith(prefix) and ".." not in Path(name).parts
                       and "\\" not in name for name in names), "Unsafe archive member"
            core_prefix = prefix + "bundled/game_asset_tools/"
            cores.append({name.removeprefix(core_prefix): archive.read(name)
                          for name in names if name.startswith(core_prefix)})
            if kind == "addon":
                version = ".".join(map(str, literal_assignment(
                    archive.read(prefix + "__init__.py"), "bl_info")["version"]))
                for source in (PROJECT / "blender_addon/game_asset_tools_addon").rglob("*.py"):
                    name = source.relative_to(PROJECT / "blender_addon").as_posix()
                    assert archive.read(name) == source.read_bytes(), f"Stale addon wrapper: {name}"
            else:
                version = json.loads(archive.read(prefix + ".codex-plugin/plugin.json"))["version"]
                source = PROJECT / "codex/plugins/game-asset-tools/scripts/gat.py"
                assert archive.read(prefix + "scripts/gat.py") == source.read_bytes(), "Stale Codex wrapper"
            archives[kind] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "version": version, "members": len(names)}
    expected = {path.relative_to(PROJECT / "game_asset_tools").as_posix(): path.read_bytes()
                for path in (PROJECT / "game_asset_tools").rglob("*.py")
                if "__pycache__" not in path.parts}
    assert cores[0] == cores[1] == expected, "ZIP Core differs between packages or from the checkout"
    assert "i18n.py" in expected
    version = literal_assignment(expected["__init__.py"], "__version__")
    assert archives["addon"]["version"] == archives["codex"]["version"] == version
    return {"archives": archives, "version": version, "identical_core_files": len(expected)}


ADDON_CHECK = PROFILE_GUARD + r'''
import addon_utils, bpy, json
args = sys.argv[sys.argv.index('--') + 1:]
archive, project, output, report_path = map(Path, args)
assert Path(bpy.utils.user_resource('CONFIG')).resolve() == Path(os.environ['BLENDER_USER_CONFIG']).resolve()
assert Path(bpy.utils.user_resource('SCRIPTS')).resolve() == Path(os.environ['BLENDER_USER_SCRIPTS']).resolve()
assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True) == {'FINISHED'}
bpy.utils.refresh_script_paths()
addon_utils.modules_refresh()
assert bpy.ops.preferences.addon_enable(module='game_asset_tools_addon') == {'FINISHED'}
import game_asset_tools_addon as addon
import game_asset_tools
from game_asset_tools.i18n import translate
from game_asset_tools_addon.i18n import get_preferences, tr
assert Path(addon.__file__).resolve().is_relative_to(root / 'blender/scripts')
assert Path(game_asset_tools.__file__).resolve().is_relative_to(Path(addon.__file__).parent / 'bundled')
assert translate('Build', 'ru_RU') == 'Создать'
preferences = get_preferences()
assert preferences.language == 'AUTO', 'The normal add-on language default must remain AUTO'
preferences.language = 'ru_RU'
assert tr('Build') == 'Создать'
preferences.language = 'en_US'
assert tr('Build') == 'Build'
preferences.language = 'AUTO'
settings = bpy.context.scene.game_asset_tools
settings.project = str(project)
assert bpy.ops.game_asset_tools.refresh() == {'FINISHED'}
settings.category = 'props'
settings.asset = 'industrial_crate'
settings.output = str(output)
settings.overwrite = True
settings.resolution = '256'
assert bpy.ops.game_asset_tools.sprites(action='load') == {'FINISHED'}
fields = {item.path: item for item in settings.sprite_parameters}
assert fields['resolution'].int_value == 128, 'The manual panel did not load the CLI settings'
fields['resolution'].int_value = 256
assert bpy.ops.game_asset_tools.sprites(action='save') == {'FINISHED'}
assert bpy.ops.game_asset_tools.action(action='build') == {'FINISHED'}
built = json.loads(bpy.data.texts[settings.report_text].as_string())
assert built['objects'] > 0 and built['stage'] == 'BLOCKOUT'
assert bpy.ops.game_asset_tools.action(action='preview', view='front') == {'FINISHED'}
preview = json.loads(bpy.data.texts[settings.report_text].as_string())
assert Path(preview['paths']['front']).stat().st_size > 1000
assert bpy.ops.wm.save_userpref() == {'FINISHED'}
assert (root / 'blender/config/userpref.blend').is_file()
report = {'status': 'pass', 'core': str(game_asset_tools.__file__), 'addon': str(addon.__file__),
          'home': str(Path.home()), 'build': built, 'preview': preview,
          'local_settings_resolution': 256, 'language_default': 'AUTO',
          'languages_tested': ['en_US', 'ru_RU']}
report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
assert bpy.ops.preferences.addon_disable(module='game_asset_tools_addon') == {'FINISHED'}
assert bpy.ops.preferences.addon_enable(module='game_asset_tools_addon') == {'FINISHED'}
assert get_preferences().language == 'AUTO'
assert bpy.ops.preferences.addon_disable(module='game_asset_tools_addon') == {'FINISHED'}
print('GAT_EXACT_ADDON_INSTALL_BUILD_PREVIEW_PASS')
'''


def run(command: list[str], *, root: Path, env: dict[str, str], log: Path) -> str:
    result = subprocess.run(command, cwd=root, env=env, text=True, encoding="utf-8",
                            errors="replace", capture_output=True)
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Release-candidate command failed ({result.returncode}); see {log}\n"
                           f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon-zip", type=Path, required=True)
    parser.add_argument("--codex-zip", type=Path, required=True)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory for the report, command logs and rendered artifacts")
    args = parser.parse_args()
    addon_zip, codex_zip = args.addon_zip.resolve(), args.codex_zip.resolve()
    blender = Path(shutil.which(args.blender) or args.blender).resolve()
    if not blender.is_file():
        parser.error(f"Blender executable does not exist: {blender}")
    report = inspect_archives(addon_zip, codex_zip)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="gat_release_candidate_") as directory:
        root = Path(directory).resolve()
        env = isolated_environment(root)
        run([sys.executable, "-I", "-c", PROFILE_GUARD], root=root, env=env, log=output / "profile.log")
        plugin_parent = root / "home/.codex/release-candidate"
        with zipfile.ZipFile(codex_zip) as archive:
            archive.extractall(plugin_parent)
        plugin = plugin_parent / "game-asset-tools"
        core_check = PROFILE_GUARD + """
sys.path.insert(0, sys.argv[1])
import game_asset_tools.i18n as i18n
assert Path(i18n.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert i18n.translate('Build', 'ru_RU') == '\\u0421\\u043e\\u0437\\u0434\\u0430\\u0442\\u044c'
assert 'bpy' not in sys.modules
print('GAT_EXACT_CODEX_LOCALE_PASS')
"""
        run([sys.executable, "-I", "-c", core_check, str(plugin / "bundled")],
            root=root, env=env, log=output / "codex_locale.log")
        runner = [sys.executable, "-I", str(plugin / "scripts/gat.py")]
        project = root / "editable-project"

        def cli(arguments, name):
            return json.loads(run([*runner, *arguments], root=root, env=env, log=output / f"{name}.log"))

        cli(["init-project", str(project)], "codex_init_project")
        command = ["--project", str(project), "--blender", str(blender)]
        assets = cli([*command, "list"], "codex_list")
        assert "industrial_crate" in {entry["id"] for entry in assets["assets"]}
        settings = cli([*command, "sprite-settings", "industrial_crate", "--set", "resolution=128"],
                       "codex_settings_write")
        assert settings["settings"]["resolution"] == 128
        built = cli([*command, "build", "industrial_crate", "--stage", "BLOCKOUT",
                     "--output", str(output / "codex")], "codex_build")
        assert built["objects"] > 0 and Path(built["blend"]).is_file()
        preview = cli([*command, "preview", "industrial_crate", "--blend", built["blend"],
                       "--view", "front", "--resolution", "256", "--output", str(output / "codex")],
                      "codex_preview")
        assert Path(preview["paths"]["front"]).stat().st_size > 1000
        check = root / "check_addon.py"
        check.write_text(ADDON_CHECK, encoding="utf-8")
        run([str(blender), "--background", "--factory-startup", "--python-exit-code", "1",
             "--python", str(check), "--", str(addon_zip), str(project), str(output / "addon"),
             str(output / "addon_result.json")], root=root, env=env, log=output / "addon.log")
        fresh = cli([*command, "sprite-settings", "industrial_crate"], "codex_settings_after_ui")
        assert fresh["settings"]["resolution"] == 256, "The packaged CLI did not read the manual UI save"
        for source in (PROJECT / "game_assets").rglob("config.json"):
            relative = source.relative_to(PROJECT)
            assert (plugin / "bundled" / relative).read_bytes() == source.read_bytes()
            installed_addon = root / "blender/scripts/addons/game_asset_tools_addon"
            assert (installed_addon / "bundled" / relative).read_bytes() == source.read_bytes()
        assert not (root / "home/.codex/auth.json").exists()
        # Local recipe changes must never modify either installed snapshot.
        for relative, data in ((path.relative_to(PROJECT / "game_asset_tools"), path.read_bytes())
                               for path in (PROJECT / "game_asset_tools").rglob("*.py")
                               if "__pycache__" not in path.parts):
            assert (plugin / "bundled/game_asset_tools" / relative).read_bytes() == data
        report.update(status="pass", isolated_home_verified=True, account_credentials=False,
                      marketplace_used=False, blender=str(blender), codex_build=built, codex_preview=preview,
                      addon=json.loads((output / "addon_result.json").read_text(encoding="utf-8")),
                      cli_manual_settings_roundtrip=True)
        (output / "test_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"GAT_EXACT_RELEASE_CANDIDATE_PASS {output / 'test_result.json'}")


if __name__ == "__main__":
    main()
