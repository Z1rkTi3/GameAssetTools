"""Build a portable Codex plugin ZIP with the shared Core bundled at release time."""

import argparse
import ast
import json
from pathlib import Path
import re
import zipfile

if __package__:
    from .package_addon import release_version
else:
    from package_addon import release_version


PLUGIN_NAME = "game-asset-tools"
SOURCE_PATH = Path("codex/plugins") / PLUGIN_NAME
_EXCLUDED = {"__pycache__", "node_modules", "output", "bundled",
             "auth.json", "credentials.json", "secrets.json"}


def _manifest(project: Path) -> dict:
    path = project / SOURCE_PATH / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read plugin manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN_NAME:
        raise ValueError(f"Plugin manifest name must be {PLUGIN_NAME!r}")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Plugin manifest requires a release version")
    if version != release_version(project):
        raise ValueError("Plugin manifest version does not match game_asset_tools.__version__")
    if not isinstance(manifest.get("description"), str) or not manifest["description"].strip():
        raise ValueError("Plugin manifest requires a description")
    return manifest


def default_output(project: Path) -> Path:
    project = Path(project)
    version = _manifest(project)["version"]
    return project / "output" / f"game_asset_tools_codex_{version}.zip"


def _files(directory: Path, suffixes: set[str]):
    if not directory.is_dir():
        raise ValueError(f"Missing package source directory: {directory}")
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") or part in _EXCLUDED for part in relative.parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            if path.is_symlink() or any((directory / parent).is_symlink()
                                        for parent in relative.parents):
                raise ValueError(f"Symlinks are not portable package sources: {path}")
            yield path, relative.as_posix()


def _members(project: Path) -> list[tuple[str, bytes]]:
    plugin = project / SOURCE_PATH
    _manifest(project)
    required = (
        SOURCE_PATH / ".codex-plugin/plugin.json",
        SOURCE_PATH / "README.md",
        SOURCE_PATH / "scripts/gat.py",
        Path("codex/install_codex_plugin.py"),
        Path("game_asset_tools/__init__.py"),
        Path("game_asset_tools/__main__.py"),
        Path("game_asset_tools/cli.py"),
        Path("game_asset_tools/operations.py"),
        Path("game_asset_tools/i18n.py"),
        Path("scripts/blender_command.py"),
        Path("game_style.json"), Path("AGENTS.md"), Path("LICENSE"),
        Path("docs/asset_recipes.md"),
    )
    for relative in required:
        if not (project / relative).is_file():
            raise ValueError(f"Missing required package source: {relative.as_posix()}")
    if not any((plugin / "skills").glob("*/SKILL.md")):
        raise ValueError("Plugin requires at least one skills/<name>/SKILL.md")

    sources = [(plugin / ".codex-plugin/plugin.json", ".codex-plugin/plugin.json"),
               (project / "codex/install_codex_plugin.py", "install_codex_plugin.py")]
    sources.extend(_files(plugin, {".py", ".md", ".json", ".svg", ".png"}))
    for folder, suffixes in (("game_asset_tools", {".py"}),
                             ("game_assets", {".py", ".json", ".md"}),
                             ("docs", {".md"}), ("codex/workflows", {".md"})):
        sources.extend((path, f"bundled/{folder}/{relative}")
                       for path, relative in _files(project / folder, suffixes))
    for relative in ("scripts/blender_command.py", "game_style.json", "AGENTS.md", "LICENSE"):
        sources.append((project / relative, f"bundled/{relative}"))

    # Validate every source before opening the destination, including replacement builds.
    members = []
    for path, name in sorted(sources, key=lambda item: item[1]):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not portable package sources: {path}")
        data = path.read_bytes()
        if path.suffix == ".py":
            ast.parse(data, filename=name)
        elif path.suffix == ".json":
            metadata = json.loads(data)
            if not isinstance(metadata, dict):
                raise ValueError(f"Expected a JSON object in {name}")
            if path.name == "metadata.json" and name.startswith("bundled/game_assets/"):
                for sibling in ("asset.py", "config.json"):
                    if not (path.parent / sibling).is_file():
                        raise ValueError(f"Recipe {name} is missing {sibling}")
        members.append((f"{PLUGIN_NAME}/{name}", data))
    if len({name for name, _ in members}) != len(members):
        raise ValueError("Duplicate package member")
    return members


def package_codex_plugin(project: Path, output: Path | None = None, *, overwrite=False) -> Path:
    project = Path(project).resolve()
    output = Path(output if output is not None else default_output(project)).resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(f"Package already exists: {output}")
    members = _members(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w" if overwrite else "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path,
                        help="ZIP path (default: PROJECT/output/game_asset_tools_codex_VERSION.zip)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(package_codex_plugin(args.project, args.output, overwrite=args.overwrite))


if __name__ == "__main__":
    main()
