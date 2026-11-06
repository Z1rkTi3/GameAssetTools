"""Small, Blender-independent recipe contract shared by both interfaces."""

from dataclasses import dataclass
from typing import Any, Protocol

from .parameters import Parameter

STAGES = ("BLOCKOUT", "REFINE", "DETAIL", "FINALIZE")


@dataclass(frozen=True)
class ComponentSpec:
    """Semantic collection and upstream components used to build a component."""

    collection: str
    depends_on: tuple[str, ...] = ()
    helper: bool = False
    persistent: bool = False


class AssetRecipe(Protocol):
    """Recipes are ordinary Python objects; Blender imports belong in build code."""

    parameters: tuple[Parameter, ...]

    def components(self, config: dict[str, Any]) -> dict[str, ComponentSpec]: ...

    def build_component(self, ctx: Any, key: str, config: dict[str, Any]) -> None: ...


def validate_stage(stage: str, supported_stages: tuple[str, ...] = STAGES) -> str:
    """Normalize a stage and reject unsupported transitions/recipe stages."""
    if not isinstance(stage, str):
        raise ValueError("Stage must be a string.")
    result = stage.upper()
    if result not in STAGES or result not in supported_stages:
        raise ValueError(f"Unsupported stage {stage!r}; choose {', '.join(supported_stages)}.")
    return result


def validate_components(components: dict[str, ComponentSpec]) -> None:
    """Reject invalid dependencies and cycles before scene mutation."""
    if not isinstance(components, dict) or not components:
        raise ValueError("Recipe must declare at least one component.")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError(f"Component dependency cycle involving {key!r}.")
        if key in visited:
            return
        if key not in components:
            raise ValueError(f"Unknown component dependency {key!r}.")
        spec = components[key]
        if not isinstance(key, str) or not key or not isinstance(spec, ComponentSpec):
            raise ValueError("Components must map nonempty names to ComponentSpec values.")
        if not isinstance(spec.collection, str) or not spec.collection:
            raise ValueError(f"Component {key!r} requires a collection name.")
        if not isinstance(spec.depends_on, tuple) or not all(isinstance(name, str) and name for name in spec.depends_on):
            raise ValueError(f"Component {key!r} dependencies must be a tuple of names.")
        if len(set(spec.depends_on)) != len(spec.depends_on):
            raise ValueError(f"Component {key!r} has duplicate dependencies.")
        if type(spec.helper) is not bool:
            raise ValueError(f"Component {key!r} helper must be a boolean.")
        if type(spec.persistent) is not bool:
            raise ValueError(f"Component {key!r} persistent must be a boolean.")
        visiting.add(key)
        for dependency in spec.depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for component in components:
        visit(component)
