"""In-memory editor state; values here are never written into a .blend."""

from contextlib import contextmanager


values = {}
stages = {}
active = {}
drafts = {}
geometry_sources = {}
root_projects = {}
selection = {}
messages = {}
_suspended = set()


def scene_id(settings):
    return settings.id_data.as_pointer()


def value_key(item):
    # Adding another RNA collection item can relocate every item's C pointer.
    # Its path within the owning scene stays stable until we clear the form.
    return item.id_data.as_pointer(), item.path_from_id()


def get_value(item, default):
    return values.get(value_key(item), default)


def set_value(item, value):
    values[value_key(item)] = value


def clear_parameters(collection):
    for item in collection:
        values.pop(value_key(item), None)
    collection.clear()


def suspended(settings):
    return scene_id(settings) in _suspended


@contextmanager
def suspend(settings):
    key = scene_id(settings)
    already = key in _suspended
    _suspended.add(key)
    try:
        yield
    finally:
        if not already:
            _suspended.discard(key)


def clear():
    for mapping in (values, stages, active, drafts, geometry_sources, root_projects, selection, messages):
        mapping.clear()
    _suspended.clear()
