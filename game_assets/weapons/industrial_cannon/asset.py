"""Самостоятельный сменный cannon payload существующей библиотеки GAT."""
import hashlib
import importlib.util
from pathlib import Path
import sys


def _recipe():
    # Registry учитывает эти файлы через source_files. Уникальное имя helper
    # исключает старый sys.modules/pyc после изменения кода или профиля.
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
    return module.Recipe("industrial_cannon")


RECIPE = _recipe()
