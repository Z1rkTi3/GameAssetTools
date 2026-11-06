"""Адресная замена библиотечной детали с сохранением постоянного рига.

Все проверки и подключение выполняются до удаления прежних объектов.
Скелет, Actions, кадр и соседние компоненты не пересоздаются.
"""
from dataclasses import asdict
import uuid

from game_asset_tools.asset.lifecycle import _guard, _remove_object
from game_asset_tools.asset.metadata import encode, fingerprint, tag
from game_asset_tools.asset.scene import asset_objects, component_records, find_root
from game_asset_tools.core.naming import semantic_name
from .contracts import Issue, check_compatibility, part_from_dict, rig_from_dict, slot_from_dict
from .authoring import INTERFACE_KEY, interface_to_dict
from .inspection import ObjectRef, inspect_part
from .library import LibraryError, _ids, _material_dependencies, _open_entry, read_part


def _refuse(component, code, field, message):
    raise LibraryError((Issue("error", code, component, field, "безопасная адресная замена", None,
                             message, "Исправьте причину и повторите проверку; источник сохранён"),))


def _checked(report):
    if report["status"] != "pass":
        raise LibraryError(Issue(**issue) for issue in report["issues"])


def _marker_parent(obj, rig, bone_id, rest):
    """Bone parenting компенсирует хвост кости и не требует менять текущую позу."""
    from mathutils import Matrix
    bone = rig.data.bones[bone_id]
    obj.parent, obj.parent_type, obj.parent_bone = rig, "BONE", bone_id
    obj.matrix_parent_inverse = Matrix.Translation((0, -bone.length, 0))
    obj.matrix_basis = bone.matrix_local.inverted() @ rest


def _explicit_references(owner, targets):
    """Отличает членство в Scene/Collection от авторских ID-ссылок.

    user_map включает сцену даже из-за обычного ViewLayer base. Поэтому для
    разрешённых контейнеров читаем их собственные RNA/ID-properties; в чужие
    ID не заходим — их зависимости уже представлены отдельно в user_map.
    """
    import bpy
    found, visited = set(), set()

    def visit(value, *, root=False):
        if isinstance(value, bpy.types.ID) and not root:
            if value in targets:
                found.add(value)
            return
        if hasattr(value, "bl_rna"):
            pointer = value.as_pointer()
            if pointer in visited:
                return
            visited.add(pointer)
            if hasattr(value, "items"):
                try:
                    properties = value.items()
                except TypeError:
                    # RNA structures вроде RenderSettings не имеют IDProperties.
                    properties = ()
                for key, item in properties:
                    visit(item)
            for prop in value.bl_rna.properties:
                if prop.identifier in {"rna_type", "id_data"}:
                    continue
                if prop.type == "POINTER":
                    visit(getattr(value, prop.identifier, None))
                elif prop.type == "COLLECTION":
                    for item in getattr(value, prop.identifier):
                        # ID-коллекции — обычное членство, а не поле-ссылка.
                        if not isinstance(item, bpy.types.ID):
                            visit(item)
        elif hasattr(value, "items"):
            for key, item in value.items():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(owner, root=True)
    return found


def _remove_unused_dependencies(instance):
    """Очищает только собственные копии прежней установки, не чужие orphans."""
    import bpy
    if not instance:
        return
    while True:
        unused = {item for item in _ids() if item.get("gat_library_instance") == instance and item.users == 0}
        if not unused:
            return
        # После удаления материала может освободиться node group, затем image.
        bpy.data.batch_remove(ids=unused)


def replace_part(library_root, asset_id, component, current, slot, rig, candidate_id,
                 candidate_revision, *, armature, objects, sockets, contacts, dry_run=False):
    """Меняет один компонент; возвращает manifest и mappings нового экземпляра.

current/slot/rig и старые ObjectRef задаются явно, как у inspect_part/publish_part.
dry_run проверяет также payload, не подключая его к сцене. Ручные правки, locks
и внешние ссылки не обходятся. Все отказы до commit восстанавливают источник.
"""
    import bpy
    if bpy.context.mode != "OBJECT":
        _refuse(component, "object_mode", "mode", "Перед заменой завершите Edit/Pose Mode")
    current, slot, rig = part_from_dict(asdict(current)), slot_from_dict(asdict(slot)), rig_from_dict(asdict(rig))
    root = find_root(asset_id)
    records = component_records(root)
    if component not in records or records[component].get("persistent"):
        _refuse(component, "component", "ownership", "Компонент отсутствует либо является постоянным")
    issues = check_compatibility(current, slot, rig)
    if issues:
        raise LibraryError(issues)
    _checked(inspect_part(asset_id, component, current, rig, armature=armature,
                          objects=objects, sockets=sockets, contacts=contacts))
    errors = _guard(root, {component})
    if errors:
        _refuse(component, "protected_source", "component", "; ".join(errors))
    lookup = {(obj.get("gat_component"), obj.get("gat_local_name")): obj for obj in asset_objects(root)}
    skeleton = lookup[(armature.component, armature.local_name)]
    old_objects = set(asset_objects(root, component))
    old_mappings = {("mesh", key): lookup[(ref.component, ref.local_name)] for key, ref in objects.items()}
    old_mappings.update({("socket", key): lookup[(ref.component, ref.local_name)] for key, ref in sockets.items()})
    old_mappings.update({("contact", key): lookup[(ref.component, ref.local_name)] for key, ref in contacts.items()})
    memberships = {obj: tuple(obj.users_collection) for obj in old_objects}
    # Не обрываем чужие modifiers, constraints, drivers или ID-ссылки на старую деталь.
    containers = {root, *root.children_recursive, bpy.context.scene}
    for container in containers:
        if _explicit_references(container, old_objects):
            _refuse(component, "external_reference", container.name, "Контейнер хранит авторскую ссылку на заменяемую деталь")
    allowed_users = old_objects | containers
    for obj, users in bpy.data.user_map(subset=old_objects).items():
        external = users - allowed_users
        if external:
            _refuse(component, "external_reference", obj.name, "Деталь используется вне заменяемого компонента: " + ", ".join(sorted(user.name for user in external)))
    destinations = [c for c in root.children if c.get("gat_asset_id") == asset_id
                    and c.get("gat_group") == records[component]["collection"]]
    if len(destinations) != 1:
        _refuse(component, "collection", "ownership", "Не найдена однозначная коллекция компонента")
    destination = destinations[0]
    entry = read_part(library_root, candidate_id, candidate_revision)
    issues = check_compatibility(entry.part, slot, rig)
    if issues:
        raise LibraryError(issues)
    local_names = {("mesh", item.object_id): "Mesh_" + item.object_id for item in entry.part.bindings}
    local_names.update({("socket", item.id): "Socket_" + item.id for item in (entry.part.input, *entry.part.outputs)})
    local_names.update({("contact", item.id): "Contact_" + item.id for item in entry.part.contacts})
    for local in local_names.values():
        occupied = bpy.data.objects.get(semantic_name(asset_id, component, local))
        if occupied is not None and occupied not in old_objects:
            _refuse(component, "name_collision", local, "Итоговое имя занято сохраняемым объектом")
    report = {"asset": asset_id, "component": component, "status": "planned",
              "part": asdict(entry.part), "payload_sha256": entry.payload_sha256,
              "replaced_objects": len(old_objects), "created_objects": len(local_names)}
    before_ids = _ids()
    before_records = root["gat_components"]
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    staging, replacements = None, {}
    instance = uuid.uuid4().hex
    old_instance = records[component].get("library_part", {}).get("instance")
    committed = detached = False
    try:
        with _open_entry(entry) as payload:
            if dry_run:
                return report
            staging = bpy.data.collections.new("GAT_PartReplacement_" + uuid.uuid4().hex)
            root.children.link(staging)
            staging_component = component + "_Replacement_" + uuid.uuid4().hex
            materials = {}
            definitions = {("mesh", item.object_id): item for item in entry.part.bindings}
            definitions.update({("socket", item.id): item for item in (entry.part.input, *entry.part.outputs)})
            definitions.update({("contact", item.id): item for item in entry.part.contacts})
            sources = {("mesh", key): value for key, value in payload.objects.items()}
            sources.update({("socket", key): value for key, value in payload.sockets.items()})
            sources.update({("contact", key): value for key, value in payload.contacts.items()})
            for identity, original in sources.items():
                role, key = identity
                definition, local = definitions[identity], local_names[identity]
                data = original.data.copy() if role == "mesh" else None
                if data is not None:
                    indices = [face.material_index for face in data.polygons]
                    data.materials.clear()
                    for material in original.data.materials:
                        data.materials.append(_material_dependencies(material, copy=True, memo=materials) if material else None)
                    for face, index in zip(data.polygons, indices):
                        face.material_index = index
                obj = bpy.data.objects.new(semantic_name(asset_id, staging_component, local), data)
                staging.objects.link(obj)
                tag(obj, asset_id, staging_component, root["gat_stage"], root["gat_recipe_version"], helper=role != "mesh")
                obj["gat_local_name"] = local
                if role == "mesh":
                    obj.color = original.color
                    obj.parent = skeleton
                    # Payload не связан со сценой: world matrix могла остаться
                    # невычисленной. Проверенная basis хранит rig-rest transform.
                    obj.matrix_basis = original.matrix_basis.copy()
                    obj.vertex_groups.new(name=definition.bone).add(list(range(len(data.vertices))), 1.0, "REPLACE")
                    obj.modifiers.new("RigidSkeletonSkin", "ARMATURE").object = skeleton
                else:
                    obj.empty_display_type, obj.empty_display_size = original.empty_display_type, original.empty_display_size
                    obj["gat_socket" if role == "socket" else "gat_contact"] = key
                    _marker_parent(obj, skeleton, definition.bone, original.matrix_basis.copy())
                replacements[identity] = obj
            for dependency in materials.values():
                dependency["gat_library_instance"] = instance
                dependency.use_fake_user = False
            def mappings(owner):
                return {kind: {key: ObjectRef(owner, local_names[(role, key)]) for r, key in local_names if r == role}
                        for kind, role in (("objects", "mesh"), ("sockets", "socket"), ("contacts", "contact"))}
            _checked(inspect_part(asset_id, staging_component, entry.part, rig, armature=armature, **mappings(staging_component)))
        # Старые ID остаются живы до успешного postflight и могут быть возвращены.
        detached = True
        for obj, collections in memberships.items():
            for collection in collections:
                collection.objects.unlink(obj)
        for identity, obj in replacements.items():
            obj["gat_component"] = component
            destination.objects.link(obj)
            staging.objects.unlink(obj)
        _checked(inspect_part(asset_id, component, entry.part, rig, armature=armature, **mappings(component)))
        new_record = {**records[component], "object_count": len(replacements),
                      INTERFACE_KEY: interface_to_dict(entry.part, slot, rig, armature=armature, **mappings(component)),
                      "library_part": {"id": entry.part.id, "revision": entry.part.revision,
                                       "payload_sha256": entry.payload_sha256, "instance": instance}}
        records[component] = new_record
        root["gat_components"] = encode(records)
        reverse = {obj: identity for identity, obj in old_mappings.items()}
        selection_after = [replacements.get(reverse[obj], skeleton) if obj in reverse else obj for obj in selected]
        active_after = replacements.get(reverse[active], skeleton) if active in reverse else active
        for obj in replacements.values():
            obj["gat_fingerprint"] = fingerprint(obj)
        # Смена выделения тоже может отказать, например для исключённой
        # LayerCollection. Проверяем её пока старые ID ещё можно восстановить.
        bpy.context.view_layer.update()
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in selection_after:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active_after
        if set(bpy.context.selected_objects) != set(selection_after):
            _refuse(component, "selection_destination", destination.name,
                    "Коллекция назначения скрывает выбранную деталь; сначала сделайте её доступной в ViewLayer")
        committed = True
        for obj in old_objects:
            _remove_object(obj)
        _remove_unused_dependencies(old_instance)
        for identity, obj in replacements.items():
            obj.name = semantic_name(asset_id, component, local_names[identity])
        bpy.data.collections.remove(staging)
        report.update(status="replaced", mappings={kind: {key: asdict(ref) for key, ref in mapping.items()}
                                                   for kind, mapping in mappings(component).items()})
        return report
    except BaseException:
        if not committed:
            root["gat_components"] = before_records
            if detached:
                for obj, collections in memberships.items():
                    for collection in collections:
                        if obj.name not in collection.objects:
                            collection.objects.link(obj)
            added = _ids() - before_ids
            if added:
                bpy.data.batch_remove(ids=added)
            bpy.context.view_layer.update()
            for obj in bpy.context.selected_objects:
                obj.select_set(False)
            for obj in selected:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = active
        raise
