"""Независимые revisions деталей: rest payload без rig/Actions и без изменения сцены.

Это хранилище и проверяемое чтение данных, не операция подключения/замены.
Blender вызывается только publish_part/open_part; read_part работает без bpy.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

from .contracts import Issue, PartContract, TOLERANCE, part_from_dict

LIBRARY_VERSION = 1
_FILES = {"manifest.json", "payload.blend"}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class LibraryError(ValueError):
    """Адресные причины отказа; исходник и опубликованные revisions сохраняются."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{i.field} [{i.code}]: {i.message} ({i.actual!r}). {i.remedy}" for i in self.issues))


@dataclass(frozen=True)
class LibraryEntry:
    directory: Path
    part: PartContract
    payload_sha256: str


@dataclass(frozen=True)
class PartPayload:
    """Detached данные живут только внутри with open_part(...)."""

    entry: LibraryEntry
    collection: object
    objects: dict
    sockets: dict
    contacts: dict


def _fail(code, field, expected, actual, message, remedy="Исправьте данные и опубликуйте новую revision"):
    raise LibraryError((Issue("error", code, "library", field, expected, actual, message, remedy),))


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _publish_directory(staging, destination):
    """Atomic no-replace, включая конкурентное появление пустого каталога."""
    if os.name == "nt":
        try:
            staging.rename(destination)  # Windows rename никогда не заменяет target.
            return
        except FileExistsError:
            _fail("revision_exists", "revision", "новая revision", str(destination), "Revision уже существует")
    # POSIX os.rename может заменить пустой target; используем именно NOREPLACE.
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        _fail("atomic_publish_unavailable", "filesystem", "atomic rename без overwrite", os.name,
              "Платформа не предоставляет поддержанный no-replace rename", "Публикуйте на поддержанной Windows/Linux системе")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            _fail("revision_exists", "revision", "новая revision", str(destination), "Revision уже существует")
        raise OSError(code, os.strerror(code), str(destination))


def _location(root, part_id, revision):
    if (not isinstance(part_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", part_id)
            or part_id.upper() in _RESERVED or len(part_id) > 100):
        _fail("library_path", "id", "переносимый ID длиной до 100", part_id, "Недопустимое имя каталога детали")
    if type(revision) is not int or revision < 1:
        _fail("library_path", "revision", "положительное целое", revision, "Некорректная revision")
    root = Path(root).absolute()
    # Не следуем ссылкам даже в существующей части пути; исключаем junction Windows.
    for path in (*reversed(root.parents), root, root / part_id, root / part_id / str(revision)):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            _fail("library_path", "path", "обычный локальный каталог", str(path), "Ссылки в пути библиотеки запрещены")
    return root / part_id / str(revision)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("library_schema", key, "уникальный JSON-ключ", key, "Повторный ключ manifest")
        result[key] = value
    return result


def _shape(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail("library_schema", field, sorted(keys), list(value) if isinstance(value, dict) else repr(value), "Поля не соответствуют версии формата")


def _identities(part):
    return ([('mesh', item.object_id) for item in part.bindings]
            + [('socket', item.id) for item in (part.input, *part.outputs)]
            + [('contact', item.id) for item in part.contacts])


def _manifest(part, digest):
    return {"schema_version": LIBRARY_VERSION, "part": asdict(part),
            "payload": {"file": "payload.blend", "sha256": digest},
            "objects": [{"role": role, "id": key} for role, key in _identities(part)]}


def _read_directory(directory, part_id, revision):
    for name in _FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            _fail("library_path", name, "обычный файл", str(path), "Файл отсутствует или является ссылкой")
    if {p.name for p in directory.iterdir()} != _FILES:
        _fail("library_files", "directory", sorted(_FILES), sorted(p.name for p in directory.iterdir()), "Неожиданный состав revision")
    try:
        value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda value: _fail("library_schema", "number", "конечное число", value, "NaN/Infinity запрещены"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail("library_schema", "manifest.json", "UTF-8 JSON", str(error), "Невозможно прочитать manifest")
    _shape(value, ("schema_version", "part", "payload", "objects"), "manifest")
    if type(value["schema_version"]) is not int or value["schema_version"] != LIBRARY_VERSION:
        _fail("library_schema", "schema_version", LIBRARY_VERSION, value["schema_version"], "Неподдерживаемая версия библиотеки")
    part = part_from_dict(value["part"])
    if (part.id, part.revision) != (part_id, revision):
        _fail("library_identity", "part", [part_id, revision], [part.id, part.revision], "ID/revision не совпадают с каталогом")
    payload = value["payload"]
    _shape(payload, ("file", "sha256"), "payload")
    if payload["file"] != "payload.blend" or not isinstance(payload["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]):
        _fail("library_schema", "payload", "payload.blend + SHA256", payload, "Некорректная ссылка на payload")
    if value["objects"] != _manifest(part, payload["sha256"])["objects"]:
        _fail("library_identity", "objects", _manifest(part, payload["sha256"])["objects"], value["objects"], "Явные IDs/роли отличаются от PartContract")
    digest = _hash(directory / "payload.blend")
    if digest != payload["sha256"]:
        _fail("library_hash", "payload.sha256", payload["sha256"], digest, "Payload изменился после публикации", "Восстановите исходную revision; изменённый файл публикуйте под новой revision")
    return LibraryEntry(directory, part, digest)


def read_part(root, part_id: str, revision: int) -> LibraryEntry:
    """Строгий manifest + hash; Blender-структура проверяется через open_part."""
    return _read_directory(_location(root, part_id, revision), part_id, revision)


def _ids():
    import bpy
    return {item for prop in bpy.data.bl_rna.properties if prop.type == "COLLECTION"
            for item in getattr(bpy.data, prop.identifier) if isinstance(item, bpy.types.ID)}


@contextmanager
def _temporary_ids():
    import bpy
    before = _ids()
    try:
        yield before
    finally:
        # Удаляем только созданные этим синхронным вызовом datablocks, не orphan purge.
        added = _ids() - before
        if added:
            bpy.data.batch_remove(ids=added)


def _property_items(data):
    try:
        return list(data.items())
    except TypeError:
        # Некоторые встроенные NodeSocket вообще не поддерживают IDProperties.
        return []


def _clean_properties(data):
    for key, _ in _property_items(data):
        del data[key]


def _properties(data, allowed=()):
    # Payload metadata имеет закрытый набор scalar-полей: вложенный IDPropertyGroup
    # тоже отклоняется, а не может незаметно пронести scene/datablock dependency.
    items = _property_items(data)
    if any(key not in allowed or type(value) not in (str, int) for key, value in items):
        _fail("payload_dependency", data.name, "только объявленные scalar metadata", [key for key, _ in items], "Посторонние или вложенные metadata в payload")


def _material_dependencies(material, *, copy, memo):
    """Копируем только shader graph/images; ссылки на scene IDs запрещены."""
    import bpy
    if material in memo:
        return memo[material]
    if material.library is not None or material.animation_data is not None:
        _fail("material_dependency", material.name, "локальный материал без анимации", material.name, "Материал зависит от library/Actions")
    result = material.copy() if copy else material
    memo[material] = result
    if copy:
        _clean_properties(result)
        for key in ("gat_material_role", "gat_material_name", "gat_material_signature"):
            if key in material and isinstance(material[key], str):
                result[key] = material[key]
    else:
        _properties(result, ("gat_material_role", "gat_material_name", "gat_material_signature"))
    if result.node_tree:
        _node_tree(result.node_tree, copy=copy, memo=memo)
    return result


def _node_tree(tree, *, copy, memo):
    import bpy
    if tree.animation_data is not None or tree.library is not None:
        _fail("material_dependency", tree.name, "локальный shader graph без Actions", tree.name, "Shader graph анимирован или связан с внешней библиотекой")
    if copy:
        _clean_properties(tree)
    else:
        _properties(tree)
    for item in tree.interface.items_tree:
        if copy:
            _clean_properties(item)
        else:
            _properties(item)
    for node in tree.nodes:
        if node.bl_idname in {"ShaderNodeScript", "ShaderNodeTexIES"}:
            _fail("material_dependency", node.name, "обычные shader nodes", node.bl_idname, "OSL/IES требуют отдельного формата переносимых зависимостей")
        if copy:
            _clean_properties(node)
        else:
            _properties(node)
        for prop in node.bl_rna.properties:
            if prop.type != "POINTER" or prop.identifier == "rna_type":
                continue
            value = getattr(node, prop.identifier, None)
            if not isinstance(value, bpy.types.ID):
                continue
            if isinstance(value, bpy.types.Image):
                if value.library is not None or value.source not in {"FILE", "GENERATED"} or getattr(value, "animation_data", None) is not None:
                    _fail("material_dependency", node.name, "локальное неподвижное изображение", value.source, "Непереносимый тип изображения")
                if copy:
                    if value not in memo:
                        image = value.copy()
                        _clean_properties(image)
                        if image.source == "FILE" and not image.packed_file:
                            # Смена пути может сбросить ImBuf. Сначала разрешаем
                            # путь, затем переносим несохранённые пиксели.
                            image.filepath = bpy.path.abspath(value.filepath, library=value.library)
                        # Blender Image.copy() не копирует текущий ImBuf:
                        # GENERATED остаётся без пикселей, а несохранённая
                        # правка FILE может замениться старым содержимым диска.
                        # Переносим буфер только в копию, не pack/update source.
                        if value.source == "GENERATED" or value.is_dirty:
                            from array import array
                            pixels = array("f", [0.0]) * len(value.pixels)
                            value.pixels.foreach_get(pixels)
                            # FILE.pack() может упаковать старый файл с диска,
                            # даже когда ImBuf копии содержит новые цвета.
                            # GENERATED.pack() кодирует именно текущий буфер.
                            image.source = "GENERATED"
                            image.generated_width, image.generated_height = value.size
                            image.use_generated_float = value.is_float
                            image.pixels.foreach_set(pixels)
                            image.update()
                        try:
                            image.pack()
                        except RuntimeError as error:
                            _fail("material_dependency", node.name, "доступные пиксели для pack", str(error), "Нельзя упаковать изображение")
                        if not image.packed_file:
                            _fail("material_dependency", node.name, "packed image", image.name, "Изображение не упаковано")
                        # Имя не ссылается на исходный пользовательский файл.
                        # raw не инициирует ненужную перезагрузку из пустого пути;
                        # packed bytes уже содержат проверяемые пиксели копии.
                        image.filepath_raw = ""
                        memo[value] = image
                    setattr(node, prop.identifier, memo[value])
                elif not value.packed_file or value.filepath:
                    _fail("material_dependency", node.name, "packed image без внешнего пути", value.filepath, "Payload зависит от внешнего файла")
            elif isinstance(value, bpy.types.ShaderNodeTree):
                if copy and value not in memo:
                    memo[value] = value.copy()
                    _node_tree(memo[value], copy=True, memo=memo)
                elif not copy and value not in memo:
                    memo[value] = value
                    _node_tree(value, copy=False, memo=memo)
                if copy:
                    setattr(node, prop.identifier, memo[value])
            else:
                _fail("material_dependency", node.name + "." + prop.identifier, "только shader graph/packed image", value.name,
                      "Shader ссылается на объект/данные исходной сцены")
        for socket in (*node.inputs, *node.outputs):
            if copy:
                _clean_properties(socket)
            else:
                _properties(socket)
            if isinstance(getattr(socket, "default_value", None), bpy.types.ID):
                _fail("material_dependency", node.name + "." + socket.name, "не ID сцены", repr(socket.default_value), "Socket содержит внешнюю зависимость")


def _transforms(part):
    from mathutils import Matrix
    from .inspection import _matrix
    bones = {bone.id: _matrix(bone.rest) for bone in part.bones}
    return ({("mesh", b.object_id): bones[b.bone] @ _matrix(b.bind_frame) for b in part.bindings}
            | {("socket", p.id): _matrix(p.frame) for p in (part.input, *part.outputs)}
            | {("contact", c.id): bones[c.bone] @ Matrix.Translation(c.position) for c in part.contacts})


def _create_payload(part, source):
    import bpy
    collection = bpy.data.collections.new("GAT_PartPayload")
    collection["gat_library_version"] = LIBRARY_VERSION
    collection["gat_part_id"], collection["gat_part_revision"] = part.id, part.revision
    materials = {}
    for (role, key), matrix in _transforms(part).items():
        original = source[(role, key)]
        data = None
        if role == "mesh":
            if original.data.shape_keys is not None or original.data.animation_data is not None:
                _fail("payload_geometry", key, "mesh без shape keys/animation", original.name, "Непереносимая геометрия")
            data = original.data.copy()
            _clean_properties(data)
            data.materials.clear()
            for slot in original.material_slots:
                data.materials.append(_material_dependencies(slot.material, copy=True, memo=materials) if slot.material else None)
            # clear() сбрасывает polygon indices; возвращаем назначение граней копии.
            for face, source_face in zip(data.polygons, original.data.polygons):
                face.material_index = source_face.material_index
        obj = bpy.data.objects.new(f"{role}_{key}", data)
        collection.objects.link(obj)
        obj["gat_library_role"], obj["gat_library_id"] = role, key
        obj.matrix_world = matrix
        if role == "mesh":
            # Deform weights принадлежат mesh; создаём таблицу групп копии перед очисткой.
            for group in original.vertex_groups:
                obj.vertex_groups.new(name=group.name)
            obj.vertex_groups.clear()
            obj.color = original.color
        else:
            obj.empty_display_type = original.empty_display_type
            obj.empty_display_size = original.empty_display_size
    return collection


def _validate_payload(entry, collection, added):
    import bpy
    from .inspection import _close
    part = entry.part
    _properties(collection, ("gat_library_version", "gat_part_id", "gat_part_revision"))
    if (collection.get("gat_library_version"), collection.get("gat_part_id"), collection.get("gat_part_revision")) != (LIBRARY_VERSION, part.id, part.revision):
        _fail("payload_identity", "collection", [LIBRARY_VERSION, part.id, part.revision], collection.name, "Коллекция не соответствует manifest")
    if collection.children or collection.instance_offset.length > TOLERANCE:
        _fail("payload_hierarchy", "collection", "одна плоская коллекция без offset", collection.name, "Payload содержит дополнительную иерархию")
    lookup, materials = {}, {}
    transforms = _transforms(part)
    for obj in collection.objects:
        _properties(obj, ("gat_library_role", "gat_library_id"))
        key = (obj.get("gat_library_role"), obj.get("gat_library_id"))
        if key in lookup or key not in transforms:
            _fail("payload_identity", "objects", "уникальные явные role/ID", list(key), "Неизвестная или повторная идентичность объекта")
        lookup[key] = obj
        expected_type = "MESH" if key[0] == "mesh" else "EMPTY"
        if obj.type != expected_type or obj.parent or obj.modifiers or obj.constraints or obj.animation_data or obj.vertex_groups or obj.instance_type != "NONE":
            _fail("payload_dependency", str(key), "независимый " + expected_type, obj.type, "Payload содержит rig/parent/modifier/animation/instance зависимость")
        # Detached объект не входит в depsgraph: matrix_world пока может быть stale.
        # При отсутствии parent/constraints его сохранённый transform — matrix_basis.
        if (any(not math.isfinite(v) for row in obj.matrix_basis for v in row)
                or not _close(obj.matrix_basis, transforms[key])
                or any(abs(v - 1.0) > TOLERANCE for v in (*obj.scale, *obj.delta_scale))):
            _fail("payload_transform", str(key), "канонический rig-rest transform", [list(row) for row in obj.matrix_basis], "Transform отличается от manifest")
        if obj.type == "MESH":
            _properties(obj.data)
            if (not obj.data.vertices or not obj.data.polygons or obj.data.shape_keys or obj.data.animation_data
                    or any(v.groups or any(not math.isfinite(x) for x in v.co) for v in obj.data.vertices)):
                _fail("payload_geometry", str(key), "непустая конечная жёсткая геометрия без weights", obj.name, "Геометрия payload повреждена или зависит от rig")
            if (any(not math.isfinite(v) for layer in obj.data.uv_layers for uv in layer.data for v in uv.uv)
                    or any(not math.isfinite(v) for normal in obj.data.corner_normals for v in normal.vector)
                    or any(p.material_index >= max(1, len(obj.material_slots)) for p in obj.data.polygons)):
                _fail("payload_geometry", str(key), "конечные UV/normals и действующие material slots", obj.name, "Повреждённые атрибуты поверхности")
            for slot in obj.material_slots:
                if slot.material:
                    _material_dependencies(slot.material, copy=False, memo=materials)
    if set(lookup) != set(transforms):
        _fail("payload_identity", "objects", sorted(transforms), sorted(lookup), "Набор объектов отличается от PartContract")
    allowed = (bpy.types.Collection, bpy.types.Object, bpy.types.Mesh, bpy.types.Material, bpy.types.ShaderNodeTree, bpy.types.Image)
    for data in added:
        if not isinstance(data, allowed) or data.library is not None or data.use_fake_user:
            _fail("payload_dependency", "datablocks", "только независимые объекты/меши/материалы/изображения",
                  [data.name, data.bl_rna.identifier, data.library.name if data.library else None, data.use_fake_user], "Payload загрузил посторонние данные")
        if isinstance(data, (bpy.types.Image, bpy.types.ShaderNodeTree)):
            _properties(data)
        if isinstance(data, bpy.types.Object) and data not in lookup.values():
            _fail("payload_dependency", "objects", "только declared objects", data.name, "Скрытый объект вне payload collection")
        if isinstance(data, bpy.types.Mesh) and data not in {obj.data for obj in lookup.values() if obj.type == "MESH"}:
            _fail("payload_dependency", "meshes", "только declared mesh data", data.name, "Скрытый mesh datablock")
    return PartPayload(entry, collection,
                       {key: obj for (role, key), obj in lookup.items() if role == "mesh"},
                       {key: obj for (role, key), obj in lookup.items() if role == "socket"},
                       {key: obj for (role, key), obj in lookup.items() if role == "contact"})


@contextmanager
def _load_library(path):
    import bpy
    try:
        with bpy.data.libraries.load(str(path), link=False) as handles:
            yield handles
    except (OSError, RuntimeError) as error:
        _fail("payload_read", "payload.blend", "корректная standalone Blender library", str(error), "Blender не смог прочитать payload")


@contextmanager
def _open_entry(entry):
    import bpy
    before, created = _ids(), None
    try:
        with tempfile.TemporaryDirectory(prefix="gat_part_read_") as temporary:
            # Hash и Blender читают одни приватные bytes даже при изменении библиотеки.
            frozen = Path(temporary) / "payload.blend"
            shutil.copyfile(entry.directory / "payload.blend", frozen)
            if _hash(frozen) != entry.payload_sha256:
                _fail("library_hash", "payload.sha256", entry.payload_sha256, _hash(frozen), "Payload изменился во время чтения")
            # Никаких scene open/append operators: scripts и frames не запускаются.
            with _load_library(frozen) as (source, target):
                allowed = {"collections", "objects", "meshes", "materials", "node_groups", "images"}
                inventory = {}
                for name in dir(source):
                    values = getattr(source, name)
                    if isinstance(values, list) and values:
                        if name not in allowed:
                            _fail("payload_dependency", name, "нет посторонних datablocks", values, "Файл содержит rig/Actions/scene или другую зависимость")
                        inventory[name] = len(values)
                if len(source.collections) != 1:
                    _fail("payload_hierarchy", "collections", 1, len(source.collections), "Ожидается одна независимая коллекция")
                target.collections = list(source.collections)
            if len(target.collections) != 1 or target.collections[0] is None:
                _fail("payload_read", "collection", "загруженная коллекция", None, "Не удалось прочитать payload")
            created = _ids() - before
            # Append оставляет служебный Library ID даже при полностью local данных.
            # Он относится только к приватной копии, а не к зависимости payload.
            for data in list(created):
                if isinstance(data, bpy.types.Library) and Path(data.filepath) == frozen and not any(item.library == data for item in created):
                    created.remove(data)
                    bpy.data.libraries.remove(data)
            for name, count in inventory.items():
                actual = sum(item in created for item in getattr(bpy.data, name))
                if actual != count:
                    _fail("payload_dependency", name, count, actual, "Payload содержит лишние либо повторно использует исходные datablocks")
            payload = _validate_payload(entry, target.collections[0], created)
        # После yield потребитель может делать собственные копии; их не удаляем.
        yield payload
    finally:
        if created is None:
            created = _ids() - before
        remaining = created & _ids()
        if remaining:
            bpy.data.batch_remove(ids=remaining)


@contextmanager
def open_part(root, part_id: str, revision: int):
    """Проверяет и читает отдельную revision; все возвращённые ID временные.

    Вызывающий код может читать/copy данные, но не должен сохранять ссылки после
    выхода из with. Подключение к существующей сборке — отдельная операция.
    """
    entry = read_part(root, part_id, revision)
    with _open_entry(entry) as payload:
        yield payload


def publish_part(root, asset_id, component, part, rig, *, armature, objects, sockets, contacts) -> LibraryEntry:
    """Публикует новую revision из проверенного источника без снятия текущей позы."""
    import bpy
    from game_asset_tools.asset.scene import asset_objects, find_root
    from .inspection import inspect_part
    part = part_from_dict(asdict(part))
    destination = _location(root, part.id, part.revision)
    if destination.exists():
        _fail("revision_exists", "revision", "новая revision", str(destination), "Revision уже опубликована", "Увеличьте PartContract.revision; overwrite не поддерживается")
    report = inspect_part(asset_id, component, part, rig, armature=armature, objects=objects, sockets=sockets, contacts=contacts)
    if report["status"] != "pass":
        raise LibraryError(Issue(**issue) for issue in report["issues"])
    owned = {(obj.get("gat_component"), obj.get("gat_local_name")): obj for obj in asset_objects(find_root(asset_id))}
    source = {(role, key): owned[(ref.component, ref.local_name)]
              for role, mapping in (("mesh", objects), ("socket", sockets), ("contact", contacts)) for key, ref in mapping.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".publish-", dir=destination.parent))
    try:
        with _temporary_ids():
            collection = _create_payload(part, source)
            bpy.data.libraries.write(str(staging / "payload.blend"), {collection}, path_remap="NONE", fake_user=False, compress=True)
        digest = _hash(staging / "payload.blend")
        (staging / "manifest.json").write_text(json.dumps(_manifest(part, digest), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        entry = _read_directory(staging, part.id, part.revision)
        with _open_entry(entry):
            pass
        _publish_directory(staging, destination)
    finally:
        if staging.exists():
            # Удалять разрешено только наш созданный staging внутри этой библиотеки.
            if staging.resolve().parent != destination.parent.resolve() or not staging.name.startswith(".publish-"):
                raise RuntimeError("Staging path escaped its library directory")
            shutil.rmtree(staging)
    return read_part(root, part.id, part.revision)
