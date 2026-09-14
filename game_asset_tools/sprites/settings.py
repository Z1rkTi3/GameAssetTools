"""Canonical, Blender-independent sprite settings shared by the CLI and add-on."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from game_asset_tools.asset.parameters import (
    SCHEMA_VERSION, Parameter, merge_values, set_value, validate_config,
)
from game_asset_tools.asset.registry import Registry


# Both the Blender properties and programmatic validation consume this schema.
# Numeric choices are strings so the same choices can populate Blender enums.
FIELDS = (
    {"key": "look", "label": "Look", "type": "enum", "default": "toon",
     "min": None, "max": None, "choices": ("toon", "standard")},
    {"key": "resolution", "label": "Frame Size", "type": "int", "default": 512,
     "min": 64, "max": 2048, "choices": ()},
    {"key": "directions", "label": "Directions", "type": "int", "default": 8,
     "min": 1, "max": 16, "choices": ("1", "4", "8", "16")},
    {"key": "azimuth", "label": "Camera Azimuth", "type": "float", "default": 45.0,
     "min": -360.0, "max": 360.0, "choices": ()},
    {"key": "elevation", "label": "Camera Elevation", "type": "float", "default": 30.0,
     "min": 0.0, "max": 85.0, "choices": ()},
    {"key": "margin", "label": "Frame Margin", "type": "float", "default": 0.08,
     "min": 0.01, "max": 0.49, "choices": ()},
    {"key": "cel_steps", "label": "Cel Light Steps", "type": "int", "default": 3,
     "min": 2, "max": 4, "choices": ()},
    {"key": "light_azimuth", "label": "Light Azimuth", "type": "float", "default": -35.0,
     "min": -360.0, "max": 360.0, "choices": ()},
    {"key": "light_elevation", "label": "Light Elevation", "type": "float", "default": 55.0,
     "min": 5.0, "max": 85.0, "choices": ()},
    {"key": "padding", "label": "Atlas Padding", "type": "int", "default": 2,
     "min": 0, "max": 16, "choices": ()},
    {"key": "atlas_columns", "label": "Atlas Columns", "type": "int", "default": 4,
     "min": 1, "max": 16, "choices": ()},
)


def validate_settings(overlay: dict[str, Any]) -> dict[str, Any]:
    """Return full validated settings, accepting only declared JSON controls."""
    if not isinstance(overlay, dict):
        raise ValueError("Sprite settings must be a JSON object.")
    known = {field["key"] for field in FIELDS}
    unknown = set(overlay) - known
    if unknown:
        raise ValueError(f"Unknown sprite settings: {', '.join(sorted(map(str, unknown)))}.")
    result = {}
    for field in FIELDS:
        key = field["key"]
        value = overlay.get(key, field["default"])
        parameter = Parameter(f"sprites.{key}", field["label"], field["type"],
                              field["default"], min=field["min"], max=field["max"],
                              choices=field["choices"])
        parameter.validate(value)
        if field["type"] == "int" and field["choices"] and str(value) not in field["choices"]:
            raise ValueError(f"Sprite setting {key!r} must be one of {', '.join(field['choices'])}.")
        result[key] = float(value) if field["type"] == "float" else value
    return result


def _validate_document(entry, config: dict[str, Any]) -> None:
    """Use normal recipe defaults for validation without expanding the document."""
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object.")
    defaults = {}
    for parameter in entry.load().parameters:
        set_value(defaults, parameter.path, parameter.default)
    validate_config(entry, merge_values(
        {"schema_version": SCHEMA_VERSION, "asset": entry.id,
         "parameters": defaults, "style": {}}, config))


def _snapshot(entry) -> tuple[dict[str, Any], str]:
    path = entry.config_path

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number {value!r} is not supported.")

    try:
        contents = path.read_bytes()
        config = json.loads(contents.decode("utf-8-sig"), parse_constant=reject_constant)
        _validate_document(entry, config)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    return config, hashlib.sha256(contents).hexdigest()


def _result(entry, settings: dict[str, Any], revision: str, status: str) -> dict[str, Any]:
    return {"status": status, "asset": entry.id, "settings": settings,
            "revision": revision, "path": str(entry.config_path)}


def read_settings(project: str | Path, asset: str) -> dict[str, Any]:
    """Read recipe-local settings and a revision for optimistic UI editing."""
    entry = Registry(Path(project)).get(asset)
    config, revision = _snapshot(entry)
    return _result(entry, validate_settings(config.get("sprites", {})), revision, "ok")


def write_settings(project: str | Path, asset: str, updates: dict[str, Any],
                   expected_revision: str | None = None,
                   dry_run: bool = False) -> dict[str, Any]:
    """Merge sprite settings only, validating the entire config before replacement.

    Passing the revision returned by read_settings protects a UI edit from stale
    values after another client changes the file. Dry runs retain that revision.
    """
    if expected_revision is not None and not isinstance(expected_revision, str):
        raise ValueError("expected_revision must be a string or null.")
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean.")
    validate_settings(updates)
    entry = Registry(Path(project)).get(asset)
    config, revision = _snapshot(entry)
    if expected_revision is not None and expected_revision != revision:
        raise ValueError("Sprite settings conflict: config.json changed; reload settings before saving.")
    settings = validate_settings({**config.get("sprites", {}), **updates})
    replacement = deepcopy(config)
    replacement["sprites"] = settings
    _validate_document(entry, replacement)
    if dry_run:
        return _result(entry, settings, revision, "planned")
    contents = (json.dumps(replacement, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=entry.path, prefix=".sprites-",
                                         suffix=".json.tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
        if hashlib.sha256(entry.config_path.read_bytes()).hexdigest() != revision:
            raise ValueError("Sprite settings conflict: config.json changed during saving; reload settings.")
        os.replace(temporary_path, entry.config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return _result(entry, settings, hashlib.sha256(contents).hexdigest(), "saved")
