"""Portable entry point to the unchanged bundled GameAssetTools CLI."""

import json
from pathlib import Path
import shutil
import sys

PLUGIN = Path(__file__).resolve().parents[1]
BUNDLED = PLUGIN / "bundled"


def writable_project(path):
    project = Path(path).expanduser().resolve()
    if project == PLUGIN or PLUGIN in project.parents:
        raise ValueError("Choose a project outside the installed plugin/cache.")
    return project


def init_project(path):
    project = writable_project(path)
    if (project / "game_assets").exists() or (project / "game_style.json").exists():
        raise ValueError("Project already has assets or style; use --project without init-project.")
    if not (BUNDLED / "game_assets").is_dir() or not (BUNDLED / "game_style.json").is_file():
        raise ValueError("Bundled recipes are missing; install the packaged plugin ZIP.")
    project.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BUNDLED / "game_assets", project / "game_assets",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(BUNDLED / "game_style.json", project / "game_style.json")
    if not (project / "AGENTS.md").exists():
        shutil.copyfile(BUNDLED / "AGENTS.md", project / "AGENTS.md")
    return {"status": "created", "project": str(project), "assets": str(project / "game_assets")}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "init-project":
            if len(argv) != 2:
                raise ValueError("Usage: gat.py init-project PATH")
            print(json.dumps(init_project(argv[1]), ensure_ascii=True))
            return 0
        if not (BUNDLED / "game_asset_tools" / "cli.py").is_file():
            raise ValueError("Bundled Core is missing; install the packaged plugin ZIP.")
        sys.path.insert(0, str(BUNDLED))
        from game_asset_tools.cli import main as cli_main, make_parser
        args = make_parser().parse_args(argv)
        project = writable_project(args.project)
        if not (project / "game_assets").is_dir() or not (project / "game_style.json").is_file():
            raise ValueError("No GameAssetTools project here. Run gat.py init-project PATH first.")
        return cli_main(argv)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
