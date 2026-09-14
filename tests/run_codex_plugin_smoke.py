"""Install in an unsigned-in Codex profile and build via its cached plugin runtime."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import hashlib
import time

PROJECT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    result = subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--blender", required=True)
    args = parser.parse_args()
    executable = shutil.which(args.codex) or args.codex
    output = PROJECT / "output/codex_plugin_smoke_0_2"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gat_codex_") as directory:
        root = Path(directory)
        profile = root / "codex-profile"
        profile.mkdir()
        env = {**os.environ, "CODEX_HOME": str(profile)}
        installed = run([executable, "plugin", "add", "game-asset-tools@personal", "--json"],
                        env=env, cwd=root)
        cached = Path(installed["installedPath"]).resolve()
        assert profile.resolve() in cached.parents, "Codex ignored the isolated profile"
        assert not (profile / "auth.json").exists(), "Test must not carry account credentials"
        listed = run([executable, "plugin", "list", "--marketplace", "personal", "--json"],
                     env=env, cwd=root)
        entry = next(p for p in listed["installed"] if p["name"] == "game-asset-tools")
        assert entry["installed"] and entry["enabled"]
        runner = cached / "scripts/gat.py"
        project = root / "editable-project"
        run([sys.executable, str(runner), "init-project", str(project)], cwd=root)
        names = run([sys.executable, str(runner), "--project", str(project), "list"], cwd=root)
        assert "rubin_tower" in {a["id"] for a in names["assets"]}
        command = [sys.executable, str(runner), "--project", str(project), "--blender", args.blender]
        built = run([*command, "build", "rubin_tower", "--stage", "BLOCKOUT", "--output", str(output), "--overwrite"], cwd=root)
        assert built["objects"] == 17 and built["stage"] == "BLOCKOUT"
        validated = run([*command, "validate", "rubin_tower", "--blend", built["blend"],
                         "--output", str(output), "--overwrite"], cwd=root)
        assert validated["errors"] == [] and validated["warnings"] == []
        preview = run([*command, "preview", "rubin_tower", "--blend", built["blend"],
                       "--view", "front", "--view", "perspective", "--output", str(output), "--overwrite"], cwd=root)
        assert all(Path(path).stat().st_size > 2000 for path in preview["paths"].values())
        source_hash = hashlib.sha256(Path(built["blend"]).read_bytes()).hexdigest()
        materials = root / "paint.json"
        materials.write_text(json.dumps({"Rubin_Body": {"base_color": [.02, .1, .6, 1]}}), encoding="utf-8")
        paint_command = [*command, "recolor", "rubin_tower", "--blend", built["blend"],
                         "--materials", str(materials), "--component", "Body", "--output", str(output / "painted"), "--overwrite"]
        plan = run([*paint_command, "--dry-run"], cwd=root)
        assert len(plan["objects"]) == 1 and not plan["errors"]
        painted = run(paint_command, cwd=root)
        assert painted["status"] == "recolored" and painted["geometry_unchanged"]
        inspection = run([*command, "inspect", "rubin_tower", "--blend", painted["blend"],
                          "--swatches", "--output", str(output / "painted"), "--overwrite"], cwd=root)
        assert Path(inspection["swatches"]).is_file()
        assert list(inspection["material_roles"]["Rubin_Body"]["components"]) == ["Body"]
        for mode in ("stdout", "stdout", "unique", "unique", "replace", "replace"):
            result = run([*command, "validate", "rubin_tower", "--blend", painted["blend"],
                          "--output", str(output / "painted"), "--report-mode", mode], cwd=root)
            assert not result["errors"]
        viewed = run([*command, "save", "rubin_tower", "--blend", painted["blend"], "--view-copy",
                      "--save-view", "perspective", "--output", str(output / "painted"), "--overwrite"], cwd=root)
        assert viewed["view_copy"] and Path(viewed["blend"]).is_file()
        started = time.perf_counter()
        batch = run([*command, "batch", "rubin_tower", "--blend", built["blend"],
                     "--batch-config", str(project / "game_assets/towers/rubin_tower/palettes.json"),
                     "--view", "front", "--view", "perspective", "--resolution", "512",
                     "--output", str(output), "--overwrite"], cwd=root)
        batch_seconds = time.perf_counter() - started
        assert batch["status"] == "passed" and len(batch["variants"]) == 4
        assert all(v["status"] == "passed" and v["preview"]["framing"] == batch["framing"] for v in batch["variants"])
        assert Path(batch["comparison"]).is_file()
        for view in ("front", "perspective"):
            hashes = {hashlib.sha256(Path(v["preview"]["paths"][view]).read_bytes()).hexdigest() for v in batch["variants"]}
            assert len(hashes) == 4, "Palette previews must be visually distinct"
        assert hashlib.sha256(Path(built["blend"]).read_bytes()).hexdigest() == source_hash
        # The installed runtime is a byte-identical snapshot of the shared source.
        for source in (PROJECT / "game_asset_tools").rglob("*.py"):
            relative = source.relative_to(PROJECT)
            assert (cached / "bundled" / relative).read_bytes() == source.read_bytes()
        report = {"status": "pass", "account_credentials": False, "installed": entry,
                  "build": built, "validation": validated, "preview": preview,
                  "recolor": painted, "view_copy": viewed, "inspection": inspection,
                  "batch": batch, "batch_seconds": batch_seconds, "source_unchanged": True}
        (output / "test_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("GAT_CODEX_PLUGIN_ISOLATED_INSTALL_BUILD_PREVIEW_PASS")


if __name__ == "__main__":
    main()
