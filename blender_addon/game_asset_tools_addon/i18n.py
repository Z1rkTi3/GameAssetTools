"""Add-on language preference and display-only localization wrappers."""

import bpy
from bpy.props import EnumProperty

from game_asset_tools.i18n import translate
from . import session


ADDON_ID = "game_asset_tools_addon"


def get_preferences(context=None):
    """Return user-wide add-on preferences, or None during source registration."""
    context = context if context is not None else bpy.context
    preferences = getattr(context, "preferences", None)
    addons = getattr(preferences, "addons", None)
    addon = addons.get(ADDON_ID) if addons is not None else None
    return getattr(addon, "preferences", None)


def language(context=None):
    """Resolve AUTO against Blender without changing its global language."""
    context = context if context is not None else bpy.context
    preferences = get_preferences(context)
    choice = getattr(preferences, "language", "AUTO")
    if choice in {"en_US", "ru_RU"}:
        return choice
    view = getattr(getattr(context, "preferences", None), "view", None)
    locale = getattr(view, "language", "DEFAULT")
    if locale == "DEFAULT":
        locale = getattr(bpy.app.translations, "locale", "en_US")
    return "ru_RU" if str(locale).lower().replace("-", "_").split("_")[0] == "ru" else "en_US"


def tr(message, context=None, **values):
    """Translate presentation text; never write translated text into config."""
    return translate(message, language(context), **values)


def set_status(settings, field, message, **values):
    """Keep the message key so language changes can redraw existing status text."""
    source = message.format(**values) if values else message
    setattr(settings, field, source)
    session.messages[(session.scene_id(settings), field)] = (source, message, values)


def status_text(settings, field, context=None):
    source = getattr(settings, field)
    cached = session.messages.get((session.scene_id(settings), field))
    if cached and cached[0] == source:
        values = dict(cached[2])
        if "status" in values:
            values["status"] = tr(values["status"], context)
        return tr(cached[1], context, **values)
    return tr(source, context)


class LocalizedOperator:
    @classmethod
    def description(cls, context, properties):
        return tr(getattr(cls, "bl_description", cls.bl_label), context)


def _language_changed(self, context):
    # Do not reload controls: a language switch must preserve unsaved edits.
    manager = getattr(context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            area.tag_redraw()


class GAT_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    language: EnumProperty(
        name="Language",
        description="GameAssetTools interface language",
        items=(
            ("AUTO", "Automatic / Автоматически", "Follow Blender's interface language"),
            ("en_US", "English", "Use English for GameAssetTools"),
            ("ru_RU", "Русский", "Use Russian for GameAssetTools"),
        ),
        default="AUTO",
        update=_language_changed,
    )

    def draw(self, context):
        self.layout.prop(self, "language", text=tr("Language", context))
        self.layout.label(text=tr("Saved with Blender preferences; shared across projects", context))
        self.layout.label(text=tr("Save Preferences to keep this choice after restarting Blender", context))


CLASSES = (GAT_Preferences,)
