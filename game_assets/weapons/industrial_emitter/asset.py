"""Самостоятельный сменный emitter payload существующей библиотеки GAT."""
import hashlib
import importlib.util
from pathlib import Path
import sys


def _recipe():
    # Имя зависит от source+profile, поэтому импортируем именно текущую версию.
    source = Path(__file__).parent.parent / "industrial_weapon.py"
    profile = source.with_name("industrial_biped.rig.json")
    data = source.read_bytes()
    digest = hashlib.sha256(str(source.resolve()).encode()+b"\0"+data+b"\0"+profile.read_bytes()).hexdigest()
    name = "_gat_industrial_weapon_"+digest
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            exec(compile(data, str(source), "exec"), module.__dict__)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module.Recipe("industrial_emitter")


RECIPE = _recipe()
