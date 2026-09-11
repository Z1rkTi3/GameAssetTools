"""Typed, nested JSON configuration and parameter-aware rebuild selection."""

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .recipe import AssetRecipe
    from .registry import RecipeEntry

SCHEMA_VERSION = 1
_MISSING = object()


@dataclass(frozen=True)
class Parameter:
    """A useful design control; components identifies its rebuild effects."""

    path: str
    label: str
    type: str
    default: Any
    min: float | int | None = None
    max: float | int | None = None
    choices: tuple[str, ...] = ()
    components: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.path or any(not part for part in self.path.split(".")):
            raise ValueError("Parameter path must contain nonempty dotted names.")
        if self.type not in ("float", "int", "bool", "str", "enum"):
            raise ValueError(f"Unknown parameter type {self.type!r}.")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"Invalid bounds for {self.path}.")
        self.validate(self.default)

    def validate(self, value: Any) -> None:
        valid = {
            "float": isinstance(value, (float, int)) and not isinstance(value, bool),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "bool": isinstance(value, bool),
            "str": isinstance(value, str),
            "enum": isinstance(value, str) and value in self.choices,
        }[self.type]
        if not valid:
            suffix = f" ({', '.join(self.choices)})" if self.type == "enum" else ""
            raise ValueError(f"Parameter {self.path!r} must be {self.type}{suffix}.")
        if self.type in ("float", "int"):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Parameter {self.path!r} must be finite.")
            if self.min is not None and value < self.min:
                raise ValueError(f"Parameter {self.path!r} must be >= {self.min}.")
            if self.max is not None and value > self.max:
                raise ValueError(f"Parameter {self.path!r} must be <= {self.max}.")


def get_value(values: dict[str, Any], path: str, default: Any = _MISSING) -> Any:
    """Read a dotted parameter path without interpreting Python expressions."""
    current: Any = values
    for name in path.split("."):
        if not isinstance(current, dict) or name not in current:
            if default is _MISSING:
                raise ValueError(f"Missing parameter {path!r}.")
            return default
        current = current[name]
    return current


def set_value(values: dict[str, Any], path: str, value: Any) -> None:
    """Assign a dotted JSON path, rejecting conflicting scalar parents."""
    names = path.split(".")
    if any(not name for name in names):
        raise ValueError(f"Invalid parameter path {path!r}.")
    current = values
    for name in names[:-1]:
        current = current.setdefault(name, {})
        if not isinstance(current, dict):
            raise ValueError(f"Parameter path {path!r} has a scalar parent.")
    current[names[-1]] = deepcopy(value)


def merge_values(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Deep merge JSON mappings without mutating either input."""
    result = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_values(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number {value!r} is not supported.")

    try:
        result = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return result


def _leaf_paths(values: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if not isinstance(key, str) or not key or "." in key:
            raise ValueError("JSON parameter keys must be nonempty names without dots.")
        if isinstance(value, dict) and value:
            paths.update(_leaf_paths(value, path))
        else:
            paths.add(path)
    return paths


def validate_config(entry: "RecipeEntry", config: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete versioned envelope and the recipe's declared controls."""
    from .recipe import validate_components

    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object.")
    extra = set(config) - {"schema_version", "asset", "parameters", "style"}
    if extra:
        raise ValueError(f"Unknown config fields: {', '.join(sorted(extra))}.")
    if type(config.get("schema_version")) is not int or config["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported config schema_version; expected {SCHEMA_VERSION}.")
    if config.get("asset") != entry.id:
        raise ValueError(f"Config asset must be {entry.id!r}.")
    if not isinstance(config.get("parameters"), dict) or not isinstance(config.get("style", {}), dict):
        raise ValueError("Config parameters and style must be JSON objects.")
    recipe = entry.load()
    paths = [parameter.path for parameter in recipe.parameters]
    if len(paths) != len(set(paths)):
        raise ValueError(f"Recipe {entry.id!r} declares duplicate parameter paths.")
    unknown = _leaf_paths(config["parameters"]) - set(paths)
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}.")
    for parameter in recipe.parameters:
        parameter.validate(get_value(config["parameters"], parameter.path))
    components = recipe.components(config)
    validate_components(components)
    for parameter in recipe.parameters:
        missing = set(parameter.components) - set(components)
        if missing:
            raise ValueError(f"Parameter {parameter.path!r} references unknown components: {', '.join(sorted(missing))}.")
    return config


def load_config(entry: "RecipeEntry", path: str | Path | None = None,
                overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load defaults, optional config and dotted parameter overrides in that order."""
    defaults: dict[str, Any] = {}
    for parameter in entry.load().parameters:
        set_value(defaults, parameter.path, parameter.default)
    result = merge_values({"schema_version": SCHEMA_VERSION, "asset": entry.id,
                           "parameters": defaults, "style": {}}, read_json(entry.path / "config.json"))
    if path is not None:
        result = merge_values(result, read_json(Path(path)))
    if not isinstance(result.get("parameters"), dict):
        raise ValueError("Config parameters must be a JSON object.")
    for parameter_path, value in (overrides or {}).items():
        set_value(result["parameters"], parameter_path, value)
    return validate_config(entry, result)


def changed_components(recipe: "AssetRecipe", old_config: dict[str, Any],
                       new_config: dict[str, Any]) -> set[str]:
    """Find parameter effects and downstream dependency closure conservatively."""
    from .recipe import validate_components

    old_specs = recipe.components(old_config)
    new_specs = recipe.components(new_config)
    validate_components(new_specs)
    all_keys = set(old_specs) | set(new_specs)
    if old_config == new_config:
        return set()
    if any(old_config.get(key) != new_config.get(key)
           for key in (set(old_config) | set(new_config)) - {"parameters"}):
        return all_keys
    old_values = old_config.get("parameters", {})
    new_values = new_config.get("parameters", {})
    if not isinstance(old_values, dict) or not isinstance(new_values, dict):
        return all_keys
    changed_paths = {path for path in _leaf_paths(old_values) | _leaf_paths(new_values)
                     if get_value(old_values, path, None) != get_value(new_values, path, None)}
    known = {parameter.path: parameter for parameter in recipe.parameters}
    if changed_paths - set(known):
        return all_keys
    changed = set(old_specs) ^ set(new_specs)
    for path in changed_paths:
        if not known[path].components:
            return all_keys
        changed.update(known[path].components)
    changed.update(key for key in set(old_specs) & set(new_specs) if old_specs[key] != new_specs[key])
    while True:
        additions = {key for key, spec in new_specs.items() if set(spec.depends_on) & changed}
        if additions <= changed:
            return changed
        changed.update(additions)
