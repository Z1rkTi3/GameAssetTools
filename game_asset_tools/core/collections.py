"""Explicit collection organization without claiming existing user content."""

from __future__ import annotations

import bpy

from .naming import semantic_name


def create_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    """Create a fresh collection under parent (or the active scene root).

    An unrelated existing collection with this name is never reused or moved.
    Asset lifecycle code should retain the returned identity for later reuse.
    """
    collection = bpy.data.collections.new(semantic_name(name))
    (parent if parent is not None else bpy.context.scene.collection).children.link(collection)
    return collection


def link_object(obj: bpy.types.Object, collection: bpy.types.Collection) -> bpy.types.Object:
    """Link an object without unlinking it from any existing collection."""
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    return obj
