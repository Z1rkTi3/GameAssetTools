"""Game-wide defaults, merged with project then asset overrides; no Blender import."""

from copy import deepcopy
import math
from pathlib import Path
from typing import Any

from game_asset_tools.asset.parameters import merge_values, read_json

DEFAULT_MATERIALS = {
    "Stone": {"base_color": [0.40, 0.43, 0.47, 1.0], "roughness": 0.85},
    "Metal_Silver": {"base_color": [0.58, 0.64, 0.72, 1.0], "metallic": 0.8, "roughness": 0.3},
    "Metal_Bronze": {"base_color": [0.42, 0.22, 0.08, 1.0], "metallic": 0.75, "roughness": 0.35},
    "Glass_Clear": {"base_color": [0.16, 0.38, 0.48, 1.0], "roughness": 0.12, "transmission": 0.5},
    "Glass_Opaque": {"base_color": [0.10, 0.28, 0.38, 1.0], "roughness": 0.3, "metallic": 0.15},
    "Ruby": {"base_color": [0.55, 0.015, 0.05, 1.0], "roughness": 0.22},
    "Rubber": {"base_color": [0.025, 0.03, 0.04, 1.0], "roughness": 0.92},
    "Painted_Metal": {"base_color": [0.14, 0.29, 0.33, 1.0], "metallic": 0.35, "roughness": 0.48},
    "Dark_Metal": {"base_color": [0.055, 0.07, 0.09, 1.0], "metallic": 0.7, "roughness": 0.38},
    "Glass": {"base_color": [0.16, 0.38, 0.48, 1.0], "roughness": 0.12, "transmission": 0.5},
    "Concrete": {"base_color": [0.40, 0.43, 0.47, 1.0], "roughness": 0.85},
    "Accent": {"base_color": [0.85, 0.34, 0.055, 1.0], "roughness": 0.5},
}

DEFAULT_STYLE = {
    "schema_version": 1, "units": "meters", "unit_scale": 1.0,
    "style": "low_poly", "shading": "flat_or_simple", "silhouette_priority": "high",
    "small_detail_density": "low", "symmetry_preference": True,
    "bevel": {"width": 0.04, "segments": 1}, "default_texture_resolution": 512,
    "target_engine": "Godot", "default_export_format": "glb",
    "preview": {"resolution": 512, "background": [0.055, 0.065, 0.085], "margin": 1.18},
    "materials": DEFAULT_MATERIALS,
}


def _number(value: Any, label: str, minimum: float = 0, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Style {label} must be a finite number.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Style {label} is outside its supported range.")


def validate_style(style: dict[str, Any]) -> dict[str, Any]:
    """Validate operational settings while allowing descriptive art-direction extensions."""
    if type(style.get("schema_version")) is not int or style["schema_version"] != 1:
        raise ValueError("Unsupported style schema_version; expected 1.")
    _number(style.get("unit_scale"), "unit_scale", 1e-9)
    if style.get("units") != "meters":
        raise ValueError("Style units must be 'meters'; unit_scale controls meters per Blender unit.")
    if style.get("default_export_format") != "glb":
        raise ValueError("Only the 'glb' default export format is implemented.")
    for key in ("bevel", "preview", "materials"):
        if not isinstance(style.get(key), dict):
            raise ValueError(f"Style {key} must be a JSON object.")
    _number(style["bevel"].get("width"), "bevel.width")
    segments = style["bevel"].get("segments")
    if type(segments) is not int or not 1 <= segments <= 16:
        raise ValueError("Style bevel.segments must be an integer between 1 and 16.")
    resolution = style["preview"].get("resolution")
    if type(resolution) is not int or resolution not in (256, 512, 1024):
        raise ValueError("Style preview.resolution must be 256, 512, or 1024.")
    _number(style["preview"].get("margin"), "preview.margin", 1.0)
    background = style["preview"].get("background")
    if not isinstance(background, (list, tuple)) or len(background) != 3:
        raise ValueError("Style preview.background must be an RGB triple.")
    for value in background:
        _number(value, "preview.background", 0, 1)
    allowed = {"base_color", "metallic", "roughness", "alpha", "transmission", "emission", "emission_strength"}
    for name, material in style["materials"].items():
        if not isinstance(name, str) or not name or not isinstance(material, dict):
            raise ValueError("Style materials must map nonempty names to material settings.")
        if set(material) - allowed:
            raise ValueError(f"Unknown settings for material {name!r}: {', '.join(sorted(set(material) - allowed))}.")
        for key, value in material.items():
            if key in ("base_color", "emission"):
                if not isinstance(value, (list, tuple)) or len(value) != 4:
                    raise ValueError(f"Material {name}.{key} must be RGBA.")
                for channel in value:
                    _number(channel, f"materials.{name}.{key}", 0, 1)
            else:
                _number(value, f"materials.{name}.{key}", 0, None if key == "emission_strength" else 1)
    return style


def load_style(project_root: str | Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge Core defaults → game_style.json → asset style; never mutate inputs."""
    path = Path(project_root) / "game_style.json"
    result = deepcopy(DEFAULT_STYLE)
    if path.is_file():
        result = merge_values(result, read_json(path))
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("Style overrides must be a JSON object.")
        result = merge_values(result, overrides)
    return validate_style(result)
