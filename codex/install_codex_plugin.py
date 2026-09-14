"""Install the extracted GameAssetTools package in the user's personal marketplace.

Uses only Python's standard library and the installed Codex CLI. No account token
is read or copied. Existing unrelated plugins and marketplace entries are preserved.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

NAME = "game-asset-tools"


def install(source, *, codex="codex", overwrite=False):
    source = Path(source).expanduser().resolve()
    manifest = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != NAME or not (source / "bundled/game_asset_tools/cli.py").is_file():
        raise ValueError("Source must be the complete extracted game-asset-tools package.")
    executable = shutil.which(codex)
    if executable is None and Path(codex).is_file():
        executable = str(Path(codex).resolve())
    if executable is None:
        raise ValueError("Codex CLI was not found. Add it to PATH or pass --codex PATH.")
    destination = Path.home() / "plugins" / NAME
    marketplace = Path.home() / ".agents/plugins/marketplace.json"
    if marketplace.exists():
        data = json.loads(marketplace.read_text(encoding="utf-8"))
    else:
        data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    market_name = data.get("name", "")
    if not isinstance(market_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", market_name):
        raise ValueError("Personal marketplace has an invalid name.")
    entries = data.get("plugins")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("Personal marketplace must contain a plugins array.")
    matching = [entry for entry in entries if entry.get("name") == NAME]
    expected_source = {"source": "local", "path": f"./plugins/{NAME}"}
    if len(matching) > 1 or (matching and matching[0].get("source") != expected_source):
        raise ValueError("Existing GameAssetTools marketplace entry points elsewhere; it was preserved.")
    if destination.exists() and source != destination.resolve():
        if not overwrite:
            raise FileExistsError(f"{destination} exists; pass --overwrite to update this plugin.")
        existing_manifest = destination / ".codex-plugin/plugin.json"
        if not existing_manifest.is_file() or json.loads(existing_manifest.read_text(encoding="utf-8")).get("name") != NAME:
            raise ValueError("Destination is not a GameAssetTools plugin; it was preserved.")
    if source != destination.resolve():
        shutil.copytree(source, destination, dirs_exist_ok=overwrite,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not matching:
        entries.append({"name": NAME, "source": expected_source,
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity"})
        marketplace.parent.mkdir(parents=True, exist_ok=True)
        marketplace.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # The default personal marketplace is discovered automatically by Codex.
    subprocess.run([executable, "plugin", "add", f"{NAME}@{market_name}", "--json"], check=True)
    listed = subprocess.run([executable, "plugin", "list", "--marketplace", market_name, "--json"],
                            check=True, text=True, capture_output=True)
    installed = json.loads(listed.stdout).get("installed", [])
    entry = next((entry for entry in installed if entry.get("name") == NAME), None)
    if entry is None or not entry.get("installed") or not entry.get("enabled"):
        raise RuntimeError("Codex did not report GameAssetTools as installed and enabled.")
    return {"status": "installed", "plugin": entry, "marketplace": str(marketplace),
            "source": str(destination), "next_step": "Start a new Codex task and use @game-asset-tools."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent,
                        help="Extracted plugin folder; defaults to this script's directory")
    parser.add_argument("--codex", default="codex", help="Codex executable (default: PATH)")
    parser.add_argument("--overwrite", action="store_true", help="Update an existing GameAssetTools source folder")
    args = parser.parse_args()
    print(json.dumps(install(args.source, codex=args.codex, overwrite=args.overwrite), indent=2))


if __name__ == "__main__":
    main()
