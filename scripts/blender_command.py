"""Blender process adapter; requests and responses use UTF-8 JSON files."""

import json
import logging
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 2:
        raise ValueError("Expected request.json and response.json")
    request_path, response_path = map(Path,args)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if request.get("debug") else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        import bpy
        from game_asset_tools.operations import execute
        from game_asset_tools.asset.scene import find_root
        from game_asset_tools.export import save_asset
        from game_asset_tools.export.paths import artifact_path, prepare_path
        action = request["action"]
        if action == "batch":
            from game_asset_tools.batch import run_batch
            result = run_batch(request)
            response_path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
            if result.get("status") in {"failed", "blocked", "error"}:
                raise SystemExit(1)
            return
        mutating = action in {"build","rebuild","recolor","status","delete"} and not request.get("dry_run")
        if action in {"rebuild", "recolor"} and mutating:
            plan = execute({**request,"dry_run":True})
            if not plan.get("components") and not plan.get("errors"):
                mutating = False
        if mutating:
            destination = artifact_path(request["output"],"blend",request["asset"],".blend")
            if action == "recolor" and destination.resolve() == Path(request["blend"]).resolve():
                raise ValueError("Recolor saves a separate version; choose a different --output directory")
            prepare_path(destination,overwrite=request.get("overwrite",False))
        if not request.get("blend"):
            # This is a fresh --factory-startup process, never a user's open scene.
            for obj in list(bpy.context.scene.objects):
                bpy.data.objects.remove(obj,do_unlink=True)
            if action not in {"build","rebuild","status","delete"}:
                execute({**request,"action":"build","dry_run":False})
        result = execute(request)
        if mutating and result.get("status") not in {"blocked", "unchanged"}:
            result.update(save_asset(request["asset"],request["output"],overwrite=request.get("overwrite",False)))
            result["status"] = {"build":"built","rebuild":"rebuilt","recolor":"recolored","status":request.get("state"),"delete":"deleted"}[action]
        response_path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
        if result.get("status") in {"error","blocked"}:
            raise SystemExit(1)
    except Exception as exc:
        logging.getLogger("game_asset_tools").error("Command failed: %s", exc)
        response_path.write_text(json.dumps({"status":"error","error":str(exc)}),encoding="utf-8")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
