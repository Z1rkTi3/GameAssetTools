"""Exercise actual host-to-Blender requests, saved edits and compact responses."""

import json
from pathlib import Path
import subprocess
import sys

PROJECT=Path(__file__).resolve().parents[1]
OUTPUT=PROJECT/"output"/"cli_smoke"
BLEND=OUTPUT/"blend"/"scout_mech.blend"


def run(*args,success=True):
    result=subprocess.run([sys.executable,"-m","game_asset_tools","--project",str(PROJECT),*args],
                          cwd=PROJECT,text=True,capture_output=True)
    if (result.returncode==0)!=success:
        raise AssertionError(f"Command {args} exited {result.returncode}: {result.stdout}\n{result.stderr}")
    response=json.loads(result.stdout)
    return response


responses=[]
responses.append(run("list"))
responses.append(run("build","scout_mech","--output",str(OUTPUT),"--overwrite"))
base=["scout_mech","--blend",str(BLEND),"--output",str(OUTPUT)]
responses.append(run("inspect",*base,"--component","Weapon_Right"))
plan=run("rebuild",*base,"--set","weapons.right_scale=1.5","--dry-run")
assert plan["components"]==["Weapon_Right"]
responses.append(plan)
responses.append(run("rebuild",*base,"--set","weapons.right_scale=1.5","--overwrite"))
unchanged=run("rebuild",*base)
assert unchanged["status"]=="unchanged"
responses.append(unchanged)
responses.append(run("preview",*base,"--component","Weapon_Right","--view","front","--resolution","256","--overwrite"))
responses.append(run("validate",*base,"--overwrite"))
responses.append(run("export",*base,"--overwrite"))
responses.append(run("save",*base,"--overwrite"))
before=BLEND.read_bytes()
error=run("rebuild",*base,"--set","legs.length=-1","--overwrite",success=False)
assert error["status"]=="error" and BLEND.read_bytes()==before
responses.append(error)
responses.append(run("status",*base,"--state","approved","--component","Body","--overwrite"))
responses.append(run("delete",*base,"--component","Weapon_Right","--dry-run"))
OUTPUT.mkdir(parents=True,exist_ok=True)
(OUTPUT/"responses.json").write_text(json.dumps(responses,indent=2),encoding="utf-8")
print(f"CLI_SMOKE_OK: {len(responses)} commands, saved config and failure preservation verified")
