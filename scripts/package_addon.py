"""Build a standalone Blender legacy add-on ZIP from the shared source tree."""

import argparse
import ast
from pathlib import Path
import zipfile


def _literal_assignment(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing literal {name} in {path}")


def release_version(project: Path) -> str:
    """Read the canonical version without importing Blender or project code."""
    return _literal_assignment(project / "game_asset_tools" / "__init__.py", "__version__")


def default_output(project: Path) -> Path:
    return project / "output" / f"game_asset_tools_blender_{release_version(project)}.zip"


def package_addon(project: Path, output: Path | None = None, *, overwrite=False) -> Path:
    project = project.resolve()
    output = (output if output is not None else default_output(project)).resolve()
    addon = project / "blender_addon" / "game_asset_tools_addon"
    metadata = _literal_assignment(addon / "__init__.py", "bl_info")
    if tuple(metadata["version"]) != tuple(int(part) for part in release_version(project).split(".")):
        raise ValueError("Add-on bl_info version does not match game_asset_tools.__version__")
    roots = ((addon, "game_asset_tools_addon"),
             (project / "game_asset_tools", "game_asset_tools_addon/bundled/game_asset_tools"),
             (project / "game_assets", "game_asset_tools_addon/bundled/game_assets"))
    members = []
    for directory, prefix in roots:
        if not directory.is_dir():
            raise ValueError(f"Missing package source: {directory}")
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in path.parts:
                members.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    style = project / "game_style.json"
    if not style.is_file():
        raise ValueError(f"Missing game-wide style: {style}")
    members.append((style, "game_asset_tools_addon/bundled/game_style.json"))
    license_path = project / "LICENSE"
    if not license_path.is_file():
        raise ValueError(f"Missing license: {license_path}")
    members.append((license_path, "game_asset_tools_addon/LICENSE"))
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with zipfile.ZipFile(output, mode, compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in members:
            # Stable archive timestamps make package contents reproducible.
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path,
                        help="ZIP path (default: PROJECT/output/game_asset_tools_blender_VERSION.zip)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(package_addon(args.project, args.output, overwrite=args.overwrite))


if __name__ == "__main__":
    main()
