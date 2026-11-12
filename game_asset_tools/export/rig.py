"""Preflight and postflight for explicitly requested skeletal GLB export."""

import math
from collections import Counter


def _bone_path(bone):
    """Имена компонентов пути сохраняются отдельно, включая возможный '/' в имени."""
    result = []
    while bone is not None:
        result.append(bone.name)
        bone = bone.parent
    return tuple(reversed(result))


def _object_path(obj):
    """Путь экспортируемого object учитывает промежуточные кости bone parent."""
    if obj.parent is None:
        return (obj.name,)
    parent = _object_path(obj.parent)
    if obj.parent_type == "BONE":
        parent += _bone_path(obj.parent.data.bones[obj.parent_bone])
    return (*parent, obj.name)


def animation_contract(objects):
    """Describe owned rigs/skins/actions without modifying Blender data.

    Actions must be assigned or stashed on an exported object. Unrelated actions
    in bpy.data.actions are never broadcast to a compatible armature.
    """
    owned = set(objects)
    rigs = [obj for obj in objects if obj.type == "ARMATURE"]
    if not rigs:
        raise ValueError("Animated export requires an armature registered with ctx.add (not a helper)")
    for obj in objects:
        if obj.parent is not None and obj.parent not in owned:
            raise ValueError(f"Animated export has an excluded or external parent: {obj.name}")
        # Live-контролы вне payload могут одинаково переопределить все Actions.
        # Явный bake/context должен отключить их до обычного animated export.
        owners = [obj, *obj.pose.bones] if obj.type == "ARMATURE" else [obj]
        for owner in owners:
            for constraint in owner.constraints:
                if constraint.mute:
                    continue
                for field in ("target", "pole_target"):
                    target = getattr(constraint, field, None)
                    if target is not None and target not in owned:
                        raise ValueError(f"Bake external animation control before export: {obj.name}/{owner.name}/{constraint.name}")
    expected = {"rigs": {}, "bindings": {}, "actions": [], "sockets": {}, "action_targets": {}}
    action_targets = {}
    for rig in rigs:
        bones = list(rig.data.bones)
        if not bones:
            raise ValueError(f"Armature has no bones: {rig.name}")
        for bone in bones:
            if bone.length <= 0 or not all(math.isfinite(v) for row in bone.matrix_local for v in row):
                raise ValueError(f"Invalid rest bone: {rig.name}/{bone.name}")
        expected["rigs"][rig.name] = [bone.name for bone in bones]
    for obj in objects:
        if obj.type == "EMPTY" and obj.get("gat_role") != "asset_root":
            expected["sockets"][obj.name] = {"parent": obj.parent.name if obj.parent else None,
                                             "bone": obj.parent_bone if obj.parent_type == "BONE" else None}
        if obj.parent_type == "BONE" and (obj.parent not in rigs or obj.parent_bone not in obj.parent.data.bones):
            raise ValueError(f"Invalid bone parent: {obj.name}/{obj.parent_bone}")
        if obj.type == "MESH":
            # glTF exporter применяет фаски к экспортной копии, временно отключая
            # Armature при export_skins=True. Shape keys этот путь не сохраняет.
            if obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 1:
                raise ValueError(f"Animated rigid export cannot preserve shape keys: {obj.name}")
            modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
            if len(modifiers) > 1:
                raise ValueError(f"Animated export supports one armature modifier per mesh: {obj.name}")
            if modifiers:
                modifier = modifiers[0]
                rig = modifier.object
                if rig not in rigs:
                    raise ValueError(f"Mesh uses an external or excluded armature: {obj.name}")
                if not modifier.show_viewport or not modifier.show_render or not modifier.use_vertex_groups:
                    raise ValueError(f"Enable the armature modifier and vertex groups: {obj.name}")
                bone_groups = {group.index for group in obj.vertex_groups if group.name in rig.data.bones}
                for vertex in obj.data.vertices:
                    weights = [group.weight for group in vertex.groups if group.group in bone_groups]
                    if not weights or any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) <= 0:
                        raise ValueError(f"Mesh has an unweighted or invalid vertex: {obj.name}/{vertex.index}")
                expected["bindings"][obj.name] = rig.name
        data = obj.animation_data
        if data is None:
            continue
        actions = [data.action] if data.action else []
        for track in data.nla_tracks:
            # glTF Actions mode supports one action per track. Reject a composed
            # NLA timeline rather than silently flattening or dropping its strips.
            if len(track.strips) != 1:
                raise ValueError(f"Use one action per NLA track for animated export: {obj.name}/{track.name}")
            strip = track.strips[0]
            if strip.action is not None:
                actions.append(strip.action)
        for action in actions:
            if action.name not in expected["actions"]:
                expected["actions"].append(action.name)
            # Actions mode может запечь все кости armature, даже если исходная
            # F-Curve меняет одну. Это допустимые адресаты данного владельца,
            # а не обещание равенства всех кривых или наличия каждого канала.
            owner_path = _object_path(obj)
            targets = {owner_path}
            if obj.type == "ARMATURE":
                targets.update(owner_path + _bone_path(bone) for bone in obj.data.bones)
            action_targets.setdefault(action.name, set()).update(targets)
    if not expected["bindings"]:
        raise ValueError("Animated export requires a mesh skinned to the registered armature")
    if not expected["actions"]:
        raise ValueError("Animated export requires an active or stashed action on the registered asset")
    expected["action_targets"] = {name: [list(path) for path in sorted(paths)]
                                  for name, paths in action_targets.items()}
    return expected


def _node_paths(summary):
    """Индексная иерархия различает одинаковые имена костей у разных ригов."""
    names, parents = summary["node_names"], summary.get("node_parent_indices")
    if not isinstance(parents, list) or len(parents) != len(names):
        raise ValueError("Animated GLB inspection lacks a complete indexed node hierarchy; rerun inspection")
    paths = []
    for index in range(len(names)):
        path, seen = [], set()
        current = index
        while current is not None:
            if type(current) is not int or not 0 <= current < len(names) or current in seen:
                raise ValueError("Animated GLB has an invalid indexed node hierarchy")
            seen.add(current)
            path.append(names[current])
            current = parents[current]
        paths.append(tuple(reversed(path)))
    return paths


def verify_animation_contract(expected, summary):
    """Fail when the real GLB lost an authored rig, skin, socket, or clip."""
    names = set(summary["node_names"])
    missing = (set(expected["rigs"]) | set(expected["sockets"])) - names
    if missing:
        raise ValueError("Animated GLB lost nodes: " + ", ".join(sorted(missing)))
    for socket, source in expected["sockets"].items():
        parent = source["bone"] or source["parent"]
        if summary["node_parents"].get(socket) != parent:
            raise ValueError(f"Animated GLB lost socket parent: {socket}; expected {parent}")
    bindings = {binding["node"]: binding for binding in summary["skin_bindings"]}
    for mesh, rig in expected["bindings"].items():
        binding = bindings.get(mesh)
        if binding is None or not binding["weighted"]:
            raise ValueError(f"Animated GLB lost skin/weights: {mesh}")
        joints = set(summary["skin_details"][binding["skin"]]["joint_names"])
        missing_bones = set(expected["rigs"][rig]) - joints
        if missing_bones:
            raise ValueError(f"Animated GLB lost joints for {mesh}: {', '.join(sorted(missing_bones))}")
        if rig not in summary["skin_details"][binding["skin"]]["ancestors"]:
            raise ValueError(f"Animated GLB attached {mesh} to the wrong armature; expected {rig}")
    clips = {clip["name"] for clip in summary["animation_details"] if clip["channels"] > 0}
    missing_clips = set(expected["actions"]) - clips
    if missing_clips:
        raise ValueError("Animated GLB lost action clips: " + ", ".join(sorted(missing_clips)))
    unexpected = clips - set(expected["actions"])
    if unexpected:
        raise ValueError("Animated GLB included unrelated action clips: " + ", ".join(sorted(unexpected)))
    allowed_targets = expected.get("action_targets")
    if not isinstance(allowed_targets, dict) or set(allowed_targets) != set(expected["actions"]):
        # Это внутренний preflight, а не сохранённая схема пользовательской сцены.
        # Старый отчёт без владельцев нельзя считать доказательством нового экспорта.
        raise ValueError("Animation contract lacks per-action target ownership; rerun preflight")
    paths = _node_paths(summary)
    path_counts = Counter(paths)
    for clip in summary["animation_details"]:
        if not clip["channels"]:
            continue
        indices = clip.get("target_indices")
        if indices is None:
            raise ValueError("Animated GLB inspection lacks indexed animation targets; rerun inspection")
        if not isinstance(indices, list) or not indices or any(
                type(index) is not int or not 0 <= index < len(paths) for index in indices):
            raise ValueError(f"Animated GLB has invalid animation target indices: {clip['name']}")
        declared = allowed_targets[clip["name"]]
        if not isinstance(declared, list) or not declared or any(
                not isinstance(path, list) or not path or any(type(name) is not str or not name for name in path)
                for path in declared):
            raise ValueError("Animation contract has invalid action target ownership; rerun preflight")
        allowed = {tuple(path) for path in declared}
        for index in indices:
            path = paths[index]
            if path not in allowed:
                raise ValueError(f"Animated GLB has an unowned animation target: {clip['name']} -> {path!r}")
            if path_counts[path] != 1:
                raise ValueError(f"Animated GLB has an ambiguous animation target: {clip['name']} -> {path!r}")
