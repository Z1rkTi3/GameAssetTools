"""Compact host CLI: filesystem recipes and one request to Blender's shared Core."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import uuid

from . import __version__
from .asset.parameters import read_json
from .asset.recipe import STAGES
from .asset.registry import IDENTIFIER, Registry

VIEWS = ("front", "back", "left", "right", "top", "perspective")


def _executable(candidate: str | Path) -> Path | None:
    expanded = os.path.expandvars(os.path.expanduser(str(candidate))).strip('"')
    path = Path(expanded)
    if path.is_file():
        return path.resolve()
    found = shutil.which(expanded)
    return Path(found).resolve() if found else None


def _windows_blender_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.name != "nt":
        return candidates
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (winreg.KEY_READ, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                       winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\blender.exe", 0, access) as key:
                    candidates.append(Path(winreg.QueryValue(key, None).strip('"')))
            except OSError:
                pass
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, access) as uninstall:
                    for index in range(winreg.QueryInfoKey(uninstall)[0]):
                        try:
                            with winreg.OpenKey(uninstall, winreg.EnumKey(uninstall, index)) as item:
                                display = str(winreg.QueryValueEx(item, "DisplayName")[0])
                                if display.lower().startswith("blender"):
                                    location = winreg.QueryValueEx(item, "InstallLocation")[0]
                                    candidates.append(Path(location) / "blender.exe")
                        except OSError:
                            continue
            except OSError:
                pass
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.extend((Path(base) / "Blender Foundation").glob("Blender*/blender.exe"))
    return candidates


def find_blender(explicit: str | None = None) -> Path:
    """Discover from explicit path, environment, PATH, then Windows installations."""
    requested = explicit or os.environ.get("BLENDER_EXECUTABLE")
    if requested:
        found = _executable(requested)
        if found:
            return found
        raise ValueError(f"Blender executable does not exist: {requested}")
    found = shutil.which("blender")
    if found:
        return Path(found).resolve()
    candidates = [path for path in _windows_blender_candidates() if path.is_file()]
    if candidates:
        # Natural version ordering chooses 4.10 after 4.9, independent of registry order.
        return max(candidates, key=lambda path: tuple(int(part) for part in re.findall(r"\d+", str(path)))).resolve()
    raise ValueError("Blender was not found. Pass --blender PATH or set BLENDER_EXECUTABLE.")


def parse_overrides(values: list[str]) -> dict[str, Any]:
    """Parse repeatable path=JSON values without eval or shell interpretation."""
    result: dict[str, Any] = {}
    for value in values:
        path, separator, encoded = value.partition("=")
        if not separator or any(not part for part in path.split(".")):
            raise ValueError(f"Invalid --set {value!r}; expected parameter.path=JSON.")
        if path in result:
            raise ValueError(f"Duplicate --set parameter {path!r}.")
        try:
            result[path] = json.loads(encoded, parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"Non-finite JSON number {token!r}.")))
        except ValueError as exc:
            raise ValueError(f"Invalid JSON for --set {path}: {exc}") from exc
    return result


def create_asset(project: Path, asset_id: str, category: str = "other",
                 display_name: str | None = None) -> dict[str, Any]:
    """Scaffold a working one-component BLOCKOUT recipe, refusing existing sources."""
    for label, value in (("asset id", asset_id), ("category", category)):
        if not IDENTIFIER.fullmatch(value):
            raise ValueError(f"Invalid {label}; use a lower_case_name beginning with a letter.")
    if any(entry.id == asset_id for entry in Registry(project).list()):
        raise ValueError(f"Asset {asset_id!r} already exists.")
    destination = project / "game_assets" / category / asset_id
    destination.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": 1, "id": asset_id,
                "display_name": display_name or asset_id.replace("_", " ").title(),
                "category": category, "recipe_version": 1, "supported_stages": ["BLOCKOUT"]}
    config = {"schema_version": 1, "asset": asset_id, "parameters": {"size": 1.0}, "style": {}}
    recipe = '''"""Replace the blockout with this asset's semantic component construction."""

from game_asset_tools.asset import ComponentSpec, Parameter


class Recipe:
    parameters = (Parameter("size", "Size", "float", 1.0, min=0.01, components=("Body",)),)

    def components(self, config):
        return {"Body": ComponentSpec("Structure")}

    def build_component(self, ctx, key, config):
        from game_asset_tools import core as gat
        size = config["parameters"]["size"]
        obj = gat.add_box(ctx.name("Body"), (size, size, size), location=(0, 0, size / 2))
        ctx.add(obj, "Body")
        gat.assign_material(obj, gat.project_material("Painted_Metal", ctx.style))


RECIPE = Recipe()
'''
    for name, value in (("metadata.json", metadata), ("config.json", config)):
        (destination / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (destination / "asset.py").write_text(recipe, encoding="utf-8")
    return {"status": "created", "asset": asset_id, "path": str(destination)}


def run_blender(request: dict[str, Any], executable: Path) -> dict[str, Any]:
    """Execute without a shell; keep Blender noise in a per-command UTF-8 log."""
    runner = Path(__file__).resolve().parents[1] / "scripts" / "blender_command.py"
    if not runner.is_file():
        raise ValueError(f"Blender command runner is missing: {runner}. Use the complete project checkout.")
    report_dir = Path(request["output"]) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    log_path = report_dir / f"{request['asset']}_{request['action']}_{stamp}.log"
    with tempfile.TemporaryDirectory(prefix="gat_command_") as temporary:
        request_path, response_path = Path(temporary) / "request.json", Path(temporary) / "response.json"
        request_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        command = [str(executable), "--background", "--factory-startup"]
        if request.get("blend"):
            command.append(request["blend"])
        command.extend(["--python-exit-code", "1", "--python", str(runner), "--",
                        str(request_path), str(response_path)])
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=str(request["project"]), check=False)
        if response_path.is_file():
            response = read_json(response_path)
        else:
            response = {"status": "error", "error": "Blender produced no response.", "exit_code": completed.returncode}
        if completed.returncode and response.get("status") != "error":
            response = {"status": "error", "error": "Blender exited unsuccessfully after producing its response.",
                        "exit_code": completed.returncode, "response": response}
        response["log"] = str(log_path)
        return response


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GameAssetTools: shared recipes, selective asset operations, compact JSON.")
    parser.add_argument("--version", action="version", version=f"GameAssetTools {__version__}")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project containing game_assets/ (default: current directory)")
    parser.add_argument("--blender", help="Blender executable; otherwise BLENDER_EXECUTABLE, PATH, then Windows discovery")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list", help="Discover recipe metadata without starting Blender")
    create = commands.add_parser("create", help="Create a new editable recipe/config/metadata scaffold")
    create.add_argument("asset")
    create.add_argument("--category", default="other")
    create.add_argument("--display-name")
    for action in ("build", "rebuild", "inspect", "preview", "validate", "save", "export", "status", "delete"):
        command = commands.add_parser(action, help=f"{action.capitalize()} an asset through Blender Core")
        command.add_argument("asset")
        command.add_argument("--config", type=Path, help="Overlay config JSON")
        command.add_argument("--set", action="append", default=[], metavar="PATH=JSON", help="Override one recipe parameter (repeatable)")
        command.add_argument("--stage", type=str.upper, choices=STAGES, help="Build stage; a new asset starts at BLOCKOUT")
        command.add_argument("--component", action="append", default=[], help="Operate on this component (repeatable)")
        command.add_argument("--blend", type=Path, help="Existing .blend to load; required for rebuild/status/delete")
        command.add_argument("--output", type=Path, help="Output root (default: PROJECT/output)")
        command.add_argument("--overwrite", action="store_true", help="Explicitly allow replacing existing output artifacts")
        command.add_argument("--replace-edited", action="store_true", help="Explicitly allow replacing manually changed generated objects")
        command.add_argument("--dry-run", action="store_true", help="Return the operation plan without committing scene changes")
        command.add_argument("--view", dest="views", action="append", choices=(*VIEWS, "all"), help="Preview direction (repeatable; default: all)")
        command.add_argument("--resolution", type=int, choices=(256, 512, 1024), help="Square preview size; default comes from project style")
        command.add_argument("--reframe", action="store_true", help="Explicitly refresh persisted preview framing")
        command.add_argument("--debug", action="store_true", help="Include optional visual debug overlays")
        command.add_argument("--state", choices=("editable", "approved", "locked"), help="Approval state for the status action")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        project = args.project.expanduser().resolve()
        if not project.is_dir():
            raise ValueError(f"Project directory does not exist: {project}")
        if args.action == "list":
            response = {"status": "ok", "assets": [entry.as_dict() for entry in Registry(project).list()]}
        elif args.action == "create":
            response = create_asset(project, args.asset, args.category, args.display_name)
        else:
            Registry(project).get(args.asset)
            if args.action in ("rebuild", "status", "delete") and args.blend is None:
                raise ValueError(f"{args.action} requires --blend pointing to the existing asset file.")
            if args.action == "status" and args.state is None:
                raise ValueError("status requires --state editable, approved, or locked.")
            for label in ("blend", "config"):
                value = getattr(args, label)
                if value is not None and not value.expanduser().is_file():
                    raise ValueError(f"{label.capitalize()} file does not exist: {value}")
            views = list(VIEWS) if not args.views or "all" in args.views else list(dict.fromkeys(args.views))
            request = {"action": args.action, "project": str(project), "asset": args.asset,
                       "config": str(args.config.expanduser().resolve()) if args.config else None,
                       "overrides": parse_overrides(args.set), "stage": args.stage,
                       "components": list(dict.fromkeys(args.component)),
                       "blend": str(args.blend.expanduser().resolve()) if args.blend else None,
                       "output": str((args.output or project / "output").expanduser().resolve()),
                       "overwrite": args.overwrite, "replace_edited": args.replace_edited,
                       "dry_run": args.dry_run, "views": views, "resolution": args.resolution,
                       "reframe": args.reframe, "debug": args.debug, "state": args.state}
            response = run_blender(request, find_blender(args.blender))
        print(json.dumps(response, ensure_ascii=True, separators=(",", ":"), allow_nan=False))
        return 1 if response.get("status") == "error" else 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
