"""Экспорт четырёх BLOCKOUT weapon payload из чистого запуска Blender.

Запуск из корня проекта:
blender --background --factory-startup --python-exit-code 1 \
    --python scripts/export_industrial_weapons.py -- \
    --project=. --output=output/industrial_weapons_delivery_01
"""

import argparse
import hashlib
from pathlib import Path
import sys


ASSETS = ("industrial_cannon", "industrial_emitter")
SIDES = ("left", "right")


def _arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True,
                        help="Корень исходного GameAssetTools с game_assets и game_style.json")
    parser.add_argument("--output", type=Path, required=True,
                        help="Новая, ещё не существующая папка доставки")
    if "--" not in sys.argv:
        parser.error("Аргументы driver передаются после Blender separator --")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _require_factory_scene(bpy):
    """Отказ вместо очистки уже населённой или сохранённой сцены пользователя."""
    blender_arguments = sys.argv[:sys.argv.index("--")]
    if "--factory-startup" not in blender_arguments or bpy.data.filepath:
        raise ValueError("Нужен новый Blender --factory-startup без открытого .blend")
    expected = {"Cube": "MESH", "Camera": "CAMERA", "Light": "LIGHT"}
    objects = list(bpy.context.scene.objects)
    if (len(bpy.data.scenes) != 1 or len(bpy.data.objects) != len(expected)
            or {obj.name: obj.type for obj in objects} != expected
            or bpy.data.actions or bpy.context.mode != "OBJECT"):
        raise ValueError("Ожидается свежая factory-сцена с Cube/Camera/Light; ничего не удаляется")
    if any(obj.get("gat_asset_id") or obj.get("gat_generated") for obj in objects):
        raise ValueError("Factory-сцена уже содержит GAT assets")
    if any(collection.get("gat_asset_id") for collection in bpy.data.collections):
        raise ValueError("Factory-сцена уже содержит GAT collections")
    return objects


def _bootstrap(project):
    """Импортируем выбранный Core, не подменяя уже загруженную другую установку."""
    project = project.expanduser().resolve(strict=True)
    package = project / "game_asset_tools"
    if not (package / "__init__.py").is_file() or not (project / "game_style.json").is_file():
        raise ValueError("--project должен указывать на исходный проект GameAssetTools")
    for name, module in tuple(sys.modules.items()):
        if name != "game_asset_tools" and not name.startswith("game_asset_tools."):
            continue
        filename = getattr(module, "__file__", None)
        if filename is None or not Path(filename).resolve().is_relative_to(package):
            raise ValueError("Уже загружен другой GAT Core; нужен отдельный factory-запуск")
    sys.path.insert(0, str(project))
    sys.dont_write_bytecode = True
    import game_asset_tools
    if Path(game_asset_tools.__file__).resolve().parent != package:
        raise ValueError("Импортирован Core вне выбранного --project")
    return project, game_asset_tools.__version__


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rig_snapshot(root, asset_objects, fingerprint):
    """Второй борт пересобирает payload, сохраняя настоящий persistent Rig."""
    result = []
    for obj in asset_objects(root, "Rig"):
        bones = []
        if obj.type == "ARMATURE":
            bones = [(bone.name, bone.parent.name if bone.parent else None,
                      tuple(tuple(row) for row in bone.matrix_local)) for bone in obj.data.bones]
        result.append((obj.as_pointer(), obj.data.as_pointer() if obj.data else None,
                       fingerprint(obj), bones))
    return result


def main():
    args = _arguments()
    import bpy
    factory_objects = _require_factory_scene(bpy)
    project, version = _bootstrap(args.project)
    from game_asset_tools.asset.lifecycle import build
    from game_asset_tools.asset.metadata import fingerprint
    from game_asset_tools.asset.parameters import load_config
    from game_asset_tools.asset.registry import Registry
    from game_asset_tools.asset.scene import asset_objects, find_root
    from game_asset_tools.export import export_asset, save_asset
    from game_asset_tools.export.paths import write_json
    from game_asset_tools.style import load_style

    # Сначала проверяем все конфигурации. Ошибка не создаёт частичный output.
    registry = Registry(project)
    entries = {asset: registry.get(asset) for asset in ASSETS}
    configs = {asset: {side: load_config(entry, overrides={"payload.side": side})
                       for side in SIDES} for asset, entry in entries.items()}
    style = load_style(project)
    recipe_hashes = {asset: entry.source_digest() for asset, entry in entries.items()}
    style_hash = _sha256(project / "game_style.json")
    factory_before = [(obj.as_pointer(), obj.data.as_pointer(), fingerprint(obj))
                      for obj in factory_objects]

    def require_preserved_factory():
        current = [(obj.as_pointer(), obj.data.as_pointer(), fingerprint(obj))
                   for obj in factory_objects]
        if current != factory_before:
            raise RuntimeError("Build/export изменил исходные Cube/Camera/Light")

    # Даже пустая существующая папка — отказ. Повторный запуск получает новый путь.
    requested_output = args.output.expanduser().absolute()
    if requested_output.exists() or requested_output.is_symlink():
        raise FileExistsError(f"Папка доставки уже существует: {requested_output}")
    output = requested_output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    deliveries = []
    for asset, entry in entries.items():
        recipe = entry.load()
        persistent_rig = None
        for side in SIDES:
            config = configs[asset][side]
            result = build(entry, config, style, stage="BLOCKOUT", rebuild=side != SIDES[0])
            root = find_root(asset)
            if persistent_rig is None:
                persistent_rig = _rig_snapshot(root, asset_objects, fingerprint)
            elif (result["components"] != ["WeaponPayload"]
                  or _rig_snapshot(root, asset_objects, fingerprint) != persistent_rig):
                raise RuntimeError("Смена борта должна пересобирать только WeaponPayload, сохраняя Rig")
            recipe.run_authoring_tool(asset, "register_interface")
            require_preserved_factory()

            # Старый asset остаётся в .blend. Штатный exporter выбирает только
            # owned objects текущего asset; ни default cube, ни сосед в GLB не входят.
            destination = output / asset / side
            exported = export_asset(asset, destination, entry=entry,
                                    overwrite=False, animations=False)
            foreign_names = {obj.name for obj in bpy.context.scene.objects
                             if obj.get("gat_asset_id") != asset}
            if foreign_names.intersection(exported["structure"]["node_names"]):
                raise RuntimeError("В GLB попали объекты вне экспортируемого asset")
            saved = save_asset(asset, destination, overwrite=False)
            glb = Path(exported["glb"])
            manifest_path = glb.with_suffix(".weapon.json")
            manifest = recipe.delivery_manifest(asset, glb)
            write_json(manifest_path, manifest, overwrite=False)
            require_preserved_factory()
            deliveries.append({"asset": asset, "side": side, "stage": "BLOCKOUT",
                               "config": config,
                               "glb": glb.relative_to(output).as_posix(),
                               "delivery": manifest_path.relative_to(output).as_posix(),
                               "blend": Path(saved["blend"]).relative_to(output).as_posix(),
                               "glb_sha256": manifest["glb_sha256"],
                               "delivery_sha256": _sha256(manifest_path)})
            print(f"WEAPON_DELIVERY {asset} {side}: {glb}", flush=True)

    if ({asset: entry.source_digest() for asset, entry in entries.items()} != recipe_hashes
            or _sha256(project / "game_style.json") != style_hash):
        raise RuntimeError("Recipe/helper/profile/style изменились во время доставки")
    # Индекс появляется только после всех четырёх удачных доставок. Он не меняет
    # schema weapon.json: каждый delivery_manifest записан без добавочных полей.
    write_json(output / "index.json", {"schema_version": 1, "kind": "industrial_weapon_delivery_set",
               "project_root": str(project), "gat_version": version,
               "blender_version": bpy.app.version_string,
               "driver_sha256": _sha256(Path(__file__)), "recipe_source_sha256": recipe_hashes,
               "style_sha256": style_hash, "factory_objects_preserved": True,
               "deliveries": deliveries}, overwrite=False)
    print(f"WEAPON_DELIVERY_COMPLETE count={len(deliveries)} output={output}", flush=True)


if __name__ == "__main__":
    main()
