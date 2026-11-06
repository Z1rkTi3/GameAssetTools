"""Preflight and postflight for explicitly requested skeletal GLB export."""

import math


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
    expected = {"rigs": {}, "bindings": {}, "actions": [], "sockets": {}}
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
    if not expected["bindings"]:
        raise ValueError("Animated export requires a mesh skinned to the registered armature")
    if not expected["actions"]:
        raise ValueError("Animated export requires an active or stashed action on the registered asset")
    return expected


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
